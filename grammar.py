import os
import json
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd

# Firebase Admin
import firebase_admin
from firebase_admin import credentials, firestore, storage


st.set_page_config(page_title="Falowen Marking Tab", layout="wide")

# =============================================================================
# CONFIG: GOOGLE SHEETS SOURCES (edit to your sheet URLs)
# =============================================================================
STUDENTS_CSV_URL = "https://docs.google.com/spreadsheets/d/12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U/export?format=csv"
REF_ANSWERS_URL  = "https://docs.google.com/spreadsheets/d/1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo/export?format=csv"

# =============================================================================
# FIREBASE GLOBALS + INIT
# =============================================================================
_DB = None
_BUCKET = None


def _get_firebase_cred_dict():
    """Return a dict of service account credentials from secrets/env/dev file."""
    # 1) Preferred: Streamlit secrets (supports either table name)
    try:
        if "FIREBASE_SERVICE_ACCOUNT" in st.secrets:
            return dict(st.secrets["FIREBASE_SERVICE_ACCOUNT"])
        if "firebase" in st.secrets:
            return dict(st.secrets["firebase"])
    except Exception:
        pass

    # 2) Optional: Environment variable with full JSON
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass

    # 3) Optional: local dev file (do NOT commit)
    if os.path.exists("serviceAccountKey.json"):
        with open("serviceAccountKey.json", "r", encoding="utf-8") as f:
            return json.load(f)

    return None


def _ensure_firebase_clients():
    """Create _DB and _BUCKET once, safely."""
    global _DB, _BUCKET
    if _DB is not None:
        return  # already initialized

    cred_dict = _get_firebase_cred_dict()
    if not cred_dict:
        _DB, _BUCKET = None, None
        return

    # Bucket name from secrets or env (optional)
    bucket_name = None
    try:
        bucket_name = st.secrets.get("FIREBASE_STORAGE_BUCKET")
    except Exception:
        pass
    if not bucket_name:
        bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")

    # Initialize app once
    if not firebase_admin._apps:
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
    # sometimes the sheet uses 'student_code' — normalize to 'studentcode'
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


@st.cache_data(ttl=60, show_spinner=False)
def load_student_submissions_from_firebase(student_code: str, assignment_title: str, limit: int = 5) -> pd.DataFrame:
    """Fetch latest submissions for a given student_code + assignment_title from Firestore.

    Expected collection: assignments
    Expected fields on docs: student_code, assignment_title, submitted_at, score, comment/feedback,
                             file_path or storage_path (optional), answer_text/answer/text/content
    """
    _ensure_firebase_clients()
    if _DB is None:
        return pd.DataFrame()

    q = _DB.collection("assignments").where("student_code", "==", str(student_code))
    if assignment_title:
        q = q.where("assignment_title", "==", str(assignment_title))

    # Order by submitted_at if present
    try:
        q = q.order_by("submitted_at", direction=firestore.Query.DESCENDING)
    except Exception:
        pass

    docs = list(q.limit(int(limit)).stream())

    rows = []
    for d in docs:
        data = d.to_dict() or {}
        ts = data.get("submitted_at")
        # Normalize timestamp
        try:
            if hasattr(ts, "to_datetime"):
                ts = ts.to_datetime()
            elif isinstance(ts, (int, float)):
                ts = datetime.fromtimestamp(ts)
        except Exception:
            pass

        # Optional signed file URL if storage path exists
        file_path = data.get("file_path") or data.get("storage_path")
        signed_url = None
        if file_path and _BUCKET is not None:
            try:
                blob = _BUCKET.blob(file_path)
                signed_url = blob.generate_signed_url(expiration=timedelta(hours=6), method="GET")
            except Exception:
                signed_url = None

        rows.append({
            "doc_id": d.id,
            "submitted_at": ts,
            "score": data.get("score"),
            "comment": data.get("comment") or data.get("feedback"),
            "file": signed_url,
            "answer_text": (
                data.get("answer_text")
                or data.get("answer")
                or data.get("text")
                or data.get("content")
                or ""
            ),
        })

    return pd.DataFrame(rows)


# =============================================================================
# UI: MARKING TAB
# =============================================================================
def render_marking_tab():
    _ensure_firebase_clients()

    st.title("📝 Reference & Student Work Share")

    # --- Load Data (Sheets) ---
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

    # --- Column mapping ---
    name_col = col_lookup(df_students, "name")
    code_col = col_lookup(df_students, "studentcode")
    if not name_col or not code_col:
        st.error("Required columns 'name' or 'studentcode' not found in students sheet.")
        return

    # --- Student search/select ---
    st.subheader("1. Search & Select Student")
    with st.form("marking_student_form"):
        search_student = st.text_input("Type student name or code...", key="tab7_search_student")
        submitted_student = st.form_submit_button("Apply")

    if submitted_student and search_student:
        mask = (
            df_students[name_col].astype(str).str.contains(search_student, case=False, na=False) |
            df_students[code_col].astype(str).str.contains(search_student, case=False, na=False)
        )
        students_filtered = df_students[mask].copy()
    else:
        students_filtered = df_students.copy()

    if students_filtered.empty:
        st.info("No students match your search. Try a different query.")
        return

    display_name = students_filtered[name_col].fillna("").astype(str)
    display_code = students_filtered[code_col].fillna("").astype(str)
    student_list = (display_name + " (" + display_code + ")").tolist()

    chosen = st.selectbox("Select Student", student_list, key="tab7_single_student")
    if not chosen or "(" not in chosen:
        st.warning("Select a student to continue.")
        return

    student_code = chosen.split("(")[-1].replace(")", "").strip()
    sel_rows = students_filtered[students_filtered[code_col] == student_code]
    if sel_rows.empty:
        st.warning("Selected student not found.")
        return
    student_row = sel_rows.iloc[0]

    st.markdown(f"**Selected:** {student_row.get(name_col, '')} ({student_code})")

    # --- Student Code display ---
    st.subheader("Student Code")
    st.code(student_code)

    # --- Assignment search/select ---
    st.subheader("2. Select Assignment")
    available_assignments = (
        ref_df['assignment'].dropna().astype(str).unique().tolist()
        if 'assignment' in ref_df.columns else []
    )

    with st.form("marking_assignment_form"):
        search_assign = st.text_input("Type assignment title...", key="tab7_search_assign")
        submitted_assign = st.form_submit_button("Filter assignments")

    if submitted_assign and search_assign:
        filtered = [a for a in available_assignments if search_assign.lower() in a.lower()]
    else:
        filtered = available_assignments

    if not filtered:
        st.info("No assignments match your search.")
        return

    assignment = st.selectbox("Select Assignment", filtered, key="tab7_assign_select")
    if not assignment:
        st.info("Select an assignment to continue.")
        return

    # --- Reference Answer ---
    st.subheader("3. Reference Answer (from Google Sheet)")
    ref_answers = []
    if assignment:
        assignment_row = ref_df[ref_df['assignment'].astype(str) == assignment]
        if not assignment_row.empty:
            all_cols = assignment_row.columns.tolist()
            answer_cols = [c for c in all_cols if str(c).startswith("answer")]
            answer_cols = [
                c for c in answer_cols
                if pd.notnull(assignment_row.iloc[0][c])
                and str(assignment_row.iloc[0][c]).strip() != ""
            ]
            ref_answers = [str(assignment_row.iloc[0][c]) for c in answer_cols]

    if ref_answers:
        if len(ref_answers) == 1:
            st.markdown("**Reference Answer:**")
            st.write(ref_answers[0])
        else:
            ans_tabs = st.tabs([f"Answer {i+1}" for i in range(len(ref_answers))])
            for i, ans in enumerate(ref_answers):
                with ans_tabs[i]:
                    st.write(ans)
        answers_combined_str  = "\n".join([f"{i+1}. {ans}" for i, ans in enumerate(ref_answers)])
        answers_combined_html = "<br>".join([f"{i+1}. {ans}" for i, ans in enumerate(ref_answers)])
    else:
        answers_combined_str  = "No answer available."
        answers_combined_html = "No answer available."
        st.info("No reference answer available for this assignment.")

    # --- Latest submission from Firebase ---
    st.subheader("3b. Latest Submission from Firebase (auto)")

    latest_text = ""
    if _DB is None:
        st.info("Firebase is not configured. Add FIREBASE_SERVICE_ACCOUNT (and FIREBASE_STORAGE_BUCKET) to secrets to enable live submissions.")
    else:
        df_fire = load_student_submissions_from_firebase(student_code, assignment, limit=5)
        if df_fire.empty:
            st.info("No live submission found in Firebase for this student/assignment yet.")
        else:
            # Prefer LinkColumn (Streamlit >= 1.32); otherwise fallback to dataframe
            try:
                st.data_editor(
                    df_fire,
                    use_container_width=True,
                    column_config={
                        "file": st.column_config.LinkColumn("File", help="Open uploaded file"),
                    },
                    disabled=True
                )
            except Exception:
                st.dataframe(df_fire, use_container_width=True)

            # Prefill Student Work with the most recent answer_text
            latest_text = df_fire.iloc[0].get("answer_text") or ""

    # --- Student Work ---
    st.subheader("4. Paste Student Work (for your manual cross-check or AI use)")
    student_work = st.text_area(
        "Paste the student's answer here:",
        height=160,
        key="tab7_student_work",
        value=latest_text or ""
    )

    # --- Combined copy box ---
    st.subheader("5. Copy Zone (Reference + Student Work)")
    combined_text = (
        "Reference answer:\n"
        + answers_combined_str
        + "\n\nStudent answer:\n"
        + (student_work or "")
    )
    st.code(combined_text, language="markdown")
    st.info("Copy this block and paste into your AI tool for checking.")

    # --- Quick downloads ---
    st.write("**Quick Download:**")
    st.download_button(
        "📋 Reference Answer (txt)",
        data=answers_combined_str,
        file_name="reference_answer.txt",
        mime="text/plain",
        key="tab7_copy_reference",
    )
    st.download_button(
        "📋 Reference + Student (txt)",
        data=combined_text,
        file_name="ref_and_student.txt",
        mime="text/plain",
        key="tab7_copy_both",
    )


# Run standalone OR import into your tabs and call with:
# with tabs[7]:
#     render_marking_tab()
if __name__ == "__main__":
    render_marking_tab()
