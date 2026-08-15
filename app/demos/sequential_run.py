"""v0.1 시연: 셋을 한 사람이 순서대로 짠다.

볼 것은 두 가지다. **완성되는가**(머지·테스트·기동)와 **얼마나 걸리는가**.
태스크별 시작·종료 시각을 나란히 찍어 두면, v0.2에서 같은 그림이 어떻게
겹치는지 바로 보인다.

    docker compose exec app python demos/sequential_run.py
"""

import warnings

warnings.filterwarnings("ignore")

from agent import sequential

SPEC = open("/app/specs/todo.md", encoding="utf-8").read()

result = sequential.run(SPEC)

print("=== v0.1 순차 실행 ===\n")
print(f"{'역할':<10}{'모델':<32}{'구간':>14}")
for task in result["tasks"]:
    span = f"{task.get('started_s', 0):>5.1f}s → {task.get('ended_s', 0):>5.1f}s"
    print(f"{task['role']:<10}{task.get('model', ''):<32}{span:>14}  {task['status']}")

cost = result["cost"]
print(f"\n전체 {result['elapsed_s']}초 · LLM {cost['calls']}회 · "
      f"출력 {cost['out_tokens']:,} 토큰 · ${cost['cost_usd']:.4f}")
print(f"머지 {result['merged']} · 테스트 {result['tested']} · 기동 {result['served']}")

print("\n=== 에이전트의 작업 기록 (git) ===")
print(result["graph"])

print("\n구간이 겹치지 않는다. 한 사람이 하나씩 했기 때문이다.")
print("셋은 서로의 결과를 기다릴 이유가 없는데도 줄을 서 있다. 그것이 v0.2의 자리다.")
