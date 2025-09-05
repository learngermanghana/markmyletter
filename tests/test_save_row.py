import os
import sys
from unittest.mock import Mock

import pytest


# Ensure project root on path for local imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from firebase_utils import save_row


def _firestore_client(success: bool):
    """Return a mocked Firestore client.

    Parameters
    ----------
    success:
        If ``True`` the ``add`` call will succeed, otherwise it will raise
        an ``Exception`` to simulate a failure.
    """

    client = Mock()
    collection = Mock()
    client.collection.return_value = collection
    if success:
        collection.add.return_value = None
    else:
        collection.add.side_effect = Exception("firestore fail")
    return client, collection


def test_save_row_sheet_and_firestore_success(monkeypatch):
    row = {"foo": "bar"}

    post_mock = Mock()
    monkeypatch.setattr("firebase_utils.requests.post", post_mock)

    fs_client, coll_mock = _firestore_client(success=True)
    monkeypatch.setattr("firebase_utils.get_firestore_client", lambda: fs_client)

    result = save_row(row, to_sheet=True, to_firestore=True)

    assert result["sheet"]["ok"] is True
    assert result["firestore"]["ok"] is True
    assert result["ok"] is True
    post_mock.assert_called_once()
    coll_mock.add.assert_called_once_with(row)


def test_save_row_sheet_failure(monkeypatch):
    row = {"foo": "bar"}

    post_mock = Mock(side_effect=Exception("sheet fail"))
    monkeypatch.setattr("firebase_utils.requests.post", post_mock)

    fs_client, coll_mock = _firestore_client(success=True)
    monkeypatch.setattr("firebase_utils.get_firestore_client", lambda: fs_client)

    result = save_row(row, to_sheet=True, to_firestore=True)

    assert result["sheet"]["ok"] is False
    assert result["firestore"]["ok"] is True
    assert result["ok"] is False
    post_mock.assert_called_once()
    coll_mock.add.assert_called_once_with(row)


def test_save_row_firestore_failure_and_sheet_skipped(monkeypatch):
    row = {"foo": "bar"}

    post_mock = Mock()
    monkeypatch.setattr("firebase_utils.requests.post", post_mock)

    fs_client, coll_mock = _firestore_client(success=False)
    monkeypatch.setattr("firebase_utils.get_firestore_client", lambda: fs_client)

    result = save_row(row, to_sheet=False, to_firestore=True)

    assert "sheet" not in result
    assert result["firestore"]["ok"] is False
    assert result["ok"] is False
    post_mock.assert_not_called()
    coll_mock.add.assert_called_once_with(row)

