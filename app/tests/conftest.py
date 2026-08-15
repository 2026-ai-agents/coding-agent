"""LLM도 도커도 부르지 않는 테스트 대역 — 다른 저장소와 같은 규약.

다만 이 저장소에서는 **파일과 git은 진짜로 쓴다.** 도구의 실체를 시험하는
것이 목적이라 흉내로는 확인할 수 없다. 임시 디렉터리에서 돌린다.
"""

import json
import uuid
from types import SimpleNamespace

import pytest

from agent import workspace


class ScriptedLLM:
    """각본대로 돌려주는 completion 대역. 호출 인자는 전부 기록한다."""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("각본이 모자랍니다 — 예상보다 LLM을 많이 불렀습니다")
        return self.script.pop(0)


def fake_response(content: str = "", tool_calls: list | None = None,
                  in_tokens: int = 100, out_tokens: int = 200):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    usage = SimpleNamespace(prompt_tokens=in_tokens, completion_tokens=out_tokens,
                            total_tokens=in_tokens + out_tokens)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage,
                           model="gemini/gemini-3.5-flash-lite")


def fake_tool_call(name: str, arguments: dict):
    return SimpleNamespace(id=f"call_{uuid.uuid4().hex[:6]}", type="function",
                           function=SimpleNamespace(name=name,
                                                    arguments=json.dumps(arguments, ensure_ascii=False)))


def write_call(path: str, content: str):
    return fake_response(tool_calls=[fake_tool_call("write_file",
                                                    {"path": path, "content": content})])


def plan_response(difficulties: dict | None = None):
    difficulties = difficulties or {}
    tasks = [{"role": role, "title": f"{role} 구현", "detail": f"{role}를 만든다",
              "difficulty": difficulties.get(role, "easy")}
             for role in ("backend", "frontend", "tests")]
    return fake_response(content=json.dumps({"tasks": tasks}, ensure_ascii=False))


@pytest.fixture
def project(tmp_path, monkeypatch):
    """임시 워크스페이스의 진짜 git 저장소."""
    monkeypatch.setattr(workspace, "WORKSPACE", str(tmp_path))
    made = workspace.Project("test-app")
    made.reset()
    return made
