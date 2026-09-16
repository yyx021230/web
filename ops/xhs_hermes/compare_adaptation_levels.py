#!/usr/bin/env python3
"""Generate a local, auditable comparison of all Hermes adaptation levels."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
from typing import Any

from core import image_ocr_errors
from creative_profiles import adaptation_contract
from run_daily_8x5 import (
    DEFAULT_CASES,
    NEGATIVE_PROMPT,
    OnlineData,
    atomic_json,
    build_image_plan,
    compile_ocr,
    make_generation_prompt,
    ocr_image,
    request_json,
)
from test_selected_prompt import download, wait_task


LEVELS = ("replica", "light", "interpretive")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _template_from_source(post: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(post["selected_prompt_id"]),
        "name": f"固定母图 #{post['selected_prompt_id']}",
        "chinese": str(post["selected_prompt_original"]),
        "image_url": str(post["selected_prompt_image"]),
        "source_slot_count": int(post.get("source_slot_count") or 0),
        "template_type": str(post.get("image_template_type") or "standard"),
        "structure_id": str(post.get("selected_prompt_structure_id") or ""),
        "source_section_title": post.get("selected_prompt_source_section"),
        "source_full_original": post.get("selected_prompt_full_original"),
    }


def _make_plan(
    *,
    level: str,
    worker_dir: Path,
    template: dict[str, Any],
    case: dict[str, Any],
    car_images: dict[str, str],
    online: OnlineData,
    model: str,
    output_dir: Path,
) -> dict[str, Any]:
    copy_result = _load_json(worker_dir / f"{level}.output.json")
    if not copy_result.get("ok"):
        raise RuntimeError(f"{level} copy output is not valid")
    copy = {
        "title": str(copy_result["title"]),
        "content": str(copy_result["content"]),
    }
    plan = build_image_plan(
        copy=copy,
        template=dict(template),
        case=case,
        car_images=car_images,
        model=model,
        attempts=3,
        public_root=online.public_root,
        adaptation_level=level,
        trace_dir=output_dir / "traces" / level,
    )
    return {
        "level": level,
        "contract": adaptation_contract(level),
        "copy": copy,
        "copy_validation": copy_result.get("validation") or {},
        "image_plan": plan,
    }


def _generate_image(
    *,
    item: dict[str, Any],
    online: OnlineData,
    case: dict[str, Any],
    image_model: str,
    output_dir: Path,
) -> dict[str, Any]:
    level = str(item["level"])
    image_path = output_dir / f"{level}.png"
    if image_path.exists() and image_path.stat().st_size > 0:
        return {
            "task_id": "reused-local",
            "attempt": 0,
            "local_image": image_path.name,
            "reused": True,
            "previous_failures": [],
        }
    plan = item["image_plan"]
    prompt = make_generation_prompt(plan, case)
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
    base_request_id = f"hermes-level-{dt.date.today().isoformat()}-{level}-{digest}"
    failures: list[dict[str, Any]] = []
    for attempt in range(1, 3):
        client_request_id = base_request_id if attempt == 1 else f"{base_request_id}-a{attempt}"
        response = request_json(
            online.backend + "/ai-image/generate",
            method="POST",
            headers=online.auth,
            body={
                "prompt": prompt,
                "client_request_id": client_request_id,
                "negative_prompt": NEGATIVE_PROMPT,
                "model": image_model,
                "width": 1536,
                "height": 2048,
                "quality": "high",
                "count": 1,
                "images_data": [plan["vehicle_image"]["url"]],
            },
            timeout=180,
            attempts=3,
        )
        data = response.get("data") if isinstance(response.get("data"), dict) else response
        task_id = str(data.get("task_id") or "")
        if not task_id:
            failures.append({"attempt": attempt, "error": "image backend returned no task_id"})
            continue
        terminal = wait_task(online, task_id, image_model)
        urls = terminal.get("image_urls") if isinstance(terminal.get("image_urls"), list) else []
        if str(terminal.get("status") or "") != "completed" or not urls:
            failures.append({
                "attempt": attempt,
                "task_id": task_id,
                "error": str(terminal.get("error") or terminal),
            })
            continue
        download(online, str(urls[0]), image_path)
        return {
            "task_id": task_id,
            "attempt": attempt,
            "image_url": online.absolute_url(str(urls[0])),
            "local_image": image_path.name,
            "terminal": terminal,
            "previous_failures": failures,
        }
    return {
        "error": failures[-1]["error"] if failures else "image generation failed",
        "previous_failures": failures,
    }


def _render(output_dir: Path, source: dict[str, Any], items: list[dict[str, Any]]) -> Path:
    source_post = source["post"]
    cards: list[str] = []
    for item in items:
        contract = item["contract"]
        validation = item.get("copy_validation") or {}
        image_validation = item.get("image_validation") or {}
        hard_errors = list(validation.get("hard_errors") or []) + list(image_validation.get("hard_errors") or [])
        result_class = "pass" if not hard_errors else "fail"
        result_text = "硬校验通过" if not hard_errors else f"{len(hard_errors)} 项硬错误"
        generation = item.get("generation") or {}
        image_src = html.escape(str(generation.get("local_image") or ""))
        image_markup = (
            f'<img class="hero" src="{image_src}" alt="{html.escape(str(contract["label"]))}成图">'
            if image_src
            else '<div class="hero missing">本档图片生成失败<br><small>'
            + html.escape(str(generation.get("error") or "未知错误"))
            + '</small></div>'
        )
        content = html.escape(str(item["copy"]["content"])).replace("\n", "<br>")
        mappings = "".join(
            "<tr><td>" + html.escape(str(row.get("source") or "")) + "</td><td>" +
            html.escape(str(row.get("output") or "")) + "</td></tr>"
            for row in item["image_plan"].get("slot_mappings") or []
        )
        visual_changes = "".join(
            "<tr><td>" + html.escape(str(row.get("dimension") or "")) + "</td><td>" +
            html.escape(str(row.get("from") or "")) + "</td><td>" +
            html.escape(str(row.get("to") or "")) + "</td></tr>"
            for row in item["image_plan"].get("visual_changes") or []
        )
        layout_archetype = html.escape(str(item["image_plan"].get("layout_archetype") or "沿用母版"))
        composition_signature = html.escape(str(item["image_plan"].get("composition_signature") or ""))
        ocr = " / ".join(
            html.escape(str(row.get("text") or ""))
            for row in image_validation.get("ocr_lines") or []
            if row.get("text")
        ) or "未识别到文字"
        cards.append(f"""
        <article class="card {html.escape(str(item['level']))}">
          <div class="card-head"><div><span class="eyebrow">{html.escape(str(item['level']).upper())}</span><h2>{html.escape(str(contract['label']))}</h2></div><span class="status {result_class}">{result_text}</span></div>
          <p class="intent">{html.escape(str(contract['description']))}</p>
          {image_markup}
          <h3>{html.escape(str(item['copy']['title']))}</h3>
          <div class="copy">{content}</div>
          <details><summary>查看图片改造依据</summary>
            <p><b>视觉规则：</b>{html.escape(str(contract['image']))}</p>
            <p><b>版式原型：</b>{layout_archetype}</p>
            <p><b>构图签名：</b>{composition_signature}</p>
            <p><b>实际变化：</b>{html.escape(str(item['image_plan'].get('scene_change') or ''))}</p>
            <p><b>OCR：</b>{ocr}</p>
            <table><thead><tr><th>变化维度</th><th>母图</th><th>新方案</th></tr></thead><tbody>{visual_changes}</tbody></table>
            <table><thead><tr><th>母图文字</th><th>成图文字</th></tr></thead><tbody>{mappings}</tbody></table>
          </details>
        </article>""")
    source_image = html.escape(str(source_post.get("selected_prompt_image") or ""))
    source_copy = html.escape(str(source["mother"]["content"])).replace("\n", "<br>")
    page = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Hermes 三档创作幅度对照</title><style>
:root{{--ink:#16201d;--muted:#69736f;--line:#e4e9e6;--paper:#f4f7f4;--sage:#315f52;--warm:#f3eadc}}
*{{box-sizing:border-box}}body{{margin:0;color:var(--ink);font-family:"Avenir Next","PingFang SC",sans-serif;background:radial-gradient(circle at 8% 0,#dfece5 0,transparent 30%),radial-gradient(circle at 94% 8%,#f0e3cf 0,transparent 27%),var(--paper)}}
main{{max-width:1560px;margin:auto;padding:44px 30px 72px}}header{{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:28px}}h1{{font-size:clamp(30px,4vw,56px);letter-spacing:-.055em;margin:4px 0 8px}}header p{{margin:0;color:var(--muted);max-width:720px;line-height:1.7}}.stamp{{font-size:12px;letter-spacing:.16em;color:var(--sage)}}
.source{{display:grid;grid-template-columns:minmax(220px,360px) 1fr;gap:28px;background:#ffffffc9;border:1px solid #fff;border-radius:28px;padding:22px;box-shadow:0 24px 70px #26463a12;margin-bottom:28px}}.source img{{width:100%;aspect-ratio:3/4;object-fit:contain;border-radius:19px;background:#edf0ee}}.source-copy{{max-height:380px;overflow:auto;line-height:1.75;color:#4a5551;padding-right:8px}}.source h2{{font-size:24px;margin:5px 0 12px}}
.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}}.card{{position:relative;background:#fff;border:1px solid #ffffff;border-radius:27px;padding:18px;box-shadow:0 20px 60px #263d3510;overflow:hidden}}.card:before{{content:"";position:absolute;inset:0 0 auto;height:5px;background:#9ea9a5}}.card.light:before{{background:#c98b3e}}.card.interpretive:before{{background:#315f52}}.card-head{{display:flex;align-items:center;justify-content:space-between;gap:10px}}.card h2{{font-size:26px;margin:2px 0}}.eyebrow{{font-size:10px;letter-spacing:.16em;color:var(--muted)}}.status{{font-size:12px;padding:7px 10px;border-radius:999px;background:#edf6f0;color:#1e6a4b}}.status.fail{{background:#fff0ef;color:#a33b32}}.intent{{min-height:44px;color:var(--muted);font-size:13px;line-height:1.6}}.hero{{display:block;width:100%;aspect-ratio:3/4;object-fit:contain;background:#eef1ef;border-radius:18px}}.hero.missing{{display:grid;place-content:center;text-align:center;color:#9b443c;background:#fff3f1;padding:24px}}.hero.missing small{{display:block;max-width:280px;margin-top:8px;line-height:1.5}}.card h3{{font-size:19px;margin:18px 2px 10px}}.copy{{font-size:14px;line-height:1.82;max-height:310px;overflow:auto;padding:15px;background:#f7f8f7;border-radius:15px}}details{{margin-top:14px;border-top:1px solid var(--line);padding-top:13px}}summary{{cursor:pointer;font-weight:600;font-size:13px}}details p{{font-size:12px;line-height:1.6;color:#59635f}}table{{width:100%;border-collapse:collapse;font-size:11px}}th,td{{padding:7px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
@media(max-width:1050px){{.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:700px){{main{{padding:22px 14px 50px}}header{{display:block}}.stamp{{margin-top:16px}}.source{{grid-template-columns:1fr}}.grid{{grid-template-columns:1fr}}}}
</style></head><body><main><header><div><span class="eyebrow">HERMES · SAME SOURCE CONTROL TEST</span><h1>同一母稿，三档创作幅度</h1><p>三档使用同一篇母文、同一张母图、同一车型参考图与同一政策依据。车型、事实、禁用词和 OCR 始终按同一套硬规则校验。</p></div><div class="stamp">{dt.datetime.now().strftime('%Y.%m.%d %H:%M')} · LOCAL ONLY</div></header>
<section class="source"><img src="{source_image}" alt="固定母图"><div><span class="eyebrow">LOCKED SOURCE · 母文 #{source['mother']['id']} / 母图 #{source_post['selected_prompt_id']}</span><h2>{html.escape(str(source['mother']['title']))}</h2><div class="source-copy">{source_copy}</div></div></section>
<section class="grid">{''.join(cards)}</section></main></body></html>"""
    path = output_dir / "comparison.html"
    path.write_text(page, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--workers-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--image-model", default="gptimage2")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source = _load_json(args.source.resolve())
    source_post = source["post"]
    cases = _load_json(DEFAULT_CASES)
    case = cases[str(source_post["case_id"])]
    online = OnlineData()
    template = _template_from_source(source_post)
    car_images = {str(source_post["vehicle_image"]["label"]): str(source_post["vehicle_image"]["url"])}

    plans_path = output_dir / "image_plans.json"
    if plans_path.exists():
        saved_plans = _load_json(plans_path)
        items = [saved_plans[level] for level in LEVELS]
        for item in items:
            item["contract"] = adaptation_contract(item["level"])
            item["image_plan"]["adaptation_contract"] = adaptation_contract(item["level"])
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(LEVELS)) as executor:
            futures = {
                level: executor.submit(
                    _make_plan,
                    level=level,
                    worker_dir=args.workers_dir.resolve(),
                    template=template,
                    case=case,
                    car_images=car_images,
                    online=online,
                    model=args.model,
                    output_dir=output_dir,
                )
                for level in LEVELS
            }
            items = [futures[level].result() for level in LEVELS]
        atomic_json(plans_path, {item["level"]: item for item in items})

    if args.plan_only:
        print(json.dumps({
            "stage": "planned",
            "plans": {
                item["level"]: {
                    "visual_changes": item["image_plan"].get("visual_changes") or [],
                    "scene_change": item["image_plan"].get("scene_change"),
                }
                for item in items
            },
        }, ensure_ascii=False), flush=True)
        return 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(LEVELS)) as executor:
        futures = {
            item["level"]: executor.submit(
                _generate_image,
                item=item,
                online=online,
                case=case,
                image_model=args.image_model,
                output_dir=output_dir,
            )
            for item in items
        }
        for item in items:
            item["generation"] = futures[item["level"]].result()

    ocr = compile_ocr(output_dir)
    for item in items:
        local_image = str((item.get("generation") or {}).get("local_image") or "")
        if not local_image:
            item["image_validation"] = {
                "pass": False,
                "hard_errors": [str(item["generation"].get("error") or "图片生成失败")],
                "ocr_lines": [],
            }
            continue
        image_path = output_dir / local_image
        lines = ocr_image(ocr, image_path)
        errors = image_ocr_errors(lines, copy=item["copy"], case=case)
        item["image_validation"] = {
            "pass": not errors,
            "hard_errors": errors,
            "ocr_lines": lines,
        }

    payload = {"source": source, "items": items}
    atomic_json(output_dir / "comparison.json", payload)
    page = _render(output_dir, source, items)
    print(json.dumps({
        "stage": "done",
        "html": str(page),
        "levels": {
            item["level"]: {
                "copy_pass": not (item.get("copy_validation") or {}).get("hard_errors"),
                "image_pass": bool((item.get("image_validation") or {}).get("pass")),
                "task_id": item["generation"].get("task_id"),
            }
            for item in items
        },
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
