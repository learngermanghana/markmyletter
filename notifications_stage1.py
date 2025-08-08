# notifications_stage1.py
# Stage 1: In-app notifications (Firestore-backed)

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

import streamlit as st

try:
    # Only needed for SERVER_TIMESTAMP & Increment constants
    from google.cloud import firestore
except Exception:  # pragma: no cover
    firestore = None


# -------- Firestore handle (uses your global db if present) --------
def _get_db():
    try:
        return db  # provided by your app elsewhere
    except NameError:
        return None


# -------- Public dataclass (optional, handy for typing) ------------
@dataclass
class Notification:
    id: str
    title: str
    body: str
    type: str = "system"
    level: str = ""         # e.g. "A2"
    deeplink: str = ""      # optional URL/hash
    created_at: Optional[datetime] = None
    read: bool = False


# -------- Core Firestore operations --------------------------------
def notify(student_code: str, *, type: str, title: str, body: str,
           level: str = "", deeplink: str = "") -> Optional[str]:
    """
    Create a notification for a given student_code.

    type: "assignment" | "reminder" | "class" | "system" | "achievement"
    """
    _db = _get_db()
    if _db is None:
        st.warning("⚠️ Firestore not initialized; skipping notification.")
        return None

    now = firestore.SERVER_TIMESTAMP if firestore else datetime.now(timezone.utc)
    parent = _db.collection("notifications").document(student_code)
    items = parent.collection("items")
    doc_ref = items.document()
    doc_ref.set({
        "type": type,
        "title": title,
        "body": body,
        "level": level,
        "created_at": now,
        "read": False,
        "deeplink": deeplink,
    })
    # Best-effort unread counter bump
    if firestore:
        parent.set(
            {"unread_count": firestore.Increment(1), "last_opened": now},
            merge=True
        )
    else:
        parent.set({"last_opened": datetime.now(timezone.utc)}, merge=True)
    return doc_ref.id


def list_notifications(student_code: str, limit: int = 20) -> List[Notification]:
    _db = _get_db()
    if _db is None:
        return []

    q = (_db.collection("notifications")
          .document(student_code)
          .collection("items")
          .order_by("created_at", direction="DESCENDING")
          .limit(limit))
    out: List[Notification] = []
    for snap in q.stream():
        d = snap.to_dict() or {}
        out.append(Notification(
            id=snap.id,
            title=d.get("title", ""),
            body=d.get("body", ""),
            type=d.get("type", "system"),
            level=d.get("level", ""),
            deeplink=d.get("deeplink", ""),
            created_at=d.get("created_at"),
            read=bool(d.get("read", False)),
        ))
    return out


def fetch_unread(student_code: str, limit: int = 10) -> List[Notification]:
    _db = _get_db()
    if _db is None:
        return []

    q = (_db.collection("notifications")
          .document(student_code)
          .collection("items")
          .where("read", "==", False)
          .order_by("created_at", direction="DESCENDING")
          .limit(limit))
    out: List[Notification] = []
    for snap in q.stream():
        d = snap.to_dict() or {}
        out.append(Notification(
            id=snap.id,
            title=d.get("title", ""),
            body=d.get("body", ""),
            type=d.get("type", "system"),
            level=d.get("level", ""),
            deeplink=d.get("deeplink", ""),
            created_at=d.get("created_at"),
            read=False,
        ))
    return out


def mark_read(student_code: str, ids: List[str]) -> None:
    _db = _get_db()
    if _db is None or not ids:
        return
    batch = _db.batch()
    parent = _db.collection("notifications").document(student_code)
    for nid in ids:
        ref = parent.collection("items").document(nid)
        batch.update(ref, {"read": True})
    # Decrement unread_count best-effort
    if firestore:
        batch.set(parent, {"unread_count": firestore.Increment(-len(ids))}, merge=True)
    batch.commit()


def unread_count(student_code: str) -> int:
    _db = _get_db()
    if _db is None:
        return 0
    snap = _db.collection("notifications").document(student_code).get()
    return int((snap.to_dict() or {}).get("unread_count", 0))


# -------- UI: bell + inbox + toasts --------------------------------
def render_notifications_ui(student_code: str, *, autorefresh_ms: int = 10_000) -> None:
    """
    Call this ONCE per page render when the user is logged in.
    Shows a bell with unread count, toasts latest unread, and an inbox drawer.
    """
    if "notifications__open" not in st.session_state:
        st.session_state["notifications__open"] = False
    if "notifications__last_seen_ids" not in st.session_state:
        st.session_state["notifications__last_seen_ids"] = set()

    # Optional: lightweight auto-refresh ticker for timely updates
    st.autorefresh(interval=autorefresh_ms, key="__notify_tick__")

    # Top-right bell (use columns to align)
    col_spacer, col_bell = st.columns([8, 1])
    with col_bell:
        try:
            cnt = unread_count(student_code)
        except Exception as e:
            cnt = 0
        label = f"🔔 {cnt}" if cnt > 0 else "🔔"
        if st.button(label, key="__notify_bell__", help="Notifications"):
            st.session_state["notifications__open"] = not st.session_state["notifications__open"]

    # Toast any *new* unread so they don't keep spamming every rerun
    try:
        unread = fetch_unread(student_code, limit=10)
    except Exception as e:
        unread = []

    # Only toast things we haven't seen in this session
    new_ids = []
    for n in reversed(unread):  # oldest first -> nicer stacking
        if n.id not in st.session_state["notifications__last_seen_ids"]:
            icon = "🔔"
            if n.type == "achievement":
                icon = "🏆"
            elif n.type == "reminder":
                icon = "⏰"
            elif n.type == "assignment":
                icon = "📌"
            msg = f"**{n.title or 'Notification'}**\n\n{n.body or ''}"
            st.toast(msg, icon=icon)
            new_ids.append(n.id)
    st.session_state["notifications__last_seen_ids"].update(new_ids)

    # Inbox drawer
    if st.session_state["notifications__open"]:
        st.markdown("### Notifications")
        rows = list_notifications(student_code, limit=30)
        to_mark: List[str] = []
        if not rows:
            st.caption("No notifications yet.")
        else:
            for r in rows:
                badge = "🆕" if not r.read else "·"
                st.markdown(f"**{badge} {r.title or '(no title)'}**  \n{r.body or ''}")
                if r.deeplink:
                    st.link_button("Open", r.deeplink, key=f"lnk_{r.id}")
                st.divider()
                if not r.read:
                    to_mark.append(r.id)

            c1, c2 = st.columns(2)
            with c1:
                if to_mark and st.button("Mark all as read", key="__notif_markread__"):
                    mark_read(student_code, to_mark)
                    # Close drawer and refresh count
                    st.session_state["notifications__open"] = False
                    st.rerun()
            with c2:
                if st.button("Refresh", key="__notif_refresh__"):
                    st.rerun()


# -------- Optional admin sender (sidebar) ---------------------------
def render_admin_sender(get_recipients_by_level=None):
    """
    Small sidebar tool to send notifications.
    Pass a callable get_recipients_by_level(lvl) -> list[student_code] if you
    want 'LEVEL:XYZ' broadcast support.
    """
    with st.sidebar.expander("🛠 Admin: Send Notification"):
        to = st.text_input("To (student_code or LEVEL:A1/A2/B1/B2/C1)", placeholder="demo001 or LEVEL:A2")
        title = st.text_input("Title", value="Reminder")
        body = st.text_area("Body", value="Don't forget today's practice!")
        ntype = st.selectbox("Type", ["reminder", "achievement", "assignment", "class", "system"], index=0)
        deeplink = st.text_input("Link (optional)", placeholder="#vocab-trainer")
        if st.button("Send"):
            sent = 0
            if to.strip().upper().startswith("LEVEL:") and callable(get_recipients_by_level):
                lvl = to.split(":", 1)[1].strip().upper()
                for sc in get_recipients_by_level(lvl):
                    if notify(sc, type=ntype, title=title, body=body, level=lvl, deeplink=deeplink):
                        sent += 1
                st.success(f"Sent to {sent} students in {lvl}.")
            else:
                sc = to.strip()
                notify(sc, type=ntype, title=title, body=body, deeplink=deeplink)
                st.success(f"Sent to {sc}.")
