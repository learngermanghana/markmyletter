import streamlit as st
import requests
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import os, json

# =========================
# FIREBASE SETUP
# =========================
if not firebase_admin._apps:
    cred = credentials.Certificate(json.loads(os.environ["FIREBASE_KEY"]))  # from secrets
    firebase_admin.initialize_app(cred)

db = firestore.client()

def get_student_submission(student_id: str):
    """Fetch all submissions under drafts_v2/{student_id}/lessons"""
    doc_ref = db.collection("drafts_v2").document(student_id).collection("lessons")
    docs = doc_ref.stream()
    return [d.to_dict() for d in docs]

# =========================
# SHEET DATA (via CSV export URL)
# =========================
STUDENTS_SHEET_URL = "https://docs.google.com/spreadsheets/d/12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U/export?format=csv"
REF_ANSWERS_SHEET_URL = "https://docs.google.com/spreadsheets/d/1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo/export?format=csv"

def load_students():
    return pd.read_csv(STUDENTS_SHEET_URL)

def load_references():
    return pd.read_csv(REF_ANSWERS_SHEET_URL)

# =========================
# APP SCRIPT WEBHOOK
# =========================
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzKWo9IblWZEgD_d7sku6cGzKofis_XQj3NXGMYpf_uRqu9rGe4AvOcB15E3bb2e6O4/exec"
WEBHOOK_TOKEN = "Xenomexpress7727/"

def save_score(student, assignment, score, feedback):
    row = {
        "studentcode": student,
        "assignment": assignment,
        "score": score,
        "comments": feedback,
    }
    payload = {"token": WEBHOOK_TOKEN, "row": row}
    res = requests.post(WEBHOOK_URL, json=payload)
    return res.json()

# =========================
# STREAMLIT UI
# =========================
st.title("📘 Student Marking Dashboard")

students_df = load_students()
refs_df = load_references()

student_name = st.selectbox("Select Student", students_df["Name"].unique())
assignment_choice = st.selectbox("📌 Select Assignment (for reference answers)", refs_df["assignment"].unique())

if student_name:
    # --- Show ALL submissions from Firestore
    submissions = get_student_submission(student_name)

    st.subheader("📝 Student Submission(s)")
    student_texts = []
    if submissions:
        for i, sub in enumerate(submissions, start=1):
            text = sub.get("content", "No content")
            st.markdown(f"**Draft {i}:**")
            st.code(text, language="markdown")
            student_texts.append(text)
    else:
        st.warning("No submission found for this student.")

    # --- Reference answers (all columns in that row)
    ref_row = refs_df.loc[refs_df["assignment"] == assignment_choice].fillna("")
    if not ref_row.empty:
        ref_answers = []
        for col in ref_row.columns:
            if col.startswith("Answer") and ref_row.iloc[0][col]:
                ref_answers.append(str(ref_row.iloc[0][col]))
        ref_text = "\n".join(ref_answers)
    else:
        ref_text = "⚠️ No reference found."

    # --- Reference
    st.subheader("✅ Reference Answer(s)")
    st.code(ref_text, language="markdown")

    # --- Combined box (so you can copy & send to AI)
    st.subheader("📋 Combined for AI Marking")
    combined_text = (
        f"### Student Submission(s)\n"
        + "\n\n".join(student_texts)
        + f"\n\n### Reference Answer(s) for {assignment_choice}\n"
        + ref_text
    )
    st.text_area("Copy this text to send to AI", combined_text, height=300)

    # --- Marking inputs
    st.subheader("📊 Marking")
    score = st.number_input("Enter Score", min_value=0, max_value=100, step=1)
    feedback = st.text_area("Enter Feedback")

    if st.button("💾 Save Mark"):
        result = save_score(student_name, assignment_choice, score, feedback)
        if result.get("ok"):
            st.success("✅ Score & feedback saved to Google Sheet via App Script")
        else:
            st.error(f"❌ Error: {result}")
