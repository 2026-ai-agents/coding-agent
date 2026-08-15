# coding-agent

AI Agent 실전 **Day 3 ④** 교재. SPEC 문서를 주면 태스크로 쪼개고, 여러
에이전트가 각자의 브랜치에서 코드를 짜고, 머지해서 테스트하고, 도커로 띄우는
**코딩 에이전트**다. 3일 동안 배운 것이 전부 이 안에 있다.

| 어디서 왔나 | 무엇으로 쓰이나 |
| --- | --- |
| Day 1 도구 루프·하네스 | 파일 쓰기 도구와 스텝·수정 한도 |
| Day 1 Plan-and-Execute | planner가 SPEC을 태스크로 쪼갠다 |
| Day 2 그래프·interrupt | 비용 게이트에서 사람에게 묻는다 (v0.3) |
| Day 2 비용 사다리 | 난이도별 모델 배정 (v0.3) |
| Day 3 supervisor·병렬 | Send로 worker 셋을 동시에 (v0.2) |

## 빠른 시작

```sh
cp .env.sample .env        # 키를 하나 이상 채운다
docker compose up --build  # app(8000) · ui(8501)
```

- 진행 대시보드: http://localhost:8501
- **산출물(생성된 웹 앱)**: http://localhost:8080 — 이 compose가 아니라
  `workspace/todo-app/docker-compose.yml`로 따로 뜬다

만드는 것과 만들어진 것을 섞지 않는다. 대시보드가 죽어도 산출물은 돌고,
산출물을 내려도 대시보드는 남는다.

## 릴리즈 사다리

| 태그 | 무엇이 생기는가 |
| --- | --- |
| v0.1 | worker 하나가 순차로 전부 작성 (동작하지만 느리다) |
| v0.2 | 병렬화: Send로 worker 셋 동시 작업, 각자 git worktree에서 |
| v0.3 | 비용 게이트 + 난이도별 모델 배정: 상한을 넘으면 사람에게 묻는다 |
| v0.4 | 복구 루프: 실패 로그를 읽고 고치고, 한도를 넘으면 재계획 |
| v1.0 | (예정) 대시보드 완성과 전체 실행 |

## 시연

```sh
docker compose exec app python demos/sequential_run.py   # v0.1: 순차 실행과 소요 시간
docker compose exec app python demos/parallel_run.py     # v0.2: 순차 vs 병렬 타임라인
docker compose exec app python demos/cost_gate.py        # v0.3: 상한·승인·중단 세 경우
docker compose exec app python demos/recovery.py         # v0.4: 실패를 심고 고치게 한다
```

## 무엇을 에이전트가 쓰고, 무엇을 골격이 주는가

| | 누가 | 왜 |
| --- | --- | --- |
| `app.py` · `static/index.html` · `tests/test_api.py` | 에이전트 | 제품 코드 |
| `Dockerfile` · `docker-compose.yml` · `requirements.txt` | 골격 | 매번 흔들릴 이유가 없다 |
| 브랜치 · 커밋 · 머지 · 빌드 | 하네스 | 모델이 git을 부를 이유가 없다 |

역할마다 쓸 수 있는 파일이 정해져 있어(`agent/scaffold.py`) 병렬로 써도
충돌하지 않는다. **경계를 먼저 긋는 것이 병렬화의 전제다.**

## SPEC 바꿔 보기

`specs/` 아래에 두 개가 있다. 같은 에이전트로 다른 제품이 나온다.

```sh
docker compose exec app python -c "
from agent import sequential
sequential.run(open('/app/specs/timer.md').read())"
```

SPEC은 바인드 마운트라 호스트에서 고치면 바로 반영된다. 리빌드가 필요 없다.

## 구조

```
app/agent/scaffold.py    산출물 골격 · 규약 · 파일 소유권
app/agent/workspace.py   도구의 실체 — 파일·git·테스트·도커
app/agent/cost.py        비용 장부
app/agent/sequential.py  v0.1 파이프라인 (비교 기준점)
app/demos/               시연 스크립트
app/tests/               LLM은 각본 대역, 파일과 git은 진짜
specs/                   SPEC 2종 (todo · timer)
workspace/               에이전트가 만든 산출물 (커밋하지 않는다)
ui/                      Streamlit 진행 대시보드
```
