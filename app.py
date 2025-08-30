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
    cred = credentials.Certificate(json.loads(os.environ["FIREBASE_KEY"]))  # secret
    firebase_admin.initialize_app(cred)

db = firestore.client()

def get_student_submissions(student_code: str):
    """Fetch all lessons under drafts_v2/{student_code}/lessons"""
    docs_ref = db.collection("drafts_v2").document(student_code).collection("lessons")
    docs = docs_ref.stream()
    return {d.id: d.to_dict() for d in docs}

# =========================
# SHEET DATA (CSV export)
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

def save_score(student_code, assignment, score, feedback):
    row = {
        "studentcode": student_code,
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

student_code = st.selectbox("Select Student Code", students_df["studentcode"].unique())
assignment_choice = st.selectbox("📌 Select Assignment (for reference answers)", refs_df["assignment"].unique())

if student_code:
    # --- Show ALL submissions from Firestore
    submissions = get_student_submissions(student_code)

    st.subheader("📝 Student Submission(s)")
    student_texts = []
    if submissions:
        for doc_id, sub in submissions.items():
            text = sub.get("content", "No content")
            st.markdown(f"**{doc_id}**")  # show lesson ID
            st.code(text, language="markdown")
            student_texts.append(f"{doc_id}:\n{text}")
    else:
        st.warning("No submissions found for this student.")

    # --- Reference answers for chosen assignment
    ref_row = refs_df.loc[refs_df["assignment"] == assignment_choice].fillna("")
    ref_answers = []
    if not ref_row.empty:
        for col in ref_row.columns:
            if col.startswith("Answer") and ref_row.iloc[0][col]:
                ref_answers.append(str(ref_row.iloc[0][col]))
    ref_text = "\n".join(ref_answers) if ref_answers else "⚠️ No reference found."

    # --- Reference
    st.subheader("✅ Reference Answer(s)")
    st.code(ref_text, language="markdown")

    # --- Combined text area
    st.subheader("📋 Combined for AI Marking")
    combined_text = (
        f"### Student Submissions ({student_code})\n"
        + "\n\n".join(student_texts)
        + f"\n\n### Reference Answer(s) for {assignment_choice}\n"
        + ref_text
    )
    st.text_area("Copy this text to send to AI", combined_text, height=300)

    # --- Marking
    st.subheader("📊 Marking")
    score = st.number_input("Enter Score", min_value=0, max_value=100, step=1)
    feedback = st.text_area("Enter Feedback")

    if st.button("💾 Save Mark"):
        result = save_score(student_code, assignment_choice, score, feedback)
        if result.get("ok"):
            st.success("✅ Score & feedback saved to Scores Sheet")
        else:
            st.error(f"❌ Error: {result}")
