# teacher_app.py — Falowen Teacher Portal (NO LOGIN, Firebase-only)

import os, math
from datetime import datetime, timedelta
import streamlit as st

st.set_page_config(page_title="Falowen • Teacher Portal", page_icon="🧑‍🏫", layout="wide")

# ============================ FIREBASE (ADMIN) — NO google.cloud ============================
def _get_db():
    """
    Initializes Firebase Admin using a service account from Streamlit Secrets.
    Accepts either:
      [gcp.service_account]  OR  [firebase]
    and always passes projectId explicitly.
    """
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore as fbfs

        sa = None
        if hasattr(st, "secrets"):
            if "gcp" in st.secrets and "service_account" in st.secrets["gcp"]:
                sa = dict(st.secrets["gcp"]["service_account"])
            elif "firebase" in st.secrets:
                sa = dict(st.secrets["firebase"])

        if not sa:
            st.error("🛑 Missing service account. Add it under [gcp.service_account] or [firebase] in Streamlit secrets.", icon="🛑")
            return None

        # Fix \n if key pasted with escaped newlines
        if "private_key" in sa:
            sa["private_key"] = sa["private_key"].replace("\\n", "\n")

        project_id = sa.get("project_id") or sa.get("projectId")
        if not project_id:
            st.error("🛑 Service account JSON is missing project_id.", icon="🛑")
            return None

        if not firebase_admin._apps:
            cred = credentials.Certificate(sa)
            firebase_admin.initialize_app(cred, {"projectId": project_id})

        return fbfs.client()

    except Exception as e:
        st.error(f"Firestore init failed: {e}", icon="🛑")
        return None

db = _get_db()
if db is None:
    st.stop()

# Optional healthcheck (silent)
try:
    db.collection("healthcheck").add({"ok": True, "at": datetime.utcnow(), "app": "teacher_portal_no_login"})
except Exception:
    pass

# ============================ SMALL HELPERS ============================
def _safe_str(v, default=""):
    try:
        import pandas as pd
        if pd.isna(v): return default
    except Exception:
        if v is None or (isinstance(v, float) and math.isnan(v)): return default
    s = str(v or "").strip()
    return "" if s.lower() in ("nan", "none") else s

def log_audit(action: str, class_name: str, before: dict, after: dict, who: str = "teacher_portal"):
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
    """Calls your Apps Script webhook to append a row to Announcements sheet."""
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

# ============================ UI HEADER ============================
st.markdown("<h2 style='margin:0 0 8px 0;'>🧑‍🏫 Falowen • Teacher Portal</h2>", unsafe_allow_html=True)
st.caption("No login for now (MVP). Add your Firebase service account to Streamlit *Secrets* to connect.")

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
if not all_classes:
    st.info("No classes found yet. Create documents under collection **classes** in Firestore.")
    st.stop()

cls_names = [c.get("name", "") for c in all_classes]
selected_name = st.sidebar.selectbox("Select a class", options=cls_names, index=0)
current = next((c for c in all_classes if c.get("name", "") == selected_name), all_classes[0])

st.sidebar.markdown("---")
page = st.sidebar.radio("Section", ["Overview", "Announcements", "Q&A Manager", "Class Meta"], index=0)

# ============================ OVERVIEW ============================
if page == "Overview":
    col1, col2, col3 = st.columns([2, 2, 2])
    with col1:
        st.subheader(selected_name)
        t_list = current.get("tutors") or []
        names = []
        for t in t_list:
            if isinstance(t, dict):
                names.append(_safe_str(t.get("name")))
            else:
                names.append(_safe_str(t))
        st.write(f"**Tutors:** {', '.join([n for n in names if n]) or '—'}")

        cal = _safe_str(current.get("calendar_url"))
        if cal:
            st.write("**Calendar:**")
            st.markdown(f"- [📅 Open class calendar]({cal})")
        else:
            st.write("**Calendar:** not set")

    with col2:
        # Q&A count
        q_base = db.collection("class_qna").document(selected_name).collection("questions")
        try:
            q_docs = list(q_base.stream())
            st.write(f"**Q&A:** {len(q_docs)} questions")
        except Exception:
            st.write("**Q&A:** n/a")

    with col3:
        res = current.get("resources") or {}
        has_any = any((_safe_str(res.get("qod_url")), _safe_str(res.get("grammar_url")), _safe_str(res.get("drive_url"))))
        st.write(f"**Resources:** {'✓' if has_any else '—'}")
        if has_any:
            if _safe_str(res.get("qod_url")):
                st.markdown(f"- [❓ Question of the Day]({_safe_str(res.get('qod_url'))})")
            if _safe_str(res.get("grammar_url")):
                st.markdown(f"- [🔤 Grammar Notes]({_safe_str(res.get('grammar_url'))})")
            if _safe_str(res.get("drive_url")):
                st.markdown(f"- [📂 Class Drive]({_safe_str(res.get('drive_url'))})")

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
                st.warning("Couldn’t post — check your webhook config in Secrets.")

    st.caption("This writes a row to your Announcements sheet via Apps Script webhook (so your Gmail mailer sends).")

# ============================ Q&A MANAGER ============================
elif page == "Q&A Manager":
    st.subheader(f"💬 Class Q&A — {selected_name}")

    q_base = db.collection("class_qna").document(selected_name).collection("questions")
    left, right = st.columns([1, 1])
    with left:
        live = st.toggle("Live updates (30s)", value=False, key="teacher_qna_live")
    with right:
        if st.button("↻ Refresh now"):
            st.rerun()

    # Load questions (latest first) — sort in Python
    q_docs = list(q_base.stream())
    questions = [dict(d.to_dict() or {}, id=d.id) for d in q_docs]
    questions.sort(key=lambda x: x.get("timestamp"), reverse=True)

    if not questions:
        st.info("No questions yet.")
    else:
        for q in questions:
            qid = q.get("id", "")
            ts = q.get("timestamp")
            when = ""
            try:
                when = ts.strftime("%d %b %H:%M") + " UTC"
            except Exception:
                pass

            topic_html = f"<div style='font-size:0.9em;color:#666;'>{_safe_str(q.get('topic'))}</div>" if q.get("topic") else ""
            st.markdown(
                f"<div style='padding:10px;background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;margin:8px 0;'>"
                f"<b>{_safe_str(q.get('asked_by_name'), 'Student')}</b>"
                f"<span style='color:#94a3b8;'> • {when}</span>"
                f"{topic_html}"
                f"<div style='margin-top:6px;'>{_safe_str(q.get('question'), '')}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

            # Replies (oldest→newest)
            r_ref = q_base.document(qid).collection("replies")
            replies = list(r_ref.stream())
            replies = [(r.id, r.to_dict() or {}) for r in replies]
            replies.sort(key=lambda x: x[1].get("timestamp"))

            if replies:
                for rid, rd in replies:
                    rts = ""
                    try:
                        rts = rd.get("timestamp").strftime("%d %b %H:%M") + " UTC"
                    except Exception:
                        pass
                    st.markdown(
                        f"<div style='margin-left:18px;color:#334155;'>↳ <b>{_safe_str(rd.get('replied_by_name'), 'Tutor')}</b> "
                        f"<span style='color:#94a3b8;'>{rts}</span><br>"
                        f"{_safe_str(rd.get('reply_text'), '')}</div>",
                        unsafe_allow_html=True
                    )

                    # Edit/Delete controls (no login — allow directly)
                    col_ed, col_del, _ = st.columns([1, 1, 6])
                    with col_ed:
                        if st.button("✏️ Edit", key=f"r_ed_{qid}_{rid}"):
                            st.session_state[f"edit_{qid}_{rid}"] = rd.get("reply_text", "")
                            st.rerun()
                    with col_del:
                        if st.button("🗑️ Delete", key=f"r_del_{qid}_{rid}"):
                            before = rd.copy()
                            r_ref.document(rid).delete()
                            log_audit("delete_reply", selected_name, before, {}, "teacher_portal")
                            st.success("Reply deleted.")
                            st.rerun()

                    edit_key = f"edit_{qid}_{rid}"
                    if edit_key in st.session_state:
                        new_txt = st.text_area(
                            "Edit reply",
                            key=f"edit_box_{qid}_{rid}",
                            value=st.session_state[edit_key],
                            height=100
                        )
                        c1, c2 = st.columns([1, 1])
                        with c1:
                            if st.button("💾 Save", key=f"save_{qid}_{rid}"):
                                if new_txt.strip():
                                    before = rd.copy()
                                    r_ref.document(rid).update({
                                        "reply_text": new_txt.strip(),
                                        "edited_at": datetime.utcnow(),
                                    })
                                    log_audit("edit_reply", selected_name, before, {"reply_text": new_txt.strip()}, "teacher_portal")
                                    st.success("Updated.")
                                st.session_state.pop(edit_key, None)
                                st.rerun()
                        with c2:
                            if st.button("❌ Cancel", key=f"cancel_{qid}_{rid}"):
                                st.session_state.pop(edit_key, None)
                                st.rerun()

            # New reply
            with st.expander(f"Reply to Q{qid[:6]}", expanded=False):
                reply_text = st.text_area("Your reply", key=f"new_reply_{qid}", height=100)
                if st.button("Send reply", key=f"send_reply_{qid}") and reply_text.strip():
                    payload = {
                        "reply_text": reply_text.strip(),
                        "replied_by_name": "Tutor",
                        "replied_by_code": "TEACHER",
                        "timestamp": datetime.utcnow(),
                    }
                    r_ref.add(payload)
                    log_audit("add_reply", selected_name, {}, payload, "teacher_portal")
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

    # Reload latest
    doc = db.collection("classes").document(selected_name).get()
    data = doc.to_dict() or {}
    before = data.copy()

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
            "updated_at": datetime.utcnow(),
            "updated_by": "teacher_portal",
        }
        # Trim empty co-tutor entry
        after["tutors"] = [t for t in after["tutors"] if t.get("name")]

        try:
            db.collection("classes").document(selected_name).set(after, merge=True)
            log_audit("save_meta", selected_name, before, after, "teacher_portal")
            st.success("Saved.")
        except Exception as e:
            st.error(f"Couldn’t save: {e}")
