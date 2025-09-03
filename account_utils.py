from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Account:
    """Simple representation of a student account."""
    name: str
    email: str
    level: str
    student_code: str


def is_duplicate_account(existing: Account, candidate: Account) -> bool:
    """Return ``True`` if ``candidate`` is a duplicate of ``existing``.

    Two accounts are considered duplicates when both the ``name`` and
    ``email`` match *and* either the ``level`` or the ``student_code``
    is identical.  This mirrors the helper described in the issue which
    performs a more nuanced comparison than simply checking name and
    email equality.
    """
    same_name = existing.name.strip().lower() == candidate.name.strip().lower()
    same_email = existing.email.strip().lower() == candidate.email.strip().lower()
    if not (same_name and same_email):
        return False
    return (
        existing.level.strip().lower() == candidate.level.strip().lower()
        or existing.student_code.strip().lower() == candidate.student_code.strip().lower()
    )


def has_similar_account(candidate: Account, accounts: Iterable[Account]) -> bool:
    """Return ``True`` if any account in ``accounts`` is a duplicate of
    ``candidate``.

    This function previously compared name and email directly but now
    delegates the decision to :func:`is_duplicate_account`.  Only when
    the helper reports a duplicate do we flag the account.
    """
    for acc in accounts:
        if is_duplicate_account(acc, candidate):
            return True
    return False
