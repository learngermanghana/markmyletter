"""Streamlit page that lets students save drafts and submit course book work."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import streamlit as st
from firebase_admin import firestore

from firebase_utils import get_firestore_client, load_student_draft, save_student_draft

st.set_page_config(page_title="Course book submission", page_icon="📝")

st.title("My course → Course book → Submit")
st.caption(
    "Save a working draft of your writing or submit the final version for your teacher."
)

# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------
CODE_KEY = "coursebook_submit_student_code"
LEVEL_KEY = "coursebook_submit_level"
NAME_KEY = "coursebook_submit_name"
CHAPTER_KEY = "coursebook_submit_chapter"
ASSIGNMENT_KEY = "coursebook_submit_assignment"
CONTENT_KEY = "coursebook_submit_content"
NOTES_KEY = "coursebook_submit_notes"
LOADED_KEY = "coursebook_submit_loaded_signature"
INFO_KEY = "coursebook_submit_info"

STATE_DEFAULTS = {
    CODE_KEY: "",
    LEVEL_KEY: "",
    NAME_KEY: "",
    CHAPTER_KEY: "",
    ASSIGNMENT_KEY: "",
    CONTENT_KEY: "",
    NOTES_KEY: "",
    LOADED_KEY: None,
    INFO_KEY: None,
}

for key, default in STATE_DEFAULTS.items():
    st.session_state.setdefault(key, default)


def _as_str(value: Optional[Any]) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


# ---------------------------------------------------------------------------
# Draft loading (runs before widgets are rendered so they display loaded values)
# ---------------------------------------------------------------------------
student_code_clean = st.session_state[CODE_KEY].strip()
level_clean = st.session_state[LEVEL_KEY].strip()
signature = f"{level_clean}::{student_code_clean}" if level_clean and student_code_clean else None

if signature and st.session_state.get(LOADED_KEY) != signature:
    draft = load_student_draft(level_clean, student_code_clean)
    st.session_state[LOADED_KEY] = signature
    if draft:
        st.session_state[CONTENT_KEY] = _as_str(draft.get("content"))
        st.session_state[NOTES_KEY] = _as_str(draft.get("notes"))
        for key, source in [
            (NAME_KEY, draft.get("student_name")),
            (CHAPTER_KEY, draft.get("chapter")),
            (ASSIGNMENT_KEY, draft.get("assignment")),
        ]:
            value = _as_str(source).strip()
            if value:
                st.session_state[key] = value
        st.session_state[INFO_KEY] = "Loaded your saved draft."
    else:
        st.session_state[CONTENT_KEY] = ""
        st.session_state[NOTES_KEY] = ""
        st.session_state[INFO_KEY] = None


# ---------------------------------------------------------------------------
# Form UI
# ---------------------------------------------------------------------------
col_left, col_right = st.columns(2)
with col_left:
    st.text_input("Student name", key=NAME_KEY)
    st.text_input("Chapter / unit", key=CHAPTER_KEY)
with col_right:
    st.text_input("Student code", key=CODE_KEY)
    st.text_input("Course level", key=LEVEL_KEY)

st.text_input("Assignment / task", key=ASSIGNMENT_KEY)

st.text_area("Course book entry", height=320, key=CONTENT_KEY)
st.text_area("Notes for your teacher (optional)", height=120, key=NOTES_KEY)

if st.session_state.get(INFO_KEY):
    st.info(st.session_state[INFO_KEY])

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
student_name = st.session_state[NAME_KEY].strip()
chapter = st.session_state[CHAPTER_KEY].strip()
assignment = st.session_state[ASSIGNMENT_KEY].strip()
content = st.session_state[CONTENT_KEY]
notes = st.session_state[NOTES_KEY]

student_code_clean = st.session_state[CODE_KEY].strip()
level_clean = st.session_state[LEVEL_KEY].strip()

payload: Dict[str, Any] = {
    "student_name": student_name,
    "chapter": chapter,
    "assignment": assignment,
    "content": content,
    "notes": notes,
    "status": "draft",
    "updated_at_local": datetime.utcnow().isoformat() + "Z",
    "source": "coursebook_submit_page",
}

def _clear_loaded_signature() -> None:
    st.session_state[LOADED_KEY] = None


save_disabled = not (level_clean and student_code_clean)
submit_disabled = not (level_clean and student_code_clean and content.strip())

cols = st.columns(2)
with cols[0]:
    if st.button("💾 Save draft", disabled=save_disabled):
        result = save_student_draft(level_clean, student_code_clean, payload)
        if result.get("ok"):
            st.success("Draft saved to Firestore.")
            st.session_state[INFO_KEY] = "Draft saved just now."
            _clear_loaded_signature()
        else:
            error = result.get("error", "unknown_error")
            st.error(f"Unable to save draft ({error}).")
with cols[1]:
    if st.button("🚀 Submit to teacher", type="primary", disabled=submit_disabled):
        if not content.strip():
            st.error("Please add your course book entry before submitting.")
        else:
            db = get_firestore_client()
            if not db:
                st.error("Firestore is not configured. Please contact your teacher.")
            else:
                post_data = dict(payload)
                post_data.update(
                    {
                        "student_code": student_code_clean,
                        "level": level_clean,
                        "status": "submitted",
                        "submitted_at": firestore.SERVER_TIMESTAMP,
                    }
                )
                try:
                    (
                        db.collection("submissions")
                        .document(level_clean)
                        .collection("posts")
                        .add(post_data)
                    )
                    st.success("Submission sent! 🎉")
                    try:
                        (
                            db.collection("submissions")
                            .document(level_clean)
                            .collection("draftv2")
                            .document(student_code_clean)
                            .delete()
                        )
                    except Exception:
                        pass
                    st.session_state[CONTENT_KEY] = ""
                    st.session_state[NOTES_KEY] = ""
                    st.session_state[INFO_KEY] = None
                    _clear_loaded_signature()
                except Exception as exc:
                    st.error(f"Failed to submit: {exc}")

st.caption("Drafts auto-fill whenever you revisit this page with the same level and code.")
