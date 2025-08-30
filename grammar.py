# falowen_marking_tab.py # Streamlit app: Reference & Student Work Share + Grading export to Google Sheets
import os
import re
import json
from datetime import datetime, timedelta
import streamlit as st
import pandas as pd
import requests
import pyperclip  # To copy text to clipboard

# webhook to Google Sheets
# Firebase Admin
import firebase_admin
from firebase_admin import credentials, firestore, storage

st.set_page_config(page_title="Falowen Marking Tab", layout="wide")

# =============================================================================
# CONFIG: Google Sheets sources (edit to your sheet URLs)
# =============================================================================
STUDENTS_CSV_URL = "https://docs.google.com/spreadsheets/d/12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U/export?format=csv"
REF_ANSWERS_URL  = "https://docs.google.com/spreadsheets/d/1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo/export?format=csv"
# Optional sheet holding previously recorded scores
SCORES_CSV_URL   = st.secrets.get("SCORES_CSV_URL", "scores_backup.csv")

# === Apps Script Webhook ===
G_SHEETS_WEBHOOK_URL   = st.secrets.get("G_SHEETS_WEBHOOK_URL", "https://script.google.com/macros/s/AKfycbzKWo9IblWZEgD_d7sku6cGzKofis_XQj3NXGMYpf_uRqu9rGe4AvOcB15E3bb2e6O4/exec")
G_SHEETS_WEBHOOK_TOKEN = st.secrets.get("G_SHEETS_WEBHOOK_TOKEN", "Xenomexpress7727/")

# Optional default target tab
DEFAULT_TARGET_SHEET_GID  = 2121051612      # your grades tab gid
DEFAULT_TARGET_SHEET_NAME = None            # or e.g. "scores_backup"

# =============================================================================
# FIREBASE GLOBALS + INIT
# =============================================================================
_DB = None
_BUCKET = None

def _get_firebase_cred_dict():
    """Return service account credentials from secrets/env/dev file."""
    try:
        if "FIREBASE_SERVICE_ACCOUNT" in st.secrets:
            return dict(st.secrets["FIREBASE_SERVICE_ACCOUNT"])
        if "firebase" in st.secrets:
            return dict(st.secrets["firebase"])
    except Exception:
        pass
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    if os.path.exists("serviceAccountKey.json"):
        with open("serviceAccountKey.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def _ensure_firebase_clients():
    """Initialize Firestore and Storage once."""
    global _DB, _BUCKET
    if _DB is not None:
        return
    cred_dict = _get_firebase_cred_dict()
    if not cred_dict:
        _DB, _BUCKET = None, None
        return
    bucket_name = None
    try:
        bucket_name = st.secrets.get("FIREBASE_STORAGE_BUCKET")
    except Exception:
        pass
    if not bucket_name:
        bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")
    try:
        firebase_admin.get_app()
    except ValueError:
        cfg = {"storageBucket": bucket_name} if bucket_name else {}
        firebase_admin.initialize_app(credentials.Certificate(cred_dict), cfg)
    _DB = firestore.client()
    try:
        _BUCKET = storage.bucket()
    except Exception:
        _BUCKET = None

# =============================================================================
# HELPERS
# =============================================================================
def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip().lower().replace(" ", "").replace("_", "") for c in df.columns]
    return df

@st.cache_data(show_spinner=False)
def load_marking_students(url: str) -> pd.DataFrame:
    df = pd.read_csv(url, dtype=str)
    df = _normalize_columns(df)
    if "student_code" in df.columns:
        df = df.rename(columns={"student_code": "studentcode"})
    return df

@st.cache_data(ttl=300, show_spinner=False)
def load_marking_ref_answers(url: str) -> pd.DataFrame:
    df = pd.read_csv(url, dtype=str)
    df = _normalize_columns(df)
    return df

def col_lookup(df: pd.DataFrame, name: str):
    key = name.lower().replace(" ", "").replace("_", "")
    for c in df.columns:
        if c.lower().replace(" ", "").replace("_", "") == key:
            return c
    return None

def _pick_first_nonempty(d: dict, keys, default=""):
    for k in keys:
        if k in d and d[k] is not None:
            s = str(d[k]).strip()
            if s != "":
                return s
    return default

def _normalize_timestamp(ts):
    try:
        if hasattr(ts, "to_datetime"):
            return ts.to_datetime()
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts)
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                return None
    except Exception:
        return None
    return None

def _norm_key(s: str) -> str:
    return "".join(ch for ch in str(s).lower() if ch.isalnum())

# Webhook helper
def _post_rows_to_sheet(rows, sheet_name: str | None = None, sheet_gid: int | None = None) -> dict:
    url = st.secrets.get("G_SHEETS_WEBHOOK_URL", G_SHEETS_WEBHOOK_URL)
    token = st.secrets.get("G_SHEETS_WEBHOOK_TOKEN", G_SHEETS_WEBHOOK_TOKEN)
    if not url or not token or "PUT_YOUR" in url or "PUT_YOUR" in token:
        raise RuntimeError("Webhook URL/token missing. Add to st.secrets or set constants.")
    payload = {"token": token, "rows": rows}
    if sheet_name:
        payload["sheet_name"] = sheet_name
    if sheet_gid is not None:
        payload["sheet_gid"] = int(sheet_gid)

    r = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=20,
    )
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"ok": False, "error": r.text[:200]}

    if r.status_code != 200 or not data.get("ok"):
        raise RuntimeError(f"Webhook error {r.status_code}: {data}")
    return data

# Helper to copy data to clipboard
def copy_to_clipboard(text: str):
    """Utility function to copy content to clipboard."""
    pyperclip.copy(text)
    st.success("Content copied to clipboard!")

def display_copy_button(text: str):
    """Display a button to copy the text."""
    if st.button("Copy to clipboard"):
        copy_to_clipboard(text)

# =============================================================================
# UI: MARKING TAB
# =============================================================================
def render_marking_tab():
    _ensure_firebase_clients()

    st.title("📝 Reference & Student Work Share")

    try:
        df_students = load_marking_students(STUDENTS_CSV_URL)
    except Exception as e:
        st.error(f"Could not load students: {e}")
        return

    try:
        ref_df = load_marking_ref_answers(REF_ANSWERS_URL)
        if "assignment" not in ref_df.columns:
            st.warning("No 'assignment' column found in reference answers sheet.")
            return
    except Exception as e:
        st.error(f"Could not load reference answers: {e}")
        return

    student_code, student_name, student_row = select_student(df_students)
    chosen_row = choose_submission(student_code)
    assignment, answers_combined_str, ref_link_value = pick_reference(ref_df)
    one_row = mark_submission(
        student_code,
        student_name,
        student_row,
        chosen_row,
        assignment,
        answers_combined_str,
        ref_link_value,
    )

    # Add Copy button for the final content
    combined_content = f"Assignment: {assignment}\nScore: {one_row['score']}\nFeedback: {one_row['comments']}"
    display_copy_button(combined_content)

    # Attempt to send the data to Google Sheets
    try:
        export_row(one_row)
    except Exception as e:
        st.error(f"Failed to send: {e}")

if __name__ == "__main__":
    render_marking_tab()
