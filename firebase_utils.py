import streamlit as st
from datetime import datetime
from typing import Any, Dict, List, Optional

import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Firebase if needed and expose a Firestore client
if not firebase_admin._apps:
    fb_cfg = st.secrets.get("firebase")
    if fb_cfg:
        cred = credentials.Certificate(dict(fb_cfg))
        firebase_admin.initialize_app(cred)

db = firestore.client() if firebase_admin._apps else None


def extract_text_from_doc(doc: Dict[str, Any]) -> str:
    """Best-effort extraction of text content from heterogeneous docs."""
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


def extract_ts_ms(doc: Dict[str, Any]) -> int:
    """Return timestamp in milliseconds; accepts many Firestore/time shapes."""
    ts: Optional[Any] = doc.get("timestamp")
    if ts is None:
        ts = doc.get("_meta_ts")

    try:
        # Numeric (ms or s)
        if isinstance(ts, (int, float)):
            return int(ts if ts > 10_000_000_000 else ts * 1000)

        # datetime
        if isinstance(ts, datetime):
            return int(ts.timestamp() * 1000)

        # Firestore Timestamp-like
        if hasattr(ts, "to_datetime") and callable(ts.to_datetime):
            return int(ts.to_datetime().timestamp() * 1000)
        if hasattr(ts, "seconds") and hasattr(ts, "nanoseconds"):
            return int(int(ts.seconds) * 1000 + int(ts.nanoseconds) / 1_000_000)
        if hasattr(ts, "timestamp") and callable(ts.timestamp):
            return int(ts.timestamp() * 1000)

        # Dict-ish ({"_seconds": ...})
        if isinstance(ts, dict):
            if "_seconds" in ts:
                seconds = int(ts.get("_seconds", 0))
                nanos = int(ts.get("_nanoseconds", 0))
                return int(seconds * 1000 + nanos / 1_000_000)
            for key in ("iso", "time", "date", "datetime"):
                if key in ts and isinstance(ts[key], str):
                    try:
                        return int(datetime.fromisoformat(ts[key]).timestamp() * 1000)
                    except Exception:
                        pass

        # ISO string
        if isinstance(ts, str):
            try:
                return int(datetime.fromisoformat(ts).timestamp() * 1000)
            except Exception:
                pass
    except Exception:
        pass
    return 0


def fetch_submissions(student_code: str) -> List[Dict[str, Any]]:
    """Return submissions under drafts_v2/<student_code>/lessons."""
    if not db or not student_code:
        return []
    items: List[Dict[str, Any]] = []

    def pull(coll: str) -> None:
        try:
            for snap in db.collection("drafts_v2").document(student_code).collection(coll).stream():
                d = snap.to_dict() or {}
                d["id"] = snap.id
                d["_ts_ms"] = extract_ts_ms(d)
                items.append(d)
        except Exception:
            pass

    pull("lessons")
    if not items:
        pull("lessens")

    items.sort(key=lambda d: d.get("_ts_ms", 0), reverse=True)
    return items


def fetch_all_submissions() -> List[Dict[str, Any]]:
    """Collect all docs from ANY student's `lessons` subcollection using collection_group."""
    if not db:
        return []

    items: List[Dict[str, Any]] = []
    try:
        for snap in db.collection_group("lessons").stream():
            d = snap.to_dict() or {}
            d["id"] = snap.id

            # Parent of 'lessons' is the student document
            try:
                parent_doc = snap.reference.parent.parent
                if parent_doc:
                    d["student_code"] = parent_doc.id
            except Exception:
                pass

            if not d.get("timestamp"):
                meta_ts = getattr(snap, "update_time", None) or getattr(snap, "create_time", None)
                if meta_ts:
                    d["_meta_ts"] = meta_ts

            items.append(d)
    except Exception as e:
        st.error(f"collection_group('lessons') failed: {e}")
    return items
