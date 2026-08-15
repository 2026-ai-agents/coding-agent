"""v0.3 시연: 값을 먼저 묻는 문.

같은 SPEC을 상한만 바꿔 세 번 돌린다.

  ① 상한이 넉넉하면      문은 열려 있고 조용히 지나간다
  ② 상한이 빠듯한데 승인  멈춰서 묻고, 승인하면 그때부터 짠다
  ③ 상한이 빠듯한데 중단  한 줄도 짜지 않고 끝난다

세 번째가 이 기능의 값어치다. **거절할 수 있어야 문이다.**

    docker compose exec app python demos/cost_gate.py
"""

import warnings

warnings.filterwarnings("ignore")

from agent import graph as parallel

SPEC = open("/app/specs/todo.md", encoding="utf-8").read()


def show_estimate(estimate: dict, budget: float) -> None:
    for item in estimate["per_task"]:
        print(f"    {item['role']:<9} {item['model'].split('/')[-1]:<26}"
              f" 출력 {item['out_tokens']:>5} 토큰  ${item['cost_usd']:.4f}")
    print(f"    {'합계':<9} {'':<26} {'':>11}  ${estimate['total_usd']:.4f}"
          f"  (상한 ${budget:.4f})")


print("=== ① 상한 $0.05 — 넉넉하다 ===\n")
result = parallel.run(SPEC, budget_usd=0.05)
if result.get("state") == "approval_needed":
    print("    묻는다")
else:
    print(f"    묻지 않고 끝까지 갔다 · {result['elapsed_s']}초 · "
          f"실측 ${result['cost']['cost_usd']:.4f} · 기동 {result['served']}")
    print(f"    추정 ${result['estimate']['total_usd']:.4f} vs 실측 "
          f"${result['cost']['cost_usd']:.4f}")

print("\n=== ② 상한 $0.005 — 빠듯하다, 승인한다 ===\n")
result = parallel.run(SPEC, budget_usd=0.005)
if result.get("state") == "approval_needed":
    show_estimate(result["estimate"], result["budget_usd"])
    print("\n    사람이 승인한다 →")
    done = parallel.resume(approved=True)
    print(f"    {done['elapsed_s']}초 · 실측 ${done['cost']['cost_usd']:.4f} · 기동 {done['served']}")

print("\n=== ③ 상한 $0.005 — 빠듯하다, 중단한다 ===\n")
result = parallel.run(SPEC, budget_usd=0.005)
if result.get("state") == "approval_needed":
    stopped = parallel.resume(approved=False)
    print(f"    {stopped['report']}")
    print(f"    실측 ${stopped['cost']['cost_usd']:.4f} — planner 한 번뿐이다. "
          "worker는 돌지 않았다.")

print("\n난이도가 hard면 상위 모델, easy면 저가 모델이 배정된다.")
print("추정이 상한 안이면 문은 열려 있고, 넘으면 사람 앞에 선다.")
