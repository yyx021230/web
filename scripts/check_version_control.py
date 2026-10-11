#!/usr/bin/env python3
"""Read-only Git/version gates. Does not stage, commit, tag, or contact remotes."""

from __future__ import annotations

import argparse
import ast
from datetime import date
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

try:
    import tomllib
except ModuleNotFoundError:
    raise SystemExit("Version checks require Python 3.11+; set PYTHON_BIN to a supported interpreter.") from None


ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")
RUNTIME_DIRECTORIES = {
    "exports", "local-reviews", ".release", "private_publish_snapshots",
    "node_modules", ".next", "uploads", "test_uploads", "db_backups",
}


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], stderr=subprocess.PIPE,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    ).decode("utf-8")


def forbidden_path(name: str) -> bool:
    path = PurePosixPath(name)
    if any(part in RUNTIME_DIRECTORIES for part in path.parts[:-1]):
        return True
    # This pre-existing, tracked test fixture is not a production environment.
    if name == "backend/.env.test":
        return False
    if path.name == ".env" or path.name.startswith(".env."):
        return not path.name.endswith(".example")
    return bool(re.search(r"\.(?:db|sqlite|sqlite3)(?:-.*)?$|\.dump$", path.name))


def versions(root: Path) -> dict[str, str]:
    package = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((root / "frontend/package-lock.json").read_text(encoding="utf-8"))
    project = tomllib.loads((root / "backend/pyproject.toml").read_text(encoding="utf-8"))
    tree = ast.parse((root / "backend/app/config.py").read_text(encoding="utf-8"))
    settings = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Settings")
    default = next(node.value.value for node in settings.body if (
        isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        and node.target.id == "app_version" and isinstance(node.value, ast.Constant)
    ))
    return {
        "frontend/package.json": package["version"],
        "frontend/package-lock.json": lock["version"],
        "frontend/package-lock.json packages[root]": lock["packages"][""]["version"],
        "backend/pyproject.toml": project["project"]["version"],
        "backend/app/config.py": default,
    }


def check(root: Path, *, release: bool = False, tag: str | None = None) -> dict:
    errors: list[str] = []
    result = {"mode": "release" if release else "development", "errors": errors}
    try:
        root = root.resolve()
        if Path(git(root, "rev-parse", "--show-toplevel").strip()).resolve() != root:
            raise ValueError("--repo must be the repository root")
        result["commit"] = git(root, "rev-parse", "HEAD").strip()
        result["branch"] = git(root, "branch", "--show-current").strip()
        result["dirty"] = bool(git(root, "status", "--porcelain=v1", "-z", "--untracked-files=normal"))
        metadata = versions(root)
        version = metadata["frontend/package.json"]
        result["version"] = version
        if not isinstance(version, str) or not VERSION.fullmatch(version):
            errors.append("frontend/package.json must use a stable X.Y.Z version")
        for name, value in metadata.items():
            if value != version:
                errors.append(f"{name} does not match frontend/package.json")
        tracked = set(git(root, "ls-files", "-z").split("\0")) - {""}
        unsafe = sorted(name for name in tracked if forbidden_path(name))
        if unsafe:
            errors.append("Runtime/private files are in the Git index: " + ", ".join(unsafe[:10]))
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        if len(re.findall(r"^## \[Unreleased\]\s*$", changelog, re.MULTILINE)) != 1:
            errors.append("CHANGELOG.md must have exactly one [Unreleased] section")
        if release:
            if result["dirty"]:
                errors.append("Release requires a clean working tree, including untracked source files")
            expected = f"v{version}"
            if tag is not None and tag != expected:
                errors.append("Requested tag does not match frontend/package.json")
            try:
                kind = git(root, "cat-file", "-t", f"refs/tags/{expected}").strip()
                target = git(root, "rev-parse", f"refs/tags/{expected}^{{commit}}").strip()
                if kind != "tag":
                    errors.append("New releases require an annotated version tag; do not rewrite historical tags")
                if target != result["commit"]:
                    errors.append("Release tag must point at HEAD")
            except subprocess.CalledProcessError:
                errors.append("Release tag is missing")
            entries = list(re.finditer(
                rf"^## \[{re.escape(str(version))}\] - (\d{{4}}-\d{{2}}-\d{{2}})\s*$",
                changelog, re.MULTILINE,
            ))
            if len(entries) != 1:
                errors.append("Release needs one dated CHANGELOG.md section for its exact version")
            else:
                entry = entries[0]
                date.fromisoformat(entry.group(1))
                body = re.split(r"^## ", changelog[entry.end():], maxsplit=1, flags=re.MULTILINE)[0]
                if not re.search(r"^- \S.+", body, re.MULTILINE):
                    errors.append("Release changelog section needs an actual change description")
    except (OSError, ValueError, KeyError, StopIteration, TypeError, SyntaxError, subprocess.CalledProcessError) as exc:
        # Never echo file contents, command stderr, or configuration values.
        errors.append(f"Unable to inspect repository metadata ({type(exc).__name__})")
    result["ok"] = not errors
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--tag", help="Expected tag, including v prefix (release mode only)")
    args = parser.parse_args()
    if args.tag and not args.release:
        parser.error("--tag requires --release")
    result = check(args.repo, release=args.release, tag=args.tag)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
