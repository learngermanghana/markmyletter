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
# Prefer storing in st.secrets:
#   G_SHEETS_WEBHOOK_URL, G_SHEETS_WEBHOOK_TOKEN
# You can hardcode as fallback (replace placeholders).
G_SHEETS_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzKWo9IblWZEgD_d7sku6cGzKofis_XQj3NXGMYpf_uRqu9rGe4AvOcB15E3bb2e6O4/exec"
G_SHEETS_WEBHOOK_TOKEN = "Xenomexpress7727/"

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

# ---- Auto-pick reference link helpers ---------------------------------------
_URL_RE = re.compile(r"https?://[^\s\]>)}\"'`]+", re.IGNORECASE)

def _extract_urls_from_text(text: str) -> list[str]:
    if not isinstance(text, str) or not text:
        return []
    # find urls and strip trailing punctuation that often sticks to cells
    raw = _URL_RE.findall(text)
    cleaned = []
    for u in raw:
        u = u.strip().rstrip(".,;:)]}>\"'")
        cleaned.append(u)
    # de-dup preserve order
    seen = set()
    out = []
    for u in cleaned:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

# =============================================================================
# UI helper functions
# =============================================================================

def select_student(df_students):
    """Select a student and resolve Firestore document."""
    name_col = col_lookup(df_students, "name")
    code_col = col_lookup(df_students, "studentcode")
    if not name_col or not code_col:
        st.error("Required columns 'name' or 'studentcode' not found in students sheet.")
        return None, None, None, None
    
    st.subheader("1) Search & Select Student")
    with st.form("marking_student_form"):
        search_student = st.text_input("Type student name or code...", key="tab7_search_student")
        submitted_student = st.form_submit_button("Apply")

    if submitted_student and search_student:
        mask = (
            df_students[name_col].astype(str).str.contains(search_student, case=False, na=False)
            | df_students[code_col].astype(str).str.contains(search_student, case=False, na=False)
        )
        students_filtered = df_students[mask].copy()
    else:
        students_filtered = df_students.copy()

    if students_filtered.empty:
        st.info("No students match your search. Try a different query.")
        st.stop()

    codes = students_filtered[code_col].astype(str).tolist()
    code_to_name = dict(zip(students_filtered[code_col].astype(str), students_filtered[name_col].astype(str)))

    def _fmt_student(code: str):
        return f"{code_to_name.get(code, 'Unknown')} ({code})"

    selected_student_code = st.selectbox("Select Student", codes, format_func=_fmt_student, key="tab7_selected_code")
    if not selected_student_code:
        st.warning("Select a student to continue.")
        st.stop()

    sel_rows = students_filtered[students_filtered[code_col] == selected_student_code]
    if sel_rows.empty:
        st.warning("Selected student not found.")
        st.stop()
    student_row = sel_rows.iloc[0]
    student_code = selected_student_code
    student_name = str(student_row.get(name_col, "")).strip()

    st.markdown(f"**Selected:** {student_name} ({student_code})")
    st.subheader("Student Code")
    st.code(student_code)

    st.subheader("1b) Match to Firestore student document (drafts_v2)")
    if "tab7_effective_student_doc" not in st.session_state:
        st.session_state["tab7_effective_student_doc"] = None

    needs_resolve = st.session_state.get("tab7_resolved_for") != student_code
    colr1, colr2 = st.columns([1, 1])
    with colr1:
        if st.button("🔍 Re-resolve Firestore doc", use_container_width=True):
            needs_resolve = True
    with colr2:
        manual_override = st.text_input(
            "Manual override (exact drafts_v2 doc id)",
            value=st.session_state.get("tab7_effective_student_doc") or "",
        )

    if manual_override.strip():
        st.session_state["tab7_effective_student_doc"] = manual_override.strip()
        st.session_state["tab7_resolved_for"] = student_code
    elif needs_resolve:
        match = _find_candidate_doc_ids_from_firestore(student_code, student_name)
        exact = match.get("exact")
        suggestions = match.get("suggestions", [])
        if exact:
            st.session_state["tab7_effective_student_doc"] = exact
            st.session_state["tab7_resolved_for"] = student_code
            st.success(f"Matched Firestore doc: {exact}")
        else:
            st.info("No exact doc match. Pick from suggestions or type manual override.")
            if suggestions:
                pick = st.selectbox("Suggestions from drafts_v2", suggestions, key="tab7_doc_suggestion")
                if pick:
                    st.session_state["tab7_effective_student_doc"] = pick
                    st.session_state["tab7_resolved_for"] = student_code
            else:
                st.warning("No suggestions found. Use the manual override above.")

    effective_doc = st.session_state.get("tab7_effective_student_doc")
    if not effective_doc:
        with st.expander("🧭 Debug: list drafts_v2 doc IDs", expanded=False):
            ids = list_drafts_student_doc_ids(limit=200)
            st.write(f"Found {len(ids)} doc IDs (showing up to 200):")
            query = st.text_input("Filter IDs", "")
            if query:
                ids = [i for i in ids if query.lower() in i.lower()]
            st.dataframe(pd.DataFrame({"doc_id": ids}))
        st.stop()

    st.success(f"Using Firestore doc: drafts_v2/{effective_doc}")
    return student_code, student_name, student_row, effective_doc

# Copy Button Helper (to copy scores, comments, etc.)
def copy_to_clipboard(text: str):
    """Utility function to copy content to clipboard."""
    pyperclip.copy(text)
    st.success("Content copied to clipboard!")

# Function to display a copy button
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

    student_code, student_name, student_row, effective_doc = select_student(df_students)
    chosen_row = choose_submission(effective_doc)
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
    export_row(one_row)
    
    # Add Copy button for the final content
    combined_content = f"Assignment: {assignment}\nScore: {one_row['score']}\nFeedback: {one_row['comments']}"
    display_copy_button(combined_content)

# Run standalone OR import into your tabs and call with:
# with tabs[7]:
#     render_marking_tab()

if __name__ == "__main__":
    render_marking_tab()
