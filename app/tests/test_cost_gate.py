"""v0.3의 약속: 값을 먼저 재고, 넘으면 사람에게 묻고, 거절하면 짜지 않는다."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent import graph as parallel
from agent import sequential
from agent.cost import Ledger, estimate_run
from agent.config import pick_model
from tests.conftest import plan_response
from tests.test_parallel import ByRoleLLM


def start(project, budget: float, monkeypatch, difficulties: dict | None = None):
    monkeypatch.setattr(sequential, "completion", ByRoleLLM())
    if difficulties:
        monkeypatch.setattr(sequential, "completion",
                            lambda **kw: plan_response(difficulties)
                            if "플래너" in kw["messages"][0]["content"] else ByRoleLLM()(**kw))
    monkeypatch.setattr(parallel, "integrate", lambda runner, results: {
        "merged": True, "tested": True, "served": True, "report": "테스트 대역"})

    runner = sequential.Runner(project, Ledger(), mode="parallel")
    compiled = parallel.build_graph(runner, budget_usd=budget).compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "test"}}
    result = compiled.invoke({"spec": "SPEC", "tasks": [], "results": [], "events": [],
                              "merged": False, "tested": False, "served": False,
                              "approved": False, "report": ""}, config)
    return runner, compiled, config, result


def test_hard_tasks_get_the_strong_model():
    assert parallel.assign_model({"difficulty": "hard"}) == pick_model("strong")
    assert parallel.assign_model({"difficulty": "easy"}) == pick_model("cheap")
    assert pick_model("strong") != pick_model("cheap")


def test_estimate_grows_with_the_expensive_model():
    cheap = estimate_run([{"role": "backend", "model": pick_model("cheap")}], 3000)
    strong = estimate_run([{"role": "backend", "model": pick_model("strong")}], 3000)
    assert strong["total_usd"] > cheap["total_usd"]


def test_a_roomy_ceiling_does_not_ask(project, monkeypatch):
    runner, _, _, result = start(project, budget=10.0, monkeypatch=monkeypatch)
    assert "__interrupt__" not in result
    assert len(result["results"]) == 3
    assert not any(event["action"] == "사람의 판단" for event in runner.status["events"])


def test_a_tight_ceiling_stops_and_asks(project, monkeypatch):
    runner, compiled, config, result = start(project, budget=0.0, monkeypatch=monkeypatch)
    assert "__interrupt__" in result
    assert runner.status["state"] == "approval_needed"
    assert runner.status["estimate"]["total_usd"] > 0
    assert "feature/" not in project.git("branch", "--list")[1]   # 아직 한 줄도 짜지 않았다


def test_approval_lets_the_work_start(project, monkeypatch):
    runner, compiled, config, _ = start(project, budget=0.0, monkeypatch=monkeypatch)
    result = compiled.invoke(Command(resume={"approved": True}), config)
    assert len(result["results"]) == 3
    assert "feature/backend" in project.git("branch", "--list")[1]


def test_refusal_writes_nothing(project, monkeypatch):
    runner, compiled, config, _ = start(project, budget=0.0, monkeypatch=monkeypatch)
    result = compiled.invoke(Command(resume={"approved": False}), config)
    assert result["results"] == [] and not result["served"]
    assert "중단" in result["report"]
    assert "feature/" not in project.git("branch", "--list")[1]
    assert runner.ledger.totals()["calls"] == 1                 # planner 한 번뿐
