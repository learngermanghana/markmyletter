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

