import os
import sys
import ast

# Ensure project root is on import path if needed
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import requests


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
    assert result == {"ok": True, "raw": "All good"}
