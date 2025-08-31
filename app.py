# app.py
import os
import re
import time
import json
import io
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

import firebase_admin
from firebase_admin import credentials, firestore

st.set_page_config(page_title="Marking Dashboard", layout="wide")

# =========================================================
# SHEET IDS
# =========================================================
STUDENTS_SHEET_ID    = "12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U"
REF_ANSWERS_SHEET_ID = "1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo"
REF_TAB_NAME = "Sheet1"  # exact tab name holding the assignment list
REF_TAB_GID = st.secrets.get("REF_TAB_GID", None)  # e.g. "123456789" (recommended)

# =========================================================
# APPS SCRIPT WEBHOOK (fallbacks)
# =========================================================
WEBHOOK_URL = st.secrets.get(
    "G_SHEETS_WEBHOOK_URL",
    "https://script.google.com/macros/s/AKfycbzKWo9IblWZEgD_d7sku6cGzKofis_XQj3NXGMYpf_uRqu9rGe4AvOcB15E3bb2e6O4/exec"
)
WEBHOOK_TOKEN = st.secrets.get("G_SHEETS_WEBHOOK_TOKEN", "Xenomexpress7727/")

# =========================================================
# OpenAI (optional)
# =========================================================
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY"))
try:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception:
    client = None

# =========================================================
# Firebase init (from secrets)
# =========================================================
if not firebase_admin._apps:
    fb = st.secrets.get("firebase")
    if not fb:
        st.error("⚠️ Missing [firebase] in Streamlit secrets.")
        st.stop()
    cred = credentials.Certificate(dict(fb))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# =========================================================
# Helpers
# =========================================================
@st.cache_data(show_spinner=False, ttl=300)
def load_sheet_csv(sheet_id: str, sheet: str | None = None, gid: str | None = None, cache_bust: bool = False) -> pd.DataFrame:
    """
    Load a Google Sheet as CSV (no auth).

    Prefer `gid` with export endpoint (no truncation).
    Otherwise use gviz with an explicit high LIMIT.
    Set `cache_bust=True` to add a timestamp param.
    """
    if gid:
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    else:
        tq = "select * limit 100000"
        if sheet:
            url = (
                f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"
                f"?tqx=out:csv&sheet={requests.utils.quote(sheet)}&tq={requests.utils.quote(tq)}"
            )
        else:
            url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&tq={requests.utils.quote(tq)}"
    if cache_bust:
        url += f"&_cb={int(time.time())}"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        csv_io = io.StringIO(response.content.decode("utf-8-sig"))
        df = pd.read_csv(csv_io, dtype=str)
    except Exception as e:
        st.error(f"Failed to load sheet CSV: {e}")
        raise
    df.columns = df.columns.str.strip().str.lower()
    return df


def filter_students(df: pd.DataFrame, q: str) -> pd.DataFrame:
    """Case-insensitive contains across all columns."""
    if not q:
        return df
    mask = df.apply(lambda c: c.astype(str).str.contains(q, case=False, na=False))
    return df[mask.any(axis=1)]


def col_lookup(df: pd.DataFrame, name: str) -> str:
    """
    Fuzzy match a column: 'Assignment' == 'assignment' == 'assign_ment' etc.
    Returns the matched column name, or the first column as a fallback.
    """
    key = name.lower().strip().replace(" ", "").replace("_", "")
    for c in df.columns:
        norm = str(c).lower().strip().replace(" ", "").replace("_", "")
        if norm == key:
            return c
    return df.columns[0]


def _normalize_assignment_title(s: str) -> str:
    """Clean quotes/newlines/extra spaces in assignment titles."""
    if s is None:
        return ""
    s = str(s).replace("\r", " ").replace("\n", " ").strip()
    s = s.strip('\'"“”‘’` ')
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def build_assignment_options(refs_df: pd.DataFrame):
    """
    Build options from the 'assignment' column (sheet order, cleaned, de-duped).
    Returns (options, indices, assignment_col)
    """
    assignment_col = col_lookup(refs_df, "assignment")
    ser = refs_df[assignment_col].fillna("").astype(str)
    cleaned = ser.map(_normalize_assignment_title)
    mask = cleaned.astype(str).str.strip().ne("").values
    cleaned = cleaned[mask]
    idxs = ser.index[mask].tolist()

    seen = set()
    options, indices = [], []
    for lbl, i in zip(cleaned.tolist(), idxs):
        if lbl not in seen:
            seen.add(lbl)
            options.append(lbl)
            indices.append(i)
    return options, indices, assignment_col


def available_answer_columns(row: pd.Series):
    """Return sorted list of existing AnswerN columns for this row (by N)."""
    pairs = []
    for col in row.index:
        if col.lower().startswith("answer"):
            m = re.findall(r"\d+", col)
            if m:
                n = int(m[0])
                val = str(row[col]).strip()
                if val and val.lower() not in ("nan", "none"):
                    pairs.append((n, col))
    pairs.sort(key=lambda x: x[0])
    return pairs


def reference_text_all_for_row(row: pd.Series) -> str:
    """Concatenate all AnswerN cells for a row into a single block."""
    pairs = available_answer_columns(row)
    if not pairs:
        return "No reference answers found."
    return "\n\n".join([f"Answer{n}: {str(row[col]).strip()}" for n, col in pairs])


def reference_text_single(row: pd.Series, answer_col: str) -> str:
    """Return a single AnswerN text."""
    return str(row.get(answer_col, "")).strip() or "No reference found."


def link_for_row(row: pd.Series) -> str:
    """Prefer answer_url, then sheet_url; else link to the whole reference sheet."""
    for col in ["answer_url", "sheet_url"]:
        if col in row.index:
            v = str(row[col]).strip()
            if v and v.lower() not in ("nan", "none"):
                return v
    return f"https://docs.google.com/spreadsheets/d/{REF_ANSWERS_SHEET_ID}/edit"


def extract_text_from_doc(doc: dict) -> str:
    """
    Try common fields; else join any string-like values from the document.
    Handles nested lists/dicts with 'text' or 'content'.
    """
    preferred = ["content", "text", "answer", "body", "draft", "message"]
    for k in preferred:
        v = doc.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list):
            parts = []
            for item in v:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    for kk in ["text", "content", "value"]:
                        if kk in item and isinstance(item[kk], str):
                            parts.append(item[kk])
            if parts:
                return "\n".join(parts).strip()
        if isinstance(v, dict):
            for kk in ["text", "content", "value"]:
                vv = v.get(kk)
                if isinstance(vv, str) and vv.strip():
                    return vv.strip()
    strings = []
    for _, v in doc.items():
        if isinstance(v, str) and v.strip():
            strings.append(v.strip())
    return "\n".join(strings).strip()


def get_student_submissions(student_code: str):
    """Fetch docs under drafts_v2/{code}/lessons (or lessens)."""
    items = []
    def pull(coll):
        try:
            for snap in db.collection("drafts_v2").document(student_code).collection(coll).stream():
                d = snap.to_dict() or {}
                d["id"] = snap.id
                items.append(d)
        except Exception:
            pass
    pull("lessons")
    if not items:
        pull("lessens")
    return items


def ai_mark(student_answer: str, ref_text: str):
    """
    Return (score, feedback) via OpenAI, or (None, reason) if unavailable.
    Expects a global `client` (OpenAI).
    """
    if not client:
        return None, "⚠️ OpenAI key missing (set OPENAI_API_KEY in secrets)."
    prompt = f"""
You are a German teacher. Compare the student's answer with the reference answer.
Return STRICT JSON with:
- score: integer 0-100
- feedback: ~40 words, constructive.

Student answer:
{student_answer}

Reference answer:
{ref_text}

Return only JSON.
"""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=200,
        )
        text = resp.choices[0].message.content.strip()
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            text = m.group(0)
        data = json.loads(text)
        score = int(data.get("score", 0))
        feedback = str(data.get("feedback", "")).strip()
        return max(0, min(100, score)), (feedback or "(no feedback)")
    except Exception as e:
        return None, f"(AI error: {e})"


def save_row_to_scores(row: dict):
    """POST a single row to your Apps Script webhook."""
    payload = {"token": WEBHOOK_TOKEN, "row": row}
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=15)
        if r.headers.get("content-type", "").startswith("application/json"):
            return r.json()
        raw = r.text
        if "violates the data validation rules" in raw:
            return {"ok": False, "why": "validation", "raw": raw}
        return {"ok": False, "raw": raw}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# =========================================================
# UI – top controls
# =========================================================
st.title("📘 Marking Dashboard")

c_top1, c_top2 = st.columns([1,1])
with c_top1:
    if st.button("🔄 Refresh sheets (clear cache)"):
        st.cache_data.clear()
        st.rerun()
with c_top2:
    cache_bust = st.checkbox("Force fresh pull this run", value=False, help="Adds a timestamp to the sheet URL")

# =========================================================
# Load data (Students + Reference from 'assignment' tab)
# =========================================================
students_df = load_sheet_csv(STUDENTS_SHEET_ID, cache_bust=cache_bust)

refs_df = load_sheet_csv(
    REF_ANSWERS_SHEET_ID,
    sheet=REF_TAB_NAME,
    gid=REF_TAB_GID,          # if provided, uses export endpoint (no truncation)
    cache_bust=cache_bust
)
st.caption(f"Loaded reference tab: **{REF_TAB_NAME}** — {len(refs_df)} rows")

# Ensure expected student columns exist / rename common variants
if "studentcode" not in students_df.columns and "student_code" in students_df.columns:
    students_df = students_df.rename(columns={"student_code": "studentcode"})
for col in ["studentcode", "name", "level"]:
    if col not in students_df.columns:
        students_df[col] = ""

# =========================================================
# Student picker with search
# =========================================================
search_q = st.text_input("Search student (code, name, phone, etc.)")
filtered_students = filter_students(students_df, search_q)
if filtered_students.empty:
    st.warning("No students match your search.")
    st.stop()

student_labels = [
    f"{row.get('studentcode','')} — {row.get('name','')} ({row.get('level','')})"
    for _, row in filtered_students.iterrows()
]
pick_label = st.selectbox("Pick Student", student_labels)
sel_row = filtered_students.iloc[student_labels.index(pick_label)]
studentcode   = str(sel_row.get("studentcode","")).strip()
student_name  = str(sel_row.get("name","")).strip()
student_level = str(sel_row.get("level","")).strip()

c1, c2 = st.columns(2)
with c1: st.text_input("Name (auto)",  value=student_name,  disabled=True)
with c2: st.text_input("Level (auto)", value=student_level, disabled=True)

# =========================================================
# Reference: ALL assignments from 'assignment' column
# =========================================================
st.subheader("Reference")
ref_options, ref_indices, ASSIGNMENT_COL = build_assignment_options(refs_df)
st.caption(f"{len(ref_options)} assignments found")

search_assign = st.text_input("Search assignment title…", value="")
pairs = [(o, i) for o, i in zip(ref_options, ref_indices)
         if search_assign.lower() in o.lower()] if search_assign else list(zip(ref_options, ref_indices))

if not pairs:
    st.info("No assignments match your search.")
    st.stop()

show_options = [o for o, _ in pairs]
show_indices = [i for _, i in pairs]

assignment_choice = st.selectbox("Select Assignment", show_options)
assign_idx = show_indices[show_options.index(assignment_choice)]
assign_row = refs_df.loc[assign_idx]

mode = st.radio("Reference scope", ["All answers", "Pick a specific AnswerN"], horizontal=True)
if mode == "All answers":
    ref_text = reference_text_all_for_row(assign_row)
else:
    ans_pairs = available_answer_columns(assign_row)
    if not ans_pairs:
        st.info("This row has no AnswerN columns filled. Showing empty reference.")
        ref_text = "No reference answers found."
    else:
        ans_label = st.selectbox("Choose AnswerN", [f"Answer{n}" for n, _ in ans_pairs])
        n = int(re.findall(r"\d+", ans_label)[0])
        answer_col = dict(ans_pairs)[n]
        ref_text = reference_text_single(assign_row, answer_col)

answer_link = link_for_row(assign_row)
st.caption(f"Reference link: {answer_link}")

# =========================================================
# Firestore submissions for the student (list all; you pick one)
# =========================================================
st.subheader("Student Submissions (Firestore)")
subs = get_student_submissions(studentcode)
if not subs:
    st.warning("No submissions found under drafts_v2/.../lessons (or lessens) for this student.")
    picked_label = "none"
    student_text = ""
else:
    def sub_label(i, d):
        txt = extract_text_from_doc(d)
        preview = (txt[:70] + "…") if len(txt) > 70 else txt
        return f"{i+1} • {d.get('id','(no-id)')} • {preview}"
    sub_labels = [sub_label(i, d) for i, d in enumerate(subs)]
    picked_label = st.selectbox("Pick submission to preview/mark", sub_labels)
    student_text = extract_text_from_doc(subs[sub_labels.index(picked_label)])

st.markdown("### Student Submission")
st.code(student_text or "(empty)", language="markdown")

st.markdown("### Reference Answer")
st.code(ref_text or "(not found)", language="markdown")

# =========================================================
# Combined copy box
# =========================================================
combined = f"""# Student Submission
{student_text}

# Reference Answer
{ref_text}
"""
st.text_area("Combined (copyable)", value=combined, height=200)

# =========================================================
# AI generate (override allowed)
# =========================================================
if "ai_score" not in st.session_state:    st.session_state.ai_score = 0
if "ai_feedback" not in st.session_state: st.session_state.ai_feedback = ""
if "key_last" not in st.session_state:    st.session_state.key_last = None

combo_key = f"{studentcode}|{assign_idx}|{mode}|{picked_label}"
should_gen = (
    client is not None
    and student_text.strip()
    and ref_text.strip()
    and ref_text.strip() != "No reference answers found."
    and st.session_state.key_last != combo_key
)
if should_gen:
    ai_s, ai_fb = ai_mark(student_text, ref_text)
    if ai_s is not None:
        st.session_state.ai_score = ai_s
    st.session_state.ai_feedback = ai_fb
    st.session_state.key_last = combo_key

colA, colB = st.columns([1,1])
with colA:
    if st.button("🔁 Regenerate AI"):
        ai_s, ai_fb = ai_mark(student_text, ref_text)
        if ai_s is not None:
            st.session_state.ai_score = ai_s
        st.session_state.ai_feedback = ai_fb

score    = st.number_input("Score", min_value=0, max_value=100, step=1, value=st.session_state.ai_score)
comments = st.text_area("Feedback (you can edit)", value=st.session_state.ai_feedback, height=140)

# =========================================================
# Save to Scores via Apps Script webhook
# =========================================================
if st.button("💾 Save", type="primary", use_container_width=True):
    if not studentcode:
        st.error("Pick a student first.")
    elif not comments.strip():
        st.error("Feedback is required.")
    else:
        assignment_value = str(assign_row.get(ASSIGNMENT_COL, assignment_choice)).strip() or assignment_choice
        row = {
            "studentcode": studentcode,
            "name": student_name,
            "assignment": assignment_value,
            "score": int(score),
            "comments": comments.strip(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "level": student_level,
            "link": answer_link,
        }
        result = save_row_to_scores(row)
        if result.get("ok"):
            st.success("✅ Saved to Scores sheet.")
        elif result.get("why") == "validation":
            st.error("❌ Sheet blocked the write due to data validation (studentcode).")
        else:
            st.error(f"❌ Failed to save: {result}")
