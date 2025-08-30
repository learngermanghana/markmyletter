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
# SHEET IDS (CSV export)
# =========================
STUDENTS_SHEET_ID    = "12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U"   # studentcode, name, level
REF_ANSWERS_SHEET_ID = "1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo"    # rows = assignments (e.g., 0.1), cols Answer1..50, answer_url, sheet_url

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
    """Return list of dicts from drafts_v2/{student_code}/lessons; fallback to 'lessens'."""
    items = []
    # normal
    try:
        for snap in db.collection("drafts_v2").document(student_code).collection("lessons").stream():
            d = snap.to_dict() or {}
            d["id"] = snap.id
            items.append(d)
    except Exception:
        pass
    # typo-safe
    if not items:
        try:
            for snap in db.collection("drafts_v2").document(student_code).collection("lessens").stream():
                d = snap.to_dict() or {}
                d["id"] = snap.id
                items.append(d)
        except Exception:
            pass
    return items

def assignment_options_from_refs(refs_df: pd.DataFrame):
    """Return list of (label, row_index). Label prefers 'assignment' + 'name' if present."""
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

def reference_text_all_for_row(row: pd.Series) -> str:
    """Join all AnswerN cells from this assignment row, in numeric order."""
    tuples = []
    for col in row.index:
        if col.startswith("answer"):
            m = re.findall(r"\d+", col)
            if m:
                n = int(m[0])
                val = str(row[col]).strip()
                if val and val.lower() not in ("nan", "none"):
                    tuples.append((n, val))
    tuples.sort(key=lambda t: t[0])
    if not tuples:
        return "No reference answers found."
    return "\n\n".join([f"Answer{n}: {val}" for n, val in tuples])

def link_for_row(row: pd.Series) -> str:
    for col in ["answer_url", "sheet_url"]:
        if col in row.index:
            v = str(row[col]).strip()
            if v and v.lower() not in ("nan", "none"):
                return v
    return f"https://docs.google.com/spreadsheets/d/{REF_ANSWERS_SHEET_ID}/edit"

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

# 1) Student dropdown → auto-filled name & level
studentcode = st.selectbox("Student Code", sorted(students_df["studentcode"].dropna().unique()))
srow = students_df[students_df["studentcode"] == studentcode].head(1)
name  = srow["name"].iloc[0]  if not srow.empty else ""
level = srow["level"].iloc[0] if not srow.empty else ""

c1, c2 = st.columns(2)
with c1: st.text_input("Name (auto)",  value=name,  disabled=True)
with c2: st.text_input("Level (auto)", value=level, disabled=True)

# 2) Assignment dropdown (parent row). No Answer1/2 picking—always ALL answers in that row.
assign_opts  = assignment_options_from_refs(refs_df)  # list[(label, idx)]
assign_label = st.selectbox("Assignment (from Reference sheet)", [lbl for lbl, _ in assign_opts])
assign_idx   = dict(assign_opts)[assign_label]
assign_row   = refs_df.iloc[assign_idx]

# Build reference text for THIS row (all answers joined)
ref_text    = reference_text_all_for_row(assign_row)
answer_link = link_for_row(assign_row)
st.caption(f"Reference link: {answer_link}")

# 3) Firestore dropdown: list all in drafts_v2/{studentcode}/lessons (or 'lessens')
subs = get_student_submissions(studentcode)
if subs:
    def sub_label(i, d):
        txt = str(d.get("content", "") or "")
        preview = (txt[:70] + "…") if len(txt) > 70 else txt
        return f"{i+1} • {d.get('id','')} • {preview}"
    sub_labels = [sub_label(i, d) for i, d in enumerate(subs)]
    picked = st.selectbox("Student submission", sub_labels)
    sel_idx = sub_labels.index(picked)
    student_text = subs[sel_idx].get("content", "") or ""
else:
    st.warning("No submissions in Firestore for this student.")
    student_text = ""

st.markdown("**Student Submission**")
st.code(student_text or "(empty)", language="markdown")

st.markdown("**Reference Answer (all answers in this assignment)**")
st.code(ref_text or "(not found)", language="markdown")

# --- AI generate once per selection; allow override
if "ai_score" not in st.session_state:   st.session_state.ai_score = 0
if "ai_feedback" not in st.session_state: st.session_state.ai_feedback = ""
if "key_last" not in st.session_state:    st.session_state.key_last = None

combo_key = f"{studentcode}|{assign_idx}|{picked if subs else 'none'}"
should_gen = (
    client is not None
    and student_text.strip()
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

# Editable (override allowed)
score    = st.number_input("Score", min_value=0, max_value=100, step=1, value=st.session_state.ai_score)
comments = st.text_area("Feedback (you can edit)", value=st.session_state.ai_feedback, height=140)

# 4) Save in exact order → studentcode, name, assignment, score, comments, date, level, link
if st.button("💾 Save", type="primary", use_container_width=True):
    if not studentcode:
        st.error("Pick a student code first.")
    elif not comments.strip():
        st.error("Feedback is required (generate with AI or type manually).")
    else:
        assignment_value = str(assign_row.get("assignment", assign_label)).strip() or assign_label
        row = {
            "studentcode": studentcode,
            "name": name,
            "assignment": assignment_value,                 # parent assignment (e.g., "0.1")
            "score": int(score),
            "comments": comments.strip(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "level": level,
            "link": answer_link,                            # per-row link (usually ends with key)
        }
        result = save_row_to_scores(row)
        if result.get("ok"):
            st.success("✅ Saved to Scores sheet.")
        elif result.get("why") == "validation":
            st.error("❌ Sheet blocked the write due to **data validation** for studentcode.")
        else:
            st.error(f"❌ Failed to save: {result}")
