"""v0.1 — worker 하나가 순서대로 전부 짠다. 동작하지만 느리다.

파이프라인은 셋이다.

  planner     SPEC을 읽고 태스크로 쪼갠다
  worker      태스크를 하나씩, 자기 브랜치에서, 파일을 써서 커밋한다
  integrator  브랜치를 머지하고 테스트를 돌리고 도커로 띄운다

**이 파일은 v0.2가 나온 뒤에도 고치지 않는다.** 병렬이 무엇을 벌어 주는지
재려면 같은 일을 순서대로 한 기록이 남아 있어야 한다.

worker에게 준 도구는 `write_file` 하나뿐이다. 브랜치도 커밋도 하네스가
한다. "에이전트가 코드를 짠다"의 실체는 이 정도다.
"""

import json
import operator
import time
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from litellm import completion

from agent import scaffold
from agent.config import pick_model
from agent.cost import Ledger
from agent.workspace import Project

ROLES = ("backend", "frontend", "tests")
MAX_WRITE_ROUNDS = 3

PLANNER_PROMPT = """당신은 소프트웨어 팀의 플래너입니다.
아래 SPEC을 읽고 세 역할(backend, frontend, tests)이 각각 무엇을 만들어야
하는지 한 문단씩 적으십시오. 역할과 파일은 이미 정해져 있으므로 바꾸지
마십시오. 난이도(difficulty)는 easy 또는 hard 중 하나입니다.

{contract}

SPEC
----
{spec}

JSON으로만 답하십시오.
{{"tasks": [{{"role": "backend|frontend|tests", "title": "짧은 제목",
             "detail": "무엇을 어떻게 만들지 서너 문장",
             "difficulty": "easy|hard"}}]}}"""

WORKER_PROMPT = """당신은 {role} 담당 개발자입니다. 아래 SPEC과 규약을 지켜
맡은 파일을 완성하십시오.

{contract}

SPEC
----
{spec}

당신의 태스크
------------
{detail}

당신이 쓸 수 있는 파일: {files}
반드시 write_file 도구로 파일 전체 내용을 쓰십시오. 설명은 하지 마십시오.
코드는 그대로 실행 가능해야 하며, 없는 라이브러리를 import 하지 마십시오
(쓸 수 있는 것: fastapi, uvicorn, 표준 라이브러리, 테스트는 fastapi.testclient)."""

WRITE_FILE_TOOL = {"type": "function", "function": {
    "name": "write_file",
    "description": "파일 전체 내용을 쓴다. 기존 내용은 덮어쓴다",
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "프로젝트 기준 상대 경로"},
        "content": {"type": "string", "description": "파일 전체 내용"}},
        "required": ["path", "content"]}}}


class RunState(TypedDict):
    spec: str
    tasks: list
    results: Annotated[list, operator.add]
    events: Annotated[list, operator.add]
    merged: bool
    tested: bool
    served: bool
    report: str


def _event(agent: str, action: str, detail: str = "") -> dict:
    return {"agent": agent, "action": action, "detail": detail, "at": round(time.time(), 3)}


def _parse(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    try:
        return json.loads(text[start:end + 1])
    except (ValueError, IndexError):
        return {}


class Runner:
    """그래프가 쓰는 바깥 세계 — 프로젝트, 장부, 진행 상황."""

    def __init__(self, project: Project, ledger: Ledger, mode: str = "sequential"):
        self.project = project
        self.ledger = ledger
        self.mode = mode
        self.started = time.time()
        self.status = {"state": "running", "mode": mode, "tasks": [], "events": [],
                       "cost": {}, "elapsed_s": 0}

    def publish(self, **changes) -> None:
        self.status.update(changes)
        self.status["cost"] = self.ledger.totals()
        self.status["elapsed_s"] = round(time.time() - self.started, 1)
        self.project.save_status(self.status)

    def note(self, event: dict) -> None:
        self.status["events"].append(event)
        self.publish()

    def call(self, who: str, model: str, **kwargs):
        response = completion(model=model, **kwargs)
        self.ledger.record(who, model, response)
        self.publish()
        return response


def plan_tasks(runner: Runner, spec: str) -> list[dict]:
    model = pick_model("cheap")
    response = runner.call("planner", model, messages=[{
        "role": "user", "content": PLANNER_PROMPT.format(spec=spec, contract=scaffold.CONTRACT)}],
        temperature=0)
    parsed = _parse(response.choices[0].message.content)
    tasks = []
    for role in ROLES:                       # 역할과 파일은 코드가 정한다
        found = next((t for t in parsed.get("tasks", []) if t.get("role") == role), {})
        tasks.append({
            "role": role,
            "title": found.get("title") or f"{role} 구현",
            "detail": found.get("detail") or f"SPEC을 만족하는 {role} 코드를 작성한다.",
            "difficulty": found.get("difficulty") if found.get("difficulty") in ("easy", "hard") else "easy",
            "files": scaffold.files_for(role),
            "branch": f"feature/{role}",
            "status": "대기",
            "model": "",
        })
    return tasks


def work_on(runner: Runner, task: dict, spec: str, model: str) -> dict:
    """한 태스크: 브랜치를 만들고, 모델에게 파일을 쓰게 하고, 커밋한다."""
    project = runner.project
    started = time.time()
    project.branch(task["branch"])
    runner.note(_event(task["role"], "브랜치", task["branch"]))

    messages = [{"role": "user", "content": WORKER_PROMPT.format(
        role=task["role"], spec=spec, contract=scaffold.CONTRACT,
        detail=task["detail"], files=", ".join(task["files"]))}]

    written = []
    for _ in range(MAX_WRITE_ROUNDS):
        response = runner.call(task["role"], model, messages=messages,
                               tools=[WRITE_FILE_TOOL], temperature=0)
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            break
        for call in tool_calls:
            arguments = _parse(call.function.arguments) or {}
            path, content = arguments.get("path", ""), arguments.get("content", "")
            if path not in task["files"]:        # 남의 파일은 쓰지 못한다
                result = f"거부: {path}는 당신의 파일이 아닙니다. {task['files']} 중에서 쓰십시오."
            elif not content.strip():
                result = "거부: 내용이 비어 있습니다."
            else:
                result = project.write_file(path, content)
                written.append(path)
            messages.append({"role": "assistant", "content": "", "tool_calls": [
                {"id": call.id, "type": "function",
                 "function": {"name": "write_file", "arguments": call.function.arguments}}]})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
        if set(written) >= set(task["files"]):
            break

    sha = project.commit(f"{task['role']}: {task['title']}")
    runner.note(_event(task["role"], "커밋", f"{sha} · {', '.join(written) or '변경 없음'}"))
    return {**task, "status": "완료" if written else "빈손", "written": written,
            "sha": sha, "model": model,
            "started_s": round(started - runner.started, 1),
            "ended_s": round(time.time() - runner.started, 1)}


def integrate(runner: Runner, tasks: list[dict]) -> dict:
    project = runner.project
    merged, log = project.merge([t["branch"] for t in tasks])
    runner.note(_event("integrator", "머지", log))
    if not merged:
        return {"merged": False, "tested": False, "served": False, "report": log}

    passed, output = project.run_tests()
    runner.note(_event("integrator", "테스트", "통과" if passed else output[-400:]))
    if not passed:
        return {"merged": True, "tested": False, "served": False, "report": output}

    served, docker_log = project.docker_up()
    runner.note(_event("integrator", "도커 기동", "성공" if served else docker_log[-400:]))
    return {"merged": True, "tested": True, "served": served,
            "report": "완료" if served else docker_log}


def build_graph(runner: Runner) -> StateGraph:
    def planner(state: RunState) -> dict:
        tasks = plan_tasks(runner, state["spec"])
        runner.publish(tasks=tasks)
        return {"tasks": tasks,
                "events": [_event("planner", "태스크 분해", f"{len(tasks)}개")]}

    def worker(state: RunState) -> dict:
        """v0.1의 전부: 하나씩, 순서대로."""
        model = pick_model("cheap")
        results = []
        for index, task in enumerate(state["tasks"]):
            runner.status["tasks"][index]["status"] = "작업 중"
            runner.publish()
            result = work_on(runner, task, state["spec"], model)
            runner.status["tasks"][index] = result
            runner.publish()
            results.append(result)
        return {"results": results}

    def integrator(state: RunState) -> dict:
        outcome = integrate(runner, state["results"])
        runner.publish(state="done" if outcome["served"] else "failed")
        return outcome

    graph = StateGraph(RunState)
    graph.add_node("planner", planner)
    graph.add_node("worker", worker)
    graph.add_node("integrator", integrator)
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "worker")
    graph.add_edge("worker", "integrator")
    graph.add_edge("integrator", END)
    return graph


def run(spec: str, project: Project | None = None) -> dict:
    project = project or Project()
    project.docker_down()
    project.reset()
    runner = Runner(project, Ledger(), mode="sequential")
    runner.publish(state="running", tasks=[], events=[])

    compiled = build_graph(runner).compile()
    result = compiled.invoke({"spec": spec, "tasks": [], "results": [], "events": [],
                              "merged": False, "tested": False, "served": False, "report": ""})
    elapsed = round(time.time() - runner.started, 1)
    runner.publish(state="done" if result["served"] else "failed", elapsed_s=elapsed)
    return {"mode": "sequential", "elapsed_s": elapsed, "tasks": runner.status["tasks"],
            "merged": result["merged"], "tested": result["tested"], "served": result["served"],
            "report": result["report"], "cost": runner.ledger.totals(),
            "graph": project.graph()}
