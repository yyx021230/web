"""Read-only production acceptance through the candidate frontend's rewrites.

Run inside the configured Hermes worker. Never print passwords or access tokens.
"""
import argparse
import json
import os
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-root", default="http://hermes-frontend:3000/api/backend")
    args = parser.parse_args()
    root = args.api_root.rstrip("/")
    token = ""

    def request(path, body=None, authenticated=True):
        headers = {"Content-Type": "application/json"}
        if authenticated and token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(
            root + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"{path}: HTTP {error.code}") from None

    login = request("/auth/login", {
        "username": os.environ["XHS_BACKEND_USERNAME"],
        "password": os.environ["XHS_BACKEND_PASSWORD"],
    }, authenticated=False)
    token = login["access_token"]
    me = request("/auth/me")
    user = request("/hermes-workflows/bootstrap")["data"]
    admin = request("/admin/hermes-workflows/bootstrap")["data"]
    catalog = request("/hermes-workflows/reference-types")["data"]
    batch = request("/hermes-workflows/runs?workflow_mode=batch")["data"]
    single = request("/hermes-workflows/runs?workflow_mode=single")["data"]
    report = {
        "login": "ok", "user_id": me.get("id"), "role": me.get("role"),
        "assigned_accounts": user["accounts"], "vehicle_models": user["vehicle_models"],
        "policies": len(user["policies"]),
        "admin_accounts": [{key: account.get(key) for key in ("id", "name", "group", "owner_user_id")}
                           for account in admin["accounts"]],
        "schedule_enabled": admin["schedule"]["enabled"],
        "workers": admin["workers"], "library_counts": catalog["library_counts"],
        "copy_examples": {row["id"]: len(row.get("examples", [])) for row in catalog["copy_types"]},
        "image_examples": {row["id"]: len(row.get("examples", [])) for row in catalog["image_types"]},
        "batch_history": batch["total"], "single_history": single["total"],
    }
    if report["schedule_enabled"]:
        raise RuntimeError("Unexpected enabled production schedule")
    # ASCII JSON survives legacy Windows PowerShell native-process decoding.
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
