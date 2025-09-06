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

