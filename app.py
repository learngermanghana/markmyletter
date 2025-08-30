import os, json
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from google.oauth2.service_account import Credentials
import gspread

# =========================
# GOOGLE SHEETS
# =========================
def get_gsheet_client():
    creds_dict = json.loads(os.environ["G_SHEETS_KEY"])  # updated name
    scope = ["https://spreadsheets.google.com/feeds",
             "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    return gspread.authorize(creds)

gs_client = get_gsheet_client()

# =========================
# FIREBASE
# =========================
if not firebase_admin._apps:
    cred = credentials.Certificate(json.loads(os.environ["FIREBASE_KEY"]))  # updated name
    firebase_admin.initialize_app(cred)

db = firestore.client()

# =========================
# CONFIGURATION
# =========================
STUDENTS_SHEET_ID = "12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U"
REF_ANSWERS_SHEET_ID = "1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo"
SCORES_SHEET_ID = "1BRb8p3Rq0VpFCLSwL4eS9tSgXBo9hSWzfW_J_7W36NQ"

# =========================
# GOOGLE SHEETS SETUP
# =========================
def get_gsheet_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = json.loads(os.environ["GOOGLE_SHEETS_JSON"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    return gspread.authorize(creds)

gs_client = get_gsheet_client()

def load_students():
    ws = gs_client.open_by_key(STUDENTS_SHEET_ID).sheet1
    return pd.DataFrame(ws.get_all_records())

def load_references():
    ws = gs_client.open_by_key(REF_ANSWERS_SHEET_ID).sheet1
    return pd.DataFrame(ws.get_all_records())

def save_score(student, score, feedback):
    ws = gs_client.open_by_key(SCORES_SHEET_ID).sheet1
    ws.append_row([student, score, feedback])

# =========================
# FIRESTORE SETUP
# =========================
if not firebase_admin._apps:
    firebase_creds = json.loads(os.environ["FIREBASE_JSON"])
    cred = credentials.Certificate(firebase_creds)
    firebase_admin.initialize_app(
        cred,
        {"storageBucket": firebase_creds.get("storage_bucket")}
    )
db = firestore.client()

def get_student_submission(student_id: str):
    """Fetch all submissions under drafts_v2/{student_id}/lessons"""
    doc_ref = db.collection("drafts_v2").document(student_id).collection("lessons")
    docs = doc_ref.stream()
    return [d.to_dict() for d in docs]

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
        save_score(student_name, score, feedback)
        st.success("✅ Score & feedback saved to Google Sheet")
