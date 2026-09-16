#!/usr/bin/env python3
"""Generate several independently written Hermes samples for visual review."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import html
import json
import os
from pathlib import Path
from typing import Any

from compare_adaptation_levels import _generate_image, _template_from_source
from creative_profiles import adaptation_contract, interpretive_layout_by_id
from core import image_ocr_errors, validate_copy
from run_daily_8x5 import (
    DEFAULT_CASES,
    OnlineData,
    atomic_json,
    build_image_plan,
    compile_ocr,
    ocr_image,
    run_copy_subprocess,
)
from worker_runtime import load_dotenv


SAMPLES: tuple[dict[str, str], ...] = (
    {
        "key": "version-choice",
        "label": "版本选择",
        "layout": "kinetic_collage",
        "instruction": (
            "以405公里日常通勤与510公里长距离需求的选择矛盾为切口。最多举两个有依据的版本；"
            "如果公开价格，结尾只承接所在地地方政策流程与适用条件，不能再承诺发送同一份报价。"
        ),
    },
    {
        "key": "budget-boundary",
        "label": "预算边界",
        "layout": "asymmetric_editorial",
        "instruction": (
            "以6万级预算究竟应先看续航还是智驾为切口，像真实运营在帮读者做取舍，不写参数清单。"
            "最多使用两个配置举例；城市只用于核对地方政策流程。"
        ),
    },
    {
        "key": "benefit-check",
        "label": "权益核对",
        "layout": "paper_cutout",
        "instruction": (
            "以选装基金、家充服务包和适用条件容易混淆为避坑切口，不展开完整配置价格表。"
            "收束到下订前核对自己适用的权益与地方流程，不能把城市写成国补价格查询条件。"
        ),
    },
    {
        "key": "commute-scene",
        "label": "通勤场景",
        "layout": "spatial_installation",
        "instruction": (
            "从城市通勤和偶尔跨城的真实使用场景切入，围绕405/510km续航选择展开，少写政策播报。"
            "转化入口只承接尚未公开的所在地流程与适用条件，不重复索取正文已经给出的信息。"
        ),
    },
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def generate_copy(sample: dict[str, str], source: dict[str, Any], output_dir: Path, model: str) -> dict[str, Any]:
    case = load_json(DEFAULT_CASES)[str(source["post"]["case_id"])]
    previous = sorted((output_dir / "workers").glob(f"preview-{sample['key']}-*.output.json"))
    for path in reversed(previous):
        result = load_json(path)
        current_validation = validate_copy(
            title=str(result.get("title") or ""),
            content=str(result.get("content") or ""),
            mother=source["mother"],
            case=case,
            adaptation_level="interpretive",
        )
        if result.get("ok") and not current_validation.get("hard_errors"):
            result["validation"] = current_validation
            return {**sample, "copy_result": result}
    failures: list[dict[str, Any]] = []
    for attempt in range(1, 4):
        payload = {
            "key": f"preview-{sample['key']}",
            "case_id": str(source["post"]["case_id"]),
            "mother_id": int(source["mother"]["id"]),
            "model": model,
            "avoidance_brief": {},
            "operator_instruction": sample["instruction"],
            "adaptation_level": "interpretive",
        }
        result = run_copy_subprocess(payload, output_dir, f"a{attempt}")
        if result.get("ok"):
            return {**sample, "copy_result": result}
        failures.append({
            "attempt": attempt,
            "error": result.get("error"),
            "validation": result.get("validation"),
        })
    return {**sample, "copy_result": {"ok": False, "failures": failures}}


def generate_plan(
    item: dict[str, Any], source: dict[str, Any], case: dict[str, Any], online: OnlineData,
    output_dir: Path, model: str,
) -> dict[str, Any]:
    copy_result = item["copy_result"]
    if not copy_result.get("ok"):
        return item
    source_post = source["post"]
    try:
        plan = build_image_plan(
            copy={"title": copy_result["title"], "content": copy_result["content"]},
            template=_template_from_source(source_post),
            case=case,
            car_images={str(source_post["vehicle_image"]["label"]): str(source_post["vehicle_image"]["url"])},
            model=model,
            attempts=3,
            public_root=online.public_root,
            operator_instruction=item["instruction"],
            adaptation_level="interpretive",
            required_layout_archetype=item["layout"],
            trace_dir=output_dir / "traces" / item["key"],
        )
        return {**item, "image_plan": plan}
    except Exception as exc:
        return {**item, "plan_error": f"{type(exc).__name__}: {exc}"}


def render(output_dir: Path, source: dict[str, Any], items: list[dict[str, Any]]) -> Path:
    cards: list[str] = []
    for index, item in enumerate(items, start=1):
        copy_result = item.get("copy_result") or {}
        validation = copy_result.get("validation") or {}
        image_validation = item.get("image_validation") or {}
        errors = list(validation.get("hard_errors") or []) + list(image_validation.get("hard_errors") or [])
        if item.get("plan_error"):
            errors.append(str(item["plan_error"]))
        generation = item.get("generation") or {}
        image_name = html.escape(str(generation.get("local_image") or ""))
        image_markup = (
            f'<img src="{image_name}" alt="样本{index}">'
            if image_name else f'<div class="missing">{html.escape(str(generation.get("error") or "生成失败"))}</div>'
        )
        layout = interpretive_layout_by_id(item.get("layout")) or {"name": item.get("layout") or ""}
        content = html.escape(str(copy_result.get("content") or "")).replace("\n", "<br>")
        cards.append(f"""
        <article class="card">
          <div class="card-head"><div><span>CONCEPT {index:02d} · {html.escape(str(layout['name']))}</span><h2>{html.escape(str(item['label']))}</h2></div><b class="{'ok' if not errors else 'bad'}">{'硬校验通过' if not errors else f'{len(errors)}项错误'}</b></div>
          {image_markup}
          <section><h3>{html.escape(str(copy_result.get('title') or '文案生成失败'))}</h3><div class="copy">{content}</div></section>
          <details><summary>查看创作方向与校验</summary><p>{html.escape(str(item['instruction']))}</p><p>{html.escape('；'.join(errors) or '文案、政策、图片文字与OCR硬校验均通过')}</p></details>
        </article>""")
    page = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Hermes 多样本评审</title><style>
:root{{--ink:#111b18;--muted:#6c7773;--paper:#eef3ef;--line:#dfe6e2}}*{{box-sizing:border-box}}body{{margin:0;color:var(--ink);font-family:"Avenir Next","PingFang SC",sans-serif;background:radial-gradient(circle at 10% 0,#d8e9df 0,transparent 30%),radial-gradient(circle at 90% 4%,#efe0cf 0,transparent 28%),var(--paper)}}main{{max-width:1520px;margin:auto;padding:42px 28px 70px}}header{{display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:26px}}header span,.card-head span{{font-size:10px;letter-spacing:.15em;color:var(--muted)}}h1{{margin:5px 0 7px;font-size:clamp(32px,4vw,54px);letter-spacing:-.05em}}header p{{margin:0;max-width:720px;color:var(--muted);line-height:1.7}}.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;align-items:start}}.card{{background:#fffc;border:1px solid #fff;border-radius:26px;padding:15px;box-shadow:0 20px 60px #263d3512;backdrop-filter:blur(15px)}}.card-head{{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:3px 3px 13px}}.card h2{{margin:3px 0 0;font-size:22px}}.card b{{font-size:11px;padding:6px 9px;border-radius:99px}}.ok{{color:#176246;background:#e9f5ed}}.bad{{color:#a23b32;background:#fff0ee}}.card img,.missing{{width:100%;aspect-ratio:3/4;object-fit:contain;border-radius:17px;background:#e7ece9}}.missing{{display:grid;place-items:center;color:#9a473d;padding:20px}}.card section{{padding:2px}}.card h3{{font-size:18px;margin:16px 0 9px}}.copy{{font-size:13px;line-height:1.78;max-height:390px;overflow:auto;padding:13px;background:#f4f6f4;border-radius:14px}}details{{margin:13px 2px 2px;padding-top:12px;border-top:1px solid var(--line)}}summary{{font-size:12px;font-weight:600;cursor:pointer}}details p{{font-size:12px;line-height:1.6;color:var(--muted)}}@media(max-width:1180px){{.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:680px){{main{{padding:22px 12px 45px}}header{{display:block}}.grid{{grid-template-columns:1fr}}}}
</style></head><body><main><header><div><span>HERMES · FOUR INDEPENDENT SAMPLES</span><h1>不是换色，是四套创作</h1><p>同一篇母文与同一政策依据，分别采用版本选择、预算边界、权益核对和通勤场景四个切口；图片使用四种不同版式骨架。</p></div><span>{dt.datetime.now().strftime('%Y.%m.%d %H:%M')} · LOCAL ONLY</span></header><div class="grid">{''.join(cards)}</div></main></body></html>"""
    path = output_dir / "comparison.html"
    path.write_text(page, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--image-model", default="gptimage2")
    args = parser.parse_args()

    load_dotenv(Path(__file__).with_name(".env"))
    source = load_json(args.source.resolve())
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    assigned_path = output_dir / "assigned_mothers.json"
    atomic_json(assigned_path, {"mothers": [source["mother"]]})
    os.environ["XHS_CASES_PATH"] = str(DEFAULT_CASES)
    os.environ["XHS_ASSIGNED_MOTHERS_PATH"] = str(assigned_path)
    cases = load_json(DEFAULT_CASES)
    case = cases[str(source["post"]["case_id"])]
    online = OnlineData()

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(SAMPLES)) as executor:
        futures = [executor.submit(generate_copy, sample, source, output_dir, args.model) for sample in SAMPLES]
        items = [future.result() for future in futures]
    copy_failures = [item["key"] for item in items if not item["copy_result"].get("ok")]
    if copy_failures:
        atomic_json(output_dir / "comparison.json", {"source": source, "items": items})
        raise RuntimeError(f"copy generation failed: {copy_failures}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(items)) as executor:
        futures = [executor.submit(generate_plan, item, source, case, online, output_dir, args.model) for item in items]
        items = [future.result() for future in futures]

    ready = [item for item in items if item.get("image_plan")]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(ready))) as executor:
        futures = [executor.submit(
            _generate_image,
            item={**item, "level": item["key"], "copy": {
                "title": item["copy_result"]["title"], "content": item["copy_result"]["content"],
            }},
            online=online,
            case=case,
            image_model=args.image_model,
            output_dir=output_dir,
        ) for item in ready]
        for item, future in zip(ready, futures):
            item["generation"] = future.result()

    ocr = compile_ocr(output_dir)
    for item in items:
        generation = item.get("generation") or {}
        image_name = str(generation.get("local_image") or "")
        if not image_name:
            item["image_validation"] = {"pass": False, "hard_errors": [str(generation.get("error") or "图片生成失败")], "ocr_lines": []}
            continue
        lines = ocr_image(ocr, output_dir / image_name)
        copy = {"title": item["copy_result"]["title"], "content": item["copy_result"]["content"]}
        errors = image_ocr_errors(lines, copy=copy, case=case)
        item["image_validation"] = {"pass": not errors, "hard_errors": errors, "ocr_lines": lines}

    atomic_json(output_dir / "comparison.json", {
        "contract": adaptation_contract("interpretive"), "source": source, "items": items,
    })
    page = render(output_dir, source, items)
    print(json.dumps({"stage": "done", "html": str(page), "samples": len(items)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
