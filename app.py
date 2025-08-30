import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import os, json

# =========================
# CONFIGURATION
# =========================
STUDENTS_SHEET_CSV = "https://docs.google.com/spreadsheets/d/12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U/export?format=csv"
REF_ANSWERS_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo/export?format=csv"

WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzKWo9IblWZEgD_d7sku6cGzKofis_XQj3NXGMYpf_uRqu9rGe4AvOcB15E3bb2e6O4/exec"
WEBHOOK_TOKEN = "Xenomexpress7727/"

# =========================
# LOAD SHEETS
# =========================
def load_students():
    return pd.read_csv(STUDENTS_SHEET_CSV)

def load_references():
    return pd.read_csv(REF_ANSWERS_SHEET_CSV)

# =========================
# FIREBASE
# =========================
if not firebase_admin._apps:
    firebase_creds = json.loads(os.environ["FIREBASE_KEY"])
    cred = credentials.Certificate(firebase_creds)
    firebase_admin.initialize_app(cred)
db = firestore.client()

def get_student_submission(student_id: str):
    """Fetch all submissions under drafts_v2/{student_id}/lessons"""
    doc_ref = db.collection("drafts_v2").document(student_id).collection("lessons")
    docs = doc_ref.stream()
    return [d.to_dict() for d in docs]

# =========================
# APP SCRIPT SAVE FUNCTION
# =========================
def save_score(student_row, score, feedback, assignment="Assignment 1", level="A1", link=""):
    row = {
        "studentcode": student_row.get("Code", ""),
        "name": student_row.get("Name", ""),
        "assignment": assignment,
        "score": score,
        "comments": feedback,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "level": level,
        "link": link
    }
    payload = {"token": WEBHOOK_TOKEN, "row": row}
    resp = requests.post(WEBHOOK_URL, json=payload)
    if resp.status_code == 200:
        return resp.json()
    else:
        return {"ok": False, "error": f"HTTP {resp.status_code}"}

# =========================
# STREAMLIT UI
# =========================
st.title("📘 Student Marking Dashboard")

students_df = load_students()
refs_df = load_references()

student_name = st.selectbox("Select Student", students_df["Name"].unique())

if student_name:
    # --- Firestore submissions
    submissions = get_student_submission(student_name)

    # --- Reference answer
    ref_answer = refs_df.loc[refs_df["Name"] == student_name, "Answer"].values
    ref_text = ref_answer[0] if len(ref_answer) else "No reference answer found."

    # --- Display student submissions
    st.subheader("📝 Student Submission(s)")
    if submissions:
        for i, sub in enumerate(submissions, start=1):
            st.markdown(f"**Draft {i}:**")
            st.code(sub.get("content", "No 'content' field in Firestore"), language="markdown")
    else:
        st.warning("No submission found for this student.")

    # --- Display reference
    st.subheader("✅ Reference Answer")
    st.code(ref_text, language="markdown")

    # --- Marking inputs
    st.subheader("📊 Marking")
    score = st.number_input("Enter Score", min_value=0, max_value=100, step=1)
    feedback = st.text_area("Enter Feedback")

    if st.button("💾 Save Mark"):
        student_row = students_df.loc[students_df["Name"] == student_name].iloc[0].to_dict()
        result = save_score(student_row, score, feedback)
        if result.get("ok"):
            st.success("✅ Score & feedback sent to Google Sheet via webhook")
        else:
            st.error(f"❌ Failed to save: {result.get('error')}")
