"""산출물의 골격 — 세 에이전트가 동시에 일하려면 경계가 먼저 있어야 한다.

셋이 한 제품을 나눠 만들 때 가장 흔한 사고는 **같은 파일을 동시에 고치는
것**과 **서로 다른 규약을 가정하는 것**이다. 그래서 두 가지를 코드로 못
박는다.

  · 파일 소유권  역할마다 쓸 수 있는 파일이 정해져 있다 (충돌이 불가능하다)
  · 인터페이스   엔드포인트 규약을 골격이 정하고, 프롬프트에 그대로 실어 준다

Dockerfile·compose·requirements는 LLM이 쓰지 않는다. 매번 흔들릴 이유가
없는 것을 매번 생성하게 두면 실패만 늘어난다. **에이전트가 쓰는 것은
제품 코드이고, 인프라는 골격이 준다.**
"""

PORT = 8080

# 세 역할이 지켜야 할 규약. 프롬프트에 그대로 들어간다.
CONTRACT = f"""제품 규약 (모든 역할이 지킨다)

- 서버는 app.py의 FastAPI 인스턴스 `app`이고 포트 {PORT}에서 뜬다
- 정적 파일: `static/` 디렉터리를 `/`에 마운트하고 index.html을 연다
- 데이터는 서버 메모리(파이썬 리스트/딕셔너리)에 둔다. db는 쓰지 않는다
- REST 규약
  · GET    /api/todos            → [{{"id": 1, "title": "...", "done": false}}, ...]
  · POST   /api/todos            body {{"title": "..."}}        → 만들어진 항목
  · PATCH  /api/todos/{{item_id}}  body {{"done": true}}          → 바뀐 항목
  · DELETE /api/todos/{{item_id}}                                 → {{"ok": true}}
  · GET    /health               → {{"ok": true}}
- 없는 id에는 404를 돌려준다
"""

# 역할이 쓸 수 있는 파일. 겹치지 않으므로 병렬로 써도 충돌하지 않는다.
OWNERSHIP = {
    "backend": ["app.py"],
    "frontend": ["static/index.html"],
    "tests": ["tests/test_api.py"],
}

DOCKERFILE = f"""FROM python:3.13-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "{PORT}"]
"""

COMPOSE = f"""services:
  web:
    build: .
    ports:
      - "{PORT}:{PORT}"
"""

REQUIREMENTS = """fastapi>=0.115,<1
uvicorn>=0.34,<1
"""

PLACEHOLDER_APP = '''"""골격이 놓아 둔 자리. backend 에이전트가 덮어쓴다."""

from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health() -> dict:
    return {"ok": True}
'''

PLACEHOLDER_INDEX = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>준비 중</title></head>
<body><p>frontend 에이전트가 덮어씁니다.</p></body></html>
"""

FILES = {
    "Dockerfile": DOCKERFILE,
    "docker-compose.yml": COMPOSE,
    "requirements.txt": REQUIREMENTS,
    "app.py": PLACEHOLDER_APP,
    "static/index.html": PLACEHOLDER_INDEX,
    ".gitignore": "__pycache__/\n.pytest_cache/\n",
}


def files_for(role: str) -> list[str]:
    return OWNERSHIP.get(role, [])
