import os
import re
import json
from datetime import datetime, timedelta
import streamlit as st
import pandas as pd
import requests
import pyperclip  # To copy text to clipboard

# webhook to Google Sheets
# Firebase Admin
import firebase_admin
from firebase_admin import credentials, firestore, storage

st.set_page_config(page_title="Falowen Marking Tab", layout="wide")

# Define the select_student function
def select_student(df_students):
    """Select a student and resolve Firestore document."""
    name_col = col_lookup(df_students, "name")
    code_col = col_lookup(df_students, "studentcode")
    if not name_col or not code_col:
        st.error("Required columns 'name' or 'studentcode' not found in students sheet.")
        return None, None, None, None

    st.subheader("1) Search & Select Student")
    with st.form("marking_student_form"):
        search_student = st.text_input("Type student name or code...", key="tab7_search_student")
        submitted_student = st.form_submit_button("Apply")

    if submitted_student and search_student:
        mask = (
            df_students[name_col].astype(str).str.contains(search_student, case=False, na=False)
            | df_students[code_col].astype(str).str.contains(search_student, case=False, na=False)
        )
        students_filtered = df_students[mask].copy()
    else:
        students_filtered = df_students.copy()

    if students_filtered.empty:
        st.info("No students match your search. Try a different query.")
        st.stop()

    codes = students_filtered[code_col].astype(str).tolist()
    code_to_name = dict(zip(students_filtered[code_col].astype(str), students_filtered[name_col].astype(str)))

    def _fmt_student(code: str):
        return f"{code_to_name.get(code, 'Unknown')} ({code})"

    selected_student_code = st.selectbox("Select Student", codes, format_func=_fmt_student, key="tab7_selected_code")
    if not selected_student_code:
        st.warning("Select a student to continue.")
        st.stop()

    sel_rows = students_filtered[students_filtered[code_col] == selected_student_code]
    if sel_rows.empty:
        st.warning("Selected student not found.")
        st.stop()
    student_row = sel_rows.iloc[0]
    student_code = selected_student_code
    student_name = str(student_row.get(name_col, "")).strip()

    st.markdown(f"**Selected:** {student_name} ({student_code})")
    st.subheader("Student Code")
    st.code(student_code)

    return student_code, student_name, student_row

# Your other functions go here...

# UI: MARKING TAB
def render_marking_tab():
    _ensure_firebase_clients()

    st.title("📝 Reference & Student Work Share")

    try:
        df_students = load_marking_students(STUDENTS_CSV_URL)
    except Exception as e:
        st.error(f"Could not load students: {e}")
        return

    try:
        ref_df = load_marking_ref_answers(REF_ANSWERS_URL)
        if "assignment" not in ref_df.columns:
            st.warning("No 'assignment' column found in reference answers sheet.")
            return
    except Exception as e:
        st.error(f"Could not load reference answers: {e}")
        return

    student_code, student_name, student_row = select_student(df_students)
    chosen_row = choose_submission(student_code)
    assignment, answers_combined_str, ref_link_value = pick_reference(ref_df)
    one_row = mark_submission(
        student_code,
        student_name,
        student_row,
        chosen_row,
        assignment,
        answers_combined_str,
        ref_link_value,
    )

    # Add Copy button for the final content
    combined_content = f"Assignment: {assignment}\nScore: {one_row['score']}\nFeedback: {one_row['comments']}"
    display_copy_button(combined_content)

    # Attempt to send the data to Google Sheets
    try:
        export_row(one_row)
    except Exception as e:
        st.error(f"Failed to send: {e}")

if __name__ == "__main__":
    render_marking_tab()
