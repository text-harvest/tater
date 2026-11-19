"""``tater-launcher``: run one project for several annotators."""
from __future__ import annotations

import argparse
import ipaddress
import os
import signal
import socket
import sys

from tater.launcher.project import Project, ProjectError, check_project, load_project

BEHIND_LOGIN_PROXY_HELP = (
    "header mode only: allow listening on a non-loopback address. You are asserting that this "
    "address can be reached ONLY through the login service, and that the service removes any "
    "identity header a visitor sends; otherwise anyone can claim to be any annotator. Typical "
    "on a container platform with built-in sign-in."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tater-launcher",
        description="Run one tater project for several annotators: one tater per annotator, behind one address.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    check = sub.add_parser("check", help="validate the project file and load its schema and documents")
    check.add_argument("project", help="the project file (YAML)")

    start = sub.add_parser("start", help="run the launcher")
    start.add_argument("project", help="the project file (YAML)")
    start.add_argument("--host", default=os.getenv("TATER_LAUNCHER_HOST", "127.0.0.1"),
                       help="address to listen on (default 127.0.0.1, or TATER_LAUNCHER_HOST)")
    start.add_argument("--port", type=int, default=int(os.getenv("TATER_LAUNCHER_PORT", "8050")),
                       help="port to listen on (default 8050, or TATER_LAUNCHER_PORT)")
    start.add_argument("--behind-login-proxy", action="store_true", help=BEHIND_LOGIN_PROXY_HELP)

    status = sub.add_parser("status", help="show each annotator's process and progress")
    status.add_argument("project", help="the project file (YAML)")

    links = sub.add_parser("links", help="print each person's link (links mode)")
    links.add_argument("project", help="the project file (YAML)")
    links.add_argument("names", nargs="*", help="only these people")
    links.add_argument("--url", help="base address for the links (default: public_url, else http://127.0.0.1:8050)")

    reissue = sub.add_parser("reissue", help="replace one person's link; the old link and its cookies stop working")
    reissue.add_argument("project", help="the project file (YAML)")
    reissue.add_argument("name")
    reissue.add_argument("--url", help="base address for the link (default: public_url, else http://127.0.0.1:8050)")

    return parser


def _base_url(project: Project, url: str | None, host: str = "127.0.0.1", port: int = 8050) -> str:
    if url:
        return url.rstrip("/")
    if project.file.public_url:
        return project.file.public_url
    if host in ("0.0.0.0", "::", ""):
        host = socket.gethostname()
    return f"http://{host}:{port}"


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _print_links(project: Project, tokens: dict[str, str], base: str, only: list[str] | None = None) -> None:
    roles = {}
    for a in project.annotators:
        roles.setdefault(a.name, []).append("annotator")
    for a in project.admins:
        roles.setdefault(a.name, []).append("admin")
    width = max(len(n) for n in tokens)
    for name, token in tokens.items():
        if only and name not in only:
            continue
        print(f"{name:<{width}}  {base}/join/{token}  ({', '.join(roles[name])})")


def cmd_check(args) -> int:
    project = load_project(args.project)
    for line in check_project(project):
        print(line)
    print("ok")
    return 0


def cmd_status(args) -> int:
    from tater.launcher.progress import ProgressCounter, format_table, read_status_file, status_rows
    project = load_project(args.project)
    status = read_status_file(project)
    if status:
        print(f"{project.file.title}: launcher running at {status.get('url')} (pid {status.get('pid')}), "
              f"status as of {status.get('updated')}\n")
    else:
        print(f"{project.file.title}: launcher not running\n")
    print(format_table(status_rows(project, status, ProgressCounter(project))))
    return 0


def cmd_links(args) -> int:
    from tater.launcher.identity import LinkStore
    project = load_project(args.project)
    if project.file.identity != "links":
        raise ProjectError("this project uses identity: header; there are no personal links")
    unknown = [n for n in args.names if n not in {a.name for a in [*project.annotators, *project.admins]}]
    if unknown:
        raise ProjectError(f"not in the project: {', '.join(unknown)}")
    tokens = LinkStore(project).ensure_all()
    _print_links(project, tokens, _base_url(project, args.url), args.names or None)
    return 0


def cmd_reissue(args) -> int:
    from tater.launcher.identity import LinkStore
    project = load_project(args.project)
    if project.file.identity != "links":
        raise ProjectError("this project uses identity: header; there are no personal links")
    store = LinkStore(project)
    store.ensure_all()
    try:
        token = store.reissue(args.name)
    except KeyError:
        raise ProjectError(f"not in the project: {args.name}")
    print(f"{args.name}  {_base_url(project, args.url)}/join/{token}")
    print("The old link, and browsers that opened it, no longer work.")
    return 0


def cmd_start(args) -> int:
    from werkzeug.serving import make_server

    from tater.launcher.app import create_app
    from tater.launcher.identity import CookieSigner, Identifier, LinkStore
    from tater.launcher.supervisor import Supervisor

    project = load_project(args.project)
    if project.file.identity == "header" and not is_loopback(args.host) and not args.behind_login_proxy:
        raise ProjectError(
            f"identity: header trusts the '{project.file.header}' header, so the launcher must only be "
            f"reachable through the login service. Listening on {args.host} would let anyone who can "
            "reach it send that header themselves. Listen on 127.0.0.1 behind the login proxy, or, if "
            "this address is reachable only through the login service (as on a container platform "
            "with built-in sign-in), start with --behind-login-proxy."
        )
    for line in check_project(project):
        print(line)

    links = signer = None
    if project.file.identity == "links":
        links, signer = LinkStore(project), CookieSigner(project)
        tokens = links.ensure_all()
    supervisor = Supervisor(project)
    app = create_app(project, supervisor, Identifier(project, links, signer), links, signer)
    server = make_server(args.host, args.port, app, threaded=True)
    supervisor.launcher_url = f"http://{args.host}:{server.port}"
    base = _base_url(project, None, args.host, server.port)

    print(f"\n{project.file.title}: listening on {supervisor.launcher_url}")
    if links is not None:
        print("Send each person their own link (re-print them with 'tater-launcher links'):\n")
        _print_links(project, tokens, base)
    else:
        print(f"Annotators sign in through the login service at {base}; "
              f"identity comes from the '{project.file.header}' header.")
    print(f"\nResults: {project.results_dir}\nPress Ctrl+C to stop.\n", flush=True)

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    supervisor.write_status()
    supervisor.start_monitor()
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        print("Stopping annotators' tater processes...", flush=True)
        supervisor.shutdown()
        server.server_close()
    return 0


COMMANDS = {"check": cmd_check, "start": cmd_start, "status": cmd_status, "links": cmd_links, "reissue": cmd_reissue}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except ProjectError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
