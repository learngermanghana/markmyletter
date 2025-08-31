# app.py
import os
import re
import json
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

import firebase_admin
from firebase_admin import credentials, firestore

st.set_page_config(page_title="Marking Dashboard", layout="wide")

# =========================================================
# SHEET IDS (you provided)
# =========================================================
STUDENTS_SHEET_ID    = "12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U"
REF_ANSWERS_SHEET_ID = "1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo"
REF_TAB_NAME = "assignment"   # <— your tab name that holds Assignment 0.1, 0.2, …

# =========================================================
# APPS SCRIPT WEBHOOK (fallbacks included)
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
def load_sheet_csv(sheet_id: str, sheet: str | None = None) -> pd.DataFrame:
    """
    Load a Google Sheet as CSV (no auth).
    If `sheet` is provided, reads that worksheet/tab by name.
    """
    if sheet:
        url = (
            f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"
            f"?tqx=out:csv&sheet={requests.utils.quote(sheet)}"
        )
    else:
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"
    df = pd.read_csv(url)
    df.columns = df.columns.str.strip().str.lower()
    return df

def filter_students(df: pd.DataFrame, q: str) -> pd.DataFrame:
    if not q:
        return df
    mask = df.apply(lambda c: c.astype(str).str.contains(q, case=False, na=False))
    return df[mask.any(axis=1)]

# Reference: list ALL assignments from the 'assignment' column
st.subheader("Reference")

ref_options, ref_indices, ASSIGNMENT_COL = build_assignment_options(refs_df)
if not ref_options:
    st.warning("No assignments found in the reference sheet.")
    st.stop()

# (Optional) quick search bar like in your working snippet
search_assign = st.text_input("Search assignment title...")
show_options = [o for o in ref_options if search_assign.lower() in o.lower()] if search_assign else ref_options

assignment_choice = st.selectbox("Select Assignment", show_options)
assign_idx = ref_indices[ref_options.index(assignment_choice)]  # map back to the original row index
assign_row = refs_df.loc[assign_idx]


def ref_options_all_rows(refs_df: pd.DataFrame):
    """
    Build options from the FIRST column only, no filtering.
    Option label includes 1-based sheet row number: e.g., 'r2 • Assignment 0.1'
    """
    first_col = refs_df.columns[0]
    labels = refs_df[first_col].astype(str).fillna("").str.strip()
    options = [f"r{idx+2} • {lbl if lbl else '(blank)'}" for idx, lbl in enumerate(labels)]
    indices = list(range(len(labels)))
    return options, indices, first_col

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
    pairs = available_answer_columns(row)
    if not pairs:
        return "No reference answers found."
    return "\n\n".join([f"Answer{n}: {str(row[col]).strip()}" for n, col in pairs])

def reference_text_single(row: pd.Series, answer_col: str) -> str:
    return str(row.get(answer_col, "")).strip() or "No reference found."

def link_for_row(row: pd.Series) -> str:
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
    """Return (score, feedback) via OpenAI, or (None, reason) if unavailable."""
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
    payload = {"token": WEBHOOK_TOKEN, "row": row}
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=15)
        if r.headers.get("content-type","").startswith("application/json"):
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
if st.button("🔄 Refresh sheets (clear cache)"):
    st.cache_data.clear()
    st.rerun()

# =========================================================
# Load data (Students + Reference from 'assignment' tab)
# =========================================================
students_df = load_sheet_csv(STUDENTS_SHEET_ID)
refs_df     = load_sheet_csv(REF_ANSWERS_SHEET_ID, sheet=REF_TAB_NAME)
st.caption(f"Loaded reference tab: **{REF_TAB_NAME}**")

# Ensure expected student columns exist
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
# Reference: show ALL rows from FIRST column of 'assignment' tab
# =========================================================
st.subheader("Reference")
ref_options, ref_indices, ASSIGNMENT_COL = ref_options_all_rows(refs_df)
st.caption(f"{len(ref_options)} rows loaded from **{REF_TAB_NAME}**")
ref_choice = st.selectbox("Pick assignment (full list)", ref_options)
assign_idx = ref_indices[ref_options.index(ref_choice)]
assign_row = refs_df.iloc[assign_idx]

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
        assignment_value = str(assign_row.get(ASSIGNMENT_COL, ref_choice)).strip() or ref_choice
        row = {
            "studentcode": studentcode,
            "name": student_name,
            "assignment": assignment_value,   # exact text from first column of 'assignment' tab
            "score": int(score),
            "comments": comments.strip(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "level": student_level,
            "link": answer_link,              # auto-insert ref link
        }
        result = save_row_to_scores(row)
        if result.get("ok"):
            st.success("✅ Saved to Scores sheet.")
        elif result.get("why") == "validation":
            st.error("❌ Sheet blocked the write due to data validation (studentcode).")
        else:
            st.error(f"❌ Failed to save: {result}")
