from pathlib import Path
import json
import shutil
import subprocess

import pytest

from core.factory_reset import erase_all_user_data, preview_reset_targets


@pytest.fixture
def reset_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delenv("BILI_ACCOUNT_ID", raising=False)
    root = tmp_path / "user"
    project = tmp_path / "project"
    root.mkdir()
    project.mkdir()
    return dict(data_dir=root / "Data", user_data_dir=root, project_dir=project,
                backup_dir=root / "backups", cipher_key_file=root / ".cipher_key", config={})


def test_full_current_account_reset_clears_databases_caches_and_root_records(reset_paths):
    root = reset_paths["user_data_dir"]
    files = ["Data/account_data.sqlite3", "Data/account_data.sqlite3-wal", "Data/agent_workspace.sqlite3",
             "Data/video_watch_queue.sqlite3", "Data/token_usage.sqlite3", "custom-state.json",
             "account_data.sqlite3-shm", "diary.md", "logs/runtime.log", "uploads/background.png",
             "cache/subtitle.txt", "tmp/video.mp4", "models/whisper.bin", "KnowledgeBase/note.md"]
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private", encoding="utf-8")
    result = erase_all_user_data(**reset_paths, selected_groups=["credentials_runtime", "knowledge_generated", "local_models", "backup_files"])
    assert not result["failures"]
    assert all(not (root / name).exists() for name in files)
    assert reset_paths["data_dir"].is_dir()


def test_backup_inside_runtime_directory_is_preserved_until_selected(reset_paths):
    backup = reset_paths["data_dir"] / "backups"
    reset_paths["backup_dir"] = backup
    file = backup / "config.json"
    file.parent.mkdir(parents=True)
    file.write_text("backup", encoding="utf-8")
    erase_all_user_data(**reset_paths, selected_groups=["credentials_runtime"])
    assert file.read_text(encoding="utf-8") == "backup"
    result = erase_all_user_data(**reset_paths, selected_groups=["backup_files"])
    assert not result["failures"] and not file.exists()


@pytest.mark.parametrize("source", ["core", "services", ".."])
def test_custom_reset_paths_cannot_delete_source_or_parent(reset_paths, source):
    reset_paths["config"] = {"knowledge_base_dir": str(reset_paths["project_dir"] / source)}
    with pytest.raises(ValueError, match="不安全"):
        preview_reset_targets(**reset_paths)


def test_isolated_account_reset_never_clears_shared_or_other_account_files(reset_paths, monkeypatch):
    monkeypatch.setenv("BILI_ACCOUNT_ID", "account-002")
    shared = reset_paths["project_dir"] / "KnowledgeBase" / "shared.md"
    other = reset_paths["user_data_dir"] / "accounts" / "account-003" / "Data" / "config.json"
    external = reset_paths["project_dir"].parent / "external" / "note.md"
    for file in (shared, other, external):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("keep", encoding="utf-8")
    reset_paths["config"] = {"knowledge_base_dir": str(external.parent)}
    result = erase_all_user_data(**reset_paths)
    assert not result["failures"]
    assert all(file.exists() for file in (shared, other, external))


def test_empty_selection_does_not_fall_back_to_deleting_defaults(reset_paths):
    with pytest.raises(ValueError):
        erase_all_user_data(**reset_paths, selected_groups=[])
    with pytest.raises(ValueError):
        preview_reset_targets(**reset_paths, selected_groups=[])


@pytest.fixture
def reset_client(reset_paths, monkeypatch):
    import web_panel
    import core.config
    monkeypatch.setitem(web_panel.app.before_request_funcs, None, [])
    monkeypatch.setattr(web_panel.app, "secret_key", "reset-test-key")
    for attribute, key in [("DATA_DIR", "data_dir"), ("USER_DATA_DIR", "user_data_dir"), ("BASE_DIR", "project_dir")]:
        monkeypatch.setattr(web_panel, attribute, reset_paths[key])
    reset_paths["data_dir"].mkdir()
    config = reset_paths["data_dir"] / "config.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(web_panel, "CONFIG_FILE", config)
    monkeypatch.setattr(web_panel, "get_backup_dir", lambda: reset_paths["backup_dir"])
    monkeypatch.setattr(core.config, "CIPHER_KEY_FILE", str(reset_paths["cipher_key_file"]))
    monkeypatch.setattr(web_panel, "_reset_busy_tasks", lambda: [])
    return web_panel.app.test_client()


@pytest.mark.parametrize("body", [[], "invalid", {"selected_groups": []}, {"selected_groups": [1]}, {"selected_groups": ["unknown"]}])
def test_reset_request_rejects_malformed_or_empty_selections(reset_client, body):
    assert reset_client.post("/api/factory-reset/request", json=body).status_code == 400


def test_reset_token_is_bound_to_requesting_browser(reset_client):
    import web_panel
    token = reset_client.post("/api/factory-reset/request").get_json()["token"]
    other = web_panel.app.test_client()
    assert other.post("/api/factory-reset", json={"confirm_token": token}).status_code == 403
    assert web_panel._factory_reset_pending_token["token"] == token


def test_busy_reset_does_not_delete_any_data(reset_client, reset_paths, monkeypatch):
    import web_panel
    token = reset_client.post("/api/factory-reset/request").get_json()["token"]
    monkeypatch.setattr(web_panel, "_reset_busy_tasks", lambda: ["Agent 助理"])
    assert reset_client.post("/api/factory-reset", json={"confirm_token": token}).status_code == 409
    assert (reset_paths["data_dir"] / "config.json").exists()


def test_reset_rejects_paths_changed_after_preview(reset_client, reset_paths):
    token = reset_client.post("/api/factory-reset/request").get_json()["token"]
    path = reset_paths["data_dir"] / "config.json"
    path.write_text(json.dumps({"knowledge_base_dir": str(reset_paths["project_dir"].parent / "new-knowledge")}), encoding="utf-8")
    result = reset_client.post("/api/factory-reset", json={"confirm_token": token})
    assert result.status_code == 409
    assert path.exists()


def test_storage_open_root_does_not_accept_arbitrary_paths(reset_client, reset_paths, monkeypatch):
    import web_panel
    opened = []
    monkeypatch.setattr(web_panel.os, "startfile", lambda path: opened.append(path), raising=False)
    monkeypatch.setattr(web_panel.subprocess, "Popen", lambda command, **kwargs: opened.append(command[-1]))
    result = reset_client.post("/api/storage/open", json={"group": "root"})
    assert result.get_json()["ok"] is True
    assert opened == [str(reset_paths["user_data_dir"].resolve())]
    assert reset_client.post("/api/storage/open", json={"group": "../"}).status_code == 400
    assert reset_client.post("/api/storage/open", json=[]).status_code == 400


def test_agent_keyboard_and_page_scoped_consent_behavior(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the front-end regression")
    script = Path(__file__).resolve().parents[1] / "assets/js/agent-assistant.js"
    harness = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = {};
let permissions = ['project'];
let confirmations = 0;
let sent = 0;
let allow = true;
const element = id => elements[id] ||= {value:'',dataset:{},focus(){},addEventListener(name,handler){this.handler=handler}};
const context = {console, setTimeout, clearTimeout, document:{getElementById:element,querySelectorAll(){return permissions.map(permission=>({dataset:{assistantPermission:permission}}))}},toast(){},panelConfirm:async()=>{confirmations++;return allow},api:async(method,path)=>{if(path==='/api/agent/assistant/send'){sent++;return {ok:true,conversation_id:'test',turn_id:'turn'}}return {ok:true,conversations:[],permissions:{project:'project'},defaults:['project']}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
context.assistantRenderList=()=>{};
context.assistantLoadPortrait=async()=>{};
context.assistantWelcome=()=>{};
context.assistantRefresh=async()=>{};
(async()=>{
await context.agentAssistantInit();
const handler=element('assistantMessage').handler;
let keyboard=0;
const original=context.assistantSend;
context.assistantSend=()=>{keyboard++};
const key=extra=>({key:'Enter',preventDefault(){},...extra});
handler(key({shiftKey:true}));handler(key({isComposing:true}));handler(key({keyCode:229}));assert.equal(keyboard,0);
handler(key({}));assert.equal(keyboard,1);
context.assistantSend=original;
const send=async()=>{element('assistantMessage').value='hello';await context.assistantSend()};
await send();await send();assert.equal(confirmations,1);assert.equal(sent,2);
permissions=['project','contacts'];await send();assert.equal(confirmations,2);
context.assistantRevokeConsent();await send();assert.equal(confirmations,3);
context.assistantRevokeConsent();allow=false;await send();assert.equal(sent,4);assert.equal(element('assistantMessage').value,'hello');
context.assistantState.busy=true;await send();assert.equal(sent,4);
console.log('Agent keyboard and consent regression passed');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    test = tmp_path / "agent-regression.cjs"
    test.write_text(harness, encoding="utf-8")
    subprocess.run([node, str(test), str(script)], check=True, capture_output=True, text=True)


@pytest.mark.parametrize("filename", ["diary_schedule.sqlite3", "evolution.sqlite3"])
def test_reset_busy_detection_checks_background_generation_database(tmp_path, monkeypatch, filename):
    import sqlite3
    import web_panel
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    with sqlite3.connect(tmp_path / filename) as database:
        database.execute("CREATE TABLE jobs(status TEXT,deadline TEXT)")
        database.execute("INSERT INTO jobs VALUES('running','2999-01-01T00:00:00')")
    assert any("生成" in name for name in web_panel._reset_busy_tasks())
