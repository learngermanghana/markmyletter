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


def test_save_student_draft_success(monkeypatch):
    calls = {}

    class FakeDoc:
        def set(self, payload, merge=False):
            calls['payload'] = payload
            calls['merge'] = merge

    class FakeDrafts:
        def document(self, student_code):
            calls['student_code'] = student_code
            return FakeDoc()

    class FakeLevelDoc:
        def collection(self, name):
            calls['collection'] = name
            return FakeDrafts()

    class FakeSubmissions:
        def document(self, level):
            calls['level'] = level
            return FakeLevelDoc()

    class FakeClient:
        def collection(self, name):
            calls['root'] = name
            return FakeSubmissions()

    monkeypatch.setattr(firebase_utils, 'get_firestore_client', lambda: FakeClient())

    payload = {'content': 'hello', 'notes': 'abc'}
    result = firebase_utils.save_student_draft('A1', 'S123', payload)

    assert result == {'ok': True, 'message': 'Draft saved'}
    assert calls['root'] == 'submissions'
    assert calls['level'] == 'A1'
    assert calls['collection'] == 'draftv2'
    assert calls['student_code'] == 'S123'
    assert calls['merge'] is True
    assert calls['payload']['content'] == 'hello'
    assert calls['payload']['text'] == 'hello'
    assert calls['payload']['notes'] == 'abc'
    assert calls['payload']['student_code'] == 'S123'
    assert calls['payload']['level'] == 'A1'
    assert calls['payload']['status'] == 'draft'
    assert calls['payload']['updated_at'] is firebase_utils.firestore.SERVER_TIMESTAMP


def test_save_student_draft_no_client(monkeypatch):
    monkeypatch.setattr(firebase_utils, 'get_firestore_client', lambda: None)
    result = firebase_utils.save_student_draft('A1', 'S123', {})
    assert result == {'ok': False, 'error': 'no_client'}


def test_save_student_draft_copies_text_to_content(monkeypatch):
    calls = {}

    class FakeDoc:
        def set(self, payload, merge=False):
            calls['payload'] = payload

    class FakeDrafts:
        def document(self, student_code):
            assert student_code == 'S456'
            return FakeDoc()

    class FakeLevelDoc:
        def collection(self, name):
            assert name == 'draftv2'
            return FakeDrafts()

    class FakeSubmissions:
        def document(self, level):
            assert level == 'B2'
            return FakeLevelDoc()

    class FakeClient:
        def collection(self, name):
            assert name == 'submissions'
            return FakeSubmissions()

    monkeypatch.setattr(firebase_utils, 'get_firestore_client', lambda: FakeClient())

    payload = {'text': 'hola'}
    firebase_utils.save_student_draft('B2', 'S456', payload)

    assert calls['payload']['content'] == 'hola'
    assert calls['payload']['text'] == 'hola'


def test_load_student_draft(monkeypatch):
    class FakeSnapshot:
        def __init__(self, data, exists=True):
            self._data = data
            self.exists = exists

        def to_dict(self):
            return self._data

    class FakeDocRef:
        def __init__(self, data):
            self._data = data

        def get(self):
            if isinstance(self._data, FakeSnapshot):
                return self._data
            return FakeSnapshot(self._data)

    class FakeDrafts:
        def __init__(self, data):
            self._data = data

        def document(self, student_code):
            assert student_code == 'S123'
            return FakeDocRef(self._data)

    class FakeLevelDoc:
        def __init__(self, data):
            self._data = data

        def collection(self, name):
            assert name == 'draftv2'
            return FakeDrafts(self._data)

    class FakeSubmissions:
        def __init__(self, data):
            self._data = data

        def document(self, level):
            assert level == 'A1'
            return FakeLevelDoc(self._data)

    class FakeClient:
        def __init__(self, data):
            self._data = data

        def collection(self, name):
            assert name == 'submissions'
            return FakeSubmissions(self._data)

    monkeypatch.setattr(
        firebase_utils,
        'get_firestore_client',
        lambda: FakeClient({'content': 'draft body'})
    )

    data = firebase_utils.load_student_draft('A1', 'S123')
    assert data == {'content': 'draft body', 'text': 'draft body'}

    monkeypatch.setattr(
        firebase_utils,
        'get_firestore_client',
        lambda: FakeClient(FakeSnapshot({}, exists=False))
    )
    assert firebase_utils.load_student_draft('A1', 'S123') is None


def test_load_student_draft_copies_text_to_content(monkeypatch):
    class FakeSnapshot:
        def to_dict(self):
            return {'text': 'only text'}

        @property
        def exists(self):
            return True

    class FakeDocRef:
        def get(self):
            return FakeSnapshot()

    class FakeDrafts:
        def document(self, student_code):
            assert student_code == 'S123'
            return FakeDocRef()

    class FakeLevelDoc:
        def collection(self, name):
            assert name == 'draftv2'
            return FakeDrafts()

    class FakeSubmissions:
        def document(self, level):
            assert level == 'A1'
            return FakeLevelDoc()

    class FakeClient:
        def collection(self, name):
            assert name == 'submissions'
            return FakeSubmissions()

    monkeypatch.setattr(firebase_utils, 'get_firestore_client', lambda: FakeClient())

    data = firebase_utils.load_student_draft('A1', 'S123')
    assert data == {'text': 'only text', 'content': 'only text'}
