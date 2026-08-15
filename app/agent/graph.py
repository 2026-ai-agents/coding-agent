"""병렬 파이프라인 — 동시에 짜고(v0.2), 값을 먼저 묻는다(v0.3).

v0.1과 **다른 것은 배치뿐이다.** planner도, worker가 하는 일도, integrator도
그대로 가져다 쓴다(그래서 비교가 공정하다). 바뀐 것은 두 줄이다.

  · Send        태스크 목록을 worker 노드로 한꺼번에 흩뿌린다
  · worktree    각자 자기 작업 디렉터리에서 짠다

두 번째가 없으면 첫 번째는 사고다. 브랜치를 나눠도 작업 트리가 하나면
셋이 같은 디렉터리에서 checkout 하며 서로의 파일을 밟는다. `git worktree`는
저장소 하나에 작업 디렉터리를 여럿 붙이는 기능이고, 정확히 이 자리를 위해
있다. **병렬화는 모델의 문제가 아니라 작업 공간의 문제다.**

v0.3에서 planner와 worker 사이에 문 하나를 세웠다.

  · 모델 배정  난이도가 hard면 상위 모델, easy면 저가 모델
  · 비용 게이트 실행 전에 예상 비용을 계산하고, 상한을 넘으면 interrupt로
               사람에게 묻는다. 승인 없이는 한 줄도 짜지 않는다

Day 2의 interrupt가 여기서 돈 앞에 선다. 자동화의 문제는 폭주가 아니라
**폭주를 알아차릴 자리가 없다는 것**이고, 게이트는 그 자리를 만든다.
"""

import os
import time

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from agent.config import pick_model
from agent.cost import Ledger, estimate_run
from agent.sequential import (
    RunState,
    Runner,
    _event,
    integrate,
    plan_tasks,
    work_on,
)
from agent.workspace import Project

# 상한을 넘으면 묻는다. 넘지 않으면 묻지 않는다. 매번 묻는 문은 문이 아니다.
BUDGET_USD = float(os.environ.get("BUDGET_USD", "0.02"))


def assign_model(task: dict) -> str:
    """난이도가 모델을 고른다. 쉬운 일에 비싼 모델을 붙일 이유가 없다."""
    return pick_model("strong" if task.get("difficulty") == "hard" else "cheap")


def build_graph(runner: Runner, budget_usd: float | None = None) -> StateGraph:
    budget = BUDGET_USD if budget_usd is None else budget_usd
    def planner(state: RunState) -> dict:
        tasks = plan_tasks(runner, state["spec"])
        runner.publish(tasks=tasks)
        return {"tasks": tasks,
                "events": [_event("planner", "태스크 분해", f"{len(tasks)}개 · 동시 시작")]}

    def gate(state: RunState) -> dict:
        """실행 전에 값을 묻는다. 상한 안이면 조용히 지나간다."""
        tasks = [{**task, "model": assign_model(task)} for task in state["tasks"]]
        estimate = estimate_run(tasks, prompt_chars=len(state["spec"]) + 1200)
        runner.publish(tasks=tasks, estimate=estimate, budget_usd=budget)
        runner.note(_event("gate", "비용 추정",
                           f"${estimate['total_usd']:.4f} (상한 ${budget:.4f})"))

        if estimate["total_usd"] <= budget:
            return {"tasks": tasks, "approved": True}

        runner.publish(state="approval_needed")
        answer = interrupt({"reason": "예상 비용이 상한을 넘습니다",
                            "estimate": estimate, "budget_usd": budget})
        approved = bool(answer.get("approved")) if isinstance(answer, dict) else bool(answer)
        runner.publish(state="running")
        runner.note(_event("gate", "사람의 판단", "승인" if approved else "중단"))
        return {"tasks": tasks, "approved": approved}

    def fan_out(state: RunState) -> list[Send]:
        """여기가 v0.2의 전부다. 태스크마다 worker 하나씩."""
        if not state.get("approved"):
            return "stopped"                     # 승인하지 않았으면 짜지 않는다
        return [Send("worker", {"task": task, "spec": state["spec"], "index": index})
                for index, task in enumerate(state["tasks"])]

    def worker(payload: dict) -> dict:
        task, index = payload["task"], payload["index"]
        with runner.lock:
            runner.status["tasks"][index]["status"] = "작업 중"
        runner.publish()

        worktree = runner.project.add_worktree(task["role"], task["branch"])
        try:
            result = work_on(runner, task, payload["spec"],
                             task.get("model") or pick_model("cheap"), worktree)
        finally:
            runner.project.remove_worktree(task["role"])   # 브랜치는 남고 디렉터리만 치운다

        with runner.lock:
            runner.status["tasks"][index] = result
        runner.publish()
        return {"results": [result]}

    def integrator(state: RunState) -> dict:
        outcome = integrate(runner, state["results"])
        runner.publish(state="done" if outcome["served"] else "failed")
        return outcome

    def stopped(state: RunState) -> dict:
        runner.publish(state="stopped")
        return {"merged": False, "tested": False, "served": False,
                "report": "비용 상한을 넘어 사용자가 중단했습니다"}

    graph = StateGraph(RunState)
    graph.add_node("planner", planner)
    graph.add_node("gate", gate)
    graph.add_node("worker", worker)
    graph.add_node("integrator", integrator)
    graph.add_node("stopped", stopped)
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "gate")
    graph.add_conditional_edges("gate", fan_out, ["worker", "stopped"])
    graph.add_edge("worker", "integrator")
    graph.add_edge("integrator", END)
    graph.add_edge("stopped", END)
    return graph


# 게이트에서 멈춘 실행을 다시 이어가려면 그래프와 러너를 붙들고 있어야 한다.
ACTIVE: dict = {}


def _finish(runner: Runner, result: dict) -> dict:
    elapsed = round(time.time() - runner.started, 1)
    state = "done" if result["served"] else ("stopped" if "중단" in result.get("report", "")
                                             else "failed")
    runner.publish(state=state, elapsed_s=elapsed)
    return {"mode": "parallel", "elapsed_s": elapsed, "tasks": runner.status["tasks"],
            "merged": result["merged"], "tested": result["tested"], "served": result["served"],
            "report": result["report"], "cost": runner.ledger.totals(),
            "estimate": runner.status.get("estimate", {}), "graph": runner.project.graph()}


def run(spec: str, project: Project | None = None, budget_usd: float | None = None) -> dict:
    project = project or Project()
    project.docker_down()
    project.reset()
    runner = Runner(project, Ledger(), mode="parallel")
    runner.publish(state="running", tasks=[], events=[])

    compiled = build_graph(runner, budget_usd).compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": f"run-{int(runner.started)}"}}
    ACTIVE.update({"compiled": compiled, "runner": runner, "config": config})

    result = compiled.invoke({"spec": spec, "tasks": [], "results": [], "events": [],
                              "merged": False, "tested": False, "served": False,
                              "approved": False, "report": ""}, config)
    if "__interrupt__" in result:                # 게이트에서 멈췄다
        runner.publish(state="approval_needed")
        return {"mode": "parallel", "state": "approval_needed",
                "estimate": runner.status.get("estimate", {}),
                "budget_usd": BUDGET_USD if budget_usd is None else budget_usd}
    return _finish(runner, result)


def resume(approved: bool) -> dict:
    """사람이 답한 뒤 이어서 돈다."""
    if not ACTIVE:
        return {"error": "이어갈 실행이 없습니다"}
    result = ACTIVE["compiled"].invoke(Command(resume={"approved": approved}), ACTIVE["config"])
    return _finish(ACTIVE["runner"], result)
