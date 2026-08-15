"""v0.4 시연: 실패한 뒤가 진짜 일이다.

셋이 따로 짜면 규약의 빈틈에서 어긋난다. 실제로 관찰된 실패는 이랬다.

    FAILED tests/test_api.py::test_create_todo - assert 201 == 200

backend는 생성에 201을 돌려주고 tests는 200을 기대했다. 규약이 상태 코드를
못 박지 않았기 때문이다. 이 시연은 그 실패를 **일부러 심어** 복구 루프가
무는지 본다. 자연히 나기를 기다릴 수도 있지만, 강의는 재현이 되어야 한다.

    docker compose exec app python demos/recovery.py
"""

import warnings

warnings.filterwarnings("ignore")

from agent import graph as parallel
from agent.cost import Ledger
from agent.sequential import Runner
from agent.workspace import Project

SPEC = open("/app/specs/todo.md", encoding="utf-8").read()

BROKEN_TEST = '''"""일부러 심은 어긋남 — 규약과 다른 상태 코드를 기대한다."""

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_create_returns_the_item():
    response = client.post("/api/todos", json={"title": "심은 실패"})
    assert response.status_code == 12345          # 규약에 없는 값
    assert response.json()["title"] == "심은 실패"
'''

print("=== 준비: 정상 산출물을 한 번 만든다 ===\n")
result = parallel.run(SPEC, budget_usd=1.0)
print(f"    {result['elapsed_s']}초 · 테스트 {result['tested']} · 기동 {result['served']}\n")

project = Project()
runner = Runner(project, Ledger(), mode="parallel")

print("=== ① 통합 실패를 심는다 ===\n")
project.git("checkout", "-q", "main")
project.write_file("tests/test_api.py", BROKEN_TEST)
project.commit("inject: 규약과 어긋나는 테스트")
passed, log = project.run_tests()
print(f"    테스트 통과: {passed}")
print("    " + "\n    ".join(log.strip().splitlines()[-3:]) + "\n")

print("=== ② integrator가 로그를 읽고 한 파일을 고친다 ===\n")
for attempt in range(1, parallel.MAX_FIXES + 1):
    written, sha = parallel.fix_once(runner, log)
    passed, log = project.run_tests()
    print(f"    수정 {attempt}회차 · 고친 파일 {written or '없음'} {sha} → 테스트 {passed}")
    if passed:
        break

print(f"\n    비용: ${runner.ledger.totals()['cost_usd']:.4f} "
      f"({runner.ledger.totals()['calls']}회, 수정은 상위 모델로)")

print("\n=== ③ 고치지 못하면 재계획으로 넘어간다 ===\n")
print("    이 경로는 자연히 나기를 기다리기 어렵다. 그래서 **통합을 늘 실패시키는")
print("    대역으로 갈아끼워** 분기가 어디로 가는지 본다. 나머지는 전부 진짜다.\n")

original_integrate = parallel.integrate
parallel.integrate = lambda runner, results: {
    "merged": True, "tested": False, "served": False,
    "report": "FAILED tests/test_api.py::test_create_todo - assert 201 == 200"}
try:
    retry = parallel.run(SPEC, budget_usd=1.0, max_fixes=1)
finally:
    parallel.integrate = original_integrate

print(f"    수정 {retry['fix_rounds']}회 · 재계획 {retry['replans']}회 · 기동 {retry['served']}")
print(f"    비용 ${retry['cost']['cost_usd']:.4f} — 한도가 없었다면 여기서 멈추지 않았다.")
print("\n    두 번째 시도는 새 브랜치에서 짠다 (이력이 남는다):")
for line in retry["graph"].splitlines()[:10]:
    print("    " + line)

print("\n한도가 있어야 자동화다. 무한히 고치는 루프는 고장 난 루프다.")
