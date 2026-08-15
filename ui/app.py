"""진행 대시보드 — 에이전트가 무엇을 하고 있는지 보는 화면.

코딩 에이전트는 오래 돌고 돈을 쓴다. 그래서 보여 줄 것이 셋이다.
**어디까지 왔는가**(태스크), **무엇을 했는가**(이벤트와 git 이력),
**얼마 썼는가**(비용). 산출물은 이 화면이 아니라 8080 포트에서 따로 뜬다.
"""

import os

import requests
import streamlit as st

APP_URL = os.environ.get("APP_URL", "http://localhost:8000")
ARTIFACT_URL = "http://localhost:8080"

STATUS_LABEL = {"idle": "대기", "running": "실행 중", "done": "완료", "failed": "실패"}

st.set_page_config(page_title="coding-agent — 진행 대시보드", page_icon="🛠️", layout="wide")

health = requests.get(f"{APP_URL}/health", timeout=10).json()
status = requests.get(f"{APP_URL}/status", timeout=30).json()
state = status.get("state", "idle")

with st.sidebar:
    st.subheader("실행")
    spec = st.selectbox("SPEC", health["specs"])
    mode = st.radio("배치", ["parallel", "sequential"],
                    format_func={"parallel": "병렬 (v0.2)",
                                 "sequential": "순차 (v0.1)"}.get)
    started = st.button("에이전트 실행", type="primary", use_container_width=True,
                        disabled=state == "running")
    if started:
        requests.post(f"{APP_URL}/run", json={"spec": spec, "mode": mode}, timeout=30)
        st.rerun()

    if st.button("산출물 내리기", use_container_width=True):
        requests.post(f"{APP_URL}/stop", timeout=120)
        st.rerun()

    st.divider()
    st.caption(f"docker {health['docker']} · {health['git']}")
    if state == "running":
        st.caption("실행 중입니다. 새로고침하면 진행이 갱신됩니다.")

st.title("🛠️ coding-agent 진행 대시보드")
left, middle, right = st.columns(3)
left.metric("상태", STATUS_LABEL.get(state, state),
            {"parallel": "병렬", "sequential": "순차"}.get(status.get("mode", ""), ""))
middle.metric("경과", f"{status.get('elapsed_s', 0)}초")
cost = status.get("cost", {})
right.metric("누적 비용", f"${cost.get('cost_usd', 0):.4f}",
             f"{cost.get('calls', 0)}회 호출")

st.subheader("태스크")
tasks = status.get("tasks", [])
if not tasks:
    st.caption("아직 없습니다. 왼쪽에서 실행하십시오.")
else:
    st.table([{"역할": t["role"], "제목": t["title"], "난이도": t["difficulty"],
               "모델": t.get("model", "") or "-", "브랜치": t["branch"],
               "상태": t["status"], "커밋": t.get("sha", "") or "-"} for t in tasks])

columns = st.columns(2)
with columns[0]:
    st.subheader("git 이력")
    st.caption("에이전트의 작업 기록은 곧 git 이력이다")
    st.code(status.get("graph", "") or "아직 없습니다", language="text")

with columns[1]:
    st.subheader("무슨 일이 일어났나")
    for event in status.get("events", [])[-14:]:
        st.caption(f"**{event['agent']}** · {event['action']}")
        if event.get("detail"):
            st.caption(f"　{event['detail'][:160]}")

st.divider()
if status.get("artifact_alive"):
    st.success(f"산출물이 떠 있습니다 → {ARTIFACT_URL}")
    st.caption("만드는 것(이 화면)과 만들어진 것(산출물)은 서로 다른 compose입니다.")
else:
    st.info("산출물은 아직 떠 있지 않습니다.")
