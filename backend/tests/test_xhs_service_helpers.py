from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import openpyxl
import pytest

from app.services.xhs_service import XHSService


def test_sync_parameter_normalizers_cover_limits_and_invalid_values():
    assert XHSService._normalize_account_note_sync_mode(None) == "all"
    assert XHSService._normalize_account_note_sync_mode(" UNPUBLISHED_ONLY ") == "unpublished_only"
    with pytest.raises(ValueError, match="sync_mode"):
        XHSService._normalize_account_note_sync_mode("latest")

    assert XHSService._normalize_account_note_sync_limit(None) is None
    assert XHSService._normalize_account_note_sync_limit(5000) == 1000
    assert XHSService._normalize_account_note_sync_account_limit(500) == 200
    assert XHSService._normalize_account_note_sync_limit_per_runner(100) == 60
    assert XHSService._normalize_account_note_max_age_days(None) == 30
    assert XHSService._normalize_account_note_max_age_days(0) is None
    assert XHSService._normalize_account_note_max_age_days(9000) == 3650
    assert XHSService._normalize_account_note_sync_pause_seconds(999, field_name="暂停") == 900

    for callback, value in (
        (XHSService._normalize_account_note_sync_limit, 0),
        (XHSService._normalize_account_note_sync_account_limit, -1),
        (XHSService._normalize_account_note_sync_limit_per_runner, "bad"),
    ):
        with pytest.raises(ValueError):
            callback(value)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="不能小于"):
        XHSService._normalize_account_note_sync_pause_seconds(-1, field_name="暂停")


def test_runner_assignment_normalizers_prevent_cross_runner_duplicates():
    assert XHSService._normalize_account_note_sync_runner_ids("4,5,4,0,") == [4, 5]
    assert XHSService._normalize_account_note_sync_runner_assignments(
        '{"4":[11,"12",11],"5":[13],"0":[99]}'
    ) == {4: [11, 12], 5: [13]}
    with pytest.raises(ValueError, match="合法 JSON"):
        XHSService._normalize_account_note_sync_runner_assignments("{")
    with pytest.raises(ValueError, match="不能同时分配"):
        XHSService._normalize_account_note_sync_runner_assignments({4: [11], 5: [11]})
    with pytest.raises(ValueError, match="数组"):
        XHSService._normalize_account_note_sync_runner_assignments({4: "11"})
    with pytest.raises(ValueError, match="数字 ID"):
        XHSService._normalize_account_note_sync_runner_ids(["bad"])


def test_sync_config_parser_and_materializer_validate_directives(monkeypatch):
    rng = SimpleNamespace(
        choice=lambda values: values[-1],
        randint=lambda start, end: end,
        getrandbits=lambda _bits: 1,
    )
    monkeypatch.setattr("app.services.xhs_service._SYNC_BROWSER_CONFIG_RNG", rng)
    parsed = XHSService._parse_sync_json_object(
        '{"ua":{"$pick":["a","b"]},"width":{"$rand_int":{"min":800,"max":900}},"mobile":{"$bool":true}}',
        "启动参数",
    )
    assert parsed == {"ua": "b", "width": 900, "mobile": True}
    assert XHSService._parse_sync_json_object("", "启动参数") == {}

    with pytest.raises(RuntimeError, match="JSON 无效"):
        XHSService._parse_sync_json_object("{", "启动参数")
    with pytest.raises(RuntimeError, match="JSON 对象"):
        XHSService._parse_sync_json_object("[]", "启动参数")
    with pytest.raises(RuntimeError, match="非空数组"):
        XHSService._materialize_sync_browser_start_config({"$pick": []})
    with pytest.raises(RuntimeError, match="min 不能大于"):
        XHSService._materialize_sync_browser_start_config({"$rand_int": [2, 1]})
    with pytest.raises(RuntimeError, match="只能设置为 true"):
        XHSService._materialize_sync_browser_start_config({"$uuid": False})


def test_profile_identifiers_warmup_and_fetch_estimators(monkeypatch):
    user_id, token = XHSService._extract_profile_identifiers(
        "https://www.xiaohongshu.com/user/profile/abc123?xsec_token=a%2Bb"
    )
    assert (user_id, token) == ("abc123", "a+b")
    assert XHSService._extract_profile_identifiers("not a profile") == (None, None)

    rng = SimpleNamespace(choice=lambda values: values[-1])
    monkeypatch.setattr("app.services.xhs_service._SYNC_BROWSER_CONFIG_RNG", rng)
    assert XHSService._pick_warmup_feed({"feeds": [
        None,
        {"feed_id": "one", "xsec_token": "t1"},
        {"feed_id": "two", "xsec_token": "t2"},
    ]}) == ("two", "t2")
    assert XHSService._pick_warmup_feed({"feeds": "invalid"}) == (None, None)
    assert XHSService._estimate_account_note_profile_fetch_max_feeds(100, 60) == 160
    assert XHSService._estimate_account_note_profile_fetch_max_feeds(0, 60) == 60
    assert XHSService._estimate_account_note_profile_scroll_rounds(100, 60) >= 2
    assert XHSService._estimate_account_note_profile_scroll_rounds(0, 60) == 0


def test_note_cover_text_and_image_extractors_handle_nested_shapes():
    service = XHSService(None)  # type: ignore[arg-type]
    assert service._pick_note_cover_image_url({"urlPre": "https://cdn/cover.jpg"}) == "https://cdn/cover.jpg"
    assert service._pick_note_cover_image_url({"infoList": [{"url": "https://cdn/fallback.jpg"}]}) == "https://cdn/fallback.jpg"
    assert service._pick_note_cover_image_url(None) is None

    assert service._normalize_note_text([" 第一段 ", {"text": "第二段"}, None]) == "第一段\n第二段"
    assert service._normalize_note_text({"unknown": "value"}) is None
    assert service._extract_nested_payload_value({"a": {"b": 1}}, ("a", "b")) == 1
    assert service._extract_nested_payload_value({"a": []}, ("a", "b")) is None

    item = {"infoList": [
        {"imageScene": "OTHER", "url": "https://cdn/other.jpg"},
        {"imageScene": "WB_DFT", "url": "https://cdn/default.jpg"},
    ]}
    assert service._pick_note_image_item_url(item) == "https://cdn/default.jpg"
    assert service._pick_note_image_item_url("bad") is None


def test_account_note_detail_extracts_content_images_metrics_and_missing_reason():
    service = XHSService(None)  # type: ignore[arg-type]
    published_ms = 1_720_000_000_000
    payload = {
        "detail": {
            "note": {
                "desc": {"text": "完整正文"},
                "publishTime": published_ms,
                "interact_info": {
                    "liked_count": "1,234",
                    "comment_count": 56,
                    "collected_count": 78,
                    "share_count": 9,
                },
                "imageList": [
                    {"urlDefault": "https://cdn/1.jpg"},
                    {"urlDefault": "https://cdn/1.jpg"},
                    {"infoList": [{"url": "https://cdn/2.jpg"}]},
                ],
            }
        }
    }
    detail = service._extract_account_note_detail_data(payload, title="标题")
    assert detail["content"] == "完整正文"
    assert detail["content_status"] == "from_detail"
    assert detail["image_urls"] == ["https://cdn/1.jpg", "https://cdn/2.jpg"]
    assert detail["cover_image_url"] == "https://cdn/1.jpg"
    assert detail["liked_count"] == 1234
    assert detail["comment_count"] == 56
    assert detail["published_at"] == datetime.utcfromtimestamp(published_ms / 1000)

    missing = service._extract_account_note_detail_content(
        {"noteCard": {"content": "标题"}},
        title="标题",
    )
    assert missing["content"] is None
    assert "仅返回标题" in missing["content_missing_reason"]


def test_report_normalizers_preserve_derived_people_and_stable_keys():
    base = XHSService._normalize_report_row(
        {"msg_leads_num": 3, "initiative_message": 5},
        account_id="10",
        account_name="广告户",
    )
    assert base["msg_leads_user_cnt"] == 3
    assert base["msg_chat_user_cnt"] == 5
    assert base["account_name"] == "广告户"

    creative = XHSService._normalize_jg_report_row(
        "creative",
        {
            "date": "2026-08-01",
            "ad_id": "creative-1",
            "ad_name": "素材甲",
            "plan_name": "计划甲",
            "fee": "100",
            "interaction": "4",
        },
    )
    assert creative["time"] == "2026-08-01"
    assert creative["creative_id"] == "creative-1"
    assert creative["creative_name"] == "素材甲"
    assert creative["avg_interaction_cost"] == "25.00"

    note = XHSService._normalize_jg_report_row(
        "simple_note",
        {"feed_id": "note-1", "title": "帖子甲", "cover_url": "https://cdn/cover.jpg"},
    )
    assert note["note_id"] == "note-1"
    assert note["note_title"] == "帖子甲"
    assert note["note_image"] == "https://cdn/cover.jpg"
    key = XHSService._report_row_campaign_key("simple_note", note)
    assert key.startswith("note-1|")
    assert XHSService._report_row_campaign_key("standard", {"plan_id": "plan-1"}) == "plan-1"
    assert XHSService._report_row_campaign_key(
        "creative", {"creative_id": "c1", "unit_id": "u1"}
    ) == "|c1|u1|"
    assert len(XHSService._report_row_campaign_key("simple", {"fee": 1})) == 32


def test_creative_comparison_metrics_and_periods():
    bucket = XHSService._init_creative_compare_accumulator()
    XHSService._accumulate_creative_compare_row(bucket, {
        "fee": "100",
        "impression": "1,000",
        "click": 100,
        "interaction": 20,
        "message_consult": 10,
        "initiative_message": 5,
        "msg_leads_num": 4,
        "shop_pay_order_num_15d": 2,
    })
    result = XHSService._finalize_creative_compare_metrics(bucket)
    assert result["ctr"] == 10
    assert result["cpc"] == 1
    assert result["cpm"] == 100
    assert result["msg_leads_cost"] == 25
    assert result["shop_pay_order_cvr_15d"] == 2
    assert XHSService._creative_compare_period_parts(date(2026, 8, 11), "day")[0] == "2026-08-11"
    assert XHSService._creative_compare_period_parts(date(2026, 8, 11), "week")[0].startswith("2026-W")
    assert XHSService._creative_compare_period_parts(date(2026, 12, 11), "month") == (
        "2026-12", "2026-12", "2026-12-01", "2026-12-31",
    )


def test_browser_status_extractors_cache_and_proxy_rules(monkeypatch):
    nested = {"data": [{"browser": {"debuggerUrl": "ws://127.0.0.1:9222/devtools/browser/a"}}]}
    assert XHSService._extract_browser_ws_from_payload(nested).startswith("ws://127.0.0.1")
    assert XHSService._extract_browser_ws_from_payload("bad") is None
    assert XHSService._extract_browser_online_hint({"data": {"run_status": "运行中"}}) is True
    assert XHSService._extract_browser_online_hint({"state": "closed"}) is False
    assert XHSService._extract_browser_online_hint({"state": "unknown"}) is None
    assert XHSService._extract_browser_status_debug_value({"data": {"runStatus": 1}}) == "runStatus=1"

    XHSService._browser_status_cache.clear()
    source = {"online": True, "detail": {"state": "open"}}
    XHSService._cache_browser_status(3, source)
    cached = XHSService._get_cached_browser_status(3)
    assert cached == source
    cached["online"] = False
    assert XHSService._get_cached_browser_status(3)["online"] is True

    assert XHSService._should_bypass_env_proxy("http://127.0.0.1:8000") is True
    assert XHSService._should_bypass_env_proxy("https://example.com") is False
    assert XHSService._httpx_client_kwargs("http://localhost:8000", timeout=3)["trust_env"] is False
    monkeypatch.setattr("app.services.xhs_service.RUNNING_IN_DOCKER", True)
    assert "host.docker.internal:9222" in XHSService._normalize_browser_ws(
        "ws://127.0.0.1:9222/devtools/browser/a"
    )


def test_publish_identifiers_urls_tags_and_response_errors():
    payload = {
        "data": {
            "share": {
                "url": "https://www.xiaohongshu.com/explore/feed123?xsec_token=token456"
            }
        }
    }
    assert XHSService._extract_publish_identifiers(payload) == ("feed123", "token456")
    assert XHSService._pick_post_url_from_payload(payload).endswith("xsec_token=token456")
    assert XHSService._extract_identifiers_from_url("bad") == (None, None)
    assert XHSService._build_post_url("feed123", "token456").endswith("feed123?xsec_token=token456")
    assert XHSService._build_account_note_url("feed123", "token456").endswith("xsec_source=pc_user")
    assert XHSService._build_post_url(None, None) is None

    content, tags = XHSService._prepare_publish_content_and_tags(
        "正文 #新能源\n第二段 #车型测评",
        ["新能源", "价格优惠", "#价格优惠"],
    )
    assert content == "正文\n第二段"
    assert tags == ["新能源", "车型测评", "价格优惠"]
    assert XHSService._remove_hashtags_from_content("#只有话题") == "#只有话题"
    assert XHSService._merge_metric_count(10, 0) == 10
    assert XHSService._merge_metric_count(10, 12) == 12
    assert XHSService._extract_optional_count({"likes": "1,200"}, "likes") == 1200

    assert XHSService._is_publish_response_success(200, {"code": "success"}) is True
    assert XHSService._is_publish_response_success(200, {"message": "发布成功"}) is True
    assert XHSService._is_publish_response_success(500, {"code": 0}) is False
    assert XHSService._extract_publish_failure_message(
        {"message": "outer", "data": {"reason": "inner"}}, 400
    ) == "inner"
    assert "code=123" in XHSService._extract_publish_failure_message({"code": 123}, 400)


def test_sms_device_command_and_app_slot_helpers():
    service = XHSService(None)  # type: ignore[arg-type]
    assert service._infer_xhs_app_slot(SimpleNamespace(notes="双开 app2", labels="", group_name="", account_name="")) == "app2"
    assert service._infer_xhs_app_slot(SimpleNamespace(notes="主应用", labels="", group_name="", account_name="")) == "app1"
    assert service._infer_xhs_app_slot(None) is None
    assert service._extract_sms_activation_device_id({"device": {"id": "phone-1"}}) == "phone-1"
    assert service._extract_sms_activation_device_id({}) == ""
    command = {"command_id": "cmd-1", "status": "succeeded"}
    assert service._find_sms_command({"items": [None, command]}, "cmd-1") == command
    assert service._find_sms_command({"items": "bad"}, "cmd-1") is None


def test_creator_stats_excel_parse_rates_dates_and_note_matching():
    service = XHSService(None)  # type: ignore[arg-type]
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["创作者中心导出"])
    sheet.append(["笔记标题", "首次发布时间", "曝光", "观看", "封面点击率", "点赞", "评论", "收藏", "分享"])
    sheet.append(["帖子甲", "2026年08月11日 10:30", "1,000", 800, "12.5%", 10, 2, 3, 4])
    sheet.append(["", "2026-08-11", 1, 1, 1, 1, 1, 1, 1])
    buffer = io.BytesIO()
    workbook.save(buffer)

    rows = service._parse_creator_stats_excel(buffer.getvalue())
    assert len(rows) == 1
    assert rows[0]["title"] == "帖子甲"
    assert rows[0]["published_at"] == datetime(2026, 8, 11, 10, 30)
    assert rows[0]["exposure_count"] == 1000
    assert rows[0]["cover_click_rate"] == 12.5
    assert service._safe_rate(0.25) == 25
    assert service._safe_rate("bad") == 0
    assert service._parse_creator_stats_published_at(date(2026, 8, 11)) == datetime(2026, 8, 11)
    assert service._parse_creator_stats_published_at("bad") is None

    note = SimpleNamespace(feed_id="", title="帖子甲", published_at=datetime(2026, 8, 11, 2, 30))
    candidates = [
        {"title": "帖子甲", "published_at": datetime(2026, 8, 10, 10, 0)},
        {"title": "帖子甲", "published_at": datetime(2026, 8, 11, 10, 30)},
    ]
    assert service._match_creator_note_stats(note, candidates) == candidates[1]
    by_id = SimpleNamespace(feed_id="feed-1", title="other", published_at=None)
    row = {"note_id": "feed-1", "title": "帖子乙"}
    assert service._match_creator_note_stats(by_id, [row]) == row
    assert service._match_creator_note_stats(SimpleNamespace(feed_id="", title="", published_at=None), candidates) is None


def test_account_id_and_timestamp_helpers():
    assert XHSService._extract_account_id_from_env(
        SimpleNamespace(id=12, notes="广告账户 10845728", labels="", group_name="", shop_id="", account_name="")
    ) == "10845728"
    assert XHSService._extract_account_id_from_env(
        SimpleNamespace(id=100001, notes="", labels="", group_name="", shop_id="", account_name="")
    ) == "100001"
    assert XHSService._extract_account_id_from_env(
        SimpleNamespace(id=12, notes="none", labels="", group_name="", shop_id="", account_name="")
    ) is None
    assert XHSService._xhs_timestamp_ms_to_utc_naive(1_720_000_000_000) == datetime.utcfromtimestamp(1_720_000_000)
    assert XHSService._xhs_timestamp_ms_to_utc_naive(-1) is None
    assert XHSService._xhs_timestamp_ms_to_utc_naive("bad") is None


def test_profile_feed_matching_prefers_target_with_token():
    feeds = [
        {"feed_id": "first", "xsec_token": "a"},
        {"feed_id": "target", "xsec_token": "b"},
        {"feed_id": "missing-token", "xsec_token": ""},
    ]
    assert XHSService._match_profile_feed_by_feed_id(feeds, None) == feeds[0]
    assert XHSService._match_profile_feed_by_feed_id(feeds, "target") == feeds[1]
    assert XHSService._match_profile_feed_by_feed_id(feeds, "missing-token") is None
    assert XHSService._match_profile_feed_by_feed_id([], "target") is None


def test_normalized_text_and_temporary_error_classification():
    assert XHSService._normalize_text(" A \n B ") == "ab"
    assert XHSService._strip_hashtags("正文 #话题 测试") == "正文  测试"
    assert XHSService._is_temporary_unavailable_message("service temporarily unavailable") is True
    assert XHSService._is_temporary_unavailable_message("正常业务失败") is False


def test_stale_date_match_rejected_for_duplicate_creator_titles():
    note = SimpleNamespace(feed_id="", title="同名帖子", published_at=datetime(2026, 8, 11, 2, 30))
    rows = [
        {"title": "同名帖子", "published_at": datetime(2026, 8, 1, 10, 30)},
        {"title": "同名帖子", "published_at": datetime(2026, 8, 2, 10, 30)},
    ]
    assert XHSService._match_creator_note_stats(note, rows) is None
    assert XHSService._parse_creator_stats_published_at(
        datetime(2026, 8, 11, 10, 30) + timedelta(hours=8)
    ) == datetime(2026, 8, 11, 18, 30)
