import os
import json
import requests
import pandas as pd
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from openai import OpenAI
from datetime import datetime

# =========================
# FIREBASE INIT
# =========================
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# =========================
# GOOGLE SHEETS (public CSV export links)
# =========================
SCORES_SHEET_ID = "1BRb8p3Rq0VpFCLSwL4eS9tSgXBo9hSWzfW_J_7W36NQ"
REF_ANSWERS_SHEET_ID = "1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo"

def load_sheet(sheet_id):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"
    return pd.read_csv(url)

scores_df = load_sheet(SCORES_SHEET_ID)   # now main student list
refs_df = load_sheet(REF_ANSWERS_SHEET_ID)

# reshape reference answers: Answer1..Answer50 → assignment, answer
def reshape_refs(df):
    df.columns = df.columns.str.strip().str.lower()
    answer_cols = [c for c in df.columns if c.startswith("answer")]
    long_df = df.melt(
        id_vars=[c for c in df.columns if c not in answer_cols],
        value_vars=answer_cols,
        var_name="assignment",
        value_name="answer"
    )
    return long_df

refs_df = reshape_refs(refs_df)

# =========================
# APP SCRIPT WEBHOOK
# =========================
WEBHOOK_URL = st.secrets.get(
    "G_SHEETS_WEBHOOK_URL",
    "https://script.google.com/macros/s/AKfycbzKWo9IblWZEgD_d7sku6cGzKofis_XQj3NXGMYpf_uRqu9rGe4AvOcB15E3bb2e6O4/exec"
)
WEBHOOK_TOKEN = st.secrets.get("G_SHEETS_WEBHOOK_TOKEN", "Xenomexpress7727/")

def save_to_sheet(row: dict):
    payload = {"token": WEBHOOK_TOKEN, "row": row}
    r = requests.post(WEBHOOK_URL, json=payload)
    return r.json()

# =========================
# OPENAI CLIENT
# =========================
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

def ai_mark(student_answer, ref_answer):
    if not client:
        return "⚠️ OpenAI key missing", 0
    prompt = f"""
    You are a German teacher. Compare the student's answer with the reference answer.
    Give a mark out of 100 and provide 40 words of constructive feedback.
    
    Student answer: {student_answer}
    Reference answer: {ref_answer}
    """
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
    )
    text = resp.choices[0].message.content.strip()
    # naive split
    return text, None

# =========================
# STREAMLIT UI
# =========================
st.title("📘 Student Marking Dashboard")

# pick student
student_code = st.selectbox("Select Student Code", scores_df["studentcode"].dropna().unique())
student_name = scores_df.loc[scores_df["studentcode"] == student_code, "name"].values[0]

# pick assignment
assignment_num = st.selectbox("Select Assignment", refs_df["assignment"].unique())
ref_answer = refs_df.loc[refs_df["assignment"] == assignment_num, "answer"].values[0]

# fetch Firestore submissions
def get_student_submission(student_id: str):
    doc_ref = db.collection("drafts_v2").document(student_id).collection("lessons")
    docs = doc_ref.stream()
    return [d.to_dict() for d in docs]

submissions = get_student_submission(student_code)

# show submissions
st.subheader("📝 Student Submission(s)")
if submissions:
    for i, sub in enumerate(submissions, start=1):
        st.markdown(f"**Draft {i}:**")
        st.code(sub.get("content", ""), language="markdown")
else:
    st.warning("No submission found in Firestore.")

# show reference
st.subheader("✅ Reference Answer")
st.code(ref_answer, language="markdown")

# marking
st.subheader("📊 Marking")
use_ai = st.checkbox("Let AI generate mark & feedback")
if use_ai and submissions:
    ai_feedback, ai_score = ai_mark(submissions[0].get("content", ""), ref_answer)
    st.write("🤖 AI Feedback:", ai_feedback)
    score = st.number_input("Score", min_value=0, max_value=100, value=ai_score or 0)
    feedback = st.text_area("Feedback", ai_feedback)
else:
    score = st.number_input("Score", min_value=0, max_value=100, step=1)
    feedback = st.text_area("Feedback")

# save
if st.button("💾 Save to Sheet"):
    today = datetime.today().strftime("%Y-%m-%d")
    row = {
        "studentcode": student_code,
        "name": student_name,
        "assignment": assignment_num,
        "score": score,
        "comments": feedback,
        "date": today,
        "level": "",   # optional, leave blank
        "link": f"https://docs.google.com/spreadsheets/d/{REF_ANSWERS_SHEET_ID}"
    }
    result = save_to_sheet(row)
    st.success(f"✅ Saved: {result}")
