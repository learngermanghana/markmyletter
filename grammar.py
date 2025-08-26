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
    # 1) Streamlit secrets (supports either table name)
    try:
        if "FIREBASE_SERVICE_ACCOUNT" in st.secrets:
            return dict(st.secrets["FIREBASE_SERVICE_ACCOUNT"])
        if "firebase" in st.secrets:
            return dict(st.secrets["firebase"])
    except Exception:
        pass
    # 2) Env var with full JSON
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    # 3) Local dev file (never commit)
    if os.path.exists("serviceAccountKey.json"):
        with open("serviceAccountKey.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def _ensure_firebase_clients():
    """Create _DB and _BUCKET once, safely."""
    global _DB, _BUCKET
    if _DB is not None:
        return
    cred_dict = _get_firebase_cred_dict()
    if not cred_dict:
        _DB, _BUCKET = None, None
        return
    # Optional storage bucket
    bucket_name = None
    try:
        bucket_name = st.secrets.get("FIREBASE_STORAGE_BUCKET")
    except Exception:
        pass
    if not bucket_name:
        bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")
    # Init app
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

def _pick_first_nonempty(d: dict, keys: list[str], default=""):
    for k in keys:
        v = d.get(k)
        if v is not None:
            s = str(v).strip()
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
            # try iso parse
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                return None
    except Exception:
        return None
    return None

@st.cache_data(ttl=60, show_spinner=False)
def load_student_lessons_from_drafts(student_code: str, assignment_title: str | None, limit: int = 10) -> pd.DataFrame:
    """
    Reads from drafts_v2/{student_code}/lessons.
    Tries to match assignment by common fields: 'assignment', 'assignment_title', 'title', 'topic', 'lesson', 'name'.
    Returns newest first by submitted/updated/timestamp if present.
    """
    _ensure_firebase_clients()
    if _DB is None or not student_code:
        return pd.DataFrame()

    # Get the student's doc
    doc_ref = _DB.collection("drafts_v2").document(str(student_code))
    # If the document doesn't exist, just return empty
    try:
        if not doc_ref.get().exists:
            return pd.DataFrame()
    except Exception:
        # If security rules block get(), still try reading subcollection
        pass

    lessons_ref = doc_ref.collection("lessons")
    # Pull a reasonable number and filter client-side (flexible field names)
    try:
        docs = list(lessons_ref.limit(100).stream())
    except Exception:
        return pd.DataFrame()

    rows = []
    at_lower = (assignment_title or "").lower()
    for d in docs:
        data = d.to_dict() or {}

        # Identify a title/name for the lesson
        title = _pick_first_nonempty(
            data,
            ["assignment_title", "assignment", "title", "topic", "lesson", "name"],
            default=d.id
        )

        # Try to decide if this lesson matches the selected assignment
        matches = True
        if assignment_title:
            matches = (at_lower in title.lower())

        if not matches:
            continue

        # Text content fields (try several)
        answer_text = _pick_first_nonempty(
            data,
            ["answer_text", "text", "content", "draft", "body", "message", "answer"],
            default=""
        )

        # Try to extract timestamp-like fields
        ts = _pick_first_nonempty(
            data,
            ["submitted_at", "updated_at", "timestamp", "ts", "created_at"],
            default=""
        )
        ts = _normalize_timestamp(ts)

        # Optional file link (via Storage signed URL)
        file_path = _pick_first_nonempty(data, ["file_path", "storage_path", "file"], default="")
        signed_url = None
        if file_path and _BUCKET is not None:
            try:
                blob = _BUCKET.blob(file_path)
                signed_url = blob.generate_signed_url(expiration=timedelta(hours=6), method="GET")
            except Exception:
                signed_url = None

        rows.append({
            "doc_path": f"drafts_v2/{student_code}/lessons/{d.id}",
            "lesson_id": d.id,
            "title": title,
            "submitted_at": ts,
            "score": data.get("score"),
            "comment": _pick_first_nonempty(data, ["comment", "feedback", "remarks"], default=""),
            "file": signed_url,
            "answer_text": answer_text,
        })

    df = pd.DataFrame(rows)
    if not df.empty and "submitted_at" in df.columns:
        df = df.sort_values("submitted_at", ascending=False, na_position="last")
    if limit and not df.empty:
        df = df.head(int(limit))
    return df

# (Optional) keep the old loader as a fallback if you also have an 'assignments' collection
@st.cache_data(ttl=60, show_spinner=False)
def load_student_submissions_from_assignments(student_code: str, assignment_title: str | None, limit: int = 5) -> pd.DataFrame:
    _ensure_firebase_clients()
    if _DB is None:
        return pd.DataFrame()
    q = _DB.collection("assignments").where("student_code", "==", str(student_code))
    if assignment_title:
        q = q.where("assignment_title", "==", str(assignment_title))
    try:
        docs = list(q.limit(int(limit)).stream())
    except Exception:
        docs = []
    rows = []
    for d in docs:
        data = d.to_dict() or {}
        ts = _normalize_timestamp(
            _pick_first_nonempty(data, ["submitted_at", "updated_at", "timestamp", "ts", "created_at"], default="")
        )
        file_path = _pick_first_nonempty(data, ["file_path", "storage_path", "file"], default="")
        signed_url = None
        if file_path and _BUCKET is not None:
            try:
                blob = _BUCKET.blob(file_path)
                signed_url = blob.generate_signed_url(expiration=timedelta(hours=6), method="GET")
            except Exception:
                signed_url = None
        rows.append({
            "doc_path": f"assignments/{d.id}",
            "lesson_id": d.id,
            "title": _pick_first_nonempty(data, ["assignment_title", "assignment", "title"], default=d.id),
            "submitted_at": ts,
            "score": data.get("score"),
            "comment": _pick_first_nonempty(data, ["comment", "feedback", "remarks"], default=""),
            "file": signed_url,
            "answer_text": _pick_first_nonempty(data, ["answer_text", "answer", "text", "content"], default=""),
        })
    df = pd.DataFrame(rows)
    if not df.empty and "submitted_at" in df.columns:
        df = df.sort_values("submitted_at", ascending=False, na_position="last")
    return df

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
    assignment_row = ref_df[ref_df['assignment'].astype(str) == assignment]
    if not assignment_row.empty:
        all_cols = assignment_row.columns.tolist()
        answer_cols = [c for c in all_cols if str(c).startswith("answer")]
        answer_cols = [
            c for c in answer_cols
            if pd.notnull(assignment_row.iloc[0][c]) and str(assignment_row.iloc[0][c]).strip() != ""
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
    else:
        answers_combined_str  = "No answer available."
        st.info("No reference answer available for this assignment.")

    # --- Latest student drafts from drafts_v2 ---
    st.subheader("3b. Latest Student Drafts (drafts_v2 ➜ lessons)")
    latest_text = ""
    if _DB is None:
        st.info("Firebase is not configured. Add FIREBASE_SERVICE_ACCOUNT (and FIREBASE_STORAGE_BUCKET) to secrets to enable live submissions.")
    else:
        df_lessons = load_student_lessons_from_drafts(student_code, assignment_title=assignment, limit=10)
        if df_lessons.empty:
            # (Optional) Also try the old 'assignments' collection as a fallback
            df_assign = load_student_submissions_from_assignments(student_code, assignment_title=assignment, limit=5)
            if df_assign.empty:
                st.info("No drafts/submissions found for this student and assignment.")
            else:
                st.caption("Showing fallback results from 'assignments' collection.")
                try:
                    st.data_editor(
                        df_assign,
                        use_container_width=True,
                        column_config={"file": st.column_config.LinkColumn("File")},
                        disabled=True
                    )
                except Exception:
                    st.dataframe(df_assign, use_container_width=True)
                latest_text = df_assign.iloc[0].get("answer_text") or ""
        else:
            try:
                st.data_editor(
                    df_lessons,
                    use_container_width=True,
                    column_config={"file": st.column_config.LinkColumn("File")},
                    disabled=True
                )
            except Exception:
                st.dataframe(df_lessons, use_container_width=True)
            latest_text = df_lessons.iloc[0].get("answer_text") or ""

    # --- Student Work ---
    st.subheader("4. Paste Student Work (for your manual cross-check or AI use)")
    student_work = st.text_area(
        "Paste the student's answer here:",
        height=160,
        key="tab7_student_work",
        value=latest_text or ""
    )

    # --- Combined copy box & downloads ---
    st.subheader("5. Copy Zone (Reference + Student Work)")
    combined_text = (
        "Reference answer:\n"
        + answers_combined_str
        + "\n\nStudent answer:\n"
        + (student_work or "")
    )
    st.code(combined_text, language="markdown")
    st.download_button("📋 Reference Answer (txt)", data=answers_combined_str,
                       file_name="reference_answer.txt", mime="text/plain")
    st.download_button("📋 Reference + Student (txt)", data=combined_text,
                       file_name="ref_and_student.txt", mime="text/plain")


# Run standalone OR import into your tabs and call with:
# with tabs[7]:
#     render_marking_tab()
if __name__ == "__main__":
    render_marking_tab()
