"""비용 장부 — 코딩 에이전트에서 돈은 부수적인 것이 아니다.

한 번의 실행이 LLM 호출 열몇 번이고, 그중 몇은 파일 하나를 통째로 쓰는
긴 출력이다. 그래서 **쓴 만큼을 계속 센다.** litellm이 응답마다 토큰과
비용을 주므로, 우리가 할 일은 더하는 것과 어디에 썼는지 남기는 것뿐이다.

실행 **전에** 묻는 비용(v0.3의 게이트)은 추정이고, 실행 **중에** 세는
비용은 실측이다. 둘을 같은 화면에 나란히 두면 추정이 얼마나 맞는지도 함께
배운다.
"""

from litellm import completion_cost


class Ledger:
    """모델별·역할별로 쓴 것을 적어 둔다."""

    def __init__(self):
        self.entries: list[dict] = []

    def record(self, who: str, model: str, response) -> dict:
        usage = getattr(response, "usage", None)
        try:
            cost = float(completion_cost(completion_response=response))
        except Exception:                      # noqa: BLE001 — 가격표에 없는 모델
            cost = 0.0
        entry = {"who": who, "model": model,
                 "in_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                 "out_tokens": getattr(usage, "completion_tokens", 0) or 0,
                 "cost_usd": cost}
        self.entries.append(entry)
        return entry

    def totals(self) -> dict:
        by_model: dict[str, dict] = {}
        for entry in self.entries:
            bucket = by_model.setdefault(entry["model"], {"calls": 0, "cost_usd": 0.0,
                                                          "in_tokens": 0, "out_tokens": 0})
            bucket["calls"] += 1
            bucket["cost_usd"] += entry["cost_usd"]
            bucket["in_tokens"] += entry["in_tokens"]
            bucket["out_tokens"] += entry["out_tokens"]
        return {
            "calls": len(self.entries),
            "in_tokens": sum(e["in_tokens"] for e in self.entries),
            "out_tokens": sum(e["out_tokens"] for e in self.entries),
            "cost_usd": round(sum(e["cost_usd"] for e in self.entries), 6),
            "by_model": {model: {**bucket, "cost_usd": round(bucket["cost_usd"], 6)}
                         for model, bucket in by_model.items()},
        }
