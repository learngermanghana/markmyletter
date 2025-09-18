import os
import sys
import ast

# Ensure project root is on import path if needed
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import requests
from typing import Any, Dict, List


def _load_save_row_to_scores():
    path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename="app.py")
    func_node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "save_row_to_scores")
    module = ast.Module(body=[func_node], type_ignores=[])
    namespace = {
        "requests": requests,
        "WEBHOOK_URL": "https://example.com",
        "WEBHOOK_TOKEN": "token",
    }
    exec(compile(module, "app.py", "exec"), namespace)
    return namespace["save_row_to_scores"]


def _load_save_row():
    path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename="app.py")
    func_node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "save_row")
    module = ast.Module(body=[func_node], type_ignores=[])
    namespace = {
        "Dict": Dict,
        "Any": Any,
        "List": List,
        "save_row_to_scores": lambda row: {"ok": True, "message": "Saved to Scores sheet"},
        "save_row_to_firestore": lambda row: {"ok": True, "message": "Saved to Firestore"},
    }
    exec(compile(module, "app.py", "exec"), namespace)
    return namespace["save_row"]


def test_save_row_to_scores_non_2xx(monkeypatch):
    save_row_to_scores = _load_save_row_to_scores()

    class DummyResponse:
        status_code = 400
        text = "Bad request"
        headers = {}

    monkeypatch.setattr(requests, "post", lambda *a, **k: DummyResponse())

    result = save_row_to_scores({"foo": "bar"})
    assert result == {"ok": False, "status": 400, "raw": "Bad request"}


def test_save_row_to_scores_success_default(monkeypatch):
    save_row_to_scores = _load_save_row_to_scores()

    class DummyResponse:
        status_code = 200
        text = "All good"
        headers = {}

    monkeypatch.setattr(requests, "post", lambda *a, **k: DummyResponse())

    result = save_row_to_scores({"foo": "bar"})
    assert result == {"ok": True, "raw": "All good", "message": "Saved to Scores sheet"}


def test_save_row_drops_reference_link_below_sixty():
    save_row = _load_save_row()

    sheet_rows = []
    firestore_rows = []

    def fake_scores(row):
        sheet_rows.append(dict(row))
        return {"ok": True, "message": "Saved to Scores sheet"}

    def fake_firestore(row):
        firestore_rows.append(dict(row))
        return {"ok": True, "message": "Saved to Firestore"}

    save_row.__globals__["save_row_to_scores"] = fake_scores
    save_row.__globals__["save_row_to_firestore"] = fake_firestore

    res = save_row(
        {
            "studentcode": "abc",
            "score": 55,
            "link": "https://example.com",
        },
        to_sheet=True,
        to_firestore=True,
    )

    assert res["ok"]
    assert sheet_rows[0]["link"] == ""
    assert firestore_rows[0]["link"] == ""


def test_save_row_keeps_reference_link_at_sixty_or_higher():
    save_row = _load_save_row()

    captured = {}

    def fake_scores(row):
        captured.setdefault("sheet", dict(row))
        return {"ok": True, "message": "Saved to Scores sheet"}

    save_row.__globals__["save_row_to_scores"] = fake_scores
    save_row.__globals__["save_row_to_firestore"] = lambda row: {"ok": True, "message": "Saved to Firestore"}

    res = save_row(
        {
            "studentcode": "abc",
            "score": "60",
            "link": "https://example.com",
        },
        to_sheet=True,
        to_firestore=False,
    )

    assert res["ok"]
    assert captured["sheet"]["link"] == "https://example.com"
