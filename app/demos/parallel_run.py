"""v0.2 시연: 같은 일, 다른 배치. 병렬이 무엇을 벌어 주는가.

같은 SPEC으로 v0.1(순차)과 v0.2(병렬)를 각각 한 번씩 돌린다. 볼 것은
**구간이 겹치는가**와 **전체 시간**이다. 비용은 거의 같아야 한다. 같은 일을
같은 모델로 하기 때문이다. 줄어드는 것은 시간뿐이고, 그것이 병렬화가
파는 물건이다.

    docker compose exec app python demos/parallel_run.py
"""

import warnings

warnings.filterwarnings("ignore")

from agent import graph as parallel
from agent import sequential

SPEC = open("/app/specs/todo.md", encoding="utf-8").read()


def show(title: str, result: dict) -> None:
    print(f"=== {title} ===\n")
    print(f"{'역할':<10}{'구간':>16}   {'타임라인'}")
    scale = max(1.0, max(t.get("ended_s", 0) for t in result["tasks"]))
    for task in result["tasks"]:
        start, end = task.get("started_s", 0), task.get("ended_s", 0)
        left = int(start / scale * 40)
        width = max(1, int((end - start) / scale * 40))
        bar = " " * left + "█" * width
        print(f"{task['role']:<10}{start:>6.1f}s →{end:>6.1f}s   {bar}")
    cost = result["cost"]
    print(f"\n전체 {result['elapsed_s']}초 · LLM {cost['calls']}회 · "
          f"${cost['cost_usd']:.4f} · 머지 {result['merged']} · 테스트 {result['tested']}"
          f" · 기동 {result['served']}")
    if not result["served"]:
        # 실패를 숨기지 않는다. 생성된 코드는 매번 같지 않다.
        print(f"실패 지점: {result['report'][-400:]}")
    print()


show("v0.1 순차", sequential.run(SPEC))
show("v0.2 병렬 (Send + worktree)", parallel.run(SPEC))

print("코드는 planner도 worker도 integrator도 같은 것을 쓴다.")
print("바뀐 것은 Send로 흩뿌린다는 것과, 각자 worktree에서 짠다는 것뿐이다.")
