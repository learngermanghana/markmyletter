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

@st.cache_data(ttl=60, show_spinner=False)
def load_student_lessons_from_drafts(student_code: str, limit: int = 200) -> pd.DataFrame:
    """
    Reads all lessons for a student from drafts_v2/{student_code}/lessons (no assignment filtering).
    Returns newest first by submitted/updated/timestamp if present.
    """
    _ensure_firebase_clients()
    if _DB is None or not student_code:
        return pd.DataFrame()

    doc_ref = _DB.collection("drafts_v2").document(str(student_code))
    try:
        # Safe to call even if it doesn't exist; we'll still try reading subcollection
        _ = doc_ref.get()
    except Exception:
        pass

    lessons_ref = doc_ref.collection("lessons")
    try:
        docs = list(lessons_ref.limit(limit).stream())
    except Exception:
        return pd.DataFrame()

    rows = []
    for d in docs:
        data = d.to_dict() or {}

        # Identify a title/name for the lesson (fallback to doc id)
        title = _pick_first_nonempty(
            data, ["assignment_title", "assignment", "title", "topic", "lesson", "name"], default=d.id
        )

        # Text content fields (try several)
        answer_text = _pick_first_nonempty(
            data, ["answer_text", "text", "content", "draft", "body", "message", "answer"], default=""
        )

        # Timestamp-like fields
        ts_raw = _pick_first_nonempty(
            data, ["submitted_at", "updated_at", "timestamp", "ts", "created_at"], default=""
        )
        ts = _normalize_timestamp(ts_raw)

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
    st.subheader("1) Search & Select Student")
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
    st.subheader("Student Code")
    st.code(student_code)

    # --- Student submissions (no assignment filter) ---
    st.subheader("2) Pick a Submission to Mark (from drafts_v2 → lessons)")

    # Small control bar
    colA, colB, colC = st.columns([1, 1, 1])
    with colA:
        refresh = st.button("🔄 Refresh list", use_container_width=True)
    with colB:
        max_items = st.number_input("Max lessons to load", min_value=10, max_value=500, value=200, step=10)
    with colC:
        search_lessons = st.text_input("Filter by title / doc id / text snippet", value="")

    if refresh:
        st.cache_data.clear()

    df_lessons = load_student_lessons_from_drafts(student_code, limit=int(max_items))

    if df_lessons.empty:
        st.info("No drafts found for this student.")
        return

    # Apply client-side filter
    if search_lessons:
        q = search_lessons.strip().lower()
        def _row_match(r):
            return (
                (str(r.get("title","")).lower().find(q) >= 0) or
                (str(r.get("lesson_id","")).lower().find(q) >= 0) or
                (str(r.get("answer_text","")).lower().find(q) >= 0)
            )
        df_view = df_lessons[df_lessons.apply(_row_match, axis=1)].copy()
    else:
        df_view = df_lessons.copy()

    if df_view.empty:
        st.info("No drafts matched your filter.")
        return

    # Nice preview table
    df_preview = df_view.copy()
    # Shorten long text for preview
    df_preview["answer_preview"] = df_preview["answer_text"].fillna("").astype(str).str.slice(0, 160)
    try:
        st.data_editor(
            df_preview[["title","lesson_id","submitted_at","score","comment","file","answer_preview"]],
            use_container_width=True,
            column_config={"file": st.column_config.LinkColumn("File")},
            disabled=True,
            height=300,
        )
    except Exception:
        st.dataframe(df_preview[["title","lesson_id","submitted_at","score","comment","file","answer_preview"]],
                     use_container_width=True, height=300)

    # Build a selection list
    options = [
        f"{row['title']} — {row['lesson_id']} — {(row['submitted_at'] or '')}"
        for _, row in df_view.iterrows()
    ]
    chosen_submission = st.selectbox("Choose a submission to mark", options, key="tab7_choose_submission")
    if not chosen_submission:
        st.warning("Pick a submission to continue.")
        return
    sel_idx = options.index(chosen_submission)
    chosen_row = df_view.iloc[sel_idx]

    st.markdown("**Selected submission details:**")
    st.json({
        "doc_path": chosen_row.get("doc_path"),
        "title": chosen_row.get("title"),
        "lesson_id": chosen_row.get("lesson_id"),
        "submitted_at": str(chosen_row.get("submitted_at")),
        "score": chosen_row.get("score"),
        "comment": chosen_row.get("comment"),
        "file": chosen_row.get("file"),
    })

    # --- Reference selection (independent of lesson title) ---
    st.subheader("3) Select Reference Answer (from Google Sheet)")
    available_assignments = ref_df['assignment'].dropna().astype(str).unique().tolist()
    with st.form("marking_assignment_form"):
        search_assign = st.text_input("Search reference titles...", key="tab7_search_assign")
        submitted_assign = st.form_submit_button("Filter references")
    if submitted_assign and search_assign:
        ref_filtered = [a for a in available_assignments if search_assign.lower() in a.lower()]
    else:
        ref_filtered = available_assignments
    if not ref_filtered:
        st.info("No references match your search.")
        return
    assignment = st.selectbox("Reference to use", ref_filtered, key="tab7_assign_select")
    ref_answers = []
    if assignment:
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
        answers_combined_str = "\n".join([f"{i+1}. {ans}" for i, ans in enumerate(ref_answers)])
    else:
        answers_combined_str = "No answer available."
        st.info("No reference answer available for this selection.")

    # --- Student Work (prefilled from the chosen submission) ---
    st.subheader("4) Student Work")
    student_work = st.text_area(
        "Edit before marking if needed:",
        height=180,
        key="tab7_student_work",
        value=chosen_row.get("answer_text") or ""
    )

    # --- Combined copy & downloads ---
    st.subheader("5) Copy Zone (Reference + Student Work)")
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
