# ============================ AUTH GATE (hardcoded + logging) ============================
import os, hashlib, time
from datetime import datetime, timedelta
import streamlit as st

# Hardcode your passcode HASH here (recommended only for quick MVP; prefer secrets/env later)
HARDCODED_PASS_SHA256 = "1234"

# Fallback to secrets/env if hardcoded is blank
PASS_SHA256 = (HARDCODED_PASS_SHA256
               or (st.secrets.get("teacher", {}).get("portal_sha256", "") if hasattr(st, "secrets") else "")
               or os.getenv("TEACHER_PORTAL_SHA256",""))

ATTEMPT_LIMIT = 5
LOCKOUT_MINUTES = 5

def _ok_pass(raw: str) -> bool:
    if not PASS_SHA256:
        return False
    try:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest() == PASS_SHA256
    except Exception:
        return False

def _record_login_attempt(db, status: str, email: str = ""):
    # status: "ok" or "bad"
    try:
        db.collection("teacher_login").add({
            "at": datetime.utcnow(),
            "status": status,
            "email": (email or "").strip().lower(),
            "client": "teacher.falowen.app",
        })
    except Exception:
        pass

st.set_page_config(page_title="Falowen • Teacher Portal", page_icon="🧑‍🏫", layout="wide")

if "teacher_auth" not in st.session_state:
    st.session_state["teacher_auth"] = False
if "__tries" not in st.session_state:
    st.session_state["__tries"] = 0
if "__lock_until" not in st.session_state:
    st.session_state["__lock_until"] = None

with st.container():
    st.markdown("<h2 style='margin:0;'>🧑‍🏫 Falowen • Teacher Portal</h2>", unsafe_allow_html=True)

# init DB early for logging
def _get_db():
    try:
        import firebase_admin
        from firebase_admin import firestore as fbfs
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        return fbfs.client()
    except Exception:
        pass
    try:
        from google.cloud import firestore as gcf
        return gcf.Client()
    except Exception:
        st.error("Firestore client isn't configured. Provide Firebase Admin creds or set GOOGLE_APPLICATION_CREDENTIALS.", icon="🛑")
        raise
db = _get_db()

# lockout check
now_ts = time.time()
if st.session_state["__lock_until"] and now_ts < st.session_state["__lock_until"]:
    remaining = int(st.session_state["__lock_until"] - now_ts)
    st.error(f"Too many attempts. Try again in {remaining} seconds.")
    st.stop()

if not st.session_state["teacher_auth"]:
    pw = st.text_input("Enter teacher passcode", type="password")
    email_for_audit = st.text_input("Your email (for audit)", placeholder="name@domain.com")

    col_a, col_b = st.columns([1,1])
    with col_a:
        enter = st.button("Enter")
    with col_b:
        clear = st.button("Forgot? Reset attempts")

    if clear:
        st.session_state["__tries"] = 0
        st.session_state["__lock_until"] = None
        st.info("Attempts cleared.")
        st.stop()

    if enter:
        if _ok_pass(pw):
            st.session_state["teacher_auth"] = True
            st.session_state["__tries"] = 0
            st.session_state["__lock_until"] = None
            st.session_state["teacher_email"] = (email_for_audit or "").strip().lower()
            _record_login_attempt(db, "ok", st.session_state["teacher_email"])
            st.rerun()
        else:
            st.session_state["__tries"] += 1
            _record_login_attempt(db, "bad", (email_for_audit or "").strip().lower())
            left = ATTEMPT_LIMIT - st.session_state["__tries"]
            if left <= 0:
                st.session_state["__lock_until"] = time.time() + LOCKOUT_MINUTES*60
                st.error(f"Locked for {LOCKOUT_MINUTES} minutes due to too many attempts.")
            else:
                st.error(f"Wrong passcode. {left} attempt(s) left.")
    st.stop()
