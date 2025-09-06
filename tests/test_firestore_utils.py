import os
import sys

# Ensure project root is on the import path for local imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import firebase_utils


def test_save_row_to_firestore_success(monkeypatch):
    added = {}

    class FakeCollection:
        def add(self, row):
            added['row'] = row

    class FakeClient:
        def collection(self, name):
            added['collection'] = name
            return FakeCollection()

    # Patch the Firestore client getter to return our fake client
    monkeypatch.setattr(firebase_utils, 'get_firestore_client', lambda: FakeClient())

    result = firebase_utils.save_row_to_firestore({'foo': 'bar'})
    assert result == {'ok': True, 'message': 'Saved to Firestore'}
    assert added['collection'] == 'scores'
    assert added['row'] == {'foo': 'bar'}
