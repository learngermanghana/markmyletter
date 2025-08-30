import os
import json
import requests
import pandas as pd
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
from openai import OpenAI

# =========================
# FIREBASE INIT
# =========================
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)

db = firestore.client()

# =========================
# SHEETS (CSV Export)
# =========================
SCORES_SHEET_ID = "1BRb8p3Rq0VpFCLSwL4eS9tSgXBo9hSWzfW_J_7W36NQ"
REF_ANSWERS_SHEET_ID = "1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo"

def load_sheet(sheet_id):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"
    return pd.read_csv(url)

scores_df = load_sheet(SCORES_SHEET_ID)
refs_df = load_sheet(REF_ANSWERS_SHEET_ID)

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
# FIRESTORE FETCH
# =========================
def get_student_submission(student_id: str):
    doc_ref = db.collection("drafts_v2").document(student_id).collection("lessons")
    docs = doc_ref.stream()
    return [d.to_dict() for d in docs]

# =========================
# OPENAI CLIENT
# =========================
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

def ai_feedback(student_text: str, ref_text: str) -> str:
    if not client:
        return "⚠️ OpenAI API key missing."
    prompt = f"""
    You are a German teacher. Compare the student’s answer with the reference answer.
    Give clear marking feedback in about 40 words. 

    Student Answer:
    {student_text}

    Reference Answer:
    {ref_text}
    """
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=120
    )
    return resp.choices[0].message.content.strip()

# =========================
# STREAMLIT UI
# =========================
st.title("📘 Student Marking Dashboard")

if "studentcode" not in scores_df.columns:
    st.error("⚠️ 'studentcode' column not found in Scores sheet.")
else:
    student_code = st.selectbox("Select Student Code", scores_df["studentcode"].dropna().unique())
    student_name = scores_df.loc[scores_df["studentcode"] == student_code, "name"].values[0]

    # --- Assignment numbers from columns
    answer_cols = [c for c in refs_df.columns if c.lower().startswith("answer")]
    assignment_num = st.selectbox("Select Assignment", [0] + list(range(1, len(answer_cols) + 1)))

    # --- Load submissions
    submissions = get_student_submission(student_code)

    if submissions:
        draft_options = [f"Draft {i+1}" for i in range(len(submissions))]
        selected_draft = st.selectbox("Select Draft to Review", draft_options)
        draft_index = draft_options.index(selected_draft)
        student_answer = submissions[draft_index].get("content", "")
    else:
        st.warning("No submission found in Firestore.")
        student_answer = ""

    if assignment_num == 0:  
        # join all answers into one block
        ref_text = "\n\n".join(
            f"{col}: {refs_df[col].dropna().iloc[0]}" 
            for col in answer_cols if col in refs_df.columns
        )
    else:
        col_name = f"Answer{assignment_num}"
        ref_text = str(refs_df[col_name].dropna().iloc[0]) if col_name in refs_df.columns else "No reference found."

    if student_answer:
        st.subheader("📝 Student Answer")
        st.code(student_answer, language="markdown")

    st.subheader("✅ Reference Answer")
    st.code(ref_text, language="markdown")

    # AI feedback
    feedback_text = ai_feedback(student_answer, ref_text) if student_answer else ""

    st.subheader("🤖 AI Feedback")
    st.info(feedback_text or "⚠️ No student answer to analyze")

    # Marking inputs
    st.subheader("📊 Marking")
    score = st.number_input("Enter Score", min_value=0, max_value=100, step=1)
    manual_feedback = st.text_area("Enter Feedback (optional)", value=feedback_text)

    if st.button("💾 Save Mark"):
        row = {
            "studentcode": student_code,
            "name": student_name,
            "assignment": assignment_num,
            "score": score,
            "comments": manual_feedback,
            "date": datetime.today().strftime("%Y-%m-%d"),
            "level": "",  # optional
            "link": f"https://docs.google.com/spreadsheets/d/{REF_ANSWERS_SHEET_ID}/edit"
        }
        result = save_to_sheet(row)
        st.success(f"✅ Saved to sheet: {result}")
