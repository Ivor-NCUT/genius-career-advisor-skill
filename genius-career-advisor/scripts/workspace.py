#!/usr/bin/env python3
"""Resolve the local candidate workspace without moving existing data.

New sessions use `.天才职业顾问`. Older directories are still accepted so
existing profiles, resumes, and referral state keep working. This command
does not create, move, or merge data, and its note does not rename the product.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path


PUBLIC_WORKSPACE = ".天才职业顾问"
LEGACY_WORKSPACES = (".genius-career-advisor", ".fanhan-job-agent")
WORKSPACE_NAMES = (PUBLIC_WORKSPACE, *LEGACY_WORKSPACES)


def is_workspace_name(name: str) -> bool:
    return name in WORKSPACE_NAMES


def workspace_index(parts: tuple[str, ...] | list[str]) -> int | None:
    indexes = [index for index, part in enumerate(parts) if part in WORKSPACE_NAMES]
    if not indexes:
        return None
    return indexes[-1]


def resolve(start: Path | None = None) -> Path:
    """Return the workspace directory to use. Do not create it."""
    root = (start or Path(".")).expanduser().resolve()
    public = root / PUBLIC_WORKSPACE
    if public.is_dir():
        return public
    for name in LEGACY_WORKSPACES:
        candidate = root / name
        if candidate.is_dir():
            return candidate
    return public


def describe(start: Path | None = None) -> dict:
    root = (start or Path(".")).expanduser().resolve()
    public = root / PUBLIC_WORKSPACE
    legacy_dirs = [root / name for name in LEGACY_WORKSPACES if (root / name).is_dir()]
    chosen = resolve(root)
    if public.is_dir() and legacy_dirs:
        active = "public"
        note = "已有本地档案。继续使用当前目录，不要另建或覆盖另一份档案。"
    elif public.is_dir():
        active = "public"
        note = "使用当前本地档案目录。"
    elif legacy_dirs:
        active = "legacy"
        note = "沿用已经存在的本地档案目录，不要另建空目录。"
    else:
        active = "public"
        note = "还没有本地档案。请创建 .天才职业顾问。"
    return {
        "directory": chosen.name,
        "path": str(chosen),
        "active": active,
        "public_present": public.is_dir(),
        "legacy_present": bool(legacy_dirs),
        "note": note,
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        empty = describe(root)
        assert empty["directory"] == PUBLIC_WORKSPACE
        assert empty["active"] == "public"
        assert empty["legacy_present"] is False
        for legacy_name in LEGACY_WORKSPACES:
            only = Path(tempfile.mkdtemp())
            legacy = only / legacy_name
            legacy.mkdir()
            (legacy / "profile.json").write_text("{}", encoding="utf-8")
            kept = describe(only)
            assert kept["directory"] == legacy_name
            assert kept["active"] == "legacy"
            assert resolve(only) == legacy.resolve()
        legacy = root / LEGACY_WORKSPACES[-1]
        legacy.mkdir()
        public = root / PUBLIC_WORKSPACE
        public.mkdir()
        both = describe(root)
        assert both["directory"] == PUBLIC_WORKSPACE
        assert both["public_present"] and both["legacy_present"]
        assert workspace_index((".天才职业顾问", "outbox")) == 0
        assert workspace_index(("a", ".fanhan-job-agent", "outbox")) == 1
        assert workspace_index(("a", ".genius-career-advisor", "outbox")) == 1
        assert workspace_index(("nope",)) is None
    print("workspace self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="resolve", choices=("resolve",))
    parser.add_argument("--start", type=Path, default=Path("."))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    print(json.dumps(describe(args.start), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
