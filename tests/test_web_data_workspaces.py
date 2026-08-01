from pathlib import Path

import web_panel
from services.knowledge_tutor import scan_md_files


def _authenticated_client():
    web_panel.app.testing = True
    client = web_panel.app.test_client()
    with client.session_transaction() as session:
        session["disclaimer_agreed"] = True
        session["panel_authenticated"] = True
    return client


def test_user_profiles_endpoint_reads_flat_bot_profile_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    web_panel.write_json(tmp_path / "user_profiles.json", {
        "42": {"name": "tester", "affinity": 0.35, "interactions": 3, "impression": "helpful"},
    })

    data = _authenticated_client().get("/api/users").get_json()
    assert data["summary"]["total"] == 1
    assert data["users"]["42"]["affinity_score"] == 35
    assert data["users"]["42"]["interaction_count"] == 3
    assert "helpful" in data["users"]["42"]["notes"]


def test_user_profile_update_preserves_flat_profile_store(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    web_panel.write_json(tmp_path / "user_profiles.json", {"7": {"interactions": 2, "affinity": 0.1}})

    response = _authenticated_client().post("/api/users/update", json={
        "uid": "7", "name": "edited", "tags": ["research"], "notes": ["prefers evidence"],
    })
    assert response.status_code == 200
    stored = web_panel.read_json(tmp_path / "user_profiles.json", {})
    assert stored["7"]["name"] == "edited"
    assert stored["7"]["interactions"] == 2


def test_knowledge_scan_and_web_api_accept_runtime_configured_directory(tmp_path, monkeypatch):
    kb_dir = tmp_path / "runtime-kb"
    category = kb_dir / "research"
    category.mkdir(parents=True)
    note = category / "[BV1ab411c7mD] - runtime note.md"
    note.write_text("# runtime note\n\n**UP主**: tester", encoding="utf-8")
    monkeypatch.setattr(web_panel, "active_knowledge_base_dir", lambda: kb_dir)

    assert scan_md_files(kb_dir)[0]["rel_path"] == "research/runtime note.md" or scan_md_files(kb_dir)[0]["rel_path"] == "research/[BV1ab411c7mD] - runtime note.md"
    response = _authenticated_client().get("/api/kb/list-files")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] == 1
    assert payload["files"][0]["video_url"] == "https://www.bilibili.com/video/BV1ab411c7mD"
    assert "cover" in payload["files"][0]


def test_custom_knowledge_search_returns_actions_safe_metadata(tmp_path, monkeypatch):
    kb_dir = tmp_path / "kb"
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel, "USER_DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel, "active_knowledge_base_dir", lambda: kb_dir)
    client = _authenticated_client()

    created = client.post("/api/kb/custom-add", json={
        "title": "quoted title", "category": "topic", "content": "custom knowledge content",
    }).get_json()
    found = client.post("/api/kb/custom-search", json={"q": "custom knowledge"}).get_json()
    assert created["ok"] is True
    assert found["ok"] is True
    assert found["entries"][0]["bvid"] == created["bvid"]
    assert found["entries"][0]["category"] == "topic"


def test_workspace_template_uses_themed_search_fields_and_safe_dynamic_actions():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")
    for marker in (
        "search-input",
        "userEdit(decodeURIComponent",
        "openMemKbNote(decodeURIComponent",
        "_upCandidates",
        "userStats",
        "tutorFileGrid",
        "switchTutorFileView",
        "switchMemKbView",
        "knowledge-media-card",
    ):
        assert marker in template


def test_generated_mindmap_can_be_deleted_without_deleting_its_source(tmp_path, monkeypatch):
    import core.user_data as user_data

    mindmaps = tmp_path / "MindMaps"
    mindmaps.mkdir()
    generated = mindmaps / "example.mindmap.html"
    generated.write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(user_data, "MINDMAPS_DIR", mindmaps)

    response = _authenticated_client().post("/api/mindmaps/delete", json={
        "path": str(generated),
        "confirmed": True,
    })

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert not generated.exists()
