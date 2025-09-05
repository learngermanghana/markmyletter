"""Utility helpers for working with Firebase/Firestore."""

from __future__ import annotations

import firebase_admin
from firebase_admin import credentials, firestore
import streamlit as st
import requests


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


def save_row(row: dict, *, to_sheet: bool = True, to_firestore: bool = True) -> dict:
    """Save a result ``row`` to Google Sheets and/or Firestore.

    The function is a small convenience wrapper that routes the save
    operation to the appropriate destinations based on the provided
    flags.  It returns a dictionary describing the outcome for each
    destination as well as an ``ok`` key which is ``True`` only when
    all attempted saves succeed.

    Parameters
    ----------
    row:
        Mapping of data describing a single submission/result.
    to_sheet:
        When ``True`` the row is sent to the Google Sheet webhook via
        :func:`requests.post`.
    to_firestore:
        When ``True`` the row is written to Firestore using the client
        returned by :func:`get_firestore_client`.
    """

    results: dict[str, dict] = {}
    overall_ok = True

    if to_sheet:
        try:
            requests.post("https://example.com", json=row, timeout=10)
            results["sheet"] = {"ok": True}
        except Exception as e:  # pragma: no cover - network failure path
            results["sheet"] = {"ok": False, "error": str(e)}
            overall_ok = False

    if to_firestore:
        client = get_firestore_client()
        if client is None:
            results["firestore"] = {"ok": False, "error": "no_client"}
            overall_ok = False
        else:
            try:
                client.collection("scores").add(row)
                results["firestore"] = {"ok": True}
            except Exception as e:  # pragma: no cover - exception path
                results["firestore"] = {"ok": False, "error": str(e)}
                overall_ok = False

    results["ok"] = overall_ok
    return results

