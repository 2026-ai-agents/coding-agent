"""비용 장부 — 코딩 에이전트에서 돈은 부수적인 것이 아니다.

한 번의 실행이 LLM 호출 열몇 번이고, 그중 몇은 파일 하나를 통째로 쓰는
긴 출력이다. 그래서 **쓴 만큼을 계속 센다.** litellm이 응답마다 토큰과
비용을 주므로, 우리가 할 일은 더하는 것과 어디에 썼는지 남기는 것뿐이다.

실행 **전에** 묻는 비용(v0.3의 게이트)은 추정이고, 실행 **중에** 세는
비용은 실측이다. 둘을 같은 화면에 나란히 두면 추정이 얼마나 맞는지도 함께
배운다.
"""

from litellm import completion_cost, cost_per_token


# 역할마다 뱉는 양이 다르다. 파일 하나를 통째로 쓰는 일이라 출력이 크다.
# 정확할 필요는 없다. **자릿수가 맞으면 게이트는 제 일을 한다.**
EXPECTED_OUT_TOKENS = {"backend": 1500, "frontend": 1800, "tests": 1000, "planner": 600}


def estimate_call(model: str, role: str, prompt_chars: int) -> dict:
    """호출 하나의 예상 비용. 한글은 대략 한 글자 한 토큰으로 잡는다."""
    in_tokens = max(200, prompt_chars // 2)
    out_tokens = EXPECTED_OUT_TOKENS.get(role, 1000)
    try:
        prompt_cost, completion_cost_usd = cost_per_token(
            model=model, prompt_tokens=in_tokens, completion_tokens=out_tokens)
        cost = float(prompt_cost) + float(completion_cost_usd)
    except Exception:                          # noqa: BLE001 — 가격표에 없는 모델
        cost = 0.0
    return {"role": role, "model": model, "in_tokens": in_tokens,
            "out_tokens": out_tokens, "cost_usd": round(cost, 6)}


def estimate_run(tasks: list[dict], prompt_chars: int) -> dict:
    """실행 전에 묻는 값. 실행 중에 세는 장부와 나란히 두고 보면 좋다."""
    per_task = [estimate_call(task["model"], task["role"], prompt_chars) for task in tasks]
    return {"per_task": per_task,
            "total_usd": round(sum(item["cost_usd"] for item in per_task), 6)}


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
