import json

import web_panel
from services.like_review import ActionReviewInbox, requires_review, review_settings


def test_default_policy_reviews_platform_actions_only():
    settings = review_settings({})
    assert settings["enabled"] is True
    assert requires_review({}, "video_like") is True
    assert requires_review({}, "private_reply") is True
    assert requires_review({}, "unfollow_user") is True
    assert requires_review({}, "knowledge_write") is False


def test_disabled_review_policy_never_requires_review():
    config = {"approval_review": {"enabled": False}}
    assert review_settings(config)["enabled"] is False
    assert requires_review(config, "video_like") is False
    assert requires_review(config, "private_reply") is False


def test_account_switch_cancels_all_pending_review_actions(tmp_path):
    (tmp_path / "bilibili_cookies.json").write_text(
        json.dumps({"DedeUserID": "old-account"}), encoding="utf-8"
    )
    inbox = ActionReviewInbox(tmp_path)
    row = inbox.propose("follow_up", "test account switch", payload={"uid": 123})

    assert row["account_uid"] == "old-account"
    assert inbox.cancel_pending_for_account_switch("old-account", "new-account") == 1
    cancelled = inbox.list()[0]
    assert cancelled["status"] == "cancelled_account_switch"
    assert cancelled["cancelled_reason"] == "Bilibili account changed"


def test_execution_rejects_action_from_another_account(monkeypatch):
    from api import client as client_module

    class Credential:
        dedeuserid = "current-account"

    class Client:
        credential = None

        def _load_credential(self):
            self.credential = Credential()

    monkeypatch.setattr(client_module, "BiliClient", Client)

    try:
        web_panel._execute_review_action({
            "action_type": "video_like",
            "account_uid": "previous-account",
            "payload": {"bvid": "BV1234567890"},
        })
    except RuntimeError as exc:
        assert "先前登录的账号" in str(exc)
    else:
        raise AssertionError("review action should not execute under a different account")


def test_inbox_deduplicates_pending_actions(tmp_path):
    inbox = ActionReviewInbox(tmp_path)
    first = inbox.propose("follow_up", "关注测试 UP", payload={"uid": 123}, dedupe_key="follow_up:123")
    second = inbox.propose("follow_up", "关注测试 UP", payload={"uid": 123}, dedupe_key="follow_up:123")
    assert first is not None
    assert second is None
    assert len(inbox.list(status="pending")) == 1


def test_legacy_like_rows_are_migrated(tmp_path):
    legacy = [{"id": "old", "bvid": "BV1234567890", "title": "旧建议", "status": "pending"}]
    (tmp_path / "like_review_inbox.json").write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    row = ActionReviewInbox(tmp_path).list()[0]
    assert row["action_type"] == "video_like"
    assert row["payload"]["bvid"] == "BV1234567890"


def test_batch_review_endpoint_executes_selected_items(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    inbox = ActionReviewInbox(tmp_path)
    row = inbox.propose("video_like", "测试视频", payload={"bvid": "BV1234567890"})
    monkeypatch.setattr(web_panel, "_execute_review_action", lambda _item: {"executed": True})
    web_panel.app.testing = True
    response = web_panel.app.test_client().post(
        "/api/reviews/decision", json={"ids": [row["id"]], "decision": "approved"}
    )
    assert response.status_code == 200
    assert response.get_json()["succeeded"] == 1
    assert ActionReviewInbox(tmp_path).list()[0]["status"] == "executed"


def test_review_audit_records_decision_and_execution(tmp_path):
    inbox = ActionReviewInbox(tmp_path)
    row = inbox.propose("video_like", "审核测试", payload={"bvid": "BV1234567890"})
    decided = inbox.decide(row["id"], "approved")
    inbox.update(decided["id"], status="executed", execution={"executed": True, "result": "ok"})

    audit = inbox.audit()
    assert [entry["event"] for entry in audit] == ["executed", "approved"]
    assert audit[0]["execution"]["result"] == "ok"


def test_clear_audit_keeps_review_queue_items(tmp_path):
    inbox = ActionReviewInbox(tmp_path)
    finished = inbox.propose("video_like", "已执行测试", payload={"bvid": "BV1234567890"})
    pending = inbox.propose("private_reply", "待审核私信", payload={"receiver_id": 1})
    inbox.decide(finished["id"], "approved")

    assert inbox.clear_audit() == 1
    assert inbox.audit() == []
    assert inbox.list(status="pending")[0]["id"] == pending["id"]


def test_review_audit_endpoint_returns_persisted_history(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    inbox = ActionReviewInbox(tmp_path)
    row = inbox.propose("private_reply", "回复测试", payload={"receiver_id": 1})
    inbox.decide(row["id"], "rejected")
    web_panel.app.testing = True

    response = web_panel.app.test_client().get("/api/reviews/audit")
    assert response.status_code == 200
    assert response.get_json()["items"][0]["event"] == "rejected"


def test_review_audit_clear_endpoint_keeps_pending_items(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    inbox = ActionReviewInbox(tmp_path)
    decided = inbox.propose("video_like", "已处理", payload={"bvid": "BV1234567890"})
    pending = inbox.propose("private_reply", "待处理", payload={"receiver_id": 1})
    inbox.decide(decided["id"], "rejected")
    web_panel.app.testing = True

    response = web_panel.app.test_client().post("/api/reviews/audit/clear")

    assert response.status_code == 200
    assert response.get_json()["cleared"] == 1
    assert inbox.audit() == []
    assert inbox.list(status="pending")[0]["id"] == pending["id"]
