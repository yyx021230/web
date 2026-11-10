from __future__ import annotations

import re
from typing import Any


_LEGACY_TOKEN_ERROR = re.compile(
    r"(?P<id>\d+) (?P<name>[^\n|]+?): "
    r"Token (?P<kind>不可用|复核暂时失败，继续使用缓存): (?P<error>[^\n|]*)"
)
_STATUS_PRIORITY = {"cached": 0, "missing": 1, "rejected": 2}
_DEFAULT_REASONS = {
    "missing": "授权服务未返回有效 Token",
    "cached": "授权服务暂时不可用，本次继续使用缓存 Token",
    "rejected": "报表接口拒绝了该账户的授权",
}


def token_issue_reason(error: Any, status: str) -> str:
    """Use fixed explanations; upstream errors may contain credentials."""
    message = str(error or "").lower()
    if "未找到对应账号" in message or "account not found" in message:
        return "授权服务找不到该账户"
    if "操作成功" in message or "未返回有效" in message:
        return "授权服务返回成功，但未提供有效 Token"
    if "access_token错误" in message or "invalid token" in message:
        return "报表接口提示 Token 无效"
    if "失效" in message or "token expired" in message:
        return "Token 已失效，需要重新授权"
    if "没有获取该账号授权" in message or "410019" in message:
        return "报表接口未获取该账户授权"
    if "没有该接口权限" in message or "410023" in message:
        return "该账户没有报表接口权限"
    if "timeout" in message or "timed out" in message or "超时" in message:
        return "授权请求超时" if status != "rejected" else _DEFAULT_REASONS[status]
    return _DEFAULT_REASONS[status]


def token_issue(item: dict, status: str, report_type: str | None = None) -> dict | None:
    account_id = str(item.get("account_id") or "").strip()[:64]
    if not account_id:
        return None
    return {
        "account_id": account_id,
        "account_name": str(item.get("account_name") or account_id).strip()[:255],
        "status": status,
        "reason": token_issue_reason(item.get("error") or item.get("token_message"), status),
        "report_types": [report_type] if report_type else [],
    }


def merge_token_issues(existing: list[dict], incoming: list[dict | None]) -> list[dict]:
    accounts = {row["account_id"]: row for row in existing}
    for row in incoming:
        if not row:
            continue
        account_id = row["account_id"]
        previous = accounts.get(account_id)
        if previous is None:
            accounts[account_id] = row
            continue
        preferred = row if _STATUS_PRIORITY[row["status"]] > _STATUS_PRIORITY[previous["status"]] else previous
        accounts[account_id] = {
            **preferred,
            "report_types": sorted(set(previous["report_types"]) | set(row["report_types"])),
        }
    return sorted(accounts.values(), key=lambda row: (-_STATUS_PRIORITY[row["status"]], row["account_id"]))


def report_token_issues(report: dict, report_type: str) -> list[dict | None]:
    issues = [token_issue(account, "missing", report_type)
              for account in report.get("skipped_token_accounts") or [] if isinstance(account, dict)]
    for account in report.get("failed_accounts") or []:
        if not isinstance(account, dict):
            continue
        if account.get("stage") == "token":
            issues.append(token_issue(account, "missing", report_type))
        elif account.get("stage") == "report" and any(
            marker in str(account.get("error") or "").lower()
            for marker in ("access_token错误", "invalid token", "token expired", "unauthorized", "forbidden",
                           "没有获取该账号授权", "没有该接口权限", "410019", "410023", "鉴权失败")
        ):
            issues.append(token_issue(account, "rejected", report_type))
    return issues


def legacy_token_issues(summary: dict, error: str | None) -> list[dict]:
    issues = [
        token_issue({"account_id": m["id"], "account_name": m["name"], "error": m["error"]},
                    "missing" if m["kind"] == "不可用" else "cached")
        for part in (error or "").split(" | ")
        if (m := _LEGACY_TOKEN_ERROR.fullmatch(part.strip()))
    ]
    for report in summary.get("reports") or []:
        if isinstance(report, dict) and report.get("report_type"):
            issues.extend(report_token_issues(report, report["report_type"]))
    return merge_token_issues([], issues)
