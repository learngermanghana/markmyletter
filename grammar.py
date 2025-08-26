# app.py  —  Falowen dashboard (Marking + Form Intake)
# Streamlit 1.49+ / Python 3.11+
# ----------------------------------------------------

# 1) IMPORTS
import os
import re
import json
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import requests

# Firebase Admin
import firebase_admin
from firebase_admin import credentials, firestore, storage


# 2) CONFIG / CONSTANTS
st.set_page_config(page_title="Falowen Dashboard", layout="wide")

# Google Sheets sources (Marking)
STUDENTS_CSV_URL = "https://docs.google.com/spreadsheets/d/12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U/export?format=csv"
REF_ANSWERS_URL  = "https://docs.google.com/spreadsheets/d/1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo/export?format=csv"

# Grades webhook (Apps Script container-bound web app)
G_SHEETS_WEBHOOK_URL   = st.secrets.get("G_SHEETS_WEBHOOK_URL",   "")
G_SHEETS_WEBHOOK_TOKEN = st.secrets.get("G_SHEETS_WEBHOOK_TOKEN", "")
DEFAULT_TARGET_SHEET_GID  = st.secrets.get("DEFAULT_SHEET_GID", 2121051612)  # your grades tab gid
DEFAULT_TARGET_SHEET_NAME = st.secrets.get("DEFAULT_SHEET_NAME", None)

# Students master sheet (tab gid = 104087906) — used by Form Intake (Lite)
STUDENTS_GID = 104087906
STUDENTS_MASTER_CSV_URL = f"https://docs.google.com/spreadsheets/d/12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U/export?format=csv&gid={STUDENTS_GID}"

# Students webhook (Apps Script on the Students sheet)
STUDENTS_WEBHOOK_URL   = st.secrets.get("STUDENTS_WEBHOOK_URL", "")
STUDENTS_WEBHOOK_TOKEN = st.secrets.get("STUDENTS_WEBHOOK_TOKEN", "")

G_SHEETS_WEBHOOK_URL   = "https://script.google.com/macros/s/AKfycbzKWo9IblWZEgD_d7sku6cGzKofis_XQj3NXGMYpf_uRqu9rGe4AvOcB15E3bb2e6O4/exec"
G_SHEETS_WEBHOOK_TOKEN = "Xenomexpress7727/"



# Form responses CSV (published to web link to the Responses tab)
DEFAULT_FORM_RESPONSES_CSV_URL = st.secrets.get("FORM_RESPONSES_CSV_URL", "")

# Students “lite” schema — exactly the 14 you asked for:
STUDENTS_REQUIRED_HEADERS_LITE = [
    "Name","Phone","Location","Level","Paid","Balance","ContractStart","ContractEnd",
    "StudentCode","Email","Emergency Contact (Phone Number)","Status","EnrollDate","ClassName"
]


# 3) FIREBASE INIT
_DB = None
_BUCKET = None

def _get_firebase_cred_dict():
    """Return service account credentials from secrets/env/file."""
    try:
        if "FIREBASE_SERVICE_ACCOUNT" in st.secrets:
            return dict(st.secrets["FIREBASE_SERVICE_ACCOUNT"])
        if "firebase" in st.secrets:  # supports [firebase] table as well
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
    """Initialize Firestore + Storage exactly once."""
    global _DB, _BUCKET
    if _DB is not None:
        return
    cred_dict = _get_firebase_cred_dict()
    if not cred_dict:
        _DB, _BUCKET = None, None
        return
    bucket_name = st.secrets.get("FIREBASE_STORAGE_BUCKET", os.environ.get("FIREBASE_STORAGE_BUCKET"))
    if not firebase_admin._apps:
        cfg = {"storageBucket": bucket_name} if bucket_name else {}
        firebase_admin.initialize_app(credentials.Certificate(cred_dict), cfg)
    _DB = firestore.client()
    try:
        _BUCKET = storage.bucket()
    except Exception:
        _BUCKET = None


# 4) HELPERS & LOADERS
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

# ----- reference link auto-pick
_URL_RE = re.compile(r"https?://[^\s\]>)}\"'`]+", re.IGNORECASE)

def _extract_urls_from_text(text: str) -> list[str]:
    if not isinstance(text, str) or not text:
        return []
    raw = _URL_RE.findall(text)
    cleaned, seen, out = [], set(), []
    for u in raw:
        u = u.strip().rstrip(".,;:)]}>\"'")
        cleaned.append(u)
    for u in cleaned:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

def _is_keyish(url: str) -> bool:
    u = url.strip()
    if re.search(r"[?&]key(=|$)", u, re.IGNORECASE):
        return True
    path = re.sub(r"[?#].*$", "", u)
    return path.lower().endswith("/key") or path.lower().endswith("key")

def _autopick_ref_link_from_row(row: pd.Series) -> str:
    rd = row.to_dict()
    urls: list[str] = []
    for field in ["answer_link","answerlink","reference_link","ref_link","link","url"]:
        urls += _extract_urls_from_text(rd.get(field))
    for col, val in rd.items():
        if isinstance(col, str) and col.lower().startswith("answer"):
            urls += _extract_urls_from_text(val)
    if not urls:
        for val in rd.values():
            if isinstance(val, str):
                urls += _extract_urls_from_text(val)
    # unique keep order
    seen = set()
    urls = [u for u in urls if not (u in seen or seen.add(u))]
    if not urls:
        return ""
    keyish = [u for u in urls if _is_keyish(u)]
    return keyish[-1] if keyish else urls[-1]

# ----- drafts_v2 helpers for Marking
@st.cache_data(ttl=120, show_spinner=False)
def list_drafts_student_doc_ids(limit: int = 500) -> list:
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

def _find_candidate_doc_ids_from_firestore(student_code: str, student_name: str) -> dict:
    _ensure_firebase_clients()
    res = {"exact": None, "suggestions": []}
    if _DB is None:
        return res

    variants = []
    raw = str(student_code or "").strip()
    if raw:
        variants.extend([raw, raw.lower(), raw.upper(), raw.replace(" ", ""), "".join(ch for ch in raw if ch.isalnum())])
    seen = set()
    variants = [v for v in variants if not (v in seen or seen.add(v))]

    for vid in variants:
        try:
            if _DB.collection("drafts_v2").document(vid).get().exists:
                res["exact"] = vid
                return res
        except Exception:
            pass

    try_fields = []
    if student_code:
        try_fields += [("studentcode", student_code), ("student_code", student_code), ("code", student_code)]
    if student_name:
        try_fields += [("name", student_name)]
    for field, value in try_fields:
        try:
            q = _DB.collection("drafts_v2").where(field, "==", value).limit(5)
            for m in q.stream():
                res["suggestions"].append(m.id)
        except Exception:
            pass

    if not res["suggestions"]:
        all_ids = list_drafts_student_doc_ids(limit=200)
        code_n = _norm_key(student_code)
        name_n = _norm_key(student_name)
        for did in all_ids:
            if (code_n and code_n in _norm_key(did)) or (name_n and name_n in _norm_key(did)):
                res["suggestions"].append(did)
                if len(res["suggestions"]) >= 10:
                    break
    return res

@st.cache_data(ttl=60, show_spinner=False)
def load_student_lessons_from_drafts_doc(student_doc_id: str, limit: int = 200) -> pd.DataFrame:
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

# ----- Webhook helpers
def _post_rows_to_sheet(rows, sheet_name: str | None = None, sheet_gid: int | None = None) -> dict:
    """Grades/marking webhook"""
    url = st.secrets.get("G_SHEETS_WEBHOOK_URL", G_SHEETS_WEBHOOK_URL)
    token = st.secrets.get("G_SHEETS_WEBHOOK_TOKEN", G_SHEETS_WEBHOOK_TOKEN)
    if not url or not token:
        raise RuntimeError("Grades webhook URL/token missing.")
    payload = {"token": token, "rows": rows}
    if sheet_name:
        payload["sheet_name"] = sheet_name
    if sheet_gid is not None:
        payload["sheet_gid"] = int(sheet_gid)
    r = requests.post(url, json=payload, timeout=20)
    data = r.json() if r.headers.get("content-type","").startswith("application/json") else {"ok": False, "error": r.text[:200]}
    if r.status_code != 200 or not data.get("ok"):
        raise RuntimeError(f"Webhook error {r.status_code}: {data}")
    return data

def _post_rows_students_lite(rows: list[dict]) -> dict:
    """Students sheet webhook (14-column schema)"""
    url = st.secrets.get("STUDENTS_WEBHOOK_URL", STUDENTS_WEBHOOK_URL)
    token = st.secrets.get("STUDENTS_WEBHOOK_TOKEN", STUDENTS_WEBHOOK_TOKEN)
    if not url or not token:
        raise RuntimeError("Students webhook URL/token missing.")
    payload = {"token": token, "rows": rows, "sheet_gid": STUDENTS_GID}
    r = requests.post(url, json=payload, timeout=20)
    data = r.json() if r.headers.get("content-type","").startswith("application/json") else {"ok": False, "error": r.text[:200]}
    if r.status_code != 200 or not data.get("ok"):
        raise RuntimeError(f"Webhook error {r.status_code}: {data}")
    return data


# 5) UI TABS
# --------- A) MARKING TAB ---------
def render_marking_tab():
    _ensure_firebase_clients()
    st.title("📝 Marking — Reference & Student Work")

    # Load students + references
    try:
        df_students = load_marking_students(STUDENTS_CSV_URL)
    except Exception as e:
        st.error(f"Could not load students: {e}")
        return
    try:
        ref_df = load_marking_ref_answers(REF_ANSWERS_URL)
        if "assignment" not in ref_df.columns:
            st.warning("No 'assignment' column in reference answers sheet.")
            return
    except Exception as e:
        st.error(f"Could not load reference answers: {e}")
        return

    name_col = col_lookup(df_students, "name")
    code_col = col_lookup(df_students, "studentcode")
    if not name_col or not code_col:
        st.error("Missing 'name' or 'studentcode' in students sheet.")
        return

    # Student picker (persist by code)
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
        st.info("No students match your search.")
        return

    codes = students_filtered[code_col].astype(str).tolist()
    code_to_name = dict(zip(students_filtered[code_col].astype(str), students_filtered[name_col].astype(str)))
    selected_student_code = st.selectbox(
        "Select Student",
        codes,
        format_func=lambda c: f"{code_to_name.get(c,'Unknown')} ({c})",
        key="tab7_selected_code"
    )
    if not selected_student_code:
        st.warning("Select a student to continue.")
        return

    sel_rows = students_filtered[students_filtered[code_col] == selected_student_code]
    if sel_rows.empty:
        st.warning("Selected student not found.")
        return
    student_row = sel_rows.iloc[0]
    student_code = selected_student_code
    student_name = str(student_row.get(name_col, "")).strip()
    st.markdown(f"**Selected:** {student_name} ({student_code})")
    st.code(student_code)

    # Resolve drafts_v2 doc
    st.subheader("1b) Link to Firestore (drafts_v2)")
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
            value=st.session_state.get("tab7_effective_student_doc") or ""
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
            st.info("No exact doc match. Choose from suggestions or type override.")
            if suggestions:
                pick = st.selectbox("Suggestions", suggestions, key="tab7_doc_suggestion")
                if pick:
                    st.session_state["tab7_effective_student_doc"] = pick
                    st.session_state["tab7_resolved_for"] = student_code
            else:
                st.warning("No suggestions found.")
    effective_doc = st.session_state.get("tab7_effective_student_doc")
    if not effective_doc:
        with st.expander("List drafts_v2 doc IDs", expanded=False):
            ids = list_drafts_student_doc_ids(limit=200)
            st.dataframe(pd.DataFrame({"doc_id": ids}))
        st.stop()
    st.success(f"Using Firestore doc: drafts_v2/{effective_doc}")

    # Load lessons for this student
    st.subheader("2) Pick a Submission to Mark")
    colA, colB, colC = st.columns([1, 1, 1])
    with colA:
        refresh = st.button("🔄 Refresh", use_container_width=True)
    with colB:
        max_items = st.number_input("Max lessons", min_value=10, max_value=500, value=200, step=10)
    with colC:
        search_lessons = st.text_input("Filter title / id / text", value="")
    if refresh:
        st.cache_data.clear()

    df_lessons = load_student_lessons_from_drafts_doc(effective_doc, limit=int(max_items))
    if df_lessons.empty:
        st.info(f"No drafts under drafts_v2/{effective_doc}.")
        st.stop()

    if search_lessons:
        q = search_lessons.strip().lower()
        def _row_match(r):
            return ((str(r.get("title","")).lower().find(q) >= 0) or
                    (str(r.get("lesson_id","")).lower().find(q) >= 0) or
                    (str(r.get("answer_text","")).lower().find(q) >= 0))
        df_view = df_lessons[df_lessons.apply(_row_match, axis=1)].copy()
    else:
        df_view = df_lessons.copy()
    if df_view.empty:
        st.info("No drafts matched your filter.")
        st.stop()

    df_prev = df_view.copy()
    df_prev["answer_preview"] = df_prev["answer_text"].fillna("").astype(str).str.slice(0, 160)
    try:
        st.data_editor(
            df_prev[["title","lesson_id","submitted_at","score","comment","file","answer_preview"]],
            use_container_width=True,
            column_config={"file": st.column_config.LinkColumn("File")},
            disabled=True, height=300,
        )
    except Exception:
        st.dataframe(df_prev[["title","lesson_id","submitted_at","score","comment","file","answer_preview"]],
                     use_container_width=True, height=300)

    ids = df_view["lesson_id"].astype(str).tolist()
    id_to_row = df_view.set_index("lesson_id").to_dict(orient="index")
    selected_lesson_id = st.selectbox(
        "Choose submission",
        ids,
        format_func=lambda lid: f"{id_to_row.get(lid,{}).get('title','')} — {lid} — {id_to_row.get(lid,{}).get('submitted_at','')}",
        key="tab7_selected_submission"
    )
    chosen_row = df_view[df_view["lesson_id"] == selected_lesson_id].iloc[0]

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

    # Reference selection + auto link
    st.subheader("3) Reference Answer (Google Sheet)")
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
        st.stop()
    assignment = st.selectbox("Reference to use", ref_filtered, key="tab7_assign_select")

    ref_answers, ref_link_value = [], ""
    if assignment:
        assignment_row = ref_df[ref_df['assignment'].astype(str) == assignment]
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
            tabs = st.tabs([f"Answer {i+1}" for i in range(len(ref_answers))])
            for i, ans in enumerate(ref_answers):
                with tabs[i]:
                    st.write(ans)
        answers_combined_str = "\n".join([f"{i+1}. {ans}" for i, ans in enumerate(ref_answers)])
    else:
        answers_combined_str = "No answer available."
        st.info("No reference answer available for this selection.")

    if ref_link_value:
        st.markdown(f"**Auto-picked reference link:** [{ref_link_value}]({ref_link_value})")
    with st.expander("Edit picked link (optional)"):
        ref_link_value = st.text_input("Reference answer link", value=ref_link_value, placeholder="https://...")

    # Student work + marking inputs
    st.subheader("4) Student Work")
    student_work = st.text_area("Edit before marking if needed:", height=180,
                                key="tab7_student_work", value=chosen_row.get("answer_text") or "")
    st.subheader("4b) Your Marking")
    score_input = st.number_input("Score", min_value=0.0, max_value=10000.0, value=0.0, step=1.0)
    comments_input = st.text_area("Feedback / Comments", value="", height=120)

    # Link choice
    st.subheader("4c) Link for the sheet")
    link_source = st.selectbox(
        "Which link goes into 'link' column?",
        ["Reference answer link", "Submission file link", "Both (reference first)", "Custom..."],
        index=0
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

    # Copy helpers
    st.subheader("5) Copy Zone")
    combined_text = "Reference answer:\n" + answers_combined_str + "\n\nStudent answer:\n" + (student_work or "")
    st.code(combined_text, language="markdown")
    st.download_button("📋 Reference Answer (txt)", data=answers_combined_str,
                       file_name="reference_answer.txt", mime="text/plain")
    st.download_button("📋 Reference + Student (txt)", data=combined_text,
                       file_name="ref_and_student.txt", mime="text/plain")

    # Build one row for grades sheet
    st.subheader("6) Build Row → Grades Sheet")
    def _fmt_date(dt):
        if isinstance(dt, datetime): return dt.strftime("%Y-%m-%d")
        return str(dt) if dt else ""
    assign_source = st.selectbox("Assignment value to use",
                                 ["Use submission title", "Use reference title (if any)", "Custom..."], index=0)
    if assign_source == "Use submission title":
        assignment_value = (chosen_row.get("title") or chosen_row.get("lesson_id") or "").strip()
    elif assign_source == "Use reference title (if any)":
        assignment_value = (assignment or "").strip()
    else:
        assignment_value = st.text_input("Custom assignment text", value=(chosen_row.get("title") or ""))

    student_level = str(student_row.get("level", "")).strip()
    date_value    = _fmt_date(chosen_row.get("submitted_at"))
    one_row = {
        "studentcode": student_code,
        "name":        student_name,
        "assignment":  assignment_value,
        "score":       str(score_input) if score_input is not None else "",
        "comments":    comments_input or "",
        "date":        date_value,
        "level":       student_level,
        "link":        link_value,
    }
    st.write("Preview row:")
    st.dataframe(pd.DataFrame([one_row]), use_container_width=True)

    # Destination tab (optional)
    st.markdown("**Destination tab (optional):**")
    dest_mode = st.radio("Where to send?", ["Use defaults", "Specify by gid", "Specify by name"],
                         horizontal=True, index=0)
    dest_gid = None
    dest_name = None
    if dest_mode == "Specify by gid":
        dest_gid = st.number_input("sheet_gid",
                                   value=int(DEFAULT_TARGET_SHEET_GID) if DEFAULT_TARGET_SHEET_GID else 0, step=1)
        if int(dest_gid) <= 0: dest_gid = None
    elif dest_mode == "Specify by name":
        dest_name = st.text_input("sheet_name", value=(DEFAULT_TARGET_SHEET_NAME or ""))

    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇️ Download this row (CSV)",
                           data=pd.DataFrame([one_row]).to_csv(index=False),
                           file_name="grade_row.csv", mime="text/csv")
    with c2:
        if st.button("📤 Send this row to Google Sheet"):
            try:
                result = _post_rows_to_sheet(
                    [one_row],
                    sheet_name=dest_name if dest_name else None,
                    sheet_gid=int(dest_gid) if dest_gid else (int(DEFAULT_TARGET_SHEET_GID)
                                                              if DEFAULT_TARGET_SHEET_GID else None)
                )
                st.success(f"Appended {result.get('appended', 1)} row ✅  → {result.get('sheetName')} (gid {result.get('sheetId')})")
            except Exception as e:
                st.error(f"Failed to send: {e}")

    st.divider()

    # Export cart (batch)
    st.subheader("7) Export Cart")
    if "export_cart" not in st.session_state:
        st.session_state["export_cart"] = []
    col1, col2, col3, col4 = st.columns([1,1,1,1])
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
            if st.button("📤 Send cart to Google Sheet"):
                try:
                    edited = st.session_state.get("edited_cart_rows") or st.session_state["export_cart"]
                    result = _post_rows_to_sheet(
                        edited,
                        sheet_name=dest_name if dest_name else None,
                        sheet_gid=int(dest_gid) if dest_gid else (int(DEFAULT_TARGET_SHEET_GID)
                                                                  if DEFAULT_TARGET_SHEET_GID else None)
                    )
                    st.success(f"Appended {result.get('appended', len(edited))} rows ✅  → {result.get('sheetName')} (gid {result.get('sheetId')})")
                except Exception as e:
                    st.error(f"Failed to send: {e}")

    if st.session_state["export_cart"]:
        cart_df = pd.DataFrame(st.session_state["export_cart"],
                               columns=["studentcode","name","assignment","score","comments","date","level","link"])
        st.write("Edit cart below (optional) then download/send:")
        edited_cart = st.data_editor(cart_df, use_container_width=True, num_rows="dynamic")
        st.session_state["edited_cart_rows"] = edited_cart.to_dict(orient="records")
        st.download_button("⬇️ Download cart (CSV)", data=edited_cart.to_csv(index=False),
                           file_name="grades_export.csv", mime="text/csv")
        with st.expander("Copy-friendly TSV"):
            st.code(edited_cart.to_csv(index=False, sep="\t").strip(), language="text")
    else:
        st.info("Cart is empty — add the row above to build a batch.")


# --------- B) FORM INTAKE (LITE) TAB ---------
@st.cache_data(show_spinner=False, ttl=180)
def _load_master_students(url: str) -> pd.DataFrame:
    df = pd.read_csv(url, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    return df

@st.cache_data(show_spinner=False, ttl=120)
def _load_form_responses_csv(url: str) -> pd.DataFrame:
    df = pd.read_csv(url, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    return df

def _guess(df: pd.DataFrame, candidates: list[str]):
    norm = {c.lower().replace(" ", "").replace("_",""): c for c in df.columns}
    for token in candidates:
        key = token.lower().replace(" ", "").replace("_","")
        if key in norm: return norm[key]
    for c in df.columns:
        low = c.lower()
        for token in candidates:
            if token.lower() in low:
                return c
    return None

def _map_form_to_students_schema_lite(form_df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=form_df.index)

    name_col  = _guess(form_df, ["name","full name","student name"])
    phone_col = _guess(form_df, ["phone","phone number","contact"])
    loc_col   = _guess(form_df, ["location","city","area"])
    level_col = _guess(form_df, ["level","class level"])
    code_col  = _guess(form_df, ["studentcode","student code","code"])
    email_col = _guess(form_df, ["email","e-mail"])
    emer_col  = _guess(form_df, ["emergency contact (phone number)","emergency","guardian phone"])
    start_col = _guess(form_df, ["contractstart","start date","start"])
    end_col   = _guess(form_df, ["contractend","end date","end"])
    enroll_col= _guess(form_df, ["enrolldate","enrolment date","enrollment date","date"])
    class_col = _guess(form_df, ["classname","class name","group"])

    out["Name"]  = form_df[name_col]  if name_col  else ""
    out["Phone"] = form_df[phone_col] if phone_col else ""
    out["Location"] = form_df[loc_col] if loc_col else ""
    out["Level"]    = form_df[level_col] if level_col else ""
    out["Paid"]     = ""
    out["Balance"]  = ""
    out["ContractStart"] = form_df[start_col] if start_col else ""
    out["ContractEnd"]   = form_df[end_col]   if end_col   else ""
    out["StudentCode"]   = form_df[code_col]  if code_col  else ""
    out["Email"]         = form_df[email_col] if email_col else ""
    out["Emergency Contact (Phone Number)"] = form_df[emer_col] if emer_col else ""
    out["Status"] = ""
    out["EnrollDate"] = form_df[enroll_col] if enroll_col else datetime.now().strftime("%Y-%m-%d")
    out["ClassName"] = form_df[class_col] if class_col else ""

    out = out.reindex(columns=STUDENTS_REQUIRED_HEADERS_LITE)
    for c in out.columns:
        out[c] = out[c].astype(str).str.strip()
    return out

def _dedupe_vs_master(master_df: pd.DataFrame, incoming_df: pd.DataFrame) -> pd.DataFrame:
    m = master_df.copy()
    m.columns = [str(c).strip() for c in m.columns]
    m_code  = m.get("StudentCode", pd.Series([""]*len(m))).astype(str).str.strip().str.lower()
    m_name  = m.get("Name", pd.Series([""]*len(m))).astype(str).str.strip().str.lower()
    m_phone = m.get("Phone", pd.Series([""]*len(m))).astype(str).str.strip()
    master_code_set = set(m_code[m_code!=""].tolist())
    master_np_set   = set(zip(m_name, m_phone))

    inc = incoming_df.copy()
    inc_code  = inc.get("StudentCode", pd.Series([""]*len(inc))).astype(str).str.strip().str.lower()
    inc_name  = inc.get("Name", pd.Series([""]*len(inc))).astype(str).str.strip().str.lower()
    inc_phone = inc.get("Phone", pd.Series([""]*len(inc))).astype(str).str.strip()

    keep = []
    for i in range(len(inc)):
        c = inc_code.iat[i]; n = inc_name.iat[i]; p = inc_phone.iat[i]
        if c and c in master_code_set:
            keep.append(False)
        elif (n, p) in master_np_set:
            keep.append(False)
        else:
            keep.append(True)
    return inc[keep].reset_index(drop=True)

def render_form_intake_tab_lite():
    st.title("🧾 Form Intake → Students (Lite)")

    # 1) Master
    try:
        master_df = _load_master_students(STUDENTS_MASTER_CSV_URL)
    except Exception as e:
        st.error(f"Could not load Students master sheet: {e}")
        return

    # 2) Form responses CSV
    st.subheader("1) Google Form Responses")
    form_csv_url = st.text_input(
        "Paste the published CSV link (Form → Responses linked sheet → Publish to web → CSV)",
        value=DEFAULT_FORM_RESPONSES_CSV_URL,
        placeholder="https://docs.google.com/spreadsheets/d/.../export?format=csv&gid=..."
    )
    if not form_csv_url:
        st.info("Paste your published CSV link to continue.")
        return
    try:
        raw_form_df = _load_form_responses_csv(form_csv_url)
    except Exception as e:
        st.error(f"Could not load Form responses: {e}")
        return
    with st.expander("Raw responses (preview)"):
        st.dataframe(raw_form_df.head(20), use_container_width=True)

    # 3) Map to 14-column schema
    st.subheader("2) Map to Students schema")
    mapped_df = _map_form_to_students_schema_lite(raw_form_df)
    st.dataframe(mapped_df.head(20), use_container_width=True)

    # 4) Pending (new vs master)
    st.subheader("3) Pending (new vs master)")
    pending_df = _dedupe_vs_master(master_df, mapped_df)
    if pending_df.empty:
        st.success("No new students detected 🎉")
        return
    st.caption(f"Detected **{len(pending_df)}** new row(s). Edit and confirm below:")

    editable = st.data_editor(
        pending_df,
        use_container_width=True,
        num_rows="dynamic",
        column_order=STUDENTS_REQUIRED_HEADERS_LITE
    )

    # 5) Select rows and export
    st.subheader("4) Select rows to append")
    idx_options = list(range(len(editable)))
    to_add = st.multiselect(
        "Pick rows",
        idx_options,
        default=idx_options,
        format_func=lambda i: f"{editable.loc[i,'Name']} ({editable.loc[i,'Phone']})"
    )
    confirm_rows = editable.iloc[to_add].fillna("").astype(str).to_dict(orient="records") if to_add else []

    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button(
            "⬇️ CSV",
            data=pd.DataFrame(confirm_rows, columns=STUDENTS_REQUIRED_HEADERS_LITE).to_csv(index=False),
            file_name="students_pending_lite.csv", mime="text/csv"
        )
    with c2:
        st.download_button(
            "⬇️ TSV",
            data=pd.DataFrame(confirm_rows, columns=STUDENTS_REQUIRED_HEADERS_LITE).to_csv(index=False, sep="\t"),
            file_name="students_pending_lite.tsv",
            mime="text/tab-separated-values"
        )
    with c3:
        if st.button("📤 Append to Students sheet"):
            if not confirm_rows:
                st.warning("Nothing selected.")
            else:
                try:
                    result = _post_rows_students_lite(confirm_rows)
                    st.success(f"Appended {result.get('appended', len(confirm_rows))} row(s) ✅ → {result.get('sheetName')} (gid {result.get('sheetId')})")
                except Exception as e:
                    st.error(f"Failed to send: {e}")


# 6) RADIO SELECTOR (main)
def main():
    st.sidebar.title("Falowen")
    choice = st.sidebar.radio("Go to", ["Marking", "Form Intake (Lite)"], index=0)
    if choice == "Marking":
        render_marking_tab()
    else:
        render_form_intake_tab_lite()

if __name__ == "__main__":
    main()

