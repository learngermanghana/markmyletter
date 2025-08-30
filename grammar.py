import os
import re
import json
from datetime import datetime, timedelta
import streamlit as st
import pandas as pd
import requests

# webhook to Google Sheets
# Firebase Admin
import firebase_admin
from firebase_admin import credentials, firestore, storage

st.set_page_config(page_title="Falowen Marking Tab", layout="wide")
st.title("Falowen Marking Tab")

if st.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# =============================================================================
# CONFIG: Google Sheets sources (edit to your sheet URLs)
# =============================================================================
STUDENTS_CSV_URL = "https://docs.google.com/spreadsheets/d/12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U/export?format=csv"
REF_ANSWERS_URL = "https://docs.google.com/spreadsheets/d/1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo/export?format=csv"

# Optional sheet holding previously recorded scores
SCORES_CSV_URL = st.secrets.get("SCORES_CSV_URL", "scores_backup.csv")

# === Apps Script Webhook ===
G_SHEETS_WEBHOOK_URL = st.secrets.get("G_SHEETS_WEBHOOK_URL", "https://script.google.com/macros/s/AKfycbzKWo9IblWZEgD_d7sku6cGzKofis_XQj3NXGMYpf_uRqu9rGe4AvOcB15E3bb2e6O4/exec")
G_SHEETS_WEBHOOK_TOKEN = st.secrets.get("G_SHEETS_WEBHOOK_TOKEN", "Xenomexpress7727/")

# Optional default target tab
DEFAULT_TARGET_SHEET_GID = 2121051612      # your grades tab gid
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

@st.cache_data(ttl=300, show_spinner=False)
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

def copy_to_clipboard(row):
    """Function to copy data to clipboard."""
    import pyperclip
    pyperclip.copy(str(row))
    st.success("Row copied to clipboard!")

def export_row(one_row):
    """Preview, download, or export the built row."""
    st.write("Preview row:")
    st.dataframe(pd.DataFrame([one_row]), use_container_width=True)

    # Add the copy to clipboard functionality here.
    st.button("Copy to Clipboard", on_click=copy_to_clipboard, args=(one_row,))

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
                    sheet_gid=int(dest_gid) if dest_gid else DEFAULT_TARGET_SHEET_GID,
                )
            except Exception as e:
                st.error(f"Failed to send row: {e}")
            else:
                st.success("Row sent to Google Sheet!")
                st.write(result)
                st.cache_data.clear()
                st.experimental_rerun()
