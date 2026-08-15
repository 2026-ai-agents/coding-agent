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

v0.4는 실패한 뒤를 다룬다. 셋이 따로 짜면 규약의 빈틈에서 어긋난다.
실제로 관찰된 실패는 이랬다. backend는 생성에 201을 돌려주고, tests는 200을
기대했다. 규약이 상태 코드를 못 박지 않았기 때문이다.

  · 고치기   실패 로그를 읽고 한 파일을 다시 쓴다 (최대 MAX_FIXES회)
  · 재계획   그래도 안 되면 planner로 돌아가 새 브랜치에서 다시 짠다
  · 포기     재계획도 한도가 있다. 무한히 도는 자동화는 자동화가 아니다

Day 1의 Reflexion이 여기서는 빌드 로그를 되먹이는 일이 된다.
"""

import os
import time

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from agent import scaffold
from agent.config import pick_model
from agent.cost import Ledger, estimate_run
from agent.sequential import (
    WRITE_FILE_TOOL,
    RunState,
    Runner,
    _event,
    _parse,
    integrate,
    plan_tasks,
    work_on,
)
from agent.workspace import Project

# 상한을 넘으면 묻는다. 넘지 않으면 묻지 않는다. 매번 묻는 문은 문이 아니다.
BUDGET_USD = float(os.environ.get("BUDGET_USD", "0.02"))

MAX_FIXES = 2        # integrator가 같은 시도 안에서 고쳐 볼 횟수
MAX_REPLANS = 1      # 그래도 안 되면 계획부터 다시. 그것도 한 번뿐이다

FIXABLE_FILES = ["app.py", "static/index.html", "tests/test_api.py"]

FIXER_PROMPT = """당신은 통합 담당입니다. 셋이 따로 짠 코드를 합쳤더니 아래처럼
실패했습니다. **파일 하나만** 골라 전체 내용을 다시 써서 고치십시오.

실패 로그
--------
{failure}

현재 파일
--------
{files}

규약
----
{contract}

write_file 도구로 고친 파일 하나를 쓰십시오. 설명은 하지 마십시오.
테스트가 규약과 어긋나면 테스트를 고쳐도 되고, 서버가 어긋나면 서버를
고쳐도 됩니다. 무엇이 규약에 맞는지로 판단하십시오."""


def assign_model(task: dict) -> str:
    """난이도가 모델을 고른다. 쉬운 일에 비싼 모델을 붙일 이유가 없다."""
    return pick_model("strong" if task.get("difficulty") == "hard" else "cheap")


def fix_once(runner: Runner, failure: str) -> tuple[list[str], str]:
    """실패 로그를 읽고 한 파일을 다시 쓴다. Day 1의 Reflexion이 하던 일.

    고르는 것은 모델이다. 테스트가 규약과 어긋났으면 테스트를, 서버가
    어긋났으면 서버를 고친다. 우리가 정하는 것은 **한 번에 한 파일**이라는
    제약뿐이다. 여러 파일을 한꺼번에 고치게 두면 무엇이 나았는지 알 수 없다.
    """
    project = runner.project
    project.git("checkout", "-q", "main")
    files = "\n\n".join(
        f"### {path}\n{project.read_file(path)[:2500]}" for path in FIXABLE_FILES)
    prompt = FIXER_PROMPT.format(failure=(failure or "")[-2000:], files=files,
                                 contract=scaffold.CONTRACT)

    response = runner.call("fixer", pick_model("strong"),
                           messages=[{"role": "user", "content": prompt}],
                           tools=[WRITE_FILE_TOOL], temperature=0)
    message = response.choices[0].message
    written = []
    for call in (getattr(message, "tool_calls", None) or [])[:1]:
        arguments = _parse(call.function.arguments) or {}
        path, content = arguments.get("path", ""), arguments.get("content", "")
        if path in FIXABLE_FILES and content.strip():
            project.write_file(path, content)
            written.append(path)

    sha = project.commit(f"fix: {', '.join(written)}") if written else ""
    return written, sha


def build_graph(runner: Runner, budget_usd: float | None = None,
                max_fixes: int | None = None) -> StateGraph:
    fix_limit = MAX_FIXES if max_fixes is None else max_fixes
    budget = BUDGET_USD if budget_usd is None else budget_usd
    def planner(state: RunState) -> dict:
        """처음이면 SPEC만 보고, 재계획이면 실패 로그도 함께 본다.

        재계획 횟수는 여기서 센다. 실패를 안고 들어왔다면 그것이 재계획이다.
        """
        replanned = bool(state.get("failure"))
        replans = state.get("replans", 0) + (1 if replanned else 0)

        spec = state["spec"]
        if replanned:
            spec += ("\n\n## 이전 시도가 실패했다\n"
                     "아래 실패를 피하도록 각 역할의 지시를 더 분명히 적으십시오.\n"
                     + state["failure"][-1200:])

        tasks = plan_tasks(runner, spec)
        if replans:                         # 새 시도는 새 브랜치에서 (이력이 남는다)
            tasks = [{**task, "branch": f"{task['branch']}-r{replans + 1}"} for task in tasks]
            runner.note(_event("planner", "재계획", f"{replans + 1}번째 시도 · 새 브랜치"))
        runner.publish(tasks=tasks, state="running", replans=replans, fix_rounds=0)
        return {"tasks": tasks, "replans": replans, "fix_rounds": 0, "failure": "",
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
        if outcome["served"]:
            runner.publish(state="done")
        return {**outcome, "failure": "" if outcome["served"] else outcome["report"]}

    def fixer(state: RunState) -> dict:
        rounds = state.get("fix_rounds", 0) + 1
        written, sha = fix_once(runner, state["failure"])
        runner.publish(fix_rounds=rounds)          # 대시보드가 복구 횟수를 읽는다
        runner.note(_event("fixer", f"수정 {rounds}회차",
                           f"{', '.join(written) or '고치지 못했다'} {sha}"))
        return {"fix_rounds": rounds}

    def after_integrate(state: RunState) -> str:
        if state["served"]:
            return "__end__"
        if state.get("fix_rounds", 0) < fix_limit:
            return "fixer"
        if state.get("replans", 0) < MAX_REPLANS:
            return "planner"
        runner.publish(state="failed")
        runner.note(_event("integrator", "포기", "수정과 재계획 한도를 모두 썼다"))
        return "__end__"

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
    graph.add_node("fixer", fixer)
    graph.add_edge("worker", "integrator")
    graph.add_conditional_edges("integrator", after_integrate,
                                {"fixer": "fixer", "planner": "planner", "__end__": END})
    graph.add_edge("fixer", "integrator")
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
            "fix_rounds": result.get("fix_rounds", 0), "replans": result.get("replans", 0),
            "estimate": runner.status.get("estimate", {}), "graph": runner.project.graph()}


def run(spec: str, project: Project | None = None, budget_usd: float | None = None,
        max_fixes: int | None = None) -> dict:
    project = project or Project()
    project.docker_down()
    project.reset()
    runner = Runner(project, Ledger(), mode="parallel")
    runner.publish(state="running", tasks=[], events=[])

    compiled = build_graph(runner, budget_usd, max_fixes).compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": f"run-{int(runner.started)}"}}
    ACTIVE.update({"compiled": compiled, "runner": runner, "config": config})

    result = compiled.invoke({"spec": spec, "tasks": [], "results": [], "events": [],
                              "merged": False, "tested": False, "served": False,
                              "approved": False, "report": "", "failure": "",
                              "fix_rounds": 0, "replans": 0}, config)
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
