"""Utility helpers for working with Firebase/Firestore."""

from __future__ import annotations

import firebase_admin
from firebase_admin import credentials, firestore
import streamlit as st


def get_firestore_client():
    """Return a Firestore client, initializing Firebase if needed.

    The function attempts to obtain the default Firebase app using
    :func:`firebase_admin.get_app`.  If no app has been initialized yet a
    ``ValueError`` is raised, in which case we try to initialize it with
    credentials loaded from ``st.secrets['firebase']``.  When initialization
    cannot be completed (e.g. missing secrets) ``None`` is returned.
    """

    try:
        app = firebase_admin.get_app()
    except ValueError:
        fb_cfg = st.secrets.get("firebase")
        if not fb_cfg:
            return None
        cred = credentials.Certificate(dict(fb_cfg))
        app = firebase_admin.initialize_app(cred)

    try:
        return firestore.client(app)
    except ValueError:
        return None


def save_row_to_firestore(row: dict, collection: str = "scores") -> dict:
    """Save a row to a Firestore collection.

    Parameters
    ----------
    row:
        The data to be written to Firestore.
    collection:
        Name of the Firestore collection. Defaults to ``"scores"``.

    Returns
    -------
    dict
        ``{"ok": True, "message": "Saved to Firestore"}`` on success or
        ``{"ok": False, "error": str}`` on failure.
    """

    db = get_firestore_client()
    if not db:
        return {"ok": False, "error": "no_client"}

    try:
        db.collection(collection).add(row)
        return {"ok": True, "message": "Saved to Firestore"}
    except Exception as e:  # pragma: no cover - broad to capture Firestore errors
        return {"ok": False, "error": str(e)}


def save_student_draft(level: str, student_code: str, payload: dict) -> dict:
    """Persist a student's draft entry under ``submissions/{level}/draftv2``.

    Parameters
    ----------
    level:
        Course level used as the Firestore document id (e.g. ``"A1"``).
    student_code:
        Unique student identifier that becomes the draft document id.
    payload:
        Arbitrary dictionary containing draft data (text plus metadata).

    Returns
    -------
    dict
        ``{"ok": True, "message": "Draft saved"}`` on success. When saving
        fails the response contains ``{"ok": False, "error": str}`` with a
        short error code/message.
    """

    level_id = str(level or "").strip()
    code_id = str(student_code or "").strip()
    if not level_id or not code_id:
        return {"ok": False, "error": "invalid_args"}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "invalid_payload"}

    db = get_firestore_client()
    if not db:
        return {"ok": False, "error": "no_client"}

    data = dict(payload)
    data.setdefault("status", "draft")
    data["level"] = level_id
    data["student_code"] = code_id
    data.setdefault("updated_at", firestore.SERVER_TIMESTAMP)

    def _has_content(value: object) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True

    content_present = _has_content(data.get("content"))
    text_present = _has_content(data.get("text"))

    if content_present and not text_present:
        data["text"] = data.get("content")
    elif text_present and not content_present:
        data["content"] = data.get("text")

    try:
        (
            db.collection("submissions")
            .document(level_id)
            .collection("draftv2")
            .document(code_id)
            .set(data, merge=True)
        )
        return {"ok": True, "message": "Draft saved"}
    except Exception as e:  # pragma: no cover - Firestore failures
        return {"ok": False, "error": str(e)}


def load_student_draft(level: str, student_code: str) -> dict | None:
    """Load a draft for ``student_code`` if one exists.

    Parameters
    ----------
    level:
        Course level document id.
    student_code:
        Student identifier / draft document id.

    Returns
    -------
    dict | None
        Draft dictionary when present, otherwise ``None``. ``None`` is also
        returned if Firestore is unavailable.
    """

    level_id = str(level or "").strip()
    code_id = str(student_code or "").strip()
    if not level_id or not code_id:
        return None

    db = get_firestore_client()
    if not db:
        return None

    try:
        snap = (
            db.collection("submissions")
            .document(level_id)
            .collection("draftv2")
            .document(code_id)
            .get()
        )
    except Exception:  # pragma: no cover - Firestore client errors
        return None

    if getattr(snap, "exists", False):
        return snap.to_dict() or {}
    return None

