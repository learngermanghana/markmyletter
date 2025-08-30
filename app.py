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
    cred = credentials.Certificate(json.loads(st.secrets["firebase"]))
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
WEBHOOK_URL = st.secrets["G_SHEETS_WEBHOOK_URL"]
WEBHOOK_TOKEN = st.secrets["G_SHEETS_WEBHOOK_TOKEN"]

def save_to_sheet(row: dict):
    payload = {"token": WEBHOOK_TOKEN, "row": row}
    r = requests.post(WEBHOOK_URL, json=payload)
    return r.json()

# =========================
# FIREBASE SUBMISSIONS
# =========================
def get_student_submissions(student_code: str):
    """Fetch all drafts for a student"""
    docs = db.collection("drafts_v2").document(student_code).collection("lessons").stream()
    return [d.to_dict() for d in docs]

# =========================
# OPENAI CLIENT
# =========================
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

def ai_mark(student_text: str, reference_text: str):
    """Use GPT to assign a score (0-100) and give 40 words feedback"""
    prompt = f"""
    You are a German teacher. Compare the student's answer to the reference answer.
    Assign a numeric score (0-100) and give exactly 40 words constructive feedback.
    Student Answer: {student_text}
    Reference Answer: {reference_text}
    """

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    feedback = resp.choices[0].message.content.strip()

    # very naive parse: first number found = score
    import re
    match = re.search(r"(\d{1,3})", feedback)
    score = int(match.group(1)) if match else 0

    return score, feedback

# =========================
# STREAMLIT UI
# =========================
st.title("📘 Student Marking Dashboard")

# 🔹 Select student
student_code = st.selectbox("Select Student Code", students_df["studentcode"].unique())
student_name = students_df.loc[students_df["studentcode"] == student_code, "name"].values[0]

# 🔹 Load submissions from Firebase
submissions = get_student_submissions(student_code)

st.subheader("📝 Submissions")
if submissions:
    for i, sub in enumerate(submissions, start=1):
        st.markdown(f"**Draft {i}:**")
        st.code(sub.get("content", ""), language="markdown")
else:
    st.warning("No submissions found in Firebase.")

# 🔹 Select assignment (reference answer sheet)
assignment = st.selectbox("Select Assignment", refs_df["assignment"].unique())
ref_row = refs_df.loc[refs_df["assignment"] == assignment]
reference_answer = " ".join([str(v) for v in ref_row.filter(like="Answer").values[0] if pd.notna(v)])
sheet_link = ref_row["sheet_url"].values[0] if not ref_row.empty else ""

st.subheader("✅ Reference Answer")
st.code(reference_answer, language="markdown")

# =========================
# MANUAL MARKING
# =========================
st.subheader("✍️ Manual Marking")
score = st.number_input("Enter Score", min_value=0, max_value=100, step=1)
feedback = st.text_area("Enter Feedback (manual)")

if st.button("💾 Save Manual Mark"):
    row = {
        "studentcode": student_code,
        "name": student_name,
        "assignment": assignment,
        "score": score,
        "comments": feedback,
        "date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "level": "",  # optional
        "link": sheet_link
    }
    resp = save_to_sheet(row)
    st.success(f"✅ Saved to sheet: {resp}")

# =========================
# AI MARKING
# =========================
st.subheader("🤖 AI Marking")
if st.button("🔮 Let AI Mark"):
    if submissions:
        # take latest draft
        student_answer = submissions[-1].get("content", "")
        ai_score, ai_feedback = ai_mark(student_answer, reference_answer)

        st.write("**AI Score:**", ai_score)
        st.write("**AI Feedback:**", ai_feedback)

        row = {
            "studentcode": student_code,
            "name": student_name,
            "assignment": assignment,
            "score": ai_score,
            "comments": ai_feedback,
            "date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": "",
            "link": sheet_link
        }
        resp = save_to_sheet(row)
        st.success(f"✅ AI result saved to sheet: {resp}")
    else:
        st.error("No student submission found to mark.")
