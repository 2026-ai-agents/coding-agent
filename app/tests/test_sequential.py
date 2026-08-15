"""v0.1의 약속: 계획이 서고, 하나씩 짜고, 합쳐서 돌린다."""

from agent import sequential
from agent.cost import Ledger
from agent.workspace import Project
from tests.conftest import ScriptedLLM, fake_response, plan_response, write_call


def runner_for(project: Project) -> sequential.Runner:
    return sequential.Runner(project, Ledger(), mode="sequential")


def test_planner_fills_all_three_roles(project, monkeypatch):
    monkeypatch.setattr(sequential, "completion", ScriptedLLM([plan_response()]))
    tasks = sequential.plan_tasks(runner_for(project), "SPEC")
    assert [t["role"] for t in tasks] == ["backend", "frontend", "tests"]
    assert [t["files"] for t in tasks] == [["app.py"], ["static/index.html"], ["tests/test_api.py"]]


def test_planner_survives_a_useless_answer(project, monkeypatch):
    """모델이 엉뚱하게 답해도 역할과 파일은 코드가 정한다."""
    monkeypatch.setattr(sequential, "completion", ScriptedLLM([fake_response(content="음…")]))
    tasks = sequential.plan_tasks(runner_for(project), "SPEC")
    assert len(tasks) == 3 and all(t["files"] for t in tasks)


def test_worker_writes_its_file_and_commits(project, monkeypatch):
    monkeypatch.setattr(sequential, "completion", ScriptedLLM([
        write_call("app.py", "# 생성된 백엔드\n"), fake_response(content="완료")]))
    task = {"role": "backend", "title": "구현", "detail": "만든다", "difficulty": "easy",
            "files": ["app.py"], "branch": "feature/backend", "status": "대기", "model": ""}
    result = sequential.work_on(runner_for(project), task, "SPEC", "fake-model")

    assert result["written"] == ["app.py"] and result["sha"]
    assert project.read_file("app.py").strip() == "# 생성된 백엔드"
    assert "backend: 구현" in project.graph()


def test_worker_cannot_touch_another_roles_file(project, monkeypatch):
    llm = ScriptedLLM([write_call("static/index.html", "<h1>남의 파일</h1>"),
                       write_call("app.py", "# 내 파일\n"), fake_response(content="완료")])
    monkeypatch.setattr(sequential, "completion", llm)
    task = {"role": "backend", "title": "구현", "detail": "만든다", "difficulty": "easy",
            "files": ["app.py"], "branch": "feature/backend", "status": "대기", "model": ""}
    result = sequential.work_on(runner_for(project), task, "SPEC", "fake-model")

    assert result["written"] == ["app.py"]
    assert "남의 파일" not in project.read_file("static/index.html")
    refusal = [m for m in llm.calls[-1]["messages"] if m.get("role") == "tool"][0]["content"]
    assert "거부" in refusal


def test_empty_content_is_refused(project, monkeypatch):
    llm = ScriptedLLM([write_call("app.py", "   "), fake_response(content="포기")])
    monkeypatch.setattr(sequential, "completion", llm)
    task = {"role": "backend", "title": "구현", "detail": "만든다", "difficulty": "easy",
            "files": ["app.py"], "branch": "feature/backend", "status": "대기", "model": ""}
    result = sequential.work_on(runner_for(project), task, "SPEC", "fake-model")
    assert result["status"] == "빈손"


def test_ledger_counts_every_call(project, monkeypatch):
    monkeypatch.setattr(sequential, "completion", ScriptedLLM([plan_response()]))
    runner = runner_for(project)
    sequential.plan_tasks(runner, "SPEC")
    totals = runner.ledger.totals()
    assert totals["calls"] == 1 and totals["in_tokens"] == 100 and totals["out_tokens"] == 200
