import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import requests
import json
import os

# =========================
# CONFIGURATION
# =========================
WEBHOOK_URL   = st.secrets["appscript"]["url"]   # from secrets.toml
WEBHOOK_TOKEN = st.secrets["appscript"]["token"] # from secrets.toml

# =========================
# FIREBASE
# =========================
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)

db = firestore.client()

# =========================
# FIRESTORE FUNCTIONS
# =========================
def get_student_submission(student_id: str):
    """Fetch all submissions under drafts_v2/{student_id}/lessons"""
    doc_ref = db.collection("drafts_v2").document(student_id).collection("lessons")
    docs = doc_ref.stream()
    return [d.to_dict() for d in docs]

# =========================
# GOOGLE SHEETS via APP SCRIPT
# =========================
def save_score(studentcode, name, assignment, score, comments, level="A1", link=""):
    payload = {
        "token": WEBHOOK_TOKEN,
        "row": {
            "studentcode": studentcode,
            "name": name,
            "assignment": assignment,
            "score": score,
            "comments": comments,
            "level": level,
            "link": link
        }
    }
    res = requests.post(WEBHOOK_URL, json=payload)
    return res.json()

# =========================
# STREAMLIT UI
# =========================
st.title("📘 Student Marking Dashboard")

student_id = st.text_input("Enter Student ID")

if student_id:
    # --- Firestore submissions
    submissions = get_student_submission(student_id)

    st.subheader("📝 Student Submission(s)")
    if submissions:
        for i, sub in enumerate(submissions, start=1):
            st.markdown(f"**Draft {i}:**")
            st.code(sub.get("content", "No 'content' field"), language="markdown")
    else:
        st.warning("No submission found.")

    # --- Marking inputs
    st.subheader("📊 Marking")
    score = st.number_input("Enter Score", min_value=0, max_value=100, step=1)
    feedback = st.text_area("Enter Feedback")
    assignment = st.text_input("Assignment name")

    if st.button("💾 Save Mark"):
        result = save_score(student_id, student_id, assignment, score, feedback)
        if result.get("ok"):
            st.success("✅ Score & feedback saved to Google Sheet")
        else:
            st.error(f"❌ Failed: {result}")
