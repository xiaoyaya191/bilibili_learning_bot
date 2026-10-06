from services.learning_loop import LearningLoopService


def test_goal_tree_mastery_weakness_and_plan(tmp_path):
    service = LearningLoopService(tmp_path / "learning.sqlite3", tmp_path / "kb")
    goal = service.create_goal("Python", "系统掌握异步编程", "systematic", "learning")
    basics = service.add_node(goal["id"], "协程基础", "async await 事件循环")
    advanced = service.add_node(goal["id"], "任务调度", parent_id=basics["id"])
    updated = service.record_evidence(basics["id"], 45, "diagnostic", 1, "事件循环理解不足")
    assert updated["status"] == "learning"
    assert service.summary(goal["id"])["stats"]["gaps"] == 2
    assert service.next_plan(goal["id"])["current_node"]["id"] == advanced["id"]
    quiz = service.record_quiz(goal["id"], basics["id"], 1, 3, [{"question": "Q", "answer": "A", "expected": "B"}])
    assert quiz["score"] == 33.33
    summary = service.summary(goal["id"])
    assert summary["stats"]["unresolved_mistakes"] == 1
    assert len(summary["review_tasks"]) == 1


def test_candidates_are_deduplicated_and_learning_updates_state(tmp_path):
    service = LearningLoopService(tmp_path / "learning.sqlite3", tmp_path / "kb")
    goal = service.create_goal("数据库")
    node = service.add_node(goal["id"], "索引")
    first = service.add_candidate(goal["id"], "BV123", "索引入门", node["id"], 7.5)
    second = service.add_candidate(goal["id"], "BV123", "索引实战", node["id"], 9.0)
    assert first["id"] == second["id"]
    assert service.summary(goal["id"])["candidates"][0]["title"] == "索引实战"
    service.record_learning(goal["id"], node["id"], "BV123", "索引实战", "notes/index.md")
    assert service.summary(goal["id"])["candidates"][0]["status"] == "learned"


def test_legacy_mode_is_normalized_without_starting_any_process(tmp_path):
    service = LearningLoopService(tmp_path / "learning.sqlite3", tmp_path / "kb")
    goal = service.create_goal("陪我聊天", mode="companion")
    assert goal["status"] == "active"
    assert goal["mode"] == "learn_companion"
