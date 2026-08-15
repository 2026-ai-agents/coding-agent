"""모델 등급과 값 — 태스크마다 같은 모델을 쓸 이유는 없다.

코딩 에이전트에서 비용은 부수적인 것이 아니라 설계 변수다. 어려운 태스크
하나 때문에 쉬운 태스크까지 비싼 모델로 돌릴 필요는 없다. 그래서 모델을
**등급으로** 두고, 태스크 난이도에 따라 배정한다(v0.3).

모델·가격 문자열은 이 파일에만 둔다. 가격은 litellm이 응답에서 계산해
주지만, 실행 **전에** 추정하려면 우리도 표를 하나 들고 있어야 한다.
"""

import os

# (환경변수, {등급: 모델}) — 키가 있는 첫 플랫폼을 쓴다
PROVIDERS: list[tuple[str, dict]] = [
    ("GEMINI_API_KEY", {"strong": "gemini/gemini-3.5-flash",
                        "cheap": "gemini/gemini-3.5-flash-lite"}),
    ("OPENAI_API_KEY", {"strong": "openai/gpt-5.4-mini",
                        "cheap": "openai/gpt-5.4-nano"}),
    ("ANTHROPIC_API_KEY", {"strong": "anthropic/claude-sonnet-5",
                           "cheap": "anthropic/claude-haiku-4-5"}),
]

TIERS = ("strong", "cheap")

NO_KEY_MESSAGE = (
    "API 키가 없습니다. 저장소 루트에서 cp .env.sample .env 후 채우고 "
    "docker compose up -d --force-recreate 하세요."
)


def models() -> dict:
    for env_var, tier_models in PROVIDERS:
        if os.environ.get(env_var):
            return tier_models
    raise RuntimeError(NO_KEY_MESSAGE)


def pick_model(tier: str = "cheap") -> str:
    return models()[tier if tier in TIERS else "cheap"]
