# app.py
import os
import re
import json
from datetime import datetime
from typing import Dict, Any, List, Tuple

import pandas as pd
import requests
import streamlit as st

# ---------- Optional OpenAI ----------
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY"))
try:
    from openai import OpenAI
    ai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception:
    ai_client = None

# ---------- Firebase (from secrets) ----------
import firebase_admin
from firebase_admin import credentials, firestore

if not firebase_admin._apps:
    fb_cfg = st.secrets.get("firebase")
    if fb_cfg:
        cred = credentials.Certificate(dict(fb_cfg))
        firebase_admin.initialize_app(cred)
db = firestore.client() if firebase_admin._apps else None

# ---------- Constants ----------
# Students sheet (tab now "Sheet1")
STUDENTS_SHEET_ID   = "12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U"
STUDENTS_SHEET_TAB  = st.secrets.get("STUDENTS_SHEET_TAB", "Sheet1")

# Apps Script webhook (with fallbacks)
WEBHOOK_URL   = st.secrets.get(
    "G_SHEETS_WEBHOOK_URL",
    "https://script.google.com/macros/s/AKfycbzKWo9IblWZEgD_d7sku6cGzKofis_XQj3NXGMYpf_uRqu9rGe4AvOcB15E3bb2e6O4/exec",
)
WEBHOOK_TOKEN = st.secrets.get("G_SHEETS_WEBHOOK_TOKEN", "Xenomexpress7727/")

# Answers dictionary JSON from repo
ANSWERS_JSON_PATHS = [
    "answers_dictionary.json",
    "data/answers_dictionary.json",
    "assets/answers_dictionary.json",
]

# =========================================================
# Utilities
# =========================================================
def natural_key(s: str):
    """Natural sort key: 'A1 10' after 'A1 2'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.findall(r"\d+|\D+", str(s))]

@st.cache_data(show_spinner=False, ttl=300)
def load_students_csv(sheet_id: str, tab: str) -> pd.DataFrame:
    """
    Load Google Sheet tab as CSV (no auth), normalize column names.
    Uses gviz/tq export to target the specific tab.
    """
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"
        f"?tqx=out:csv&sheet={requests.utils.quote(tab)}"
        "&tq=select%20*%20limit%2010000"
    )
    df = pd.read_csv(url, dtype=str)
    df.columns = df.columns.str.strip().str.lower()
    return df

@st.cache_data(show_spinner=False)
def load_answers_dictionary() -> Dict[str, Any]:
    for p in ANSWERS_JSON_PATHS:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            # ensure every entry has an "answers" dict (Answer1, Answer2, ...)
            for k, v in data.items():
                if not isinstance(v, dict):
                    data[k] = {"answers": {}, "answer_url": ""}
                else:
                    if "answers" not in v:
                        v["answers"] = {}
                    if "answer_url" not in v:
                        v["answer_url"] = ""
            return data
    st.error("❌ answers_dictionary.json not found in the repo.")
    return {}

def list_all_assignments(ans_dict: Dict[str, Any]) -> List[str]:
    # keys of the dictionary are the assignment names
    return sorted(list(ans_dict.keys()), key=natural_key)

def build_reference_text(row_obj: Dict[str, Any]) -> Tuple[str, str]:
    """
    Join Answer1..AnswerN in numeric order into one reference text.
    Returns (reference_text, answer_url_or_blank).
    """
    answers: Dict[str, str] = row_obj.get("answers", {}) or {}
    # sort by AnswerN
    def n_from_key(k: str) -> int:
        m = re.search(r"(\d+)", k)
        return int(m.group(1)) if m else 0
    ordered = [
        k for k in sorted(answers.keys(), key=n_from_key)
        if k.lower().startswith("answer")
    ]
    chunks = []
    for k in ordered:
        v = str(answers[k]).strip()
        if v and v.lower() not in ("nan", "none"):
            n = n_from_key(k)
            chunks.append(f"{n}. {v}")
    ref_text = "\n".join(chunks) if chunks else "No reference answers found."
    # use the "answer_url" only (ignore sheet_url as requested)
    answer_link = str(row_obj.get("answer_url") or "").strip()
    return ref_text, answer_link

def filter_df_any(df: pd.DataFrame, q: str) -> pd.DataFrame:
    if not q:
        return df
    mask = df.apply(lambda c: c.astype(str).str.contains(q, case=False, na=False))
    return df[mask.any(axis=1)]

def extract_text_from_doc(doc: Dict[str, Any]) -> str:
    # Try common fields; else join string-like values
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

def fetch_submissions(student_code: str) -> List[Dict[str, Any]]:
    if not db or not student_code:
        return []
    items: List[Dict[str, Any]] = []
    def pull(coll: str):
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

def ai_mark(student_answer: str, ref_text: str) -> Tuple[int | None, str]:
    """Return (score, feedback) via OpenAI, or (None, reason) if unavailable."""
    if not ai_client:
        return None, "⚠️ OpenAI key missing (set OPENAI_API_KEY)."
    prompt = f"""
You are a German teacher. Compare the student's answer with the reference answer.
Return STRICT JSON with:
- score: integer 0-100
- feedback: constructive. List major errors and briefly justify the numeric score.
  If the student's text lacks umlauts (ä, ö, ü, ß), remind them that holding "s",
  "u", or "o" produces them, but do not deduct points for this omission.

Student answer:
{student_answer}

Reference answer:
{ref_text}

Return only JSON.
"""
    try:
        resp = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=220,
        )
        text = resp.choices[0].message.content.strip()
        m = re.search(r"\{.*\}", text, flags=re.S)
        text = m.group(0) if m else text
        data = json.loads(text)
        score = int(data.get("score", 0))
        fb = str(data.get("feedback", "")).strip()
        return max(0, min(100, score)), (fb or "(no feedback)")
    except Exception as e:
        return None, f"(AI error: {e})"

def save_row_to_scores(row: dict) -> dict:
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
# UI
# =========================================================
st.set_page_config(page_title="📘 Marking Dashboard", page_icon="📘", layout="wide")
st.title("📘 Marking Dashboard")

# Refresh button for all caches
if st.button("🔄 Refresh sheets & dictionary (clear cache)"):
    st.cache_data.clear()
    st.rerun()

# --- Load data
answers_dict = load_answers_dictionary()
assignments = list_all_assignments(answers_dict)

students_df = load_students_csv(STUDENTS_SHEET_ID, STUDENTS_SHEET_TAB)
for col in ["studentcode", "name", "level"]:
    if col not in students_df.columns:
        students_df[col] = ""

# --- Student select with search
st.subheader("1) Pick Student")
q = st.text_input("Search by code / name / phone / any field")
students_filtered = filter_df_any(students_df, q)
if students_filtered.empty:
    st.warning("No students match your search.")
    st.stop()

labels = [
    f"{r.get('studentcode','')} — {r.get('name','')} ({r.get('level','')})"
    for _, r in students_filtered.iterrows()
]
choice = st.selectbox("Select student", labels)
row_sel = students_filtered.iloc[labels.index(choice)]
studentcode = str(row_sel.get("studentcode","")).strip()
student_name = str(row_sel.get("name","")).strip()
student_level = str(row_sel.get("level","")).strip()

c1, c2 = st.columns(2)
with c1: st.text_input("Name (auto)",  value=student_name,  disabled=True)
with c2: st.text_input("Level (auto)", value=student_level, disabled=True)

# --- Reference select (from dictionary)
st.subheader("2) Reference (Answers Dictionary)")
st.caption(f"{len(assignments)} assignments available from answers_dictionary.json")
search_assign = st.text_input("Search assignment title…")
assign_pool = [a for a in assignments if search_assign.lower() in a.lower()] if search_assign else assignments
assignment_choice = st.selectbox("Select assignment", assign_pool)
ref_obj = answers_dict.get(assignment_choice, {}) if assignment_choice else {}
ref_text, answer_link = build_reference_text(ref_obj)

st.markdown("**Reference Answer**")
st.code(ref_text or "(not found)", language="markdown")
if answer_link:
    st.caption(f"Reference link: {answer_link}")

# --- Firestore submissions for this student
st.subheader("3) Student Submission (Firestore)")
subs = fetch_submissions(studentcode)
if not subs:
    st.info("No submissions found under drafts_v2/{code}/lessons (or lessens).")
    student_text = ""
else:
    def label_for(idx: int, d: Dict[str, Any]) -> str:
        txt = extract_text_from_doc(d)
        preview = (txt[:80] + "…") if len(txt) > 80 else txt
        return f"{idx+1} • {d.get('id','(no-id)')} • {preview}"
    sub_labels = [label_for(i, d) for i, d in enumerate(subs)]
    picked = st.selectbox("Pick submission to preview", sub_labels)
    student_text = extract_text_from_doc(subs[sub_labels.index(picked)])

st.markdown("**Student Submission**")
st.code(student_text or "(empty)", language="markdown")

# --- Combined copy box
st.subheader("4) Combined (copyable)")
combined = f"""# Student Submission
{student_text}

# Reference Answer
{ref_text}
"""
st.text_area("Combined", value=combined, height=200)

# --- AI generate (override allowed)
if "ai_score" not in st.session_state:    st.session_state.ai_score = 0
if "ai_feedback" not in st.session_state: st.session_state.ai_feedback = ""
if "combo_key" not in st.session_state:   st.session_state.combo_key = None

cur_key = f"{studentcode}|{assignment_choice}|{student_text[:60]}"
should_gen = (
    ai_client is not None
    and student_text.strip()
    and ref_text.strip()
    and ref_text.strip() != "No reference answers found."
    and st.session_state.combo_key != cur_key
)
if should_gen:
    s, fb = ai_mark(student_text, ref_text)
    if s is not None:
        st.session_state.ai_score = s
    st.session_state.ai_feedback = fb
    st.session_state.combo_key = cur_key

colA, colB = st.columns([1,1])
with colA:
    if st.button("🔁 Regenerate AI"):
        s, fb = ai_mark(student_text, ref_text)
        if s is not None:
            st.session_state.ai_score = s
        st.session_state.ai_feedback = fb

score = st.number_input("Score", min_value=0, max_value=100, value=int(st.session_state.ai_score))
feedback = st.text_area("Feedback (you can edit)", value=st.session_state.ai_feedback, height=140)

# --- Save to Scores (Apps Script webhook)
st.subheader("5) Save to Scores sheet")
if st.button("💾 Save", type="primary", use_container_width=True):
    if not studentcode:
        st.error("Pick a student first.")
    elif not assignment_choice:
        st.error("Pick an assignment.")
    elif not feedback.strip():
        st.error("Feedback is required.")
    else:
        row = {
            "studentcode": studentcode,
            "name":        student_name,
            "assignment":  assignment_choice,        # the dictionary key (your visible title)
            "score":       int(score),
            "comments":    feedback.strip(),
            "date":        datetime.now().strftime("%Y-%m-%d"),
            "level":       student_level,
            "link":        answer_link,              # from dictionary; sheet_url is ignored by request
        }
        result = save_row_to_scores(row)
        if result.get("ok"):
            st.success("✅ Saved to Scores sheet.")
        elif result.get("why") == "validation":
            st.error("❌ Sheet blocked the write due to data validation (studentcode).")
        else:
            st.error(f"❌ Failed to save: {result}")
