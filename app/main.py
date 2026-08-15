"""코딩 에이전트 — HTTP 경계.

실행은 오래 걸린다(모델이 파일을 통째로 쓰고, 도커가 이미지를 빌드한다).
그래서 /run은 백그라운드로 시작만 하고, 진행 상황은 /status로 읽는다.
상태는 워크스페이스의 status.json 한 장이다.
"""

import os
import subprocess
import threading

from fastapi import FastAPI
from pydantic import BaseModel

from agent import graph as parallel, sequential
from agent.workspace import Project

SPEC_DIR = "/app/specs"

app = FastAPI(title="coding-agent", version="0.2")
_lock = threading.Lock()
_thread: threading.Thread | None = None


class RunRequest(BaseModel):
    spec: str = "todo"
    mode: str = "parallel"      # parallel | sequential


@app.get("/health")
def health() -> dict:
    def first_line(command: list[str]) -> str:
        try:
            return subprocess.run(command, capture_output=True, text=True, timeout=20
                                  ).stdout.strip().splitlines()[0]
        except Exception as error:                 # noqa: BLE001 — 진단용
            return f"실패: {error}"

    return {"ok": True, "specs": specs(),
            "git": first_line(["git", "--version"]),
            "docker": first_line(["docker", "version", "--format", "{{.Server.Version}}"])}


@app.get("/specs")
def specs() -> list[str]:
    return sorted(f.removesuffix(".md") for f in os.listdir(SPEC_DIR) if f.endswith(".md"))


def read_spec(name: str) -> str:
    with open(os.path.join(SPEC_DIR, f"{name}.md"), encoding="utf-8") as f:
        return f.read()


@app.post("/run")
def run(body: RunRequest) -> dict:
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return {"started": False, "why": "이미 실행 중입니다"}
        spec = read_spec(body.spec)
        runner = sequential.run if body.mode == "sequential" else parallel.run
        _thread = threading.Thread(target=runner, args=(spec,), daemon=True)
        _thread.start()
    return {"started": True, "spec": body.spec, "mode": body.mode}


@app.get("/status")
def status() -> dict:
    state = Project.load_status()
    state["artifact_alive"] = Project().artifact_alive()
    state["graph"] = Project().graph()
    return state


@app.post("/stop")
def stop() -> dict:
    """산출물을 내린다. 만드는 것과 만들어진 것은 서로 다른 compose다."""
    Project().docker_down()
    return {"ok": True}
