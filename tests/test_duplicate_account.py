import os
import sys

# Ensure project root is on the import path for local imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from account_utils import Account, has_similar_account


def test_same_name_email_different_level_and_code_no_warning():
    existing = [
        Account(name="Jane Doe", email="jane@example.com", level="A1", student_code="a100"),
    ]
    candidate = Account(name="Jane Doe", email="jane@example.com", level="B2", student_code="b200")
    assert not has_similar_account(candidate, existing)


def test_duplicate_detected_when_level_matches():
    existing = [
        Account(name="Jane Doe", email="jane@example.com", level="A1", student_code="a100"),
    ]
    candidate = Account(name="Jane Doe", email="jane@example.com", level="A1", student_code="b200")
    assert has_similar_account(candidate, existing)
