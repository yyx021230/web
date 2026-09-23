#!/usr/bin/env python3
"""Generate six vehicle samples across six review-only adaptation gradients."""

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

from compare_adaptation_levels import _template_from_source
from core import angle_for_prompt, image_ocr_errors, validate_copy, validate_image_plan
from creative_profiles import (
    ADAPTATION_CONTRACT_VERSION,
    adaptation_contract,
    interpretive_layout_by_id,
    interpretive_layout_direction,
    interpretive_narrative_direction,
)
from run_daily_8x5 import (
    DEFAULT_CASES,
    NEGATIVE_PROMPT,
    OnlineData,
    atomic_json,
    build_image_plan,
    compile_ocr,
    image_layout_type_contract_errors,
    make_generation_prompt,
    ocr_image,
    request_json,
    run_copy_subprocess,
    source_layout_contract,
    visual_change_contract_errors,
)
from test_selected_prompt import download, wait_task
from worker_runtime import load_dotenv


LEVELS = ("g1", "g2", "g3", "g4", "g5", "g6")
LEVEL_CONFIG: dict[str, dict[str, str]] = {
    "g1": {
        "name": "原样复刻", "profile": "replica",
        "instruction": "只替换车型和必要事实，最大程度保留母文、母图与原有表达。",
    },
    "g2": {
        "name": "克制润色", "profile": "light",
        "instruction": "保留段落顺序和画面阅读顺序，只优化标题钩子、语句顺滑度、主色与一个非颜色视觉维度。",
    },
    "g3": {
        "name": "轻度微改", "profile": "light",
        "instruction": "保留信息链路和图片功能类型，明显改写标题与正文表达，并完成两项清晰视觉变化。",
    },
    "g4": {
        "name": "结构改编", "profile": "interpretive",
        "instruction": "锁定母文选题、图片功能类型和核心阅读关系，允许重组叙事段落及同类型内部版面骨架，但整体仍能看出母样逻辑。",
    },
    "g5": {
        "name": "灵感改编", "profile": "interpretive",
        "instruction": "保留事实优先级、说服目的和图片功能类型，改用新的内容切口、叙事节奏和同类型视觉方案。",
    },
    "g6": {
        "name": "开放演绎", "profile": "interpretive",
        "instruction": "在车型、事实、图片功能类型和信息关系完全不变的硬边界内，使用最大创作自由度重做小红书表达与视觉语言；单图主视觉只能在同类海报内部变化，禁止改成表格、卡片、清单、文档或多图拼贴。",
    },
}
LEVEL_NAMES = {key: value["name"] for key, value in LEVEL_CONFIG.items()}
SAMPLE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "hook-poster",
        "label": "强钩子促销母样",
        "case_id": "a05-current",
        "mother_id": 1114,
        "prompt_id": 191,
        "layout": "kinetic_collage",
        "instruction": "围绕405与510续航选择组织内容；城市只能承接地方政策流程和适用条件。",
    },
    {
        "key": "policy-document",
        "label": "政策说明母样",
        "case_id": "a10-current",
        "mother_id": 1158,
        "prompt_id": 662,
        "layout": "asymmetric_editorial",
        "instruction": "围绕预算、续航和适用条件组织内容；不得把政策说明写成完整报价单。",
    },
    {
        "key": "benefit-cards",
        "label": "权益卡片母样",
        "case_id": "b10-current",
        "mother_id": 1188,
        "prompt_id": 680,
        "layout": "paper_cutout",
        "instruction": "围绕选装基金、家充服务和对应适用版本做权益核对；不重复索取已公开信息。图片必须保留至少三张彼此独立的权益卡片，禁止改成单图海报、表格或清单；图片中不要出现“地方补贴”字样，避免与综合权益金额形成错误对应。",
    },
    {
        "key": "driver-diary",
        "label": "新手通勤日记母样",
        "case_id": "c10-current",
        "mother_id": 1155,
        "prompt_id": 640,
        "layout": "spatial_installation",
        "instruction": "围绕新手通勤的续航与补能选择组织内容；可以代入场景，但不得虚构亲身试驾或长期用车经历。",
    },
    {
        "key": "version-choice",
        "label": "版本选择对照母样",
        "case_id": "c16-current",
        "mother_id": 1375,
        "prompt_id": 647,
        "layout": "technical_dossier",
        "instruction": "围绕405与510续航对应的不同使用半径做选择题；最多举两个有依据的版本，不扩写其他车型。",
    },
    {
        "key": "city-policy-story",
        "label": "城市政策场景母样",
        "case_id": "d19-current",
        "mother_id": 1192,
        "prompt_id": 652,
        "layout": "kinetic_collage",
        "instruction": "围绕不同城市政策适用条件需要分别核对来组织内容；地方补贴只概括提及，不展示地方金额。",
    },
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def eligible_cached_copy(
    *, output_dir: Path, key: str, level: str, mother: dict[str, Any], case: dict[str, Any],
    creative_direction: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    profile = LEVEL_CONFIG[level]["profile"]
    candidates = sorted((output_dir / "workers").glob(f"{key}-{level}-*.output.json"))
    for path in reversed(candidates):
        result = load_json(path)
        if not result.get("ok"):
            continue
        if result.get("process_returncode") not in (None, 0):
            continue
        if (
            profile == "interpretive"
            and (result.get("adaptation_contract") or {}).get("version") != ADAPTATION_CONTRACT_VERSION
        ):
            continue
        if creative_direction and result.get("creative_direction") != creative_direction:
            continue
        validation = validate_copy(
            title=str(result.get("title") or ""),
            content=str(result.get("content") or ""),
            mother=mother,
            case=case,
            adaptation_level=profile,
        )
        if not validation.get("hard_errors"):
            result["validation"] = validation
            return result
    return None


def generate_copy(
    *, spec: dict[str, Any], level: str, mother: dict[str, Any], case: dict[str, Any],
    output_dir: Path, model: str, creative_direction: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    profile = LEVEL_CONFIG[level]["profile"]
    gradient_instruction = LEVEL_CONFIG[level]["instruction"]
    cached = None if force else eligible_cached_copy(
        output_dir=output_dir, key=str(spec["key"]), level=level, mother=mother, case=case,
        creative_direction=creative_direction,
    )
    if cached:
        return cached
    failures: list[dict[str, Any]] = []
    for attempt in range(1, 5):
        narrative = (creative_direction or {}).get("narrative") or {}
        direction_instruction = (
            f"\n本篇差异化叙事骨架【{narrative.get('name')}】：{narrative.get('brief')}"
            "必须让开头、推进方式和结尾都体现该骨架，不得退回通用的场景提问—建议—注意事项结构。"
            if narrative else ""
        )
        result = run_copy_subprocess({
            "key": f"{spec['key']}-{level}",
            "case_id": str(case["case_id"]),
            "mother_id": int(mother["id"]),
            "model": model,
            "avoidance_brief": {},
            "operator_instruction": (
                str(spec["instruction"]) + "\n本梯度要求：" + gradient_instruction + direction_instruction
            ),
            "adaptation_level": profile,
        }, output_dir, f"a{attempt}")
        if result.get("ok"):
            result["creative_direction"] = creative_direction or {}
            atomic_json(output_dir / "workers" / f"{spec['key']}-{level}-a{attempt}.output.json", result)
            return result
        failures.append({
            "attempt": attempt,
            "error": result.get("error"),
            "validation": result.get("validation"),
        })
    return {"ok": False, "error": "all copy attempts failed", "failures": failures}


def build_item_plan(
    *, item: dict[str, Any], source: dict[str, Any], case: dict[str, Any], online: OnlineData,
    output_dir: Path, model: str, force: bool = False,
) -> dict[str, Any]:
    copy_result = item["copy_result"]
    if not copy_result.get("ok"):
        return item
    template = _template_from_source(source["post"])
    level = str(item["level"])
    profile = LEVEL_CONFIG[level]["profile"]
    required_layout = str(
        ((((item.get("creative_direction") or {}).get("layout") or {}).get("id")) or "")
    ) if profile == "interpretive" else None
    trace_dir = output_dir / "traces" / str(item["spec"]["key"]) / level
    if not force:
        for path in sorted(trace_dir.glob("*.validation.json"), reverse=True):
            saved = load_json(path)
            plan = saved.get("result")
            if isinstance(plan, dict):
                current_errors = validate_image_plan(plan, copy_result, case)
                current_errors.extend(visual_change_contract_errors(plan, profile))
                current_errors.extend(image_layout_type_contract_errors(plan, template, profile))
                if required_layout and plan.get("layout_archetype") != required_layout:
                    current_errors.append("cached layout no longer matches the assigned batch direction")
                if not current_errors:
                    return {**item, "image_plan": plan, "plan_reused": True}
    try:
        plan = build_image_plan(
            copy={"title": copy_result["title"], "content": copy_result["content"]},
            template=template,
            case=case,
            car_images=dict(source["car_images"]),
            model=model,
            attempts=3,
            public_root=online.public_root,
            operator_instruction=(
                str(item["spec"]["instruction"])
                + "\n本梯度要求："
                + LEVEL_CONFIG[level]["instruction"]
            ),
            adaptation_level=profile,
            required_layout_archetype=required_layout,
            trace_dir=trace_dir,
        )
        plan["creative_direction"] = item.get("creative_direction") or {}
        return {**item, "image_plan": plan}
    except Exception as exc:
        return {**item, "plan_error": f"{type(exc).__name__}: {exc}"}


def assign_creative_directions(sources: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Balance high-gradient writing and layout DNA across the whole review batch."""
    directions: dict[tuple[str, str], dict[str, Any]] = {}
    layout_usage: dict[str, int] = {}
    narrative_usage: dict[str, int] = {}
    layouts_by_sample: dict[str, set[str]] = {}
    narratives_by_sample: dict[str, set[str]] = {}
    for level in ("g4", "g5", "g6"):
        for source in sources:
            key = str(source["spec"]["key"])
            template = _template_from_source(source["post"])
            source_type = source_layout_contract(template)["id"]
            layout = interpretive_layout_direction(
                key, level, source["case"].get("vehicle_model"), template.get("id"),
                source_layout_type=source_type,
                usage_counts=layout_usage,
                excluded_ids=layouts_by_sample.setdefault(key, set()),
            )
            narrative = interpretive_narrative_direction(
                key, level, source["case"].get("vehicle_model"), source["mother"].get("id"),
                usage_counts=narrative_usage,
                excluded_ids=narratives_by_sample.setdefault(key, set()),
            )
            layout_usage[layout["id"]] = layout_usage.get(layout["id"], 0) + 1
            narrative_usage[narrative["id"]] = narrative_usage.get(narrative["id"], 0) + 1
            layouts_by_sample[key].add(layout["id"])
            narratives_by_sample[key].add(narrative["id"])
            directions[(key, level)] = {
                "layout": layout,
                "narrative": narrative,
                "source_layout_type": source_type,
            }
    return directions


def generate_image(
    *, item: dict[str, Any], online: OnlineData, case: dict[str, Any], image_model: str,
    output_dir: Path, force: bool = False,
) -> dict[str, Any]:
    sample_key = str(item["spec"]["key"])
    level = str(item["level"])
    image_path = output_dir / f"{sample_key}-{level}.png"
    if not force and image_path.exists() and image_path.stat().st_size > 0:
        return {
            "task_id": "reused-local", "attempt": 0, "local_image": image_path.name,
            "reused": True, "previous_failures": [],
        }
    prompt = make_generation_prompt(item["image_plan"], case)
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
    base_request_id = f"hm-{dt.date.today().isoformat()}-{sample_key[:18]}-{level[:4]}-{digest}"
    failures: list[dict[str, Any]] = []
    for attempt in range(1, 3):
        request_id = base_request_id if attempt == 1 else f"{base_request_id}-a{attempt}"
        try:
            response = request_json(
                online.backend + "/ai-image/generate",
                method="POST",
                headers=online.auth,
                body={
                    "prompt": prompt,
                    "client_request_id": request_id,
                    "negative_prompt": NEGATIVE_PROMPT,
                    "model": image_model,
                    "width": 1536,
                    "height": 2048,
                    "quality": "high",
                    "count": 1,
                    "images_data": [item["image_plan"]["vehicle_image"]["url"]],
                },
                timeout=180,
                attempts=3,
            )
        except Exception as exc:
            failures.append({"attempt": attempt, "error": f"{type(exc).__name__}: {exc}"})
            continue
        payload = response.get("data") if isinstance(response.get("data"), dict) else response
        task_id = str(payload.get("task_id") or "")
        if not task_id:
            failures.append({"attempt": attempt, "error": "image backend returned no task_id"})
            continue
        terminal = wait_task(online, task_id, image_model)
        urls = terminal.get("image_urls") if isinstance(terminal.get("image_urls"), list) else []
        if str(terminal.get("status") or "") != "completed" or not urls:
            failures.append({
                "attempt": attempt, "task_id": task_id,
                "error": str(terminal.get("error") or terminal),
            })
            continue
        download(online, str(urls[0]), image_path)
        return {
            "task_id": task_id, "attempt": attempt,
            "image_url": online.absolute_url(str(urls[0])),
            "local_image": image_path.name, "terminal": terminal,
            "previous_failures": failures,
        }
    return {
        "error": failures[-1]["error"] if failures else "image generation failed",
        "previous_failures": failures,
    }


def build_sources(
    *, base_source: dict[str, Any], cases: dict[str, Any], online: OnlineData, output_dir: Path,
) -> list[dict[str, Any]]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        mothers_future = executor.submit(online.mothers)
        prompts_future = executor.submit(online.prompts)
        mothers = {int(row["id"]): row for row in mothers_future.result()}
        prompts = {int(row["id"]): row for row in prompts_future.result()}
    sources: list[dict[str, Any]] = []
    for spec in SAMPLE_SPECS:
        mother = mothers.get(int(spec["mother_id"]))
        prompt = prompts.get(int(spec["prompt_id"]))
        if not mother or not prompt:
            raise RuntimeError(f"missing source for {spec['key']}: mother={bool(mother)} prompt={bool(prompt)}")
        case_id = str(spec["case_id"])
        case = dict(cases[case_id])
        case["case_id"] = case_id
        car_images = online.car_images(str(case["brand"]), str(case["vehicle_model"]))
        desired_angle = angle_for_prompt(str(prompt.get("chinese") or ""))
        if desired_angle not in car_images:
            desired_angle = next(iter(car_images))
        post = dict(base_source["post"])
        post.update({
            "case_id": case_id,
            "vehicle_model": str(case["vehicle_model"]),
            "selected_prompt_id": int(prompt["id"]),
            "selected_prompt_name": str(prompt.get("name") or prompt.get("title") or ""),
            "selected_prompt_original": str(prompt.get("chinese") or ""),
            "selected_prompt_image": online.absolute_url(str(prompt.get("image_url") or "")),
            "selected_prompt_source_section": prompt.get("source_section_title"),
            "selected_prompt_full_original": prompt.get("source_full_original"),
            "selected_prompt_structure_id": str(prompt.get("structure_id") or ""),
            "image_template_type": str(prompt.get("template_type") or "standard"),
            "source_slot_count": int(prompt.get("source_slot_count") or 0),
            "vehicle_image": {"label": desired_angle, "url": car_images[desired_angle]},
        })
        sources.append({
            "spec": dict(spec), "mother": mother, "post": post,
            "case": case, "car_images": car_images,
        })
    atomic_json(output_dir / "sources.json", {"sources": sources})
    atomic_json(output_dir / "assigned_mothers.json", {"mothers": [row["mother"] for row in sources]})
    return sources


def render(output_dir: Path, sources: list[dict[str, Any]], items: list[dict[str, Any]]) -> Path:
    item_map = {(str(row["spec"]["key"]), str(row["level"])): row for row in items}
    rows: list[str] = []
    for sample_index, source in enumerate(sources, start=1):
        spec = source["spec"]
        cards: list[str] = []
        for level_index, level in enumerate(LEVELS, start=1):
            item = item_map[(str(spec["key"]), level)]
            copy_result = item.get("copy_result") or {}
            generation = item.get("generation") or {}
            image_validation = item.get("image_validation") or {}
            errors = list((copy_result.get("validation") or {}).get("hard_errors") or [])
            errors.extend(image_validation.get("hard_errors") or [])
            if item.get("plan_error"):
                errors.append(str(item["plan_error"]))
            image_name = html.escape(str(generation.get("local_image") or ""))
            image_markup = (
                f'<img src="{image_name}" alt="样本{sample_index}-{level_index}">'
                if image_name else f'<div class="missing">{html.escape(str(generation.get("error") or "生成失败"))}</div>'
            )
            content = html.escape(str(copy_result.get("content") or "")).replace("\n", "<br>")
            profile = LEVEL_CONFIG[level]["profile"]
            contract = adaptation_contract(profile)
            plan = item.get("image_plan") or {}
            layout = interpretive_layout_by_id(plan.get("layout_archetype"))
            layout_name = str(layout["name"]) if layout else "沿用母版骨架"
            cards.append(f"""
            <article class="card {level}">
              <div class="card-head"><div><span>0{level_index} / {html.escape(level.upper())}</span><h3>{html.escape(LEVEL_NAMES[level])}</h3></div><b class="{'ok' if not errors else 'bad'}">{'通过' if not errors else f'{len(errors)}项错误'}</b></div>
              <p class="intent">{html.escape(LEVEL_CONFIG[level]['instruction'])}</p>
              {image_markup}
              <section><small>{html.escape(layout_name)}</small><h4>{html.escape(str(copy_result.get('title') or '文案生成失败'))}</h4><div class="copy">{content}</div></section>
              <details><summary>查看校验与构图依据</summary><p>{html.escape('；'.join(errors) or '事实、转化逻辑、禁用词、图片文字与OCR均通过')}</p><p>{html.escape(str(plan.get('composition_signature') or ''))}</p></details>
            </article>""")
        source_image = html.escape(str(source["post"].get("selected_prompt_image") or ""))
        source_copy = html.escape(str(source["mother"].get("content") or "")).replace("\n", "<br>")
        rows.append(f"""
        <section class="sample">
          <div class="sample-title"><div><span>SAMPLE 0{sample_index}</span><h2>{html.escape(str(source['case']['vehicle_model']))} · {html.escape(str(spec['label']))}</h2><p>母文 #{int(source['mother']['id'])} · 母图 #{int(source['post']['selected_prompt_id'])}</p></div><button type="button" data-target="source-{sample_index}">查看固定母样</button></div>
          <div id="source-{sample_index}" class="source"><img src="{source_image}" alt="第{sample_index}组母图"><div><h3>{html.escape(str(source['mother'].get('title') or ''))}</h3><div>{source_copy}</div></div></div>
          <div class="grid">{''.join(cards)}</div>
        </section>""")
    page = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Hermes 六车六梯度评审</title><style>
:root{{--ink:#17201d;--muted:#68736f;--line:#dfe6e2;--paper:#edf2ef;--green:#214f42;--amber:#b86b22;--blue:#355e77}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;color:var(--ink);font-family:"Avenir Next","PingFang SC",sans-serif;background:radial-gradient(circle at 8% 0,#cfdfd5 0,transparent 28%),radial-gradient(circle at 94% 3%,#eadac6 0,transparent 25%),var(--paper)}}body:before{{content:"";position:fixed;inset:0;pointer-events:none;opacity:.22;background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 160 160' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.12'/%3E%3C/svg%3E")}}main{{position:relative;max-width:1800px;margin:auto;padding:54px 28px 90px}}header{{display:grid;grid-template-columns:1fr auto;gap:30px;align-items:end;margin-bottom:42px}}header span,.sample-title span,.card-head span{{font-size:10px;letter-spacing:.16em;color:var(--muted)}}h1{{max-width:900px;margin:7px 0 9px;font-family:"Iowan Old Style","Songti SC",serif;font-size:clamp(38px,5vw,70px);font-weight:500;line-height:.98;letter-spacing:-.055em}}header p{{max-width:780px;margin:0;color:var(--muted);line-height:1.75}}.stamp{{writing-mode:vertical-rl;font-size:11px;letter-spacing:.14em;color:var(--green)}}.sample{{margin-top:34px;padding:22px;border:1px solid #ffffffbd;border-radius:32px;background:#f9fbf9b8;box-shadow:0 28px 80px #1c352d12;backdrop-filter:blur(18px)}}.sample-title{{display:flex;justify-content:space-between;align-items:end;gap:20px;padding:2px 4px 18px}}.sample-title h2{{margin:4px 0;font-family:"Iowan Old Style","Songti SC",serif;font-size:30px;font-weight:500}}.sample-title p{{margin:0;color:var(--muted);font-size:12px}}button{{border:1px solid var(--line);border-radius:999px;background:#fff;padding:9px 14px;color:var(--ink);cursor:pointer}}button:hover{{border-color:#9fb4aa;background:#f5f8f6}}.source{{display:none;grid-template-columns:180px 1fr;gap:18px;margin:0 3px 18px;padding:14px;border-radius:20px;background:#edf1ee}}.source.open{{display:grid}}.source img{{width:100%;aspect-ratio:3/4;object-fit:contain;border-radius:13px;background:#dfe5e1}}.source h3{{margin:5px 0 10px;font-size:18px}}.source div div{{max-height:210px;overflow:auto;color:#57625e;font-size:12px;line-height:1.7}}.grid{{display:grid;grid-template-columns:repeat(6,minmax(300px,1fr));gap:16px;overflow-x:auto;padding-bottom:10px}}.card{{position:relative;min-width:0;padding:14px;border:1px solid #fff;border-radius:24px;background:#fff;box-shadow:0 16px 42px #23372f0d;overflow:hidden}}.card:before{{content:"";position:absolute;inset:0 0 auto;height:4px;background:#9aa5a0}}.card.g2:before{{background:#9d8d58}}.card.g3:before{{background:var(--amber)}}.card.g4:before{{background:#7770a7}}.card.g5:before{{background:var(--blue)}}.card.g6:before{{background:var(--green)}}.card-head{{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:2px 2px 8px}}.card h3{{margin:3px 0 0;font-size:21px}}.card b{{padding:6px 9px;border-radius:99px;font-size:10px}}.ok{{color:#176047;background:#e8f4ec}}.bad{{color:#9c3932;background:#ffefed}}.intent{{min-height:54px;margin:0 2px 10px;color:var(--muted);font-size:12px;line-height:1.55}}.card img,.missing{{display:block;width:100%;aspect-ratio:3/4;object-fit:contain;border-radius:16px;background:#e8ece9}}.missing{{display:grid;place-items:center;color:#9c3932}}.card section{{padding:14px 2px 2px}}.card section small{{color:var(--muted);font-size:10px;letter-spacing:.08em}}.card h4{{margin:5px 0 10px;font-size:18px}}.copy{{max-height:310px;overflow:auto;padding:12px;border-radius:13px;background:#f4f6f4;font-size:12px;line-height:1.72}}details{{margin:12px 2px 1px;padding-top:11px;border-top:1px solid var(--line)}}summary{{cursor:pointer;font-size:11px;font-weight:600}}details p{{color:var(--muted);font-size:11px;line-height:1.55}}@media(max-width:1050px){{.card{{width:320px}}}}@media(max-width:680px){{main{{padding:28px 10px 55px}}header{{display:block}}.stamp{{display:none}}.sample{{padding:12px;border-radius:23px}}.source{{grid-template-columns:1fr}}.grid{{grid-template-columns:repeat(6,minmax(285px,1fr))}}.card{{width:auto}}}}
</style></head><body><main><header><div><span>HERMES · SIX VEHICLES × SIX GRADIENTS</span><h1>{len(sources)}款车型，每款完整跑六档。</h1><p>每一行固定同一篇母文、同一张母图、同一车型图与同一政策依据，只逐级增加创作自由度；车型、事实、禁用词和图片功能类型始终是硬约束。</p></div><div class="stamp">{dt.datetime.now().strftime('%Y.%m.%d %H:%M')} · LOCAL REVIEW</div></header>{''.join(rows)}</main><script>document.querySelectorAll('button[data-target]').forEach(function(button){{button.addEventListener('click',function(){{var panel=document.getElementById(button.dataset.target);panel.classList.toggle('open');button.textContent=panel.classList.contains('open')?'收起固定母样':'查看固定母样';}});}});</script></body></html>"""
    path = output_dir / "comparison.html"
    path.write_text(page, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--image-model", default="gptimage2")
    parser.add_argument("--plan-workers", type=int, default=3)
    parser.add_argument("--image-workers", type=int, default=3)
    parser.add_argument(
        "--force-level", action="append", choices=LEVELS, default=[],
        help="Regenerate the selected level instead of reusing local copy, plan, or image caches.",
    )
    parser.add_argument(
        "--force-item", action="append", default=[], metavar="KEY:LEVEL",
        help="Regenerate one item's image plan and image while reusing its approved copy.",
    )
    parser.add_argument(
        "--force-copy-item", action="append", default=[], metavar="KEY:LEVEL",
        help="Regenerate one item's copy while allowing an approved image plan and image to remain cached.",
    )
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parents[2] / "backend" / ".env")
    source_payload = load_json(args.source.resolve())
    base_source = (
        source_payload["sources"][0]
        if isinstance(source_payload.get("sources"), list) and source_payload["sources"]
        else source_payload
    )
    if not isinstance(base_source, dict) or not isinstance(base_source.get("post"), dict):
        raise ValueError("source must contain a post object or a non-empty sources array")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    online = OnlineData()
    cases = load_json(DEFAULT_CASES)
    sources = build_sources(
        base_source=base_source, cases=cases, online=online, output_dir=output_dir,
    )
    creative_directions = assign_creative_directions(sources)
    os.environ["XHS_CASES_PATH"] = str(DEFAULT_CASES)
    os.environ["XHS_ASSIGNED_MOTHERS_PATH"] = str(output_dir / "assigned_mothers.json")

    copy_jobs = [
        (source, level) for source in sources for level in LEVELS
    ]
    items: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, min(args.plan_workers, len(copy_jobs)))
    ) as executor:
        futures = [executor.submit(
            generate_copy,
            spec=source["spec"], level=level, mother=source["mother"], case=source["case"],
            output_dir=output_dir, model=args.model,
            creative_direction=creative_directions.get((str(source["spec"]["key"]), level)),
            force=(
                level in args.force_level
                or f"{source['spec']['key']}:{level}" in args.force_copy_item
            ),
        ) for source, level in copy_jobs]
        for (source, level), future in zip(copy_jobs, futures):
            items.append({
                "spec": source["spec"], "source": source, "level": level,
                "creative_direction": creative_directions.get((str(source["spec"]["key"]), level), {}),
                "copy_result": future.result(),
            })
    failures = [f"{row['spec']['key']}:{row['level']}" for row in items if not row["copy_result"].get("ok")]
    if failures:
        atomic_json(output_dir / "comparison.json", {"sources": sources, "items": items})
        raise RuntimeError(f"copy generation failed: {failures}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.plan_workers, len(items)))) as executor:
        futures = [executor.submit(
            build_item_plan,
            item=item, source=item["source"], case=item["source"]["case"], online=online,
            output_dir=output_dir, model=args.model,
            force=(item["level"] in args.force_level or f"{item['spec']['key']}:{item['level']}" in args.force_item),
        ) for item in items]
        items = [future.result() for future in futures]

    ready = [row for row in items if row.get("image_plan")]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.image_workers, len(ready)))) as executor:
        futures = [executor.submit(
            generate_image,
            item=item, online=online, case=item["source"]["case"], image_model=args.image_model, output_dir=output_dir,
            force=(item["level"] in args.force_level or f"{item['spec']['key']}:{item['level']}" in args.force_item),
        ) for item in ready]
        for item, future in zip(ready, futures):
            item["generation"] = future.result()

    ocr = compile_ocr(output_dir)
    for item in items:
        generation = item.get("generation") or {}
        image_name = str(generation.get("local_image") or "")
        if not image_name:
            item["image_validation"] = {
                "pass": False,
                "hard_errors": [str(generation.get("error") or item.get("plan_error") or "图片生成失败")],
                "ocr_lines": [],
            }
            continue
        lines = ocr_image(ocr, output_dir / image_name)
        copy = {"title": item["copy_result"]["title"], "content": item["copy_result"]["content"]}
        errors = image_ocr_errors(lines, copy=copy, case=item["source"]["case"])
        item["image_validation"] = {"pass": not errors, "hard_errors": errors, "ocr_lines": lines}

    atomic_json(output_dir / "comparison.json", {
        "contract_versions": {
            level: adaptation_contract(LEVEL_CONFIG[level]["profile"]) for level in LEVELS
        },
        "sources": sources,
        "items": items,
    })
    page = render(output_dir, sources, items)
    print(json.dumps({
        "stage": "done", "html": str(page), "sample_groups": len(sources), "outputs": len(items),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
