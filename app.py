import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json, os
import requests

# =========================
# CONFIGURATION
# =========================
STUDENTS_SHEET_ID = "12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U"
REF_ANSWERS_SHEET_ID = "1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo"
SCORES_SHEET_URL = "https://docs.google.com/spreadsheets/d/1BRb8p3Rq0VpFCLSwL4eS9tSgXBo9hSWzfW_J_7W36NQ/edit"

WEBHOOK_URL   = "https://script.google.com/macros/s/AKfycbzKWo9IblWZEgD_d7sku6cGzKofis_XQj3NXGMYpf_uRqu9rGe4AvOcB15E3bb2e6O4/exec"
WEBHOOK_TOKEN = "Xenomexpress7727/"

# =========================
# GOOGLE SHEETS CLIENT
# =========================
def get_gsheet_client():
    creds_dict = json.loads(os.environ["G_SHEETS_KEY"])  # from Streamlit secrets or env
    scope = ["https://spreadsheets.google.com/feeds",
             "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    return gspread.authorize(creds)

gs_client = get_gsheet_client()

# Load students
def load_students():
    ws = gs_client.open_by_key(STUDENTS_SHEET_ID).sheet1
    return ws.get_all_records()

# Load reference answers
def load_references():
    ws = gs_client.open_by_key(REF_ANSWERS_SHEET_ID).sheet1
    return ws.get_all_records()

# Save to Scores (via App Script)
def save_score(row):
    payload = {
        "token": WEBHOOK_TOKEN,
        "row": row
    }
    res = requests.post(WEBHOOK_URL, json=payload)
    return res.json()

# =========================
# STREAMLIT UI
# =========================
st.title("📘 Student Marking Dashboard")

students = load_students()
refs = load_references()

student_names = [s["Name"] for s in students] if students else []
student_name = st.selectbox("Select Student", student_names)

if student_name:
    # --- Student info
    student = next((s for s in students if s["Name"] == student_name), None)

    # --- Reference answer
    ref_answer = next((r["Answer"] for r in refs if r["Name"] == student_name), "No reference found")

    st.subheader("✅ Reference Answer")
    st.code(ref_answer, language="markdown")

    # --- Marking inputs
    st.subheader("📊 Marking")
    assignment = st.text_input("Assignment Name")
    score = st.number_input("Enter Score", min_value=0, max_value=100, step=1)
    feedback = st.text_area("Enter Feedback")

    if st.button("💾 Save Mark"):
        row = {
            "studentcode": student.get("Code", ""),
            "name": student_name,
            "assignment": assignment,
            "score": score,
            "comments": feedback,
            "level": student.get("Level", "A1"),
            "link": SCORES_SHEET_URL
        }
        result = save_score(row)
        if result.get("ok"):
            st.success("✅ Score & feedback saved to Scores sheet")
        else:
            st.error(f"❌ Failed: {result}")
