# falowen_marking_tab.py
# Streamlit app: Reference & Student Work Share + Grading export to Google Sheets

import os
import re
import json
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import requests  # webhook to Google Sheets

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
G_SHEETS_WEBHOOK_URL   = st.secrets.get("G_SHEETS_WEBHOOK_URL",   "https://script.google.com/macros/s/AKfycbzKWo9IblWZEgD_d7sku6cGzKofis_XQj3NXGMYpf_uRqu9rGe4AvOcB15E3bb2e6O4/exec")
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

def _is_keyish(url: str) -> bool:
    """Prefer URLs that obviously carry a key."""
    u = url.strip()
    # key=... in query string, or ends with /key or ...key
    if re.search(r"[?&]key(=|$)", u, re.IGNORECASE):
        return True
    path = re.sub(r"[?#].*$", "", u)  # strip query/hash
    if path.lower().endswith("/key") or path.lower().endswith("key"):
        return True
    return False

def _autopick_ref_link_from_row(row: pd.Series) -> str:
    """Search common link columns first, then scan all answers/fields."""
    rd = row.to_dict()
    urls: list[str] = []

    # 1) Likely link columns first
    for field in ["answer_link", "answerlink", "reference_link", "ref_link", "link", "url"]:
        v = rd.get(field)
        urls.extend(_extract_urls_from_text(v))

    # 2) Search any 'answer*' columns for embedded links
    for col, val in rd.items():
        if isinstance(col, str) and col.lower().startswith("answer"):
            urls.extend(_extract_urls_from_text(val))

    # 3) As a last resort, scan every string field
    if not urls:
        for val in rd.values():
            if isinstance(val, str):
                urls.extend(_extract_urls_from_text(val))

    # uniq preserve order
    seen = set()
    urls = [u for u in urls if not (u in seen or seen.add(u))]
    if not urls:
        return ""

    # prefer "keyish" urls; if multiple, take the LAST one
    keyish = [u for u in urls if _is_keyish(u)]
    if keyish:
        return keyish[-1]
    # else take the last url found
    return urls[-1]

@st.cache_data(ttl=120, show_spinner=False)
def list_drafts_student_doc_ids(limit: int = 500) -> list:
    """List up to N top-level doc IDs under drafts_v2 (student docs)."""
    _ensure_firebase_clients()
    if _DB is None:
        return []
    out = []
    try:
        for c in _DB.collection("drafts_v2").list_documents(page_size=limit):
            out.append(c.id)
            if len(out) >= limit:
                break
    except Exception:
        try:
            for d in _DB.collection("drafts_v2").limit(limit).stream():
                out.append(d.id)
        except Exception:
            return []
    return out

@st.cache_data(ttl=60, show_spinner=False)
def load_student_lessons_from_drafts_doc(student_doc_id: str, limit: int = 200) -> pd.DataFrame:
    """Read lessons from drafts_v2/{student_doc_id}/lessons."""
    _ensure_firebase_clients()
    if _DB is None or not student_doc_id:
        return pd.DataFrame()

    doc_ref = _DB.collection("drafts_v2").document(str(student_doc_id))
    try:
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
        title = _pick_first_nonempty(data, ["assignment_title", "assignment", "title", "topic", "lesson", "name"], default=d.id)
        answer_text = _pick_first_nonempty(data, ["answer_text", "text", "content", "draft", "body", "message", "answer"], default="")
        ts_raw = _pick_first_nonempty(data, ["submitted_at", "updated_at", "timestamp", "ts", "created_at"], default="")
        ts = _normalize_timestamp(ts_raw)
        file_path = _pick_first_nonempty(data, ["file_path", "storage_path", "file"], default="")
        signed_url = None
        if file_path and _BUCKET is not None:
            try:
                blob = _BUCKET.blob(file_path)
                signed_url = blob.generate_signed_url(expiration=timedelta(hours=6), method="GET")
            except Exception:
                signed_url = None
        rows.append({
            "doc_path": f"drafts_v2/{student_doc_id}/lessons/{d.id}",
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

# --- Webhook helper -----------------------------------------------------------
def _post_rows_to_sheet(rows, sheet_name: str | None = None, sheet_gid: int | None = None) -> dict:
    """POST rows to the Apps Script webhook. Supports optional tab selection."""
    url = st.secrets.get("G_SHEETS_WEBHOOK_URL", G_SHEETS_WEBHOOK_URL)
    token = st.secrets.get("G_SHEETS_WEBHOOK_TOKEN", G_SHEETS_WEBHOOK_TOKEN)
    if not url or not token or "PUT_YOUR" in url or "PUT_YOUR" in token:
        raise RuntimeError("Webhook URL/token missing. Add to st.secrets or set constants.")
    payload = {"token": token, "rows": rows}
    if sheet_name:
        payload["sheet_name"] = sheet_name
    if sheet_gid is not None:
        payload["sheet_gid"] = int(sheet_gid)
    # Apps Script endpoint must accept JSON
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


def choose_submission(effective_doc):
    """Choose a submission (lesson) to mark."""
    st.subheader("2) Pick a Submission to Mark (from drafts_v2 → lessons)")
    colA, colB, colC = st.columns([1, 1, 1])
    with colA:
        refresh = st.button("🔄 Refresh list", use_container_width=True)
    with colB:
        max_items = st.number_input("Max lessons to load", min_value=10, max_value=500, value=200, step=10)
    with colC:
        search_lessons = st.text_input("Filter by title / doc id / text snippet", value="")
    if refresh:
        st.cache_data.clear()

    df_lessons = load_student_lessons_from_drafts_doc(effective_doc, limit=int(max_items))
    if df_lessons.empty:
        st.info(f"No drafts found under drafts_v2/{effective_doc}.")
        st.stop()

    if search_lessons:
        q = search_lessons.strip().lower()

        def _row_match(r):
            return (
                (str(r.get("title", "")).lower().find(q) >= 0)
                or (str(r.get("lesson_id", "")).lower().find(q) >= 0)
                or (str(r.get("answer_text", "")).lower().find(q) >= 0)
            )

        df_view = df_lessons[df_lessons.apply(_row_match, axis=1)].copy()
    else:
        df_view = df_lessons.copy()

    if df_view.empty:
        st.info("No drafts matched your filter.")
        st.stop()

    df_preview = df_view.copy()
    df_preview["answer_preview"] = df_preview["answer_text"].fillna("").astype(str).str.slice(0, 160)
    try:
        st.data_editor(
            df_preview[["title", "lesson_id", "submitted_at", "score", "comment", "file", "answer_preview"]],
            use_container_width=True,
            column_config={"file": st.column_config.LinkColumn("File")},
            disabled=True,
            height=300,
        )
    except Exception:
        st.dataframe(
            df_preview[["title", "lesson_id", "submitted_at", "score", "comment", "file", "answer_preview"]],
            use_container_width=True,
            height=300,
        )

    ids = df_view["lesson_id"].astype(str).tolist()
    id_to_row = df_view.set_index("lesson_id").to_dict(orient="index")

    def _fmt_submission(lesson_id: str):
        r = id_to_row.get(lesson_id, {})
        return f"{r.get('title', '')} — {lesson_id} — {r.get('submitted_at', '')}"

    selected_lesson_id = st.selectbox(
        "Choose a submission to mark", ids, format_func=_fmt_submission, key="tab7_selected_submission"
    )
    chosen_row = df_view[df_view["lesson_id"] == selected_lesson_id].iloc[0]

    st.markdown("**Selected submission details:**")
    st.json(
        {
            "doc_path": chosen_row.get("doc_path"),
            "title": chosen_row.get("title"),
            "lesson_id": chosen_row.get("lesson_id"),
            "submitted_at": str(chosen_row.get("submitted_at")),
            "score": chosen_row.get("score"),
            "comment": chosen_row.get("comment"),
            "file": chosen_row.get("file"),
        }
    )
    return chosen_row


def pick_reference(ref_df):
    """Pick a reference answer from the Google Sheet."""
    st.subheader("3) Select Reference Answer (from Google Sheet)")
    available_assignments = ref_df["assignment"].dropna().astype(str).unique().tolist()
    with st.form("marking_assignment_form"):
        search_assign = st.text_input("Search reference titles...", key="tab7_search_assign")
        submitted_assign = st.form_submit_button("Filter references")
    if submitted_assign and search_assign:
        ref_filtered = [a for a in available_assignments if search_assign.lower() in a.lower()]
    else:
        ref_filtered = available_assignments
    if not ref_filtered:
        st.info("No references match your search.")
        st.stop()
    assignment = st.selectbox("Reference to use", ref_filtered, key="tab7_assign_select")

    ref_answers = []
    ref_link_value = ""
    if assignment:
        assignment_row = ref_df[ref_df["assignment"].astype(str) == assignment]
        if not assignment_row.empty:
            row = assignment_row.iloc[0]
            all_cols = assignment_row.columns.tolist()
            answer_cols = [c for c in all_cols if str(c).startswith("answer")]
            answer_cols = [c for c in answer_cols if pd.notnull(row[c]) and str(row[c]).strip() != ""]
            ref_answers = [str(row[c]) for c in answer_cols]
            ref_link_value = _autopick_ref_link_from_row(row)

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

    if ref_link_value:
        st.markdown(f"**Auto-picked reference link:** [{ref_link_value}]({ref_link_value})")
    with st.expander("Edit picked link (optional)"):
        ref_link_value = st.text_input("Reference answer link", value=ref_link_value, placeholder="https://...")

    return assignment, answers_combined_str, ref_link_value


def mark_submission(student_code, student_name, student_row, chosen_row, assignment, answers_combined_str, ref_link_value):
    """Enter marking details and build the row for export."""
    st.subheader("4) Student Work")
    student_work = st.text_area(
        "Edit before marking if needed:",
        height=180,
        key="tab7_student_work",
        value=chosen_row.get("answer_text") or "",
    )

    st.subheader("4b) Link to attach in the sheet")
    default_idx = 0
    link_source = st.selectbox(
        "Pick which link goes into the 'link' column",
        ["Reference answer link", "Submission file link", "Both (reference first)", "Custom..."],
        index=default_idx,
    )
    custom_link = ""
    if link_source == "Custom...":
        custom_link = st.text_input("Custom link", value="")
    submission_link = chosen_row.get("file") or ""
    if link_source == "Reference answer link":
        link_value = ref_link_value or submission_link
    elif link_source == "Submission file link":
        link_value = submission_link or ref_link_value
    elif link_source == "Both (reference first)":
        parts = [p for p in [ref_link_value, submission_link] if p]
        link_value = " | ".join(parts)
    else:
        link_value = custom_link.strip()

    st.subheader("5) Copy Zone (Reference + Student Work)")
    combined_text = (
        "Reference answer:\n"
        + answers_combined_str
        + "\n\nStudent answer:\n"
        + (student_work or "")
    )
    st.code(combined_text, language="markdown")
    st.download_button(
        "📋 Reference Answer (txt)", data=answers_combined_str, file_name="reference_answer.txt", mime="text/plain"
    )
    st.download_button(
        "📋 Reference + Student (txt)", data=combined_text, file_name="ref_and_student.txt", mime="text/plain"
    )

    st.subheader("5b) Your Marking")
    col_score, col_dummy = st.columns([1, 1])
    with col_score:
        score_input = st.text_input(
            "Score",
            value="",
            help="Enter the score you want to record",
        )

    score_str = ""
    if score_input.strip():
        try:
            score_str = str(float(score_input))
        except ValueError:
            score_str = score_input.strip()
            st.warning("Score is not a number; exporting as text.")

    comments_input = st.text_area("Feedback / Comments", value="", height=120)

    st.subheader("6) Build Sheet Row (for Google Sheets)")

    def _fmt_date(dt):
        if isinstance(dt, datetime):
            return dt.strftime("%Y-%m-%d")
        return str(dt) if dt else ""

    assign_source = st.selectbox(
        "Assignment value to use",
        ["Use submission title", "Use reference title (if any)", "Custom..."],
        index=0,
    )

    if assign_source == "Use submission title":
        assignment_value = (chosen_row.get("title") or chosen_row.get("lesson_id") or "").strip()
    elif assign_source == "Use reference title (if any)":
        assignment_value = (assignment or "").strip()
    else:
        assignment_value = st.text_input("Custom assignment text", value=(chosen_row.get("title") or ""))

    student_level = str(student_row.get("level", "")).strip()
    date_value = _fmt_date(chosen_row.get("submitted_at"))

    one_row = {
        "studentcode": student_code,
        "name": student_name,
        "assignment": assignment_value,
        "score": score_str,
        "comments": comments_input or "",
        "date": date_value,
        "level": student_level,
        "link": link_value,
    }
    return one_row


def export_row(one_row):
    """Preview, download, or export the built row."""
    st.write("Preview row:")
    st.dataframe(pd.DataFrame([one_row]), use_container_width=True)

    st.markdown("**Destination tab (optional):**")
    dest_mode = st.radio(
        "Where to send?",
        ["Use defaults", "Specify by gid", "Specify by name"],
        horizontal=True,
        index=0,
    )
    dest_gid = None
    dest_name = None
    if dest_mode == "Specify by gid":
        dest_gid = st.number_input(
            "sheet_gid", value=DEFAULT_TARGET_SHEET_GID if DEFAULT_TARGET_SHEET_GID else 0, step=1
        )
        if int(dest_gid) <= 0:
            dest_gid = None
    elif dest_mode == "Specify by name":
        dest_name = st.text_input("sheet_name", value=DEFAULT_TARGET_SHEET_NAME or "")

    c1, c2 = st.columns(2)
    with c1:
        row_csv = pd.DataFrame([one_row]).to_csv(index=False)
        st.download_button(
            "⬇️ Download this row (CSV)", data=row_csv, file_name="grade_row.csv", mime="text/csv"
        )
    with c2:
        if st.button("📤 Send this row to Google Sheet (Webhook)"):
            try:
                result = _post_rows_to_sheet(
                    [one_row],
                    sheet_name=dest_name if dest_name else None,
                    sheet_gid=int(dest_gid)
                    if dest_gid
                    else (DEFAULT_TARGET_SHEET_GID if DEFAULT_TARGET_SHEET_GID else None),
                )
                st.success(
                    f"Appended {result.get('appended', 1)} row ✅  → {result.get('sheetName')} (gid {result.get('sheetId')})"
                )
            except Exception as e:
                st.error(f"Failed to send: {e}")

    st.divider()

    st.subheader("7) Export Cart (build multiple rows, then export/send)")

    if "export_cart" not in st.session_state:
        st.session_state["export_cart"] = []

    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    with col1:
        if st.button("➕ Add current row to cart"):
            st.session_state["export_cart"].append(one_row)
    with col2:
        if st.button("🧹 Clear cart"):
            st.session_state["export_cart"] = []
    with col3:
        st.caption(f"{len(st.session_state['export_cart'])} row(s) in cart")
    with col4:
        if st.session_state["export_cart"]:
            if st.button("📤 Send cart to Google Sheet (Webhook)"):
                try:
                    rows_to_send = st.session_state.get("edited_cart_rows") or st.session_state["export_cart"]
                    result = _post_rows_to_sheet(
                        rows_to_send,
                        sheet_name=dest_name if dest_name else None,
                        sheet_gid=int(dest_gid)
                        if dest_gid
                        else (DEFAULT_TARGET_SHEET_GID if DEFAULT_TARGET_SHEET_GID else None),
                    )
                    st.success(
                        f"Appended {result.get('appended', len(rows_to_send))} rows ✅  → {result.get('sheetName')} (gid {result.get('sheetId')})"
                    )
                except Exception as e:
                    st.error(f"Failed to send: {e}")

    if st.session_state["export_cart"]:
        cart_df = pd.DataFrame(
            st.session_state["export_cart"],
            columns=["studentcode", "name", "assignment", "score", "comments", "date", "level", "link"],
        )
        st.write("Edit score/comments here if you like, then download or send:")
        edited_cart = st.data_editor(cart_df, use_container_width=True, num_rows="dynamic")
        st.session_state["edited_cart_rows"] = edited_cart.to_dict(orient="records")

        cart_csv = edited_cart.to_csv(index=False)
        cart_tsv = edited_cart.to_csv(index=False, sep="\t")
        st.download_button(
            "⬇️ Download cart as CSV", data=cart_csv, file_name="grades_export.csv", mime="text/csv"
        )
        with st.expander("Copy-friendly TSV (paste straight into Google Sheet)"):
            st.code(cart_tsv.strip(), language="text")
    else:
        st.info("Cart is empty — add the row above to start building a batch.")
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

# Run standalone OR import into your tabs and call with:
# with tabs[7]:
#     render_marking_tab()
if __name__ == "__main__":
    render_marking_tab()
