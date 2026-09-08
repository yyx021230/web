"""One explicitly requested rollout acceptance post; default is read-only polling.

Run inside the configured Worker. Receipts remain in its Windows-hosted volume.
Never retry an uncertain creation automatically or emit credentials.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import urllib.error
from urllib.parse import urljoin
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--verify-images", action="store_true")
    parser.add_argument("--api-root", default="http://hermes-frontend:3000/api/backend")
    args = parser.parse_args()
    root = args.api_root.rstrip("/")
    directory = Path("/app/web/ops/xhs_hermes/state/release-0.3.20")
    directory.mkdir(exist_ok=True)
    receipt = directory / "acceptance-run.json"
    intent = directory / "creation-attempted.json"
    token = ""

    def request(path, body=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(root + path, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"{path}: HTTP {error.code}") from None

    token = request("/auth/login", {
        "username": os.environ["XHS_BACKEND_USERNAME"],
        "password": os.environ["XHS_BACKEND_PASSWORD"],
    })["access_token"]
    bootstrap = request("/admin/hermes-workflows/bootstrap")["data"]
    assert bootstrap["schedule"]["enabled"] is False, "Unexpected enabled schedule"
    if not receipt.exists():
        if not args.create:
            raise RuntimeError("No acceptance run receipt; creation requires --create")
        if intent.exists():
            raise RuntimeError("Previous POST uncertain: inspect history, do not resubmit")
        account = next(a for a in bootstrap["accounts"] if a["id"] == 42)
        assert account["owner_user_id"] == 3
        policy = next(p for p in bootstrap["policies"] if p["vehicle_model"] == "零跑A05")
        assert policy
        assert any(w["online"] and w["status"] == "idle" for w in bootstrap["workers"])
        history = request("/admin/hermes-workflows/runs?limit=1")["data"]
        assert history["total"] == 0, "Unexpected existing runs: inspect before creating"
        payload = {"accounts": [{"environment_id": 42, "vehicle_model": "零跑A05", "case_id": "a05-current"}],
                   "posts_per_account": 1}
        with intent.open("x") as handle:
            json.dump(payload, handle)
        run = request("/admin/hermes-workflows/runs", payload)["data"]
        receipt.write_text(json.dumps({"run_id": run["id"], "created_at": run["created_at"],
                                       "purpose": "Windows release 0.3.20 one-post acceptance"}))
    run_id = json.loads(receipt.read_text())["run_id"]
    run = request(f"/admin/hermes-workflows/runs/{run_id}")["data"]
    (directory / "acceptance-result.json").write_text(json.dumps(run))
    report = {key: run.get(key) for key in ("id", "status", "total_posts", "generated_posts", "failed_posts",
                                          "worker_id", "error", "created_at", "started_at", "finished_at")}
    report["posts"] = [{key: p.get(key) for key in ("id", "owner_user_id", "account_name", "vehicle_model",
                                                  "status", "title", "image_url", "hard_pass", "publish_status")}
                       for p in run.get("posts", [])]
    report["schedule_enabled"] = bootstrap["schedule"]["enabled"]
    if args.verify_images:
        before = json.loads(Path("/tmp/acceptance-before-image-urls.json").read_text())
        old_post, new_post = deepcopy(before["posts"][0]), deepcopy(run["posts"][0])
        image_paths = (new_post["image_url"], new_post["source_detail"]["selected_prompt_image"])
        for row in (old_post, new_post):
            row.pop("image_url")
            row["source_detail"].pop("selected_prompt_image")
        assert old_post == new_post, "Unexpected content/provenance/version change"
        checks = []
        for path in image_paths:
            assert path.startswith("/uploads/ai-images/"), "Image URL is not browser accessible"
            with urllib.request.urlopen(urljoin(root, path), timeout=30) as response:
                assert response.status == 200
                assert response.headers.get_content_type().startswith("image/")
                assert response.read(8) == b"\x89PNG\r\n\x1a\n"
                checks.append({"path": path, "status": response.status, "type": response.headers.get_content_type()})
        report["image_checks"] = checks
        report["content_provenance_version_unchanged"] = True
    print(json.dumps(report))


if __name__ == "__main__":
    main()
