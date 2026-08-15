"""v0.2의 약속: 동시에 짜되, 서로의 파일을 밟지 않는다.

병렬화의 어려움은 모델이 아니라 작업 공간에 있다. 그래서 시험하는 것도
worktree가 정말로 갈라져 있는지, Send가 태스크마다 worker를 하나씩 띄우는지
두 가지다.
"""

from agent import graph as parallel
from agent import sequential
from agent.cost import Ledger
from tests.conftest import fake_response, plan_response, write_call

ROLE_FILES = {"backend": "app.py", "frontend": "static/index.html",
              "tests": "tests/test_api.py"}


class ByRoleLLM:
    """동시에 불려도 순서에 기대지 않는 대역 — 프롬프트를 보고 답한다."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs["messages"][0]["content"]
        if "플래너" in prompt:
            return plan_response()
        for role, path in ROLE_FILES.items():
            if f"당신은 {role} 담당" in prompt:
                return write_call(path, f"# {role}가 쓴 파일\n")
        return fake_response(content="완료")


def test_worktrees_do_not_share_a_directory(project):
    backend = project.add_worktree("backend", "feature/backend")
    frontend = project.add_worktree("frontend", "feature/frontend")

    assert backend.path != frontend.path != project.path
    backend.write_file("app.py", "# 백엔드\n")
    frontend.write_file("static/index.html", "<h1>프론트</h1>\n")
    backend.commit("backend: 구현")
    frontend.commit("frontend: 구현")

    # 본체는 그대로다. 각자 자기 트리에서 짰다.
    assert project.read_file("app.py") != "# 백엔드\n"
    assert "backend: 구현" in project.graph() and "frontend: 구현" in project.graph()

    project.remove_worktree("backend")
    project.remove_worktree("frontend")
    merged, _ = project.merge(["feature/backend", "feature/frontend"])
    assert merged
    assert project.read_file("app.py") == "# 백엔드\n"
    assert project.read_file("static/index.html") == "<h1>프론트</h1>\n"


def test_send_dispatches_one_worker_per_task(project, monkeypatch):
    llm = ByRoleLLM()
    monkeypatch.setattr(sequential, "completion", llm)
    monkeypatch.setattr(parallel, "integrate", lambda runner, results: {
        "merged": True, "tested": True, "served": True, "report": "테스트 대역"})

    runner = sequential.Runner(project, Ledger(), mode="parallel")
    compiled = parallel.build_graph(runner).compile()
    result = compiled.invoke({"spec": "SPEC", "tasks": [], "results": [], "events": [],
                              "merged": False, "tested": False, "served": False, "report": ""})

    assert len(result["results"]) == 3
    assert {r["role"] for r in result["results"]} == set(ROLE_FILES)
    assert all(r["sha"] for r in result["results"])
    branches = project.git("branch", "--list")[1]
    assert all(f"feature/{role}" in branches for role in ROLE_FILES)


def test_worktrees_are_cleaned_up_after_the_run(project, monkeypatch):
    monkeypatch.setattr(sequential, "completion", ByRoleLLM())
    monkeypatch.setattr(parallel, "integrate", lambda runner, results: {
        "merged": True, "tested": True, "served": True, "report": ""})

    runner = sequential.Runner(project, Ledger(), mode="parallel")
    parallel.build_graph(runner).compile().invoke(
        {"spec": "SPEC", "tasks": [], "results": [], "events": [],
         "merged": False, "tested": False, "served": False, "report": ""})

    listed = project.git("worktree", "list")[1].splitlines()
    assert len(listed) == 1                                        # 본체 하나만 남았고
    assert "feature/backend" in project.git("branch", "--list")[1]  # 브랜치는 남았다


def test_parallel_reuses_the_sequential_parts():
    """공정한 비교의 조건 — 배치만 다르고 부품은 같다."""
    assert parallel.plan_tasks is sequential.plan_tasks
    assert parallel.work_on is sequential.work_on
