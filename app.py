# app.py
import os
import re
import json
from datetime import datetime
from typing import Dict, Any

import streamlit as st
try:
    from streamlit_autorefresh import st_autorefresh
except Exception:  # pragma: no cover - allow running without plugin
    def st_autorefresh(*args, **kwargs):
        return None

from utils.data_sources import (
    load_sheet_csv,
    load_answers_dictionary,
    fetch_submissions,
    extract_text_from_doc,
    save_row_to_scores,
)
from utils.answer_utils import (
    find_col,
    list_sheet_assignments,
    build_reference_text_from_sheet,
    list_json_assignments,
    build_reference_text_from_json,
    filter_any,
)

# ---------------- IDs / Config ----------------
# Students Google Sheet (tab now "Sheet1" unless you override in secrets)
STUDENTS_SHEET_ID   = "12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U"
STUDENTS_SHEET_TAB  = st.secrets.get("STUDENTS_SHEET_TAB", "Sheet1")

# Reference Google Sheet (answers) and tab name (default Sheet1)
REF_ANSWERS_SHEET_ID = "1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo"
REF_ANSWERS_TAB      = st.secrets.get("REF_ANSWERS_TAB", "Sheet1")


# Default reference source: "json" or "sheet" (configurable via Streamlit
# secrets or environment variable "ANSWER_SOURCE")
ANSWER_SOURCE = (
    st.secrets.get("ANSWER_SOURCE")
    or os.environ.get("ANSWER_SOURCE", "")
).lower()
if ANSWER_SOURCE not in ("json", "sheet"):
    ANSWER_SOURCE = ""

# =========================================================
# UI
# =========================================================
st.set_page_config(page_title="📘 Marking Dashboard", page_icon="📘", layout="wide")
st.title("📘 Marking Dashboard")

if st.button("🔄 Refresh caches"):
    st.cache_data.clear()
    st.rerun()

# --- Load students
students_df = load_sheet_csv(STUDENTS_SHEET_ID, STUDENTS_SHEET_TAB)
code_col  = find_col(students_df, ["studentcode", "student_code", "code"], default="studentcode")
name_col  = find_col(students_df, ["name", "fullname"], default="name")
level_col = find_col(students_df, ["level"], default="level")

# Pick student
st.subheader("1) Pick Student")
q = st.text_input("Search student (code / name / any field)")
df_filtered = filter_any(students_df, q)
if df_filtered.empty:
    st.warning("No students match your search.")
    st.stop()

labels = [f"{r.get(code_col,'')} — {r.get(name_col,'')} ({r.get(level_col,'')})" for _, r in df_filtered.iterrows()]
choice = st.selectbox("Select student", labels)
srow = df_filtered.iloc[labels.index(choice)]
studentcode = str(srow.get(code_col,"")).strip()
student_name = str(srow.get(name_col,"")).strip()
student_level = str(srow.get(level_col,"")).strip()

c1, c2 = st.columns(2)
with c1: st.text_input("Name (auto)",  value=student_name,  disabled=True)
with c2: st.text_input("Level (auto)", value=student_level, disabled=True)

# ---------------- Reference chooser (Tabs) ----------------
st.subheader("2) Reference source")

# Session holder for the *chosen* reference
if "ref_source" not in st.session_state:
    st.session_state.ref_source = ANSWER_SOURCE or None
if "ref_assignment" not in st.session_state:
    st.session_state.ref_assignment = ""
if "ref_text" not in st.session_state:
    st.session_state.ref_text = ""
if "ref_link" not in st.session_state:
    st.session_state.ref_link = ""
if "ref_format" not in st.session_state:
    st.session_state.ref_format = "essay"
if "ref_answers" not in st.session_state:
    st.session_state.ref_answers = {}

tab_titles = ["📦 JSON dictionary", "🔗 Google Sheet"]
if st.session_state.ref_source == "sheet":
    tab_sheet, tab_json = st.tabs(tab_titles[::-1])
else:
    tab_json, tab_sheet = st.tabs(tab_titles)

# ---- JSON tab
with tab_json:
    ans_dict = load_answers_dictionary()
    if not ans_dict:
        st.info("answers_dictionary.json not found in repo.")
    else:
        all_assignments_json = list_json_assignments(ans_dict)
        st.caption(f"{len(all_assignments_json)} assignments in JSON")
        qj = st.text_input("Search assignment (JSON)", key="search_json")
        pool_json = [a for a in all_assignments_json if qj.lower() in a.lower()] if qj else all_assignments_json
        pick_json = st.selectbox("Select assignment (JSON)", pool_json, key="pick_json")
        ref_text_json, link_json, fmt_json, ans_map_json = build_reference_text_from_json(
            ans_dict.get(pick_json, {})
        )
        st.markdown("**Reference preview (JSON):**")
        st.code(ref_text_json or "(none)", language="markdown")
        st.caption(f"Format: {fmt_json}")
        if link_json:
            st.caption(f"Reference link: {link_json}")
        if st.button("✅ Use this JSON reference"):
            st.session_state.ref_source = "json"
            st.session_state.ref_assignment = pick_json
            st.session_state.ref_text = ref_text_json
            st.session_state.ref_link = link_json
            st.session_state.ref_format = fmt_json
            st.session_state.ref_answers = ans_map_json
            st.success("Using JSON reference")

# ---- Sheet tab
with tab_sheet:
    ref_df = load_sheet_csv(REF_ANSWERS_SHEET_ID, REF_ANSWERS_TAB)
    try:
        assign_col = find_col(ref_df, ["assignment"])
    except KeyError:
        st.error("The reference sheet must have an 'assignment' column.")
        assign_col = None
    if assign_col:
        all_assignments_sheet = list_sheet_assignments(ref_df, assign_col)
        st.caption(f"{len(all_assignments_sheet)} assignments in sheet tab “{REF_ANSWERS_TAB}”")
        qs = st.text_input("Search assignment (Sheet)", key="search_sheet")
        pool_sheet = [a for a in all_assignments_sheet if qs.lower() in a.lower()] if qs else all_assignments_sheet
        pick_sheet = st.selectbox("Select assignment (Sheet)", pool_sheet, key="pick_sheet")
        (
            ref_text_sheet,
            link_sheet,
            fmt_sheet,
            ans_map_sheet,
        ) = build_reference_text_from_sheet(ref_df, assign_col, pick_sheet)
        st.markdown("**Reference preview (Sheet):**")
        st.code(ref_text_sheet or "(none)", language="markdown")
        st.caption(f"Format: {fmt_sheet}")
        if link_sheet:
            st.caption(f"Reference link: {link_sheet}")
        if st.button("✅ Use this SHEET reference"):
            st.session_state.ref_source = "sheet"
            st.session_state.ref_assignment = pick_sheet
            st.session_state.ref_text = ref_text_sheet
            st.session_state.ref_link = link_sheet
            st.session_state.ref_format = fmt_sheet
            st.session_state.ref_answers = ans_map_sheet
            st.success("Using Sheet reference")

# Ensure default reference choice based on config/availability
if st.session_state.ref_source == "json" and not load_answers_dictionary():
    st.session_state.ref_source = None
if st.session_state.ref_source == "sheet":
    try:
        find_col(load_sheet_csv(REF_ANSWERS_SHEET_ID, REF_ANSWERS_TAB), ["assignment"])
    except Exception:
        st.session_state.ref_source = None

if not st.session_state.ref_source:
    if load_answers_dictionary():
        st.session_state.ref_source = "json"
    else:
        try:
            find_col(load_sheet_csv(REF_ANSWERS_SHEET_ID, REF_ANSWERS_TAB), ["assignment"])
            st.session_state.ref_source = "sheet"
        except Exception:
            pass

if st.session_state.ref_source == "json" and not st.session_state.ref_assignment:
    ans = load_answers_dictionary()
    if ans:
        first = list_json_assignments(ans)[0]
        txt, ln, fmt, ans_map = build_reference_text_from_json(ans[first])
        st.session_state.ref_assignment = first
        st.session_state.ref_text = txt
        st.session_state.ref_link = ln
        st.session_state.ref_format = fmt
        st.session_state.ref_answers = ans_map
elif st.session_state.ref_source == "sheet" and not st.session_state.ref_assignment:
    ref_df_tmp = load_sheet_csv(REF_ANSWERS_SHEET_ID, REF_ANSWERS_TAB)
    try:
        ac = find_col(ref_df_tmp, ["assignment"])
        first = list_sheet_assignments(ref_df_tmp, ac)[0]
        txt, ln, fmt, ans_map = build_reference_text_from_sheet(ref_df_tmp, ac, first)
        st.session_state.ref_assignment = first
        st.session_state.ref_text = txt
        st.session_state.ref_link = ln
        st.session_state.ref_format = fmt
        st.session_state.ref_answers = ans_map
    except Exception:
        pass

st.info(
    f"Currently using **{st.session_state.ref_source or '—'}** reference → **{st.session_state.ref_assignment or '—'}** (format: {st.session_state.ref_format})"
)

# ---------------- Submissions & Marking ----------------
st.subheader("3) Student submission (Firestore)")
student_text = ""
tab_subs, tab_new = st.tabs(["Submissions", "New drafts"])

with tab_subs:
    subs = fetch_submissions(studentcode)
    if not subs:
        st.warning(
            "No submissions found under drafts_v2/{code}/lessons (or lessens)."
        )
    else:
        def label_for(d: Dict[str, Any]) -> str:
            txt = extract_text_from_doc(d)
            preview = (txt[:80] + "…") if len(txt) > 80 else txt
            ts = datetime.fromtimestamp(d.get("_ts_ms", 0) / 1000).strftime("%Y-%m-%d %H:%M")
            return f"{ts} • {d.get('id','(no-id)')} • {preview}"

        labels_sub = [label_for(d) for d in subs]
        pick = st.selectbox("Pick submission", labels_sub)
        student_text = extract_text_from_doc(subs[labels_sub.index(pick)])

with tab_new:
    st_autorefresh(interval=5000, key="draft_refresh")
    subs = fetch_submissions(studentcode)
    if not subs:
        st.info("No drafts yet.")
    else:
        latest = subs[0]
        latest_text = extract_text_from_doc(latest)
        st.markdown("**Newest Draft**")
        st.code(latest_text or "(empty)", language="markdown")
        st.caption(
            datetime.fromtimestamp(latest.get("_ts_ms", 0) / 1000).strftime("%Y-%m-%d %H:%M")
        )

st.markdown("**Student Submission**")
st.code(student_text or "(empty)", language="markdown")

st.markdown("**Reference Answer (chosen)**")
st.code(st.session_state.ref_text or "(not set)", language="markdown")
st.caption(f"Format: {st.session_state.ref_format}")
if st.session_state.ref_link:
    st.caption(f"Reference link: {st.session_state.ref_link}")

# Combined copy block
st.subheader("4) Combined (copyable)")
combined = f"""# Student Submission
{student_text}

# Reference Answer
{st.session_state.ref_text}
"""
st.text_area("Combined", value=combined, height=200)

# Manual scoring
if "ai_score" not in st.session_state:
    st.session_state.ai_score = 0
if "feedback" not in st.session_state:
    st.session_state.feedback = ""

if st.button("Reset"):
    st.session_state.ai_score = 0
    st.session_state.feedback = ""

score = st.number_input("Score", 0, 100, value=int(st.session_state.ai_score))
st.session_state.ai_score = score

feedback = st.text_area("Feedback", key="feedback", height=80)

# Save to Scores
st.subheader("5) Save to Scores sheet")
if st.button("💾 Save", type="primary", use_container_width=True):
    if not studentcode:
        st.error("Pick a student first.")
    elif not st.session_state.ref_assignment:
        st.error("Pick a reference (JSON or Sheet) and click its 'Use this … reference' button.")
    elif not feedback.strip():
        st.error("Feedback is required.")
    else:
        try:
            studentcode_val = int(studentcode)
        except ValueError:
            studentcode_val = studentcode

        row = {
            "studentcode": studentcode_val,
            "name":        student_name,
            "assignment":  st.session_state.ref_assignment,
            "score":       int(score),
            "comments":    feedback.strip(),
            "date":        datetime.now().strftime("%Y-%m-%d"),
            "level":       student_level,
            "link":        st.session_state.ref_link,  # uses answer_url only
        }

        result = save_row_to_scores(row)
        if result.get("ok"):
            st.success("✅ Saved to Scores sheet.")
        elif result.get("why") == "validation":
            field = result.get("field")
            if field:
                st.error(f"❌ Sheet blocked the write due to data validation ({field}).")
            else:
                st.error("❌ Sheet blocked the write due to data validation.")
                if result.get("raw"):
                    st.caption(result["raw"])
        else:
            st.error(f"❌ Failed to save: {result}")
