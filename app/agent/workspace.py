"""에이전트가 쥔 도구의 실체 — 파일, git, 테스트, 도커.

"에이전트가 코드를 짠다"는 문장은 대개 이 파일 안의 함수 열몇 개를 뜻한다.
마법은 없다. LLM은 문자열을 돌려주고, **파일로 만드는 것도 커밋하는 것도
빌드하는 것도 전부 여기 있는 평범한 코드**다.

경계를 하나 정해 두었다. **모델에게 준 도구는 파일 읽기와 쓰기뿐이다.**
브랜치·커밋·머지·빌드는 하네스가 정해진 순서로 실행한다. 모델이 git을
직접 부르게 하면 배우는 것은 없고 사고 날 자리만 는다.

컨테이너 안의 경로와 도커 데몬이 보는 경로가 다르다는 점을 기억해 둘 것.
빌드 컨텍스트는 CLI가 직접 읽어 데몬으로 흘려보내므로 **컨테이너 경로**를
쓴다. 반대로 compose 안에서 호스트 디렉터리를 bind mount 하려 했다면
호스트 경로가 필요했을 것이고, 그래서 산출물은 bind mount를 쓰지 않는다.
"""

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request

from agent import scaffold

WORKSPACE = os.environ.get("WORKSPACE", "/workspace")
ARTIFACT_URL = f"http://host.docker.internal:{scaffold.PORT}"
GIT_ENV = {"GIT_AUTHOR_NAME": "coding-agent", "GIT_AUTHOR_EMAIL": "agent@codecompose.net",
           "GIT_COMMITTER_NAME": "coding-agent", "GIT_COMMITTER_EMAIL": "agent@codecompose.net"}


class Project:
    """산출물 하나. 워크스페이스 아래의 독립된 git 저장소다."""

    def __init__(self, name: str = "todo-app"):
        self.name = name
        self.path = os.path.join(WORKSPACE, name)

    # ── 파일 ────────────────────────────────────────────────────────
    def write_file(self, relpath: str, content: str) -> str:
        target = os.path.join(self.path, relpath)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return f"{relpath} ({len(content)}자)"

    def read_file(self, relpath: str) -> str:
        target = os.path.join(self.path, relpath)
        if not os.path.exists(target):
            return ""
        with open(target, encoding="utf-8") as f:
            return f.read()

    def list_files(self) -> list[str]:
        found = []
        for root, dirs, files in os.walk(self.path):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".pytest_cache")]
            for name in files:
                found.append(os.path.relpath(os.path.join(root, name), self.path))
        return sorted(found)

    # ── git ─────────────────────────────────────────────────────────
    def _run(self, command: list[str], timeout: int = 300) -> tuple[int, str]:
        # 첫 실행에는 프로젝트 디렉터리가 아직 없다 (docker_down이 먼저 불린다)
        cwd = self.path if os.path.isdir(self.path) else WORKSPACE
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                                timeout=timeout, env={**os.environ, **GIT_ENV})
        return result.returncode, (result.stdout + result.stderr).strip()

    def git(self, *args: str, timeout: int = 120) -> tuple[int, str]:
        return self._run(["git", *args], timeout=timeout)

    def reset(self) -> None:
        """빈 자리에서 시작한다. 골격을 놓고 main에 커밋해 둔다."""
        if os.path.exists(self.path):
            shutil.rmtree(self.path)
        os.makedirs(self.path)
        self.git("init", "-q", "-b", "main")
        for relpath, content in scaffold.FILES.items():
            self.write_file(relpath, content)
        self.write_file("tests/__init__.py", "")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "Scaffold the product skeleton")

    def branch(self, name: str) -> None:
        code, _ = self.git("rev-parse", "--verify", name)
        self.git("checkout", "-q", name) if code == 0 else self.git("checkout", "-q", "-b", name)

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        code, out = self.git("commit", "-q", "-m", message)
        if code != 0 and "nothing to commit" in out:
            return ""
        return self.git("rev-parse", "--short", "HEAD")[1]

    def merge(self, branches: list[str]) -> tuple[bool, str]:
        self.git("checkout", "-q", "main")
        logs = []
        for branch in branches:
            code, out = self.git("merge", "--no-ff", "-m", f"Merge branch '{branch}'", branch)
            logs.append(f"{branch}: {'머지' if code == 0 else '충돌'}")
            if code != 0:
                self.git("merge", "--abort")
                return False, "\n".join(logs + [out[-600:]])
        return True, "\n".join(logs)

    def graph(self, limit: int = 20) -> str:
        return self.git("log", "--graph", "--oneline", "--all", f"-{limit}")[1]

    # ── 검증 ────────────────────────────────────────────────────────
    def run_tests(self) -> tuple[bool, str]:
        """생성된 테스트를 app 컨테이너에서 그대로 돌린다. 빠르고 로그가 깨끗하다."""
        result = subprocess.run(
            ["python", "-m", "pytest", "-q", "--no-header", "tests"],
            cwd=self.path, capture_output=True, text=True, timeout=300,
            env={**os.environ, "PYTHONPATH": self.path, "PYTHONDONTWRITEBYTECODE": "1"})
        output = (result.stdout + result.stderr).strip()
        return result.returncode == 0, output[-3000:]

    # ── 도커 ────────────────────────────────────────────────────────
    def docker_up(self) -> tuple[bool, str]:
        code, out = self._run(
            ["docker", "compose", "--project-directory", self.path,
             "-f", os.path.join(self.path, "docker-compose.yml"),
             "-p", self.name, "up", "-d", "--build"], timeout=900)
        if code != 0:
            return False, out[-3000:]
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"{ARTIFACT_URL}/health", timeout=2) as response:
                    if response.status == 200:
                        return True, out[-800:]
            except (urllib.error.URLError, OSError):
                time.sleep(1)
        return False, (out + "\n" + self.docker_logs())[-3000:]

    def docker_down(self) -> None:
        self._run(["docker", "compose", "-p", self.name, "down", "-v"], timeout=300)

    def docker_logs(self, tail: int = 60) -> str:
        return self._run(["docker", "compose", "-p", self.name, "logs", f"--tail={tail}"])[1]

    def artifact_alive(self) -> bool:
        try:
            with urllib.request.urlopen(f"{ARTIFACT_URL}/health", timeout=2) as response:
                return response.status == 200
        except (urllib.error.URLError, OSError):
            return False

    # ── 진행 상태 ───────────────────────────────────────────────────
    def save_status(self, status: dict) -> None:
        """대시보드가 읽을 진행 상황. 파일 하나면 충분하다."""
        with open(os.path.join(WORKSPACE, "status.json"), "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False)

    @staticmethod
    def load_status() -> dict:
        try:
            with open(os.path.join(WORKSPACE, "status.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"state": "idle", "tasks": [], "events": [], "cost": {}}
