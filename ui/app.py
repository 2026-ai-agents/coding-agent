"""진행 대시보드 — 에이전트가 무엇을 하고 있는지 보는 화면.

코딩 에이전트는 오래 돌고 돈을 쓴다. 그래서 보여 줄 것이 넷이다.

  · 어디까지 왔는가   태스크 표와 구간
  · 무엇을 했는가     이벤트와 git 이력 (작업 기록은 곧 git이다)
  · 얼마 썼는가       추정과 실측을 나란히
  · 무엇이 나왔는가   산출물은 8080에서 따로 뜬다

만드는 것(이 화면)과 만들어진 것(산출물)은 서로 다른 compose다.
"""

import os
import time

import requests
import streamlit as st
import streamlit.components.v1 as components

APP_URL = os.environ.get("APP_URL", "http://localhost:8000")
ARTIFACT_URL = "http://localhost:8080"

STATUS_LABEL = {"idle": "대기", "running": "실행 중", "done": "완료", "failed": "실패",
                "approval_needed": "승인 대기", "stopped": "중단됨"}
AGENT_ICON = {"planner": "🧭", "gate": "💰", "backend": "⚙️", "frontend": "🎨",
              "tests": "🧪", "integrator": "🔗", "fixer": "🩹"}

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
    budget = st.number_input("비용 상한 ($)", min_value=0.0, max_value=5.0,
                             value=0.02, step=0.005, format="%.3f")

    if st.button("에이전트 실행", type="primary", use_container_width=True,
                 disabled=state in ("running", "approval_needed")):
        requests.post(f"{APP_URL}/run",
                      json={"spec": spec, "mode": mode, "budget_usd": budget}, timeout=30)
        st.rerun()

    if st.button("산출물 내리기", use_container_width=True):
        requests.post(f"{APP_URL}/stop", timeout=120)
        st.rerun()

    follow = st.checkbox("자동 새로고침", value=state in ("running", "approval_needed"))

    st.divider()
    st.caption(f"docker {health['docker']} · {health['git']}")
    st.caption("산출물은 별도 compose로 8080에서 뜹니다")

st.title("🛠️ coding-agent 진행 대시보드")

cost = status.get("cost", {})
estimate_total = status.get("estimate", {}).get("total_usd")
columns = st.columns(4)
columns[0].metric("상태", STATUS_LABEL.get(state, state),
                  {"parallel": "병렬", "sequential": "순차"}.get(status.get("mode", ""), ""))
columns[1].metric("경과", f"{status.get('elapsed_s', 0)}초")
columns[2].metric("실측 비용", f"${cost.get('cost_usd', 0):.4f}",
                  f"추정 ${estimate_total:.4f}" if estimate_total
                  else f"{cost.get('calls', 0)}회 호출")
columns[3].metric("복구", f"수정 {status.get('fix_rounds', 0)}회",
                  f"재계획 {status.get('replans', 0)}회")

if state == "approval_needed":
    estimate = status.get("estimate", {})
    st.warning(f"예상 비용 ${estimate.get('total_usd', 0):.4f}이 상한 "
               f"${status.get('budget_usd', 0):.4f}을 넘습니다. 승인해야 시작합니다.")
    st.table([{"역할": item["role"], "모델": item["model"].split("/")[-1],
               "예상 출력": f"{item['out_tokens']:,} 토큰",
               "예상 비용": f"${item['cost_usd']:.4f}"}
              for item in estimate.get("per_task", [])])
    approve, reject = st.columns(2)
    if approve.button("승인하고 진행", type="primary", use_container_width=True):
        requests.post(f"{APP_URL}/approve", json={"approved": True}, timeout=30)
        st.rerun()
    if reject.button("중단", use_container_width=True):
        requests.post(f"{APP_URL}/approve", json={"approved": False}, timeout=30)
        st.rerun()

st.subheader("태스크")
tasks = status.get("tasks", [])
if not tasks:
    st.caption("아직 없습니다. 왼쪽에서 실행하십시오.")
else:
    st.table([{"역할": f"{AGENT_ICON.get(task['role'], '')} {task['role']}",
               "제목": task["title"], "난이도": task["difficulty"],
               "모델": (task.get("model") or "-").split("/")[-1],
               "브랜치": task["branch"], "상태": task["status"],
               "구간": (f"{task['started_s']:.1f}s → {task['ended_s']:.1f}s"
                        if task.get("ended_s") is not None else "-"),
               "커밋": task.get("sha", "") or "-"} for task in tasks])

columns = st.columns(2)
with columns[0]:
    st.subheader("git 이력")
    st.caption("에이전트의 작업 기록은 곧 git 이력이다")
    st.code(status.get("graph", "") or "아직 없습니다", language="text")

with columns[1]:
    st.subheader("무슨 일이 일어났나")
    for event in status.get("events", [])[-16:]:
        st.caption(f"{AGENT_ICON.get(event['agent'], '·')} **{event['agent']}** · {event['action']}")
        if event.get("detail"):
            st.caption(f"　{event['detail'][:200]}")

st.divider()
if status.get("artifact_alive"):
    st.success(f"산출물이 떠 있습니다 → {ARTIFACT_URL}")
    components.iframe(ARTIFACT_URL, height=420)
else:
    st.info("산출물은 아직 떠 있지 않습니다.")

if follow and state in ("running", "approval_needed"):
    time.sleep(3)
    st.rerun()
