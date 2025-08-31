# app.py
import os
import json
import re
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

import firebase_admin
from firebase_admin import credentials, firestore

# =========================
# SHEET IDS
# =========================
STUDENTS_SHEET_ID    = "12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U"   # studentcode, name, level (and others)
REF_ANSWERS_SHEET_ID = "1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo"    # rows=assignments, cols=Answer1..N, answer_url, sheet_url, (optional) name

# =========================
# WEBHOOK (with fallbacks)
# =========================
WEBHOOK_URL = st.secrets.get(
    "G_SHEETS_WEBHOOK_URL",
    "https://script.google.com/macros/s/AKfycbzKWo9IblWZEgD_d7sku6cGzKofis_XQj3NXGMYpf_uRqu9rGe4AvOcB15E3bb2e6O4/exec"
)
WEBHOOK_TOKEN = st.secrets.get("G_SHEETS_WEBHOOK_TOKEN", "Xenomexpress7727/")

# =========================
# OPENAI (optional)
# =========================
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY"))
try:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception:
    client = None

# =========================
# Firebase Init (secrets)
# =========================
if not firebase_admin._apps:
    fb_cfg = st.secrets.get("firebase")
    if not fb_cfg:
        st.error("⚠️ Missing [firebase] in Streamlit secrets.")
        st.stop()
    cred = credentials.Certificate(dict(fb_cfg))
    firebase_admin.initialize_app(cred)

db = firestore.client()

# =========================
# Helpers
# =========================
@st.cache_data(show_spinner=False, ttl=300)
def load_sheet_csv(sheet_id: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"
    df = pd.read_csv(url)
    df.columns = df.columns.str.strip().str.lower()  # normalize headers
    return df

def filter_students(df: pd.DataFrame, query: str) -> pd.DataFrame:
    if not query:
        return df
    # case-insensitive search across all columns
    mask = df.apply(lambda col: col.astype(str).str.contains(query, case=False, na=False))
    return df[mask.any(axis=1)]

def assignment_options_from_refs(refs_df: pd.DataFrame):
    """Return list of (label, row_index). Uses 'assignment' + 'name' if present."""
    opts = []
    for idx, row in refs_df.iterrows():
        a = str(row.get("assignment", "")).strip()
        n = str(row.get("name", "")).strip()
        if a and n:   label = f"{a} — {n}"
        elif a:       label = a
        elif n:       label = n
        else:         label = f"Row {idx+1}"
        opts.append((label, idx))
    return opts

def available_answer_columns(row: pd.Series):
    """Return sorted list of existing AnswerN columns for this row (by number)."""
    pairs = []
    for col in row.index:
        if col.startswith("answer"):
            m = re.findall(r"\d+", col)
            if m:
                n = int(m[0])
                val = str(row[col]).strip()
                if val and val.lower() not in ("nan", "none"):
                    pairs.append((n, col))
    pairs.sort(key=lambda x: x[0])
    return pairs  # [(n, 'answerN'), ...]

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
    Try common field names first; then fall back to any string-like content in the doc.
    """
    preferred = ["content", "text", "answer", "body", "draft", "message"]
    for k in preferred:
        v = doc.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list):
            # join paragraphs/strings
            parts = []
            for item in v:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    # common paragraph structure
                    for key in ["text", "content", "value"]:
                        if key in item and isinstance(item[key], str):
                            parts.append(item[key])
            if parts:
                return "\n".join(parts).strip()
        if isinstance(v, dict):
            for key in ["text", "content", "value"]:
                if key in v and isinstance(v[key], str):
                    return v[key].strip()
    # fallback: join any string values in doc
    strings = []
    for k, v in doc.items():
        if isinstance(v, str) and v.strip():
            strings.append(v.strip())
    return "\n".join(strings).strip()

def get_student_submissions(student_code: str):
    """Return list of dicts with id + fields from lessons (and lessens fallback)."""
    items = []
    def pull(coll_name):
        try:
            for snap in db.collection("drafts_v2").document(student_code).collection(coll_name).stream():
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
    """Ask OpenAI for JSON: {score:int 0-100, feedback: ~40 words}."""
    if not client:
        return None, "⚠️ OpenAI key missing (set in secrets)."
    prompt = f"""
You are a German teacher. Compare the student's answer with the reference answer.
Return STRICT JSON with two keys:
- score: integer 0-100
- feedback: ~40 words of constructive feedback (no extra text)

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
        if m: text = m.group(0)
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

# =========================
# Load data
# =========================
students_df = load_sheet_csv(STUDENTS_SHEET_ID)
refs_df     = load_sheet_csv(REF_ANSWERS_SHEET_ID)

# Safety: ensure columns exist
for col in ["studentcode", "name", "level"]:
    if col not in students_df.columns:
        students_df[col] = ""
if "assignment" not in refs_df.columns:
    refs_df["assignment"] = ""

# =========================
# UI
# =========================
st.title("📘 Marking Dashboard")

# ---- Search + select student
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
studentcode = str(sel_row.get("studentcode","")).strip()
name        = str(sel_row.get("name","")).strip()
level       = str(sel_row.get("level","")).strip()

c1, c2 = st.columns(2)
with c1: st.text_input("Name (auto)",  value=name,  disabled=True)
with c2: st.text_input("Level (auto)", value=level, disabled=True)

# ---- Reference dropdown (list everything in the sheet)
assign_opts = assignment_options_from_refs(refs_df)  # list[(label, idx)]
ref_label   = st.selectbox("Reference (assignment row from sheet)", [lbl for lbl, _ in assign_opts])
assign_idx  = dict(assign_opts)[ref_label]
assign_row  = refs_df.iloc[assign_idx]

# Default: ALL answers on the row. Optionally allow single AnswerN.
mode = st.radio("Reference scope", ["All answers", "Pick a specific AnswerN"], horizontal=True)
ref_text = ""
if mode == "All answers":
    ref_text = reference_text_all_for_row(assign_row)
else:
    ans_pairs = available_answer_columns(assign_row)   # [(n, 'answerN')]
    if not ans_pairs:
        st.info("This row has no AnswerN columns filled. Showing empty reference.")
        ref_text = "No reference answers found."
    else:
        ans_label = st.selectbox("Choose AnswerN", [f"Answer{n}" for n, _ in ans_pairs])
        # map label back to column
        n = int(re.findall(r"\d+", ans_label)[0])
        answer_col = dict(ans_pairs)[n]
        ref_text = reference_text_single(assign_row, answer_col)

answer_link = link_for_row(assign_row)
st.caption(f"Reference link: {answer_link}")

# ---- Firestore submissions for the student
subs = get_student_submissions(studentcode)
if not subs:
    st.warning("No submissions in Firestore for this student (under drafts_v2/.../lessons or lessens).")
    student_text = ""
else:
    def sub_label(i, d):
        txt = extract_text_from_doc(d)
        preview = (txt[:70] + "…") if len(txt) > 70 else txt
        return f"{i+1} • {d.get('id','')} • {preview}"
    sub_labels = [sub_label(i, d) for i, d in enumerate(subs)]
    picked = st.selectbox("Pick submission to mark", sub_labels)
    student_text = extract_text_from_doc(subs[sub_labels.index(picked)])

st.markdown("### Student Submission")
st.code(student_text or "(empty)", language="markdown")

st.markdown("### Reference Answer")
st.code(ref_text or "(not found)", language="markdown")

# ---- Combined (easy to copy)
combined = f"""# Student Submission
{student_text}

# Reference Answer
{ref_text}
"""
st.text_area("Combined (copyable)", value=combined, height=200)

# ---- AI generate (override allowed)
if "ai_score" not in st.session_state:   st.session_state.ai_score = 0
if "ai_feedback" not in st.session_state: st.session_state.ai_feedback = ""
if "key_last" not in st.session_state:    st.session_state.key_last = None

combo_key = f"{studentcode}|{assign_idx}|{mode}|{picked if subs else 'none'}"
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

# ---- Save to Scores via webhook
if st.button("💾 Save", type="primary", use_container_width=True):
    if not studentcode:
        st.error("Pick a student first.")
    elif not comments.strip():
        st.error("Feedback is required.")
    else:
        assignment_value = str(assign_row.get("assignment", ref_label)).strip() or ref_label
        row = {
            "studentcode": studentcode,
            "name": name,
            "assignment": assignment_value,              # parent assignment value (e.g., "0.1")
            "score": int(score),
            "comments": comments.strip(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "level": level,
            "link": answer_link,                         # from sheet row
        }
        result = save_row_to_scores(row)
        if result.get("ok"):
            st.success("✅ Saved to Scores sheet.")
        elif result.get("why") == "validation":
            st.error("❌ Sheet blocked the write due to data validation (studentcode).")
        else:
            st.error(f"❌ Failed to save: {result}")
