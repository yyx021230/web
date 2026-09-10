"""Back up and atomically install the 0.3.25 Hermes policy/config/plugin files."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
from pathlib import Path


SOURCE = Path("/release/source")
CONFIG = Path("/live/config")
HOME = Path("/live/home")
RELEASE = Path("/release")
CONFIG_FILES = ("cases.json", "policy_display.json", "policy_overrides.json")
PLUGIN_REL = Path("plugins/xhs-copy-tools/__init__.py")
RUNTIME_ROOT = Path("/app/web/ops/xhs_hermes")
RUNTIME_FILES = ("core.py", "run_daily_8x5.py", "policy_sync.py", "policy_constraints.py")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.0.3.25.tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, target)


def paths() -> list[tuple[Path, Path]]:
    rows = [
        (SOURCE / "ops/xhs_hermes/config" / name, CONFIG / name)
        for name in CONFIG_FILES
    ]
    rows.append((SOURCE / "ops/xhs_hermes/hermes_home" / PLUGIN_REL, HOME / PLUGIN_REL))
    return rows


def validate() -> dict[str, object]:
    cases = json.loads((CONFIG / "cases.json").read_text(encoding="utf-8"))
    display = json.loads((CONFIG / "policy_display.json").read_text(encoding="utf-8"))
    forbidden = ("报废更新", "报废补贴", "报废价格", "置换更新")
    serialized = json.dumps(cases, ensure_ascii=False)
    assert not any(term in serialized for term in forbidden), "production policy contains retired wording"
    assert all("display_quote_rows" not in case for case in cases.values())
    assert all(
        row.get("provincial_trade_in_after_price") == "不在线上展示金额"
        for case in cases.values()
        for row in case.get("quote_rows", [])
    )
    assert set(display) == set(cases), "display and production policy case sets differ"
    assert all(display[case_id] for case_id in cases), "display policy row missing"
    return {
        "case_count": len(cases),
        "display_case_count": len(display),
        "production_province_amounts_hidden": True,
        "retired_wording_absent": True,
        "plugin_sha256": sha(HOME / PLUGIN_REL),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    planned = paths()
    for source, _ in planned:
        assert source.is_file(), f"missing staged source: {source}"
    if args.verify:
        for source, target in planned:
            assert target.is_file() and sha(source) == sha(target), f"live file mismatch: {target}"
        for name in RUNTIME_FILES:
            source = SOURCE / "ops/xhs_hermes" / name
            target = RUNTIME_ROOT / name
            assert target.is_file() and sha(source) == sha(target), f"runtime file mismatch: {target}"
        print(json.dumps({"verified": True, **validate()}, ensure_ascii=False))
        return
    if not args.execute:
        print(json.dumps({"preflight": True, "files": [str(t) for _, t in planned]}))
        return
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = RELEASE / "private" / f"policy-copy-before-{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    for _, target in planned:
        if target.is_file():
            relative = Path("config") / target.name if target.parent == CONFIG else Path("home") / PLUGIN_REL
            destination = backup / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
    for source, target in planned:
        atomic_copy(source, target)
    result = {"installed": True, "backup": str(backup), **validate()}
    (RELEASE / "policy-install.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
