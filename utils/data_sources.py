import os
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Firestore
if not firebase_admin._apps:
    fb_cfg = st.secrets.get("firebase")
    if fb_cfg:
        cred = credentials.Certificate(dict(fb_cfg))
        firebase_admin.initialize_app(cred)

db = firestore.client() if firebase_admin._apps else None

# Paths for answers dictionary JSON
ANSWERS_JSON_PATHS = [
    "answers_dictionary.json",
    "data/answers_dictionary.json",
    "assets/answers_dictionary.json",
]

# Apps Script webhook configuration
WEBHOOK_URL = st.secrets.get(
    "G_SHEETS_WEBHOOK_URL",
    "https://script.google.com/macros/s/AKfycbzKWo9IblWZEgD_d7sku6cGzKofis_XQj3NXGMYpf_uRqu9rGe4AvOcB15E3bb2e6O4/exec",
)
WEBHOOK_TOKEN = st.secrets.get("G_SHEETS_WEBHOOK_TOKEN", "Xenomexpress7727/")


@st.cache_data(show_spinner=False, ttl=300)
def load_sheet_csv(sheet_id: str, tab: str) -> pd.DataFrame:
    """Load a specific Google Sheet tab as CSV (no auth)."""
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"
        f"?tqx=out:csv&sheet={requests.utils.quote(tab)}"
        "&tq=select%20*%20limit%20100000"
    )
    df = pd.read_csv(url, dtype=str)
    df.columns = df.columns.str.strip().str.lower()
    return df


@st.cache_data(show_spinner=False)
def load_answers_dictionary() -> Dict[str, Any]:
    for p in ANSWERS_JSON_PATHS:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    return {}


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

    def _ts_ms(doc: Dict[str, Any]) -> int:
        """Best-effort extraction of timestamp in milliseconds."""
        ts: Optional[Any] = doc.get("timestamp")
        try:
            if isinstance(ts, (int, float)):
                return int(ts if ts > 10_000_000_000 else ts * 1000)
            if isinstance(ts, datetime):
                return int(ts.timestamp() * 1000)
            if hasattr(ts, "to_datetime") and callable(ts.to_datetime):
                return int(ts.to_datetime().timestamp() * 1000)
            if hasattr(ts, "seconds") and hasattr(ts, "nanoseconds"):
                return int(int(ts.seconds) * 1000 + int(ts.nanoseconds) / 1_000_000)
            if hasattr(ts, "timestamp") and callable(ts.timestamp):
                return int(ts.timestamp() * 1000)
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
            if isinstance(ts, str):
                try:
                    return int(datetime.fromisoformat(ts).timestamp() * 1000)
                except Exception:
                    pass
        except Exception:
            pass
        return 0

    def pull(coll: str):
        try:
            for snap in db.collection("drafts_v2").document(student_code).collection(coll).stream():
                d = snap.to_dict() or {}
                d["id"] = snap.id
                d["_ts_ms"] = _ts_ms(d)
                items.append(d)
        except Exception:
            pass

    pull("lessons")
    if not items:
        pull("lessens")

    items.sort(key=lambda d: d.get("_ts_ms", 0), reverse=True)
    return items


def save_row_to_scores(row: Dict[str, Any]) -> Dict[str, Any]:
    try:
        r = requests.post(
            WEBHOOK_URL,
            json={"token": WEBHOOK_TOKEN, "row": row},
            timeout=15,
        )
        raw = r.text
        if r.headers.get("content-type", "").startswith("application/json"):
            try:
                data = r.json()  # type: ignore[assignment]
            except Exception:
                data = {}
            if isinstance(data, dict):
                field = data.get("field")
                if not data.get("ok") and field:
                    return {
                        "ok": False,
                        "why": "validation",
                        "field": field,
                        "raw": raw,
                    }
                data.setdefault("raw", raw)
                return data
        if "violates the data validation rules" in raw:
            return {"ok": False, "why": "validation", "raw": raw}
        return {"ok": False, "raw": raw}
    except Exception as e:
        return {"ok": False, "error": str(e)}
