import os
import json
import requests
import pandas as pd
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from openai import OpenAI

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
    df = pd.read_csv(url)
    # normalize headers: lowercase + strip spaces
    df.columns = df.columns.str.strip().str.lower()
    return df

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

# --- Reference answers (based on assignment, not studentcode)
if "assignment" in refs_df.columns:
    ref_row = refs_df[refs_df["assignment"] == assignment_num]
    if not ref_row.empty:
        ref_answers = ref_row.iloc[0].to_dict()
    else:
        ref_answers = {}
else:
    ref_answers = {}


# =========================
# STREAMLIT UI
# =========================
st.title("📘 Student Marking Dashboard")

# --- Select Student Code
if "studentcode" not in students_df.columns:
    st.error("❌ The students sheet does not have a 'studentcode' column. Please check the headers.")
else:
    student_code = st.selectbox("Select Student Code", students_df["studentcode"].unique())

    if student_code:
        # --- Firestore submissions (all drafts under this student)
        submissions_ref = db.collection("drafts_v2").document(student_code).collection("lessons")
        submissions = [doc.to_dict() for doc in submissions_ref.stream()]

        # --- Reference answers (all assignment answers in row)
        ref_row = refs_df[refs_df["studentcode"] == student_code]
        if not ref_row.empty:
            ref_answers = ref_row.iloc[0].to_dict()
        else:
            ref_answers = {}

        # --- Display submissions
        st.subheader("📝 Student Submission(s)")
        if submissions:
            for i, sub in enumerate(submissions, start=1):
                st.markdown(f"**Draft {i}:**")
                st.code(sub.get("content", ""), language="markdown")
        else:
            st.warning("No submission found for this student in Firestore.")

        # --- Display reference answers
        st.subheader("✅ Reference Answers")
        if ref_answers:
            st.json(ref_answers)
        else:
            st.warning("No reference answers found in sheet.")

        # --- Marking section
        st.subheader("📊 Marking")
        assignment_num = st.number_input("Assignment Number", min_value=1, max_value=50, step=1)
        score = st.number_input("Enter Score", min_value=0, max_value=100, step=1)
        comments = st.text_area("Enter Feedback (manual)")

        # --- AI Feedback
        ai_feedback = ""
        if client and st.button("🤖 Generate AI Feedback"):
            combined_text = f"Student submission:\n{submissions}\n\nReference:\n{ref_answers}"
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a teacher giving short constructive feedback."},
                    {"role": "user", "content": combined_text}
                ],
                max_tokens=120
            )
            ai_feedback = response.choices[0].message.content.strip()
            st.success(ai_feedback)

        # --- Save to Google Sheets via App Script
        if st.button("💾 Save Mark"):
            row = {
                "studentcode": student_code,
                "name": students_df.loc[students_df["studentcode"] == student_code, "name"].values[0] if "name" in students_df.columns else "",
                "assignment": assignment_num,
                "score": score,
                "comments": comments or ai_feedback,
                "date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                "level": students_df.loc[students_df["studentcode"] == student_code, "level"].values[0] if "level" in students_df.columns else "",
                "link": f"https://docs.google.com/spreadsheets/d/{REF_ANSWERS_SHEET_ID}"
            }
            result = save_to_sheet(row)
            st.success(f"✅ Saved! Response: {result}")
