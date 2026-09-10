import csv
import json
import shutil
import types
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


SOURCE_ROOT = Path("/Users/yyx/ztqc/car_shiping/ai_pro/car_scrip")
TARGET_ROOT = Path("/Users/yyx/ztqc/web/dify/knowledge/leapmotor-original-format-20260819")
CONFIG_ROOT = TARGET_ROOT / "configs"
OUTPUT_ROOT = TARGET_ROOT / "kb_output"


def load_module(name: str, path: Path):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    source = "from __future__ import annotations\n" + path.read_text(encoding="utf-8")
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


scraper = load_module("original_config_scraper", SOURCE_ROOT / "config_scraper.py")
converter = load_module("original_convert_to_kb", SOURCE_ROOT / "convert_to_kb.py")

if TARGET_ROOT.exists():
    shutil.rmtree(TARGET_ROOT)
CONFIG_ROOT.mkdir(parents=True)
OUTPUT_ROOT.mkdir(parents=True)

with (SOURCE_ROOT / "cars_data.csv").open(encoding="utf-8-sig") as handle:
    rows = [row for row in csv.DictReader(handle) if row.get("汽车品牌") == "零跑汽车"]

scraper.OUTPUT_DIR = CONFIG_ROOT
scraper.REQUEST_DELAY = (0.2, 0.5)
scraper.PAGE_DELAY = (0.2, 0.5)
scraper._total = len(rows)

results = []
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = {
        executor.submit(scraper.process_row, row, index): row
        for index, row in enumerate(rows, start=1)
    }
    for future in as_completed(futures):
        row = futures[future]
        results.append({"model": row["详细车型"], "status": future.result()})

failed = [item for item in results if item["status"] != "done"]
if failed:
    raise RuntimeError(f"车型配置刷新不完整: {failed}")

converter.CONFIGS_DIR = CONFIG_ROOT
converter.OUTPUT_DIR = OUTPUT_ROOT
model_count = converter.process_brand(CONFIG_ROOT / "零跑汽车")
output_file = OUTPUT_ROOT / "零跑汽车" / "零跑汽车.md"
text = output_file.read_text(encoding="utf-8")

headers = [line for line in text.splitlines() if line.startswith("品牌:")]
summary = {
    "models_requested": len(rows),
    "models_written": model_count,
    "versions_written": len(headers),
    "variant_separators": sum(line == "---" for line in text.splitlines()),
    "model_separators": sum(line == "====" for line in text.splitlines()),
    "bytes": output_file.stat().st_size,
    "output_file": str(output_file),
    "models": sorted({line.split("|", 2)[1].split(":", 1)[1].strip() for line in headers}),
}
(TARGET_ROOT / "refresh_summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(summary, ensure_ascii=False, indent=2))
