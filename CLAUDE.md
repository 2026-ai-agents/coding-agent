# CLAUDE.md

AI Agent 실전 Day 3 ④: 코딩 에이전트. SPEC → 태스크 분해 → 병렬 작성 →
머지 → 테스트 → 도커 기동. 릴리즈 사다리 v0.1(순차) → v0.2(병렬) →
v0.3(비용 게이트·모델 배정) → v0.4(복구 루프) → v1.0(대시보드 완성).

## 실행·검증 (전부 컨테이너에서)

```sh
docker compose up --build           # app(8000) · ui(8501)
docker compose exec app pytest      # LLM은 각본 대역, 파일·git은 진짜
docker compose exec app python demos/sequential_run.py
```

산출물은 8080에서 따로 뜬다. 내릴 때는 `POST /stop` 또는 대시보드 버튼.

## Git 워크플로: git flow

- `develop`에서 `feature/*` 분기 → `develop` 머지. `main` 직접 커밋 금지
- 릴리즈 사다리: `release/<태그>` → `main` 머지 + annotated 태그 + GitHub
  Release + `develop` 역머지. **태그를 옮기거나 지우지 않는다**
- 컨테이너 코드를 고쳤으면 `docker compose cp`가 아니라 **리빌드**로 반영한다
- `workspace/`는 산출물이라 커밋하지 않는다 (gitignore)

## 이 저장소의 핵심 규율

- **v0.1은 고치지 않는다.** 병렬이 무엇을 벌어 주는지 재려면 순차 기록이
  남아 있어야 한다
- **경계를 먼저 긋는다.** 역할별 파일 소유권과 엔드포인트 규약이 있어야
  병렬 작성이 성립한다. 소유권 밖의 파일 쓰기는 코드가 거부한다
- **인프라는 골격이 준다.** Dockerfile·compose·requirements를 LLM이 매번
  쓰게 하지 않는다. 흔들릴 이유가 없는 것을 흔들리게 두지 않는다
- **git은 하네스가 부른다.** 모델에게 준 도구는 파일 쓰기뿐이다
- **컨테이너 경로와 데몬 경로가 다르다.** 빌드 컨텍스트는 CLI가 읽어
  보내므로 컨테이너 경로를 쓰고, 산출물 compose에는 bind mount를 넣지 않는다
- 비용은 매 호출 장부에 적는다. 추정(게이트)과 실측(장부)을 같은 화면에 둔다
- `.env`는 절대 커밋하지 않는다

## 강의 사이트와의 동기화

이 저장소의 내용이 바뀌면 강의 사이트(`2026-ai-agents`)의
day-03-session-04 문서도 함께 고친다.
