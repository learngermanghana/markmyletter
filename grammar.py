# teacher_app.py — Falowen Teacher Portal (MVP)
# Run: streamlit run teacher_app.py

import os, hashlib, math
from datetime import datetime, timedelta
import streamlit as st

# ============================ AUTH GATE (v1) ============================
PASS_SHA256 = (
    st.secrets.get("teacher", {}).get("portal_sha256", "")
    if hasattr(st, "secrets") else os.getenv("TEACHER_PORTAL_SHA256", "")
)

def _ok_pass(raw: str) -> bool:
    if not PASS_SHA256:
        return False
    try:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest() == PASS_SHA256
    except Exception:
        return False

st.set_page_config(page_title="Falowen • Teacher Portal", page_icon="🧑‍🏫", layout="wide")

if "teacher_auth" not in st.session_state:
    st.session_state["teacher_auth"] = False

with st.container():
    st.markdown("<h2 style='margin:0;'>🧑‍🏫 Falowen • Teacher Portal</h2>", unsafe_allow_html=True)

if not st.session_state["teacher_auth"]:
    pw = st.text_input("Enter teacher passcode", type="password")
    if st.button("Enter"):
        if _ok_pass(pw):
            st.session_state["teacher_auth"] = True
            st.rerun()
        else:
            st.error("Wrong passcode.")
    st.stop()

# (optional) Audit identity
ALLOWED = set(st.secrets.get("roles", {}).get("teachers", [])) if hasattr(st, "secrets") else set()
ADMINS  = set(st.secrets.get("roles", {}).get("admins", [])) if hasattr(st, "secrets") else set()

if "teacher_email" not in st.session_state:
    email = st.text_input("Your email (for audit logging)", placeholder="name@domain.com")
    if st.button("Continue"):
        email = (email or "").strip().lower()
        if not email:
            st.error("Enter your email.")
        elif ALLOWED and (email not in ALLOWED and email not in ADMINS):
            st.error("Not on teacher list. Contact admin.")
        else:
            st.session_state["teacher_email"] = email
            st.success("Welcome!")
            st.rerun()
    st.stop()

TEACHER_EMAIL = st.session_state.get("teacher_email", "")

# ============================ DB CLIENT ============================
def _get_db():
    # Try Firebase Admin → google.cloud fallback
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

# ============================ HELPERS ============================
def _safe_str(v, default=""):
    try:
        import pandas as pd
        if pd.isna(v): return default
    except Exception:
        if v is None or (isinstance(v, float) and math.isnan(v)): return default
    s = str(v or "").strip()
    return "" if s.lower() in ("nan", "none") else s

