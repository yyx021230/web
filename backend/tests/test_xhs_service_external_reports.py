"""External advertising-report and YunDeng synchronization contracts."""

import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db.session import async_session as session_factory
from app.models.xhs_environment import XHSEnvironment
from app.models.xhs_report import XHSReportToken
from app.services import xhs_service as module
from app.services.xhs_service import XHSService


class _JSONResponse:
    def __init__(self, body, *, status_code=200, text=""):
        self._body = body
        self.status_code = status_code
        self.text = text
        self.content = b"x"

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _ReportClient:
    responses = []
    requests = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_fetch_report_rows_paginates_and_rejects_upstream_errors(monkeypatch):
    first_batch = [{"id": index} for index in range(200)]
    _ReportClient.responses = [
        _JSONResponse({"success": True, "data": {"data_list": first_batch, "page": {"total_count": 201}, "aggregation_data": {"fee": 10}}}),
        _JSONResponse({"success": True, "data": {"data_list": [{"id": 200}], "page": {"total_count": 201}}}),
    ]
    _ReportClient.requests = []
    monkeypatch.setattr(module.httpx, "AsyncClient", _ReportClient)
    rows, aggregate = await XHSService(None)._fetch_report_rows(  # type: ignore[arg-type]
        "token", "account", "/report", "2026-06-01", "2026-06-02"
    )
    assert len(rows) == 201
    assert aggregate == {"fee": 10}
    assert _ReportClient.requests[1][1]["json"]["page_num"] == 2

    _ReportClient.responses = [_JSONResponse({"success": False, "msg": "denied"})]
    with pytest.raises(RuntimeError, match="denied"):
        await XHSService(None)._fetch_report_rows("token", "account", "/report", "2026-06-01", "2026-06-02")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_report_combines_missing_success_and_failure_accounts(monkeypatch):
    envs = [
        SimpleNamespace(id=1, account_name="无ID", notes="", labels="", group_name="", shop_id="shop-a"),
        SimpleNamespace(id=2, account_name="成功", notes="account_id=100000", labels="", group_name="", shop_id="shop-b"),
        SimpleNamespace(id=3, account_name="失败", notes="account_id=200000", labels="", group_name="", shop_id="shop-c"),
    ]
    service = XHSService(None)  # type: ignore[arg-type]

    async def list_envs(_user):
        return envs

    async def token(account_id):
        if account_id == "200000":
            raise RuntimeError("no token")
        return "token"

    async def rows(**_kwargs):
        return ([{"fee": "1", "note_material": "note-1"}], {"fee": 1})

    async def attach(items):
        for item in items:
            item["ai_origin_type"] = "manual"
        return items

    monkeypatch.setattr(service, "list_environments", list_envs)
    monkeypatch.setattr(service, "_fetch_report_token", token)
    monkeypatch.setattr(service, "_fetch_report_rows", rows)
    monkeypatch.setattr(service, "_attach_account_note_ai_origin_to_report_rows", attach)

    user = SimpleNamespace(id=1)
    result = await service.get_jg_report(user, "creative", start_date="2026-06-01", end_date="2026-06-02")
    assert result["total_accounts"] == 3
    assert result["total_rows"] == 1
    assert result["rows"][0]["ai_origin_type"] == "manual"
    assert result["items"][0]["error"].startswith("未识别")
    assert result["items"][2]["error"] == "no token"

    by_name = await service.get_jg_report(user, "simple", account_name="成功", days=2)
    assert by_name["total_accounts"] == 1
    with pytest.raises(ValueError, match="不支持"):
        await service.get_jg_report(user, "unknown")


class _Sheet:
    def __init__(self, rows):
        self.rows = rows
        self.nrows = len(rows)
        self.ncols = len(rows[0])

    def cell_value(self, row, column):
        return self.rows[row][column]


class _Workbook:
    def __init__(self, rows, has_sheet=True):
        self.sheet = _Sheet(rows)
        self.has_sheet = has_sheet

    def sheet_names(self):
        return ["导出信息"] if self.has_sheet else ["其他"]

    def sheet_by_name(self, _name):
        return self.sheet


@pytest.mark.asyncio
async def test_import_and_list_report_accounts(client, monkeypatch):
    rows = [
        ["账户ID", "账户名称", "token", "token状态", "token接口code", "token接口message", "token时间戳"],
        ["100.0", "广告一", "tk-1", "成功", "0", "ok", "now"],
        ["", "忽略", "", "", "", "", ""],
    ]
    workbook = _Workbook(rows)
    monkeypatch.setitem(sys.modules, "xlrd", SimpleNamespace(open_workbook=lambda _path: workbook))
    async with session_factory() as db:
        service = XHSService(db)
        assert await service.import_report_tokens_from_xls("fake.xls") == {
            "upserted": 1,
            "valid_tokens": 1,
            "mode": "token_export",
        }
        accounts = await service.list_report_accounts()
        assert accounts == [
            {
                "account_id": "100",
                "account_name": "广告一",
                "has_token": True,
                "token_status": "成功",
                "token_message": "0|ok",
                "token_timestamp": "now",
            }
        ]

        workbook.sheet.rows[1][1] = "广告一（更新）"
        workbook.sheet.rows[1][2] = "tk-2"
        assert (await service.import_report_tokens_from_xls("fake.xls"))["upserted"] == 1
        saved = (await db.execute(select(XHSReportToken))).scalar_one()
        assert saved.account_name == "广告一（更新）" and saved.token == "tk-2"

    monkeypatch.setitem(sys.modules, "xlrd", SimpleNamespace(open_workbook=lambda _path: _Workbook(rows, False)))
    async with session_factory() as db:
        with pytest.raises(RuntimeError, match="导出信息"):
            await XHSService(db).import_report_tokens_from_xls("fake.xls")


class _YunDengClient(_ReportClient):
    async def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_sync_yundeng_upserts_batches_and_marks_stale_inactive(client, monkeypatch):
    shop_ids = [{"shopId": f"shop-{index}"} for index in range(11)]
    first_details = [
        {
            "browserid": f"shop-{index}",
            "name": f"环境{index}",
            "notes": f"note-{index}",
            "proxy": {"name": "proxy", "PublicIP": "1.2.3.4"},
            "accounts": {"groupName": "group"},
            "label": [{"name": "A"}, {"name": "B"}],
        }
        for index in range(10)
    ]
    second_details = [{"browserid": "shop-10", "name": "环境10", "proxy": {}, "accounts": {}, "label": []}]
    _YunDengClient.requests = []
    _YunDengClient.responses = [
        _JSONResponse({"code": 0, "data": {"list": shop_ids}}),
        _JSONResponse({"code": 0, "data": {"browser": first_details}}),
        _JSONResponse({"code": 0, "data": {"browser": second_details}}),
    ]
    monkeypatch.setattr(module.httpx, "AsyncClient", _YunDengClient)
    async with session_factory() as db:
        db.add_all(
            [
                XHSEnvironment(shop_id="shop-0", account_name="旧名称", status="active"),
                XHSEnvironment(shop_id="stale", account_name="已删除", status="active"),
            ]
        )
        await db.commit()
        service = XHSService(db)
        monkeypatch.setattr(service, "_should_delegate_browser_ops", lambda: False)
        monkeypatch.setattr(service, "_require_local_browser_ops", lambda _action: None)
        assert await service.sync_environments_from_yundeng() == 11
        assert len(_YunDengClient.requests) == 3
        environments = (await db.execute(select(XHSEnvironment).order_by(XHSEnvironment.shop_id))).scalars().all()
        assert len(environments) == 12
        assert next(item for item in environments if item.shop_id == "stale").status == "inactive"
        updated = next(item for item in environments if item.shop_id == "shop-0")
        assert updated.account_name == "环境0"
        assert updated.proxy_info == "proxy (1.2.3.4)"
        assert updated.labels == "A, B"


@pytest.mark.asyncio
async def test_sync_yundeng_delegates_and_handles_remote_failures(client, monkeypatch):
    async with session_factory() as db:
        service = XHSService(db)

        async def delegated():
            return 7

        monkeypatch.setattr(service, "_should_delegate_browser_ops", lambda: True)
        monkeypatch.setattr(service, "trigger_worker_sync_environments", delegated)
        assert await service.sync_environments_from_yundeng() == 7

        monkeypatch.setattr(service, "_should_delegate_browser_ops", lambda: False)
        monkeypatch.setattr(service, "_require_local_browser_ops", lambda _action: None)
        _YunDengClient.responses = [_JSONResponse({"code": 500})]
        monkeypatch.setattr(module.httpx, "AsyncClient", _YunDengClient)
        assert await service.sync_environments_from_yundeng() == 0

        class _BrokenClient:
            def __init__(self, **_kwargs):
                raise OSError("network")

        monkeypatch.setattr(module.httpx, "AsyncClient", _BrokenClient)
        assert await service.sync_environments_from_yundeng() == 0
