import web_panel


class ImmediateThread:
    def __init__(self, target, daemon):
        self.target = target
        self.daemon = daemon

    def start(self):
        self.target()


def setup_function():
    web_panel.app.testing = True
    with web_panel._TASKS_LOCK:
        web_panel.TASKS.clear()


def test_start_task_finishes_with_complete_result(monkeypatch):
    monkeypatch.setattr(web_panel.threading, "Thread", ImmediateThread)

    task_id = web_panel._start_task(
        "working",
        lambda tid: web_panel._finish_task(tid, {"value": "ready"}),
    )

    with web_panel._TASKS_LOCK:
        task = dict(web_panel.TASKS[task_id])
    assert task["status"] == "done"
    assert task["result"] == {"value": "ready"}
    assert task["error"] is None
    assert task["finished_at"]


def test_start_task_converts_unhandled_exception_to_error(monkeypatch):
    monkeypatch.setattr(web_panel.threading, "Thread", ImmediateThread)

    def fail(_task_id):
        raise RuntimeError("boom")

    task_id = web_panel._start_task("working", fail)

    with web_panel._TASKS_LOCK:
        task = dict(web_panel.TASKS[task_id])
    assert task["status"] == "error"
    assert task["result"] is None
    assert task["error"] == "boom"


def test_task_status_endpoint_returns_snapshot_and_notfound():
    with web_panel._TASKS_LOCK:
        web_panel.TASKS["complete"] = {
            "status": "done",
            "message": "complete",
            "result": {"value": "ready"},
            "error": None,
            "finished_at": 0,
        }

    client = web_panel.app.test_client()
    assert client.get("/api/action/task?id=missing").get_json() == {"status": "notfound"}
    assert client.get("/api/action/task?id=complete").get_json()["result"] == {"value": "ready"}


def test_cleanup_tasks_removes_only_expired_finished_tasks():
    with web_panel._TASKS_LOCK:
        web_panel.TASKS.update({
            "finished": {"status": "done", "finished_at": 200},
            "active": {"status": "running"},
            "recent": {"status": "error", "finished_at": 201},
        })
        web_panel._cleanup_tasks(now=200 + web_panel._TASK_TTL_SECONDS - 1)

    assert "finished" in web_panel.TASKS
    assert "recent" in web_panel.TASKS
    web_panel._cleanup_tasks(now=200 + web_panel._TASK_TTL_SECONDS)
    assert "finished" not in web_panel.TASKS
    assert "recent" in web_panel.TASKS
    assert "active" in web_panel.TASKS
