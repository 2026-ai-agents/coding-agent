"""v0.2 — worker 셋이 동시에 짠다.

v0.1과 **다른 것은 배치뿐이다.** planner도, worker가 하는 일도, integrator도
그대로 가져다 쓴다(그래서 비교가 공정하다). 바뀐 것은 두 줄이다.

  · Send        태스크 목록을 worker 노드로 한꺼번에 흩뿌린다
  · worktree    각자 자기 작업 디렉터리에서 짠다

두 번째가 없으면 첫 번째는 사고다. 브랜치를 나눠도 작업 트리가 하나면
셋이 같은 디렉터리에서 checkout 하며 서로의 파일을 밟는다. `git worktree`는
저장소 하나에 작업 디렉터리를 여럿 붙이는 기능이고, 정확히 이 자리를 위해
있다. **병렬화는 모델의 문제가 아니라 작업 공간의 문제다.**
"""

import time

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agent.config import pick_model
from agent.cost import Ledger
from agent.sequential import (
    RunState,
    Runner,
    _event,
    integrate,
    plan_tasks,
    work_on,
)
from agent.workspace import Project


def build_graph(runner: Runner) -> StateGraph:
    def planner(state: RunState) -> dict:
        tasks = plan_tasks(runner, state["spec"])
        runner.publish(tasks=tasks)
        return {"tasks": tasks,
                "events": [_event("planner", "태스크 분해", f"{len(tasks)}개 · 동시 시작")]}

    def fan_out(state: RunState) -> list[Send]:
        """여기가 v0.2의 전부다. 태스크마다 worker 하나씩."""
        return [Send("worker", {"task": task, "spec": state["spec"], "index": index})
                for index, task in enumerate(state["tasks"])]

    def worker(payload: dict) -> dict:
        task, index = payload["task"], payload["index"]
        with runner.lock:
            runner.status["tasks"][index]["status"] = "작업 중"
        runner.publish()

        worktree = runner.project.add_worktree(task["role"], task["branch"])
        try:
            result = work_on(runner, task, payload["spec"], pick_model("cheap"), worktree)
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

    graph = StateGraph(RunState)
    graph.add_node("planner", planner)
    graph.add_node("worker", worker)
    graph.add_node("integrator", integrator)
    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", fan_out, ["worker"])
    graph.add_edge("worker", "integrator")
    graph.add_edge("integrator", END)
    return graph


def run(spec: str, project: Project | None = None) -> dict:
    project = project or Project()
    project.docker_down()
    project.reset()
    runner = Runner(project, Ledger(), mode="parallel")
    runner.publish(state="running", tasks=[], events=[])

    compiled = build_graph(runner).compile()
    result = compiled.invoke({"spec": spec, "tasks": [], "results": [], "events": [],
                              "merged": False, "tested": False, "served": False, "report": ""})
    elapsed = round(time.time() - runner.started, 1)
    runner.publish(state="done" if result["served"] else "failed", elapsed_s=elapsed)
    return {"mode": "parallel", "elapsed_s": elapsed, "tasks": runner.status["tasks"],
            "merged": result["merged"], "tested": result["tested"], "served": result["served"],
            "report": result["report"], "cost": runner.ledger.totals(),
            "graph": project.graph()}
