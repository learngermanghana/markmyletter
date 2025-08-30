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
# GOOGLE SHEETS (via public CSV export link)
# =========================
STUDENTS_SHEET_ID = "12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U"
REF_ANSWERS_SHEET_ID = "1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo"

def load_sheet(sheet_id):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"
    return pd.read_csv(url)

students_df = load_sheet(STUDENTS_SHEET_ID)
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
# OPENAI CLIENT
# =========================
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", None)
client = None
if OPENAI_API_KEY:
    client = OpenAI(api_key=OPENAI_API_KEY)

def ai_marking(student_answer, ref_answers):
    """Generate ~40 word AI feedback"""
    if not client:
        return "⚠️ Missing OpenAI API key in secrets."
    ref_text = "\n".join([f"{k}: {v}" for k, v in ref_answers.items() if str(k).startswith("Answer")])
    prompt = f"""
    You are a teacher. Compare the student's answer with the reference answers.
    Provide marking feedback in about 40 words. 

    Student answer:
    {student_answer}

    Reference answers:
    {ref_text}
    """
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=150,
    )
    return resp.choices[0].message.content.strip()

# =========================
# FIRESTORE HELPER
# =========================
def get_student_submission(student_code: str):
    doc_ref = db.collection("drafts_v2").document(student_code).collection("lessons")
    docs = doc_ref.stream()
    return [d.to_dict() for d in docs]

# =========================
# STREAMLIT UI
# =========================
st.title("📘 Student Marking Dashboard")

# --- Choose student
if "studentcode" not in students_df.columns:
    st.error("⚠️ 'studentcode' column not found in Students sheet.")
else:
    student_code = st.selectbox("Select Student Code", students_df["studentcode"].unique())

    if student_code:
        # --- Firestore submissions
        submissions = get_student_submission(student_code)

        st.subheader("📝 Student Submissions")
        if submissions:
            for i, sub in enumerate(submissions, start=1):
                st.markdown(f"**Draft {i}:**")
                st.code(sub.get("content", ""), language="markdown")
        else:
            st.warning("No submissions found for this student.")

        # --- Assignment selector
        assignment_num = st.selectbox("Select Assignment", refs_df["assignment"].unique())

        # --- Reference answers
        ref_answers = {}
        if "assignment" in refs_df.columns:
            ref_row = refs_df[refs_df["assignment"] == assignment_num]
            if not ref_row.empty:
                ref_answers = ref_row.iloc[0].to_dict()

        st.subheader("✅ Reference Answers")
        if ref_answers:
            st.json(ref_answers)
        else:
            st.warning("No reference answers found for this assignment.")

        # --- Marking inputs
        st.subheader("📊 Marking")
        score = st.number_input("Enter Score", min_value=0, max_value=100, step=1)
        feedback = st.text_area("Enter Feedback (or auto-generate below)")

        # --- AI Feedback
        if st.button("🤖 Generate AI Feedback"):
            if submissions and ref_answers:
                ai_fb = ai_marking(submissions[-1].get("content", ""), ref_answers)
                feedback = ai_fb
                st.success("AI feedback generated:")
                st.write(ai_fb)
            else:
                st.warning("Need student submission + reference answers for AI marking.")

        # --- Save to sheet
        if st.button("💾 Save Mark"):
            row = {
                "studentcode": student_code,
                "name": students_df.loc[students_df["studentcode"] == student_code, "name"].values[0]
                if "name" in students_df.columns else "",
                "assignment": assignment_num,
                "score": score,
                "comments": feedback,
                "date": datetime.today().strftime("%Y-%m-%d"),
                "level": students_df.loc[students_df["studentcode"] == student_code, "level"].values[0]
                if "level" in students_df.columns else "",
                "link": ref_answers.get("answer_url", ""),
            }
            result = save_to_sheet(row)
            st.success(f"✅ Saved to sheet: {result}")
