"""v0.4의 약속: 실패하면 고치고, 못 고치면 다시 계획하고, 한도가 있으면 멈춘다.

여기서는 integrate를 대역으로 갈아끼워 실패를 결정적으로 만든다. 진짜
실패는 매번 다르게 나므로 배선을 시험하기에는 맞지 않는다.
"""

import json

from langgraph.checkpoint.memory import InMemorySaver

from agent import graph as parallel
from agent import sequential
from agent.cost import Ledger
from tests.conftest import fake_response, fake_tool_call
from tests.test_parallel import ByRoleLLM


class FailingIntegrate:
    """앞의 n번은 실패하고 그다음부터 성공하는 통합."""

    def __init__(self, failures: int):
        self.left = failures
        self.calls = 0

    def __call__(self, runner, results):
        self.calls += 1
        if self.left > 0:
            self.left -= 1
            return {"merged": True, "tested": False, "served": False,
                    "report": "FAILED tests/test_api.py::test_create - assert 201 == 200"}
        return {"merged": True, "tested": True, "served": True, "report": "완료"}


class FixerLLM(ByRoleLLM):
    """플래너·워커는 그대로, 고치기 요청에는 파일을 하나 다시 쓴다."""

    def __call__(self, **kwargs):
        prompt = kwargs["messages"][0]["content"]
        if "통합 담당" in prompt:
            self.calls.append(kwargs)
            return fake_response(tool_calls=[fake_tool_call(
                "write_file", {"path": "tests/test_api.py", "content": "# 고쳐진 테스트\n"})])
        return super().__call__(**kwargs)


def start(project, monkeypatch, failures: int, max_fixes: int | None = None):
    llm = FixerLLM()
    monkeypatch.setattr(sequential, "completion", llm)
    integrate = FailingIntegrate(failures)
    monkeypatch.setattr(parallel, "integrate", integrate)

    runner = sequential.Runner(project, Ledger(), mode="parallel")
    compiled = parallel.build_graph(runner, budget_usd=10.0,
                                    max_fixes=max_fixes).compile(checkpointer=InMemorySaver())
    result = compiled.invoke({"spec": "SPEC", "tasks": [], "results": [], "events": [],
                              "merged": False, "tested": False, "served": False,
                              "approved": False, "report": "", "failure": "",
                              "fix_rounds": 0, "replans": 0},
                             {"configurable": {"thread_id": "test"}})
    return runner, result, integrate


def test_a_single_failure_is_fixed_and_retried(project, monkeypatch):
    runner, result, integrate = start(project, monkeypatch, failures=1)
    assert result["served"] and result["fix_rounds"] == 1
    assert integrate.calls == 2                      # 실패 한 번, 다시 통합 한 번
    assert project.read_file("tests/test_api.py") == "# 고쳐진 테스트\n"
    assert any(event["action"].startswith("수정") for event in runner.status["events"])


def test_the_failure_log_reaches_the_fixer(project, monkeypatch):
    runner, _, _ = start(project, monkeypatch, failures=1)
    fixer_calls = [c for c in runner.ledger.entries if c["who"] == "fixer"]
    assert len(fixer_calls) == 1


def test_fix_limit_hands_over_to_replanning(project, monkeypatch):
    """고치기를 아무리 해도 안 되면 계획부터 다시. 새 브랜치에서 짠다."""
    runner, result, _ = start(project, monkeypatch, failures=3, max_fixes=1)
    assert result["replans"] == 1
    branches = project.git("branch", "--list")[1]
    assert "feature/backend-r2" in branches          # 두 번째 시도의 흔적이 남는다


def test_it_gives_up_instead_of_looping_forever(project, monkeypatch):
    runner, result, integrate = start(project, monkeypatch, failures=99, max_fixes=1)
    assert not result["served"]
    assert result["replans"] <= parallel.MAX_REPLANS
    assert integrate.calls <= 6                      # 무한히 돌지 않았다
    assert runner.status["state"] == "failed"


def test_the_fixer_may_only_touch_product_files():
    assert set(parallel.FIXABLE_FILES) == {"app.py", "static/index.html", "tests/test_api.py"}
    assert "Dockerfile" not in parallel.FIXABLE_FILES
