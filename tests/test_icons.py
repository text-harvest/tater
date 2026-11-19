"""Tater serves its own icons (tater/ui/assets/icons.js), so pages never fetch them from
api.iconify.design. If this fails after adding an icon, re-run scripts/build_icons.py."""
from scripts.build_icons import OUT, PREFIX, icons_used, read_preload


def test_every_icon_used_is_in_icons_js():
    preload = read_preload()
    assert [s["prefix"] for s in preload] == [PREFIX]
    have = {f"{PREFIX}:{name}" for name in preload[0]["icons"]}
    missing = sorted(icons_used() - have)
    assert not missing, f"not in {OUT.name}: {missing}; re-run scripts/build_icons.py"


def test_only_tabler_icons():
    others = sorted(i for i in icons_used() if not i.startswith(PREFIX + ":"))
    assert not others, f"use Tabler icons instead of {others}"


def test_scanner_finds_known_icons():
    used = icons_used()
    assert {"tabler:arrow-right", "tabler:player-play", "tabler:copy"} <= used  # py, js, CopyButton
    assert not any(i.startswith(("cursor:", "display:")) for i in used)  # CSS isn't an icon


def test_icon_bodies_are_svg():
    for name, icon in read_preload()[0]["icons"].items():
        assert icon["body"].startswith("<") and "script" not in icon["body"].lower(), name
