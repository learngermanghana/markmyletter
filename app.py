import os
import json
import re
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

import firebase_admin
from firebase_admin import credentials, firestore

# ================
# CONFIG (Sheets)
# ================
SCORES_SHEET_ID = "1BRb8p3Rq0VpFCLSwL4eS9tSgXBo9hSWzfW_J_7W36NQ"      # has studentcode, name, level
REF_ANSWERS_SHEET_ID = "1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo"  # has answer1..answer50 (+ links)

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

def get_student_submissions(student_code: str):
    """Return list of dicts from drafts_v2/{student_code}/lessons"""
    try:
        ref = db.collection("drafts_v2").document(student_code).collection("lessons")
        return [doc.to_dict() for doc in ref.stream()]
    except Exception as e:
        st.error(f"Failed to load Firestore submissions: {e}")
        return []

def join_all_reference_answers(refs_df: pd.DataFrame) -> str:
    ans_cols = [c for c in refs_df.columns if c.startswith("answer")]
    parts = []
    for col in ans_cols:
        vals = refs_df[col].dropna()
        if not vals.empty:
            parts.append(f"{col.title()}: {vals.iloc[0]}")
    return "\n\n".join(parts) if parts else "No reference answers found."

def get_reference_for_assignment(refs_df: pd.DataFrame, assignment_num: int) -> str:
    if assignment_num == 0:
        return join_all_reference_answers(refs_df)
    col = f"answer{assignment_num}"
    if col in refs_df.columns:
        vals = refs_df[col].dropna()
        return str(vals.iloc[0]) if not vals.empty else "No reference found."
    return "No reference found."

def get_reference_link(refs_df: pd.DataFrame) -> str:
    """Use answer_url first, else sheet_url, else generic sheet link."""
    for col in ["answer_url", "sheet_url"]:
        if col in refs_df.columns:
            vals = refs_df[col].dropna()
            if not vals.empty:
                return str(vals.iloc[0])
    return f"https://docs.google.com/spreadsheets/d/{REF_ANSWERS_SHEET_ID}/edit"

def ai_mark(student_answer: str, ref_text: str):
    """
    Ask OpenAI for a JSON with {score:int, feedback:str (≈40 words)}.
    """
    if not client:
        return None, "⚠️ OpenAI key missing (set in secrets)."

    prompt = f"""
You are a German teacher. Compare the student's answer with the reference answer.
Return STRICT JSON with two keys:
- score: integer 0-100
- feedback: exactly ~40 words of constructive feedback (no extra text)

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
        json_match = re.search(r"\{.*\}", text, flags=re.S)
        if json_match:
            text = json_match.group(0)
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
        return r.json() if r.headers.get("content-type","").startswith("application/json") else {"ok": False, "raw": r.text}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# =========================
# Load DataFrames
# =========================
scores_df = load_sheet_csv(SCORES_SHEET_ID)  # source for studentcode + name + level
refs_df   = load_sheet_csv(REF_ANSWERS_SHEET_ID)

# Ensure needed columns exist (scores sheet)
if "studentcode" not in scores_df.columns:
    st.error("Scores sheet must have a 'studentcode' column.")
    st.stop()
if "name" not in scores_df.columns:
    scores_df["name"] = ""
if "level" not in scores_df.columns:
    scores_df["level"] = ""

# Build assignment choices from reference sheet columns
answer_cols = [c for c in refs_df.columns if c.startswith("answer")]
max_assign = len(answer_cols)
assignment_choices = ["0 (All Answers)"] + [str(i) for i in range(1, max_assign + 1)]

# =========================
# UI
# =========================
st.title("📘 Marking Dashboard")

# 1) Pick studentcode (auto-fill: name & level)
studentcode = st.selectbox("Student Code", sorted(scores_df["studentcode"].dropna().unique()))
row_match = scores_df[scores_df["studentcode"] == studentcode].head(1)
name  = row_match["name"].iloc[0] if not row_match.empty else ""
level = row_match["level"].iloc[0] if not row_match.empty else ""

col_a, col_b = st.columns(2)
with col_a:
    st.text_input("Name (auto)", value=name, disabled=True)
with col_b:
    st.text_input("Level (auto)", value=level, disabled=True)

# 2) Pick assignment (0 = all answers joined)
assign_label = st.selectbox("Assignment", assignment_choices)
assignment = 0 if assign_label.startswith("0") else int(assign_label)

# 3) Load student's Firestore folder and pick ONE submission
subs = get_student_submissions(studentcode)
if subs:
    def draft_label(idx, d):
        txt = str(d.get("content", "") or "")
        preview = (txt[:60] + "…") if len(txt) > 60 else txt
        return f"Submission {idx+1}: {preview}"
    draft_labels = [draft_label(i, d) for i, d in enumerate(subs)]
    pick = st.selectbox("Pick submission to mark", draft_labels, index=0)
    sel_idx = draft_labels.index(pick)
    student_answer = subs[sel_idx].get("content", "") or ""
else:
    st.warning("No submissions in Firestore for this student.")
    student_answer = ""

# 4) Reference answer & link (auto)
ref_text   = get_reference_for_assignment(refs_df, assignment)
answer_link = get_reference_link(refs_df)

st.markdown("**Student Submission**")
st.code(student_answer or "(empty)", language="markdown")

st.markdown("**Reference Answer**")
st.code(ref_text or "(not found)", language="markdown")

# --- Session defaults for AI result
if "ai_score" not in st.session_state:
    st.session_state.ai_score = 0
if "ai_feedback" not in st.session_state:
    st.session_state.ai_feedback = ""

# Auto-generate once when we have both texts (you can override afterwards)
combo_key = f"{studentcode}|{assignment}|{sel_idx if subs else -1}"
if "last_combo" not in st.session_state:
    st.session_state.last_combo = None
should_autogen = (
    client is not None
    and student_answer.strip()
    and ref_text.strip()
    and st.session_state.last_combo != combo_key
)

if should_autogen:
    ai_s, ai_fb = ai_mark(student_answer, ref_text)
    if ai_s is not None:
        st.session_state.ai_score = ai_s
    st.session_state.ai_feedback = ai_fb
    st.session_state.last_combo = combo_key

col1, col2 = st.columns([1,1])
with col1:
    if st.button("🔁 Regenerate AI"):
        ai_s, ai_fb = ai_mark(student_answer, ref_text)
        if ai_s is not None:
            st.session_state.ai_score = ai_s
        st.session_state.ai_feedback = ai_fb

# Editable (override allowed)
score = st.number_input("Score", min_value=0, max_value=100, step=1, value=st.session_state.ai_score)
comments = st.text_area("Feedback (you can edit)", value=st.session_state.ai_feedback, height=140)

# 5) Save to sheet (exact order expected)
if st.button("💾 Save", type="primary", use_container_width=True):
    if not studentcode:
        st.error("Pick a student code first.")
    elif not comments.strip():
        st.error("Feedback is required (generate with AI or type manually).")
    else:
        row = {
            "studentcode": studentcode,
            "name": name,
            "assignment": assignment,                   # 0 means "all answers"
            "score": int(score),
            "comments": comments.strip(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "level": level,
            "link": answer_link,                        # auto-filled from reference sheet
        }
        result = save_row_to_scores(row)
        if result.get("ok"):
            st.success("✅ Saved to Scores sheet.")
        else:
            st.error(f"❌ Failed to save: {result}")
