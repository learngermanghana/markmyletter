import streamlit as st
from datetime import datetime
from typing import Any, Dict, List

try:
    from streamlit_autorefresh import st_autorefresh
except Exception:  # pragma: no cover
    def st_autorefresh(*args, **kwargs):
        return None

import firebase_admin
from firebase_admin import credentials, firestore

if not firebase_admin._apps:
    fb_cfg = st.secrets.get("firebase")
    if fb_cfg:
        cred = credentials.Certificate(dict(fb_cfg))
        firebase_admin.initialize_app(cred)

db = firestore.client() if firebase_admin._apps else None


def extract_text_from_doc(doc: Dict[str, Any]) -> str:
    preferred = ["content", "text", "answer", "body", "draft", "message"]
    for k in preferred:
        v = doc.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list):
            parts = []
            for item in v:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    for kk in ["text", "content", "value"]:
                        if kk in item and isinstance(item[kk], str):
                            parts.append(item[kk])
            if parts:
                return "\n".join(parts).strip()
        if isinstance(v, dict):
            for kk in ["text", "content", "value"]:
                vv = v.get(kk)
                if isinstance(vv, str) and vv.strip():
                    return vv.strip()
    strings = [str(v).strip() for v in doc.values() if isinstance(v, str) and str(v).strip()]
    return "\n".join(strings).strip()


def fetch_submissions(student_code: str) -> List[Dict[str, Any]]:
    if not db or not student_code:
        return []
    items: List[Dict[str, Any]] = []

    def pull(coll: str):
        try:
            for snap in db.collection("drafts_v2").document(student_code).collection(coll).stream():
                d = snap.to_dict() or {}
                d["id"] = snap.id
                items.append(d)
        except Exception:
            pass

    pull("lessons")
    if not items:
        pull("lessens")
    return items


def fetch_all_submissions() -> List[Dict[str, Any]]:
    """Fetch submissions for all students under ``drafts_v2``.

    Each entry in the returned list contains a ``student_code`` identifying the
    source document along with the submission data.
    """
    if not db:
        return []

    items: List[Dict[str, Any]] = []
    try:
        for doc in db.collection("drafts_v2").stream():
            code = doc.id
            for coll in ["lessons", "lessens"]:
                try:
                    for snap in doc.reference.collection(coll).stream():
                        d = snap.to_dict() or {}
                        d["id"] = snap.id
                        d["student_code"] = code
                        items.append(d)
                except Exception:
                    pass
    except Exception:
        pass
    return items


st.title("New Drafts")
st_autorefresh(interval=5000, key="new_drafts_refresh")

subs = fetch_all_submissions()
if not subs:
    st.info("No drafts found.")
else:
    subs = sorted(subs, key=lambda d: d.get("timestamp", 0), reverse=True)
    if st.checkbox("Show as table"):
        import pandas as pd
        st.dataframe(pd.DataFrame(subs))
    else:
        for doc in subs:
            ts = doc.get("timestamp", "")
            if isinstance(ts, (int, float)):
                ts_str = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M:%S")
            else:
                ts_str = str(ts)
            lesson = doc.get("lesson") or doc.get("assignment") or ""
            student_code = doc.get("student_code", "")
            content = extract_text_from_doc(doc)
            with st.container():
                st.markdown(f"**{ts_str} — {lesson} — {student_code}**")
                st.markdown(content or "(empty)")
