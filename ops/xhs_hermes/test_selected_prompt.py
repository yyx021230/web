#!/usr/bin/env python3
"""Force one selected image prompt through the production adaptation and OCR path."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from core import (
    angle_for_prompt,
    image_ocr_errors,
    normalize_structure,
    source_slot_count,
    structure_digest,
    validate_image_plan,
)
from run_daily_8x5 import (
    DEFAULT_CASES,
    NEGATIVE_PROMPT,
    ROOT,
    TRANSIENT_HTTP,
    HttpFailure,
    OnlineData,
    atomic_json,
    build_image_plan,
    compile_ocr,
    load_dotenv,
    make_generation_prompt,
    ocr_image,
    request_json,
)


def wait_task(online: OnlineData, task_id: str, model: str) -> dict[str, Any]:
    deadline = time.time() + 1800
    transient = 0
    while time.time() < deadline:
        query = urllib.parse.urlencode({"model": model, "timeout_seconds": 20, "poll_seconds": 2})
        try:
            response = request_json(
                f"{online.backend}/ai-image/tasks/{task_id}/wait?{query}",
                headers=online.auth,
                timeout=50,
                attempts=1,
            )
        except Exception as exc:
            message = str(exc)
            if (
                (isinstance(exc, HttpFailure) and exc.status in TRANSIENT_HTTP)
                or any(marker in message for marker in ("HTTP 408", "HTTP 409", "HTTP 425", "HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504"))
            ):
                transient += 1
                time.sleep(min(10, 2 + transient))
                continue
            if any(marker in message for marker in ("timed out", "RemoteDisconnected")):
                transient += 1
                time.sleep(min(10, 2 + transient))
                continue
            raise
        data = response.get("data") if isinstance(response.get("data"), dict) else response
        if str(data.get("status") or "") in {"completed", "failed", "cancelled"}:
            return data
        time.sleep(2)
    raise RuntimeError(f"image task {task_id} timed out")


def download(online: OnlineData, url: str, path: Path) -> None:
    request = urllib.request.Request(online.absolute_url(url), method="GET")
    with urllib.request.urlopen(request, timeout=180) as response:
        data = response.read(25 * 1024 * 1024 + 1)
    if not data or len(data) > 25 * 1024 * 1024:
        raise RuntimeError("generated image is empty or over 25 MB")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def structural_salvage_plan(
    *,
    template: dict[str, Any],
    copy: dict[str, Any],
    case: dict[str, Any],
    car_images: dict[str, str],
    public_root: str,
) -> dict[str, Any]:
    """Keep prompt 519's visual skeleton while replacing its unsafe quote grid."""

    source = str(template.get("chinese") or "")
    desired_angle = angle_for_prompt(source)
    if desired_angle not in car_images:
        desired_angle = next(iter(car_images))
    blocks = [
        "零跑A05",
        "9月权益更新",
        "6.39万-9.09万",
        "上市指导价区间",
        "增换购补贴3000元/台",
        "金融贴息至高2236元",
        "国补至高10908元",
        "7kW充电桩价值2680元",
        "留【城市】了解政策明细",
    ]
    prompt = (
        "竖版3:4新能源汽车商业宣传海报，8K超高清，专业汽车商业摄影，电影级黄昏落日光影，"
        "黑金高级质感，暗调氛围感大片。背景完整保留母版的黄昏城市滨江观景平台、黑色亮面"
        "抛光大理石地面、左侧现代玻璃幕墙建筑、远处摩天建筑群、湖面落日倒影和橘金渐变晚霞。"
        "主体车辆严格绘制车型库辅助图中的零跑A05，画面下半区域，45度前侧视角，车身完整，"
        "保留真实车标、灯组、车身比例和轮毂，只沿用母版的镜头位置与金色轮廓光。"
        "整体排版继续使用母版的顶部品牌区、超大双层主标题、中央超大数字区、四个横向深色"
        "半透明圆角权益模块、底部长条权益清单区和金色细光带。不得绘制旧车型成交数字或"
        "逐版本价格。顶部主标题依次为“零跑A05”“9月权益更新”；中央视觉核心只写"
        "“6.39万-9.09万”，其下小字“上市指导价区间”；四个横向权益模块依次写"
        "“增换购补贴3000元/台”“金融贴息至高2236元”“国补至高10908元”"
        "“7kW充电桩价值2680元”；底部长条区域写“留【城市】了解政策明细”。"
        "全部文字只使用白色与烫金渐变金色，商务无衬线粗体，文字不遮挡车身，边缘锐利，"
        "主次层级与母版一致。"
    )
    plan = {
        "adapted_prompt": prompt,
        "text_blocks": blocks,
        "slot_mappings": [
            {"source": "零跑C10", "output": blocks[0], "action": "替换旧车型"},
            {"source": "七月新政", "output": blocks[1], "action": "替换过期月份"},
            {"source": "10.76", "output": blocks[2], "action": "替换无依据成交数字"},
            {"source": "(含国补+置换清凉礼)", "output": blocks[3], "action": "改为已登记口径"},
            {"source": "夏季清凉礼 2000元", "output": blocks[4], "action": "替换为本篇权益"},
            {"source": "置换补贴 7000元", "output": blocks[5], "action": "替换为本篇权益"},
            {"source": "国补 17136元", "output": blocks[6], "action": "替换为本篇权益"},
            {"source": "车型版本、裸车价(元)", "output": blocks[7], "action": "将危险报价区域改为权益区域"},
            {"source": "申请条件 锁单/已订车", "output": blocks[8], "action": "替换为安全CTA"},
        ],
        "scene_change": "保留黄昏滨江黑金场景，仅将车辆换成车型库中的零跑A05",
        "vehicle_angle": desired_angle,
        "selected_prompt_id": int(template.get("id") or 0),
        "selected_prompt_name": str(template.get("name") or template.get("title") or ""),
        "selected_prompt_original": source,
        "selected_prompt_structure_id": structure_digest(normalize_structure(source)),
        "source_slot_count": int(template.get("source_slot_count") or 0),
        "selected_prompt_image": (
            str(template.get("image_url"))
            if str(template.get("image_url") or "").startswith("http")
            else public_root + str(template.get("image_url") or "")
        ),
        "vehicle_image": {"label": desired_angle, "url": car_images[desired_angle]},
        "plan_attempt": 1,
        "forced_structural_salvage": True,
    }
    errors = validate_image_plan(plan, copy, case)
    if errors:
        raise RuntimeError("structural salvage plan failed: " + "；".join(errors))
    return plan


def render(output_dir: Path, payload: dict[str, Any]) -> Path:
    prompt = payload["source_prompt"]
    plan = payload["image_plan"]
    copy = payload["copy"]
    mappings = "".join(
        f"<tr><td>{html.escape(str(row.get('source') or ''))}</td>"
        f"<td>{html.escape(str(row.get('action') or ''))}</td>"
        f"<td>{html.escape(str(row.get('output') or ''))}</td></tr>"
        for row in plan.get("slot_mappings") or []
    )
    page = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>精选 #{prompt['id']} 强制测试</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;background:#f5f5f5;color:#171717;margin:0}}main{{max-width:1180px;margin:auto;padding:24px}}section{{background:#fff;padding:20px;border-radius:16px;margin:16px 0}}.images{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}img{{width:100%;aspect-ratio:3/4;object-fit:contain;background:#eee;border-radius:12px}}pre{{white-space:pre-wrap;line-height:1.65;background:#fafafa;padding:14px;border-radius:10px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border:1px solid #ddd;text-align:left;vertical-align:top}}@media(max-width:760px){{.images{{grid-template-columns:1fr}}}}
</style></head><body><main><h1>精选 #{prompt['id']} · 强制安全改造测试</h1><section class="images"><div><h2>原母图</h2><img src="{html.escape(str(payload['source_image']))}"></div><div><h2>改造后成图</h2><img src="{html.escape(str(payload['local_image']))}"></div></section><section><h2>测试文案</h2><h3>{html.escape(str(copy['title']))}</h3><pre>{html.escape(str(copy['content']))}</pre></section><section><h2>逐槽映射</h2><table><thead><tr><th>原文字</th><th>动作</th><th>新文字</th></tr></thead><tbody>{mappings}</tbody></table></section><section><h2>原提示词</h2><pre>{html.escape(str(prompt['chinese']))}</pre></section><section><h2>改造后提示词</h2><pre>{html.escape(str(plan['adapted_prompt']))}</pre></section></main></body></html>"""
    path = output_dir / "精选提示词对照.html"
    path.write_text(page, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-id", type=int, required=True)
    parser.add_argument("--delivery", type=Path, required=True)
    parser.add_argument("--copy-key", required=True)
    parser.add_argument("--case-id", default="a05-current")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--image-model", default="gptimage2")
    parser.add_argument("--structural-salvage", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    delivery = json.loads(args.delivery.read_text(encoding="utf-8"))
    copy = next((row for row in delivery.get("posts") or [] if row.get("key") == args.copy_key), None)
    if copy is None:
        raise KeyError(f"copy key not found: {args.copy_key}")
    copy = {"title": copy["title"], "content": copy["content"]}
    cases = json.loads(DEFAULT_CASES.read_text(encoding="utf-8"))
    case = cases[args.case_id]
    online = OnlineData()
    template = next((row for row in online.prompts() if int(row.get("id") or 0) == args.prompt_id), None)
    if template is None:
        raise KeyError(f"prompt not found: {args.prompt_id}")
    template = dict(template)
    template["source_slot_count"] = source_slot_count(str(template.get("chinese") or ""))
    source_image = online.absolute_url(str(template.get("image_url") or ""))
    car_images = online.car_images(str(case["brand"]), str(case["vehicle_model"]))
    if args.structural_salvage:
        plan = structural_salvage_plan(
            template=template,
            copy=copy,
            case=case,
            car_images=car_images,
            public_root=online.public_root,
        )
    else:
        plan = build_image_plan(
            copy=copy,
            template=template,
            case=case,
            car_images=car_images,
            model=args.model,
            attempts=3,
            public_root=online.public_root,
        )
    generation_prompt = make_generation_prompt(plan, case)
    fingerprint = hashlib.sha256(
        f"{args.prompt_id}\n{args.copy_key}\n{generation_prompt}".encode("utf-8")
    ).hexdigest()[:14]
    ocr_binary = compile_ocr(output_dir)
    failures: list[dict[str, Any]] = []
    result: dict[str, Any] | None = None
    for attempt in range(1, 3):
        correction = "；".join(failures[-1].get("errors") or []) if failures else ""
        prompt = make_generation_prompt(plan, case, correction)
        response = request_json(
            online.backend + "/ai-image/generate",
            method="POST",
            headers=online.auth,
            body={
                "prompt": prompt,
                "client_request_id": f"hermes-prompt-test-{dt.date.today().isoformat()}-{args.prompt_id}-{args.copy_key}-a{attempt}-{fingerprint}",
                "negative_prompt": NEGATIVE_PROMPT,
                "model": args.image_model,
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
            raise RuntimeError("image backend returned no task_id")
        print(json.dumps({"stage": "submitted", "task_id": task_id, "attempt": attempt}), flush=True)
        terminal = wait_task(online, task_id, args.image_model)
        urls = terminal.get("image_urls") if isinstance(terminal.get("image_urls"), list) else []
        if str(terminal.get("status") or "") != "completed" or not urls:
            failures.append({"attempt": attempt, "task_id": task_id, "terminal": terminal})
            continue
        image_path = output_dir / f"prompt-{args.prompt_id}-a{attempt}.png"
        download(online, str(urls[0]), image_path)
        lines = ocr_image(ocr_binary, image_path)
        errors = image_ocr_errors(lines, copy=copy, case=case)
        if errors:
            failures.append({"attempt": attempt, "task_id": task_id, "errors": errors, "ocr_lines": lines})
            continue
        result = {
            "task_id": task_id,
            "attempt": attempt,
            "image_url": online.absolute_url(str(urls[0])),
            "local_image": image_path.name,
            "ocr_lines": lines,
        }
        break
    if result is None:
        atomic_json(output_dir / "test_failed.json", {"copy": copy, "source_prompt": template, "image_plan": plan, "failures": failures})
        raise RuntimeError("selected prompt image failed all attempts")
    payload = {
        "copy": copy,
        "source_prompt": template,
        "source_image": source_image,
        "image_plan": plan,
        "generation": result,
        "local_image": result["local_image"],
        "previous_failures": failures,
    }
    atomic_json(output_dir / "test_result.json", payload)
    html_path = render(output_dir, payload)
    print(json.dumps({"stage": "done", "result": str(output_dir / "test_result.json"), "html": str(html_path)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
