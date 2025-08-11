# teacher_app.py — Falowen Teacher Portal (MVP)
# Run: streamlit run teacher_app.py
# Login passcode: 12344

import os
import math
import hashlib
import time
from datetime import datetime, timedelta

import streamlit as st

# ============================ AUTH GATE (hardcoded + logging) ============================
# SHA-256("12344") -> 8e2ceecbcb5c7a306792a3104b9b249f16e36d70da1ed02c7ba948690a0819b3
HARDCODED_PASS_SHA256 = "8e2ceecbcb5c7a306792a3104b9b249f16e36d70da1ed02c7ba948690a0819b3"

# Fallback to secrets/env if hardcoded is blank
PASS_SHA256 = (
    HARDCODED_PASS_SHA256
    or (st.secrets.get("teacher", {}).get("portal_sha256", "") if hasattr(st, "secrets") else "")
    or os.getenv("TEACHER_PORTAL_SHA256", "")
)

ATTEMPT_LIMIT = 5
LOCKOUT_MINUTES = 5

def _ok_pass(raw: str) -> bool:
    if not PASS_SHA256:
        return False
    try:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest() == PASS_SHA256
    except Exception:
        return False

st.set_page_config(page_title="Falowen • Teacher Portal", page_icon="🧑‍🏫", layout="wide")

# ============================ DB CLIENT (init early for login logging) ============================
def _get_db():
    # Try Firebase Admin → google.cloud fallback
    try:
        import firebase_admin
        from firebase_admin import firestore as fbfs
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        return fbfs.client()
    except Exception:
        pass
    try:
        from google.cloud import firestore as gcf
        return gcf.Client()
    except Exception:
        st.error(
            "Firestore client isn't configured. Provide Firebase Admin creds or set GOOGLE_APPLICATION_CREDENTIALS.",
            icon="🛑",
        )
        raise

db = _get_db()

def _record_login_attempt(status: str, email: str = ""):
    # status: "ok" or "bad"
    try:
        db.collection("teacher_login").add({
            "at": datetime.utcnow(),
            "status": status,
            "email": (email or "").strip().lower(),
            "client": "teacher.falowen.app",
        })
    except Exception:
        pass

# ============================ LOGIN FLOW ============================
if "teacher_auth" not in st.session_state:
    st.session_state["teacher_auth"] = False
if "__tries" not in st.session_state:
    st.session_state["__tries"] = 0
if "__lock_until" not in st.session_state:
    st.session_state["__lock_until"] = None
if "teacher_email" not in st.session_state:
    st.session_state["teacher_email"] = ""

with st.container():
    st.markdown("<h2 style='margin:0;'>🧑‍🏫 Falowen • Teacher Portal</h2>", unsafe_allow_html=True)

# lockout check
now_ts = time.time()
if st.session_state["__lock_until"] and now_ts < st.session_state["__lock_until"]:
    remaining = int(st.session_state["__lock_until"] - now_ts)
    st.error(f"Too many attempts. Try again in {remaining} seconds.")
    st.stop()

if not st.session_state["teacher_auth"]:
    pw = st.text_input("Enter teacher passcode", type="password")
    email_for_audit = st.text_input("Your email (for audit)", placeholder="name@domain.com")

    col_a, col_b = st.columns([1, 1])
    with col_a:
        enter = st.button("Enter")
    with col_b:
        clear = st.button("Forgot? Reset attempts")

    if clear:
        st.session_state["__tries"] = 0
        st.session_state["__lock_until"] = None
        st.info("Attempts cleared.")
        st.stop()

    if enter:
        if _ok_pass(pw):
            st.session_state["teacher_auth"] = True
            st.session_state["__tries"] = 0
            st.session_state["__lock_until"] = None
            st.session_state["teacher_email"] = (email_for_audit or "").strip().lower()
            _record_login_attempt("ok", st.session_state["teacher_email"])
            st.rerun()
        else:
            st.session_state["__tries"] += 1
            _record_login_attempt("bad", (email_for_audit or "").strip().lower())
            left = ATTEMPT_LIMIT - st.session_state["__tries"]
            if left <= 0:
                st.session_state["__lock_until"] = time.time() + LOCKOUT_MINUTES * 60
                st.error(f"Locked for {LOCKOUT_MINUTES} minutes due to too many attempts.")
            else:
                st.error(f"Wrong passcode. {left} attempt(s) left.")
    st.stop()

# ============================ ROLES ============================
ALLOWED = set(st.secrets.get("roles", {}).get("teachers", [])) if hasattr(st, "secrets") else set()
ADMINS  = set(st.secrets.get("roles", {}).get("admins", [])) if hasattr(st, "secrets") else set()
TEACHER_EMAIL = st.session_state.get("teacher_email", "")

if ALLOWED and (TEACHER_EMAIL not in ALLOWED and TEACHER_EMAIL not in ADMINS):
    st.warning("Your email is not on the teachers/admins allow-list. You may have limited access.")

# ============================ HELPERS ============================
def _safe_str(v, default=""):
    try:
        import pandas as pd
        if pd.isna(v): return default
    except Exception:
        if v is None or (isinstance(v, float) and math.isnan(v)): return default
    s = str(v or "").strip()
    return "" if s.lower() in ("nan", "none") else s

def can_manage_class(user_email: str, class_doc: dict) -> bool:
    if user_email in ADMINS:
        return True
    owners = set((class_doc.get("owners") or []) + (class_doc.get("tutors") or []))
    # owners may be list of dicts or emails
    norm = set()
    for o in owners:
        if isinstance(o, dict):
            em = _safe_str(o.get("email"))
            if em: norm.add(em)
        else:
            norm.add(_safe_str(o))
    return user_email in norm

def log_audit(action: str, class_name: str, before: dict, after: dict, who: str):
    try:
        db.collection("audit_logs").add({
            "at": datetime.utcnow(),
            "action": action,
            "class": class_name,
            "by": who,
            "before": before, "after": after,
        })
    except Exception:
        pass

def _post_announcement_via_webhook(cls: str, text: str, pinned: bool=False, link: str=""):
    """Calls your Apps Script Webhook to append a row to Announcements sheet."""
    import requests
    url = (st.secrets.get("webhooks", {}).get("announce", "") if hasattr(st, "secrets") else "").strip()
    if not url:
        st.warning("Announcement webhook not configured in secrets: [webhooks][announce].")
        return False
    try:
        payload = {"class": cls, "announcement": text, "pinned": bool(pinned), "link": link}
        r = requests.post(url, json=payload, timeout=8)
        return r.ok
    except Exception:
        return False

# ============================ SIDEBAR: CLASS PICKER ============================
st.sidebar.markdown("### Classes")

def _load_classes():
    try:
        snaps = list(db.collection("classes").stream())
        items = []
        for s in snaps:
            d = s.to_dict() or {}
            d["__id"] = s.id
            d["name"] = d.get("name") or s.id
            items.append(d)
        items.sort(key=lambda x: x.get("name", ""))
        return items
    except Exception:
        return []

all_classes = _load_classes()

view_mode = st.sidebar.radio("View", ["My classes", "All classes"], horizontal=False)
if view_mode == "My classes":
    my_classes = [c for c in all_classes if can_manage_class(TEACHER_EMAIL, c)]
else:
    my_classes = all_classes

if not my_classes:
    st.info("No classes found for your account yet.")
    st.stop()

cls_names = [c.get("name", "") for c in my_classes]
selected_name = st.sidebar.selectbox("Select a class", options=cls_names, index=0)
current = next((c for c in my_classes if c.get("name", "") == selected_name), my_classes[0])

st.sidebar.markdown("---")
page = st.sidebar.radio("Section", ["Overview", "Announcements", "Q&A Manager", "Class Meta"], index=0)

# ============================ OVERVIEW ============================
if page == "Overview":
    col1, col2, col3 = st.columns([2, 2, 2])
    with col1:
        st.subheader(selected_name)
        t_list = current.get("tutors") or []
        # tutors may be list of dicts or strings
        display_names = []
        for t in t_list:
            if isinstance(t, dict):
                display_names.append(_safe_str(t.get("name")))
            else:
                display_names.append(_safe_str(t))
        t_display = ", ".join([n for n in display_names if n]) or "—"
        st.write(f"**Tutors:** {t_display}")
        st.write(f"**Calendar:** {'set' if _safe_str(current.get('calendar_url')) else 'not set'}")
        res = current.get("resources") or {}
        st.write(f"**Resources:** {'✓' if any(res.values()) else '—'}")

    with col2:
        # Q&A counts
        q_base = db.collection("class_qna").document(selected_name).collection("questions")
        try:
            q_docs = list(q_base.stream())
            st.write(f"**Q&A:** {len(q_docs)} questions")
        except Exception:
            st.write("**Q&A:** n/a")

    with col3:
        st.info("Use the left menu to switch sections.\n\n- Post announcements\n- Answer Q&A\n- Edit tutors / calendar / links")

# ============================ ANNOUNCEMENTS ============================
elif page == "Announcements":
    st.subheader(f"📢 Announcements — {selected_name}")

    with st.form("ann_form", clear_on_submit=True):
        txt = st.text_area("Announcement text", placeholder="[Forum update] A new reply has been posted in Class Q&A.", height=120)
        link = st.text_input("Optional link", placeholder="https://falowen.app/#classroom")
        col_a, col_b = st.columns([1, 1])
        with col_a:
            pinned = st.checkbox("Pin (e.g., urgent)", value=False)
        with col_b:
            send = st.form_submit_button("Post announcement")
    if send:
        if not txt.strip():
            st.warning("Write something first.")
        else:
            ok = _post_announcement_via_webhook(selected_name, txt.strip(), pinned, link.strip())
            if ok:
                st.success("Announcement posted (check your sheet + mailer).")
            else:
                st.warning("Couldn’t post — check your webhook config.")

    st.caption("This writes a row to your Announcements sheet via your Apps Script webhook, so your existing Gmail mailer sends the email.")

# ============================ Q&A MANAGER ============================
elif page == "Q&A Manager":
    st.subheader(f"💬 Class Q&A — {selected_name}")

    q_base = db.collection("class_qna").document(selected_name).collection("questions")

    # Top controls
    left, right = st.columns([1, 1])
    with left:
        live = st.toggle("Live updates (30s)", value=False, key="teacher_qna_live")
    with right:
        if st.button("↻ Refresh now"):
            st.rerun()

    # Load questions (latest first)
    try:
        from google.cloud import firestore
        q_docs = list(q_base.order_by("timestamp", direction=firestore.Query.DESCENDING).stream())
    except Exception:
        q_docs = list(q_base.stream())
        q_docs.sort(key=lambda d: (d.to_dict() or {}).get("timestamp"), reverse=True)

    if not q_docs:
        st.info("No questions yet.")
    else:
        for d in q_docs:
            qid = d.id
            q = d.to_dict() or {}
            ts = q.get("timestamp")
            when = ""
            try:
                when = ts.strftime("%d %b %H:%M") + " UTC"
            except Exception:
                pass

            st.markdown(
                f"<div style='padding:10px;background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;margin:8px 0;'>"
                f"<b>{_safe_str(q.get('asked_by_name'), '')}</b>"
                f"<span style='color:#94a3b8;'> • {when}</span><br>"
                f"{_safe_str(q.get('topic'), '') if q.get('topic') else ''}"
                f"<div style='margin-top:6px;'>{_safe_str(q.get('question'), '')}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

            # Reply list
            r_ref = q_base.document(qid).collection("replies")
            try:
                replies = list(r_ref.order_by("timestamp").stream())
            except Exception:
                replies = list(r_ref.stream())
                replies.sort(key=lambda x: (x.to_dict() or {}).get("timestamp"))

            if replies:
                for r in replies:
                    rd = r.to_dict() or {}
                    rts = ""
                    try:
                        rts = rd.get("timestamp").strftime("%d %b %H:%M") + " UTC"
                    except Exception:
                        pass
                    st.markdown(
                        f"<div style='margin-left:18px;color:#334155;'>↳ <b>{_safe_str(rd.get('replied_by_name'), '')}</b> "
                        f"<span style='color:#94a3b8;'>{rts}</span><br>"
                        f"{_safe_str(rd.get('reply_text'), '')}</div>",
                        unsafe_allow_html=True
                    )
                    # edit/delete
                    col_ed, col_del, _ = st.columns([1, 1, 6])
                    with col_ed:
                        if st.button("✏️ Edit", key=f"r_ed_{qid}_{r.id}"):
                            st.session_state[f"edit_{qid}_{r.id}"] = rd.get("reply_text", "")
                            st.rerun()
                    with col_del:
                        if st.button("🗑️ Delete", key=f"r_del_{qid}_{r.id}"):
                            before = rd.copy()
                            r.reference.delete()
                            log_audit("delete_reply", selected_name, before, {}, TEACHER_EMAIL)
                            st.success("Reply deleted.")
                            st.rerun()

                    # inline editor
                    edit_key = f"edit_{qid}_{r.id}"
                    if edit_key in st.session_state:
                        new_txt = st.text_area(
                            "Edit reply",
                            key=f"edit_box_{qid}_{r.id}",
                            value=st.session_state[edit_key],
                            height=100
                        )
                        c1, c2 = st.columns([1, 1])
                        with c1:
                            if st.button("💾 Save", key=f"save_{qid}_{r.id}"):
                                if new_txt.strip():
                                    before = rd.copy()
                                    r.reference.update({"reply_text": new_txt.strip(), "edited_at": datetime.utcnow()})
                                    log_audit("edit_reply", selected_name, before, {"reply_text": new_txt.strip()}, TEACHER_EMAIL)
                                    st.success("Updated.")
                                st.session_state.pop(edit_key, None)
                                st.rerun()
                        with c2:
                            if st.button("❌ Cancel", key=f"cancel_{qid}_{r.id}"):
                                st.session_state.pop(edit_key, None)
                                st.rerun()

            # New reply
            with st.expander(f"Reply to Q{qid[:6]}", expanded=False):
                reply_text = st.text_area("Your reply", key=f"new_reply_{qid}", height=100)
                if st.button("Send reply", key=f"send_reply_{qid}") and reply_text.strip():
                    payload = {
                        "reply_text": reply_text.strip(),
                        "replied_by_name": TEACHER_EMAIL or "Tutor",
                        "replied_by_code": "TEACHER",
                        "timestamp": datetime.utcnow(),
                    }
                    r_ref.add(payload)
                    log_audit("add_reply", selected_name, {}, payload, TEACHER_EMAIL)
                    st.success("Reply sent.")
                    st.rerun()

    # Live updates
    if st.session_state.get("teacher_qna_live"):
        import time as _t
        _t.sleep(30)
        st.rerun()

# ============================ CLASS META ============================
elif page == "Class Meta":
    st.subheader(f"🛠️ Class Meta — {selected_name}")

    # Reload latest doc
    doc = db.collection("classes").document(selected_name).get()
    data = doc.to_dict() or {}
    before = data.copy()

    # Tutors (simple: two rows)
    tutors = data.get("tutors") or []
    def _as_dict(t):
        if isinstance(t, dict):
            return {"name": _safe_str(t.get("name")), "email": _safe_str(t.get("email"))}
        return {"name": _safe_str(t), "email": ""}

    t1 = _as_dict(tutors[0]) if len(tutors) > 0 else {"name": "", "email": ""}
    t2 = _as_dict(tutors[1]) if len(tutors) > 1 else {"name": "", "email": ""}

    calendar_url = _safe_str(data.get("calendar_url"))
    resources = data.get("resources") or {}
    qod_url     = _safe_str(resources.get("qod_url"))
    grammar_url = _safe_str(resources.get("grammar_url"))
    drive_url   = _safe_str(resources.get("drive_url"))

    with st.form("meta_form"):
        st.markdown("**Tutors**")
        c1, c2 = st.columns(2)
        with c1:
            t1_name = st.text_input("Tutor name", value=t1["name"])
            t1_mail = st.text_input("Tutor email", value=t1["email"])
        with c2:
            t2_name = st.text_input("Co-Tutor name (optional)", value=t2["name"])
            t2_mail = st.text_input("Co-Tutor email (optional)", value=t2["email"])

        st.markdown("---")
        calendar_url_new = st.text_input("Class calendar URL", value=calendar_url, placeholder="https://calendar.app/...")

        st.markdown("---")
        st.markdown("**Class Resources (simple)**")
        qod_url_new     = st.text_input("Question of the Day URL", value=qod_url, placeholder="https://…")
        grammar_url_new = st.text_input("Grammar Notes URL", value=grammar_url, placeholder="https://…")
        drive_url_new   = st.text_input("Class Drive URL", value=drive_url, placeholder="https://…")

        save = st.form_submit_button("💾 Save meta")

    if save:
        after = {
            "name": selected_name,
            "tutors": [
                {"name": _safe_str(t1_name), "email": _safe_str(t1_mail)},
                {"name": _safe_str(t2_name), "email": _safe_str(t2_mail)},
            ],
            "calendar_url": _safe_str(calendar_url_new),
            "resources": {
                "qod_url": _safe_str(qod_url_new),
                "grammar_url": _safe_str(grammar_url_new),
                "drive_url": _safe_str(drive_url_new),
            },
            "owners": list(set((data.get("owners") or []) + ([TEACHER_EMAIL] if TEACHER_EMAIL else []))),
            "updated_at": datetime.utcnow(),
            "updated_by": TEACHER_EMAIL,
        }
        # Trim empty co-tutor if blank
        after["tutors"] = [t for t in after["tutors"] if t.get("name")]

        try:
            db.collection("classes").document(selected_name).set(after, merge=True)
            log_audit("save_meta", selected_name, before, after, TEACHER_EMAIL)
            st.success("Saved.")
        except Exception as e:
            st.error(f"Couldn’t save: {e}")
