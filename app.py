import os, json, requests
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore

# =========================
# CONFIGURATION
# =========================
APP_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbzKWo9IblWZEgD_d7sku6cGzKofis_XQj3NXGMYpf_uRqu9rGe4AvOcB15E3bb2e6O4/exec"
WEBHOOK_TOKEN = "Xenomexpress7727/"

REF_ANSWERS_SHEET_URL = "https://docs.google.com/spreadsheets/d/1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo/export?format=csv"
STUDENTS_SHEET_URL = "https://docs.google.com/spreadsheets/d/12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U/export?format=csv"

# =========================
# LOAD SHEETS
# =========================
@st.cache_data
def load_students():
    return pd.read_csv(STUDENTS_SHEET_URL)

@st.cache_data
def load_references():
    return pd.read_csv(REF_ANSWERS_SHEET_URL)

students_df = load_students()
refs_df = load_references()

# =========================
# FIREBASE
# =========================
if not firebase_admin._apps:
    cred = credentials.Certificate(json.loads(os.environ["FIREBASE_KEY"]))
    firebase_admin.initialize_app(cred)

db = firestore.client()

def get_student_submissions(student_code: str):
    """Fetch all submissions under drafts_v2/{student_code}/lessons"""
    docs = db.collection("drafts_v2").document(student_code).collection("lessons").stream()
    return {doc.id: doc.to_dict() for doc in docs}

# =========================
# STREAMLIT UI
# =========================
st.title("📘 Student Marking Dashboard")

# Select student code
student_code = st.selectbox("Select Student Code", students_df["studentcode"].unique())

if student_code:
    # Load Firestore submissions
    submissions = get_student_submissions(student_code)

    # Show submissions
    st.subheader("📝 Student Submissions")
    if submissions:
        for key, sub in submissions.items():
            st.markdown(f"**{key}**")
            st.code(sub.get("content", ""), language="markdown")
    else:
        st.warning("No submissions found.")

    # Choose assignment from reference sheet
    st.subheader("✅ Reference Answer")
    assignment = st.selectbox("Select Assignment", refs_df["assignment"].unique())
    ref_row = refs_df.loc[refs_df["assignment"] == assignment]
    if not ref_row.empty:
        answers = ref_row.drop(columns=["assignment"]).T.dropna()
        ref_text = "\n".join([f"{idx}: {val}" for idx, val in answers[ref_row.index[0]].items()])
    else:
        ref_text = "No reference answer found."
    st.code(ref_text, language="markdown")

    # Marking inputs
    st.subheader("📊 Marking")
    score = st.number_input("Score", min_value=0, max_value=100, step=1)
    comments = st.text_area("Comments")
    level = st.text_input("Level (optional)")
    link = st.text_input("Link (optional)")

    if st.button("💾 Save Result"):
        # Get student name
        student_row = students_df.loc[students_df["studentcode"] == student_code]
        student_name = student_row["name"].values[0] if not student_row.empty else ""

        # Prepare row in correct order
        row = {
            "studentcode": student_code,
            "name": student_name,
            "assignment": assignment,
            "score": score,
            "comments": comments,
            "date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "link": link
        }

        # Send to App Script webhook
        payload = {"token": WEBHOOK_TOKEN, "row": row}
        try:
            result = requests.post(APP_SCRIPT_URL, json=payload).json()
            if result.get("ok"):
                st.success(f"✅ Saved score for {student_code} → {assignment}")
            else:
                st.error(f"❌ Failed: {result}")
        except Exception as e:
            st.error(f"Error sending to webhook: {e}")
