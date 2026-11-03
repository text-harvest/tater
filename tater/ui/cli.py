"""Command-line interface utilities for Tater."""
import argparse
import os
from argparse import Namespace


def parse_args() -> Namespace:
    """Parse command-line arguments for Tater app."""
    parser = argparse.ArgumentParser(description="Tater Document Annotation App")

    parser.add_argument(
        "--hosted",
        action="store_true",
        help="Run in hosted mode: users upload their own schema and documents",
    )
    parser.add_argument(
        "--documents",
        type=str,
        help="Path to documents JSON file (required in non-hosted mode)"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--config",
        type=str,
        help="Path to a Python config file defining schema_model and widgets"
    )
    group.add_argument(
        "--schema",
        type=str,
        help="Path to a tater JSON schema file"
    )
    parser.add_argument(
        "--annotations",
        type=str,
        help="Path to save/load annotations (default: <documents>_annotations.json)"
    )
    parser.add_argument(
        "--no-restore",
        action="store_true",
        help="Skip loading existing annotations on startup",
    )
    parser.add_argument(
        "--show-disclaimer",
        action="store_true",
        help="Show a sensitive data disclaimer modal on the upload page (hosted mode only)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=os.getenv("TATER_APP_DEBUG", "").lower() in ("true", "1", "yes"),
        help="Enable debug mode with hot reloading (or set TATER_APP_DEBUG env var)"
    )
    parser.add_argument(
        "--trace",
        default=os.getenv("TATER_TRACE") or None,
        metavar="PATH",
        help="Append a JSON line per callback request to PATH, for the perf harness (or TATER_TRACE env var)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("TATER_APP_PORT", "8050")),
        help="Port to run the server on (default: 8050, or TATER_APP_PORT env var)"
    )
    parser.add_argument(
        "--host",
        default=os.getenv("TATER_APP_HOST", "127.0.0.1"),
        help="Host to bind to (default: 127.0.0.1, or TATER_APP_HOST env var)"
    )

    args = parser.parse_args()

    # Validate: one of --hosted, --config, or --schema must be provided
    if not args.hosted and not args.config and not args.schema:
        parser.error("one of --hosted, --config, or --schema is required")
    # Validate: non-hosted mode also requires --documents
    if not args.hosted and not args.documents:
        parser.error("--documents is required in non-hosted mode (or use --hosted)")
    # Validate: --no-restore only applies in non-hosted mode
    if args.hosted and args.no_restore:
        parser.error("--no-restore is not applicable in hosted mode")

    return args
