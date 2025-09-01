import streamlit as st
from streamlit.components.v1 import html as st_html
from datetime import datetime, date
from typing import Any, Dict, List, Optional

# ---- Page setup ----
st.set_page_config(page_title="New Drafts", page_icon="🛎️", layout="wide")

try:
    from streamlit_autorefresh import st_autorefresh
except Exception:  # pragma: no cover
    def st_autorefresh(*args, **kwargs):
        return None

# ---- Firebase setup ----
from firebase_utils import db, extract_text_from_doc, extract_ts_ms, fetch_all_submissions

# Show which Firestore project we’re connected to
if db:
    st.caption(f"Firestore project: {getattr(db, 'project', '?')}")




def notify_on_new(subs: List[Dict[str, Any]]) -> None:
    """Toast + desktop notification + short beep if newer drafts arrived (always show)."""
    if not subs:
        return

    times: List[int] = []
    for d in subs:
        t = extract_ts_ms(d)
        if t > 0:
            times.append(t)
    newest = max(times) if times else 0

    # Initialize on first render so old backlog doesn't trigger a burst
    if "last_seen_ts" not in st.session_state:
        st.session_state["last_seen_ts"] = newest
        return

    last_seen = int(st.session_state.get("last_seen_ts", 0))
    new_count = sum(1 for t in times if t > last_seen)

    if new_count > 0:
        st.toast(f"🔔 {new_count} new draft{'s' if new_count > 1 else ''}")

        # Desktop notification (always attempt)
        st_html(f"""
        <script>
        (async function () {{
          try {{
            if (!("Notification" in window)) return;
            if (Notification.permission !== "granted") {{
              try {{ await Notification.requestPermission(); }} catch (e) {{}}
            }}
            if (Notification.permission === "granted") {{
              new Notification("{new_count} new draft{'s' if new_count>1 else ''}", {{
                body: "Open the New Drafts page to review.",
                tag: "drafts_v2",
                renotify: true
              }});
            }}
          }} catch (e) {{}}
        }})();
        </script>
        """, height=0)

        # Short beep (may need a prior user interaction on some browsers)
        st_html("""
        <script>
          try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const o = ctx.createOscillator(), g = ctx.createGain();
            o.connect(g); g.connect(ctx.destination);
            o.type = "sine"; o.frequency.setValueAtTime(880, ctx.currentTime);
            g.gain.setValueAtTime(0.001, ctx.currentTime);
            g.gain.exponentialRampToValueAtTime(0.08, ctx.currentTime + 0.02);
            o.start(); o.stop(ctx.currentTime + 0.18);
          } catch (e) {}
        </script>
        """, height=0)

    st.session_state["last_seen_ts"] = max(last_seen, newest)


# ---- Direct path quick test ----
def quick_debug_student(student_code: str):
    """Directly read drafts_v2/{student_code}/lessons to verify access and fields."""
    try:
        col = db.collection("drafts_v2").document(student_code).collection("lessons")
        snaps = list(col.limit(5).stream())
        st.success(f"Read {len(snaps)} docs under drafts_v2/{student_code}/lessons")
        for s in snaps:
            st.write("•", s.reference.path)
        if snaps:
            st.write("First doc body:")
            st.json(snaps[0].to_dict())
    except Exception as e:
        st.error(f"Direct read error: {e}")


# ---- UI ----
st.title("New Drafts")

cols = st.columns([1, 1, 8])
with cols[0]:
    if st.button("Reload now", use_container_width=True):
        st.rerun()
with cols[1]:
    st.caption(datetime.now().strftime("Last refresh: %Y-%m-%d %H:%M:%S"))

# Auto-refresh every 5 seconds
st_autorefresh(interval=5000, key="new_drafts_refresh")

# Quick debug box
with st.expander("Quick debug"):
    default_code = "akentenga1"  # change if you like
    code = st.text_input("Student code", value=default_code)
    if st.button("Test read"):
        if not db:
            st.error("Firestore is not initialized. Check your `st.secrets['firebase']` JSON.")
        else:
            quick_debug_student(code)

# Pull data
if not db:
    st.error("Firestore is not initialized. Check your `st.secrets['firebase']` JSON.")
    st.stop()

subs = fetch_all_submissions()

# --- Filters & view controls ---
with st.expander("Filters & view", expanded=True):
    # Build choices
    all_students = sorted({d.get("student_code", "") for d in subs if d.get("student_code")})
    colA, colB, colC = st.columns([2, 2, 2])
    selected_students = colA.multiselect("Students", options=all_students, default=[])
    text_query = colB.text_input("Search (lesson/content)", value="")
    date_input_val = colC.date_input("Date range (optional)", value=None)

    colD, colE, colF = st.columns([2, 2, 2])
    group_by = colD.radio("Group by", options=["None", "Student", "Date"], horizontal=True, index=0)
    sort_choice = colE.selectbox("Sort", options=["Newest first", "Oldest first"], index=0)
    limit_n = int(colF.number_input("Show latest N", min_value=10, max_value=1000, value=200, step=10))


def _passes_filters(d: Dict[str, Any]) -> bool:
    # student filter
    if selected_students and d.get("student_code", "") not in selected_students:
        return False
    # search over lesson + content
    if text_query:
        hay = " ".join([
            str(d.get("lesson") or d.get("assignment") or ""),
            extract_text_from_doc(d)
        ]).lower()
        if text_query.lower() not in hay:
            return False
    # date filter
    if date_input_val:
        ts = extract_ts_ms(d)
        if ts <= 0:
            return False
        ddate = datetime.fromtimestamp(ts / 1000).date()
        # Streamlit can return a single date or a tuple/list(range))
        if isinstance(date_input_val, (list, tuple)):
            if len(date_input_val) == 2 and all(isinstance(x, date) for x in date_input_val):
                start, end = date_input_val
                if not (start <= ddate <= end):
                    return False
        elif isinstance(date_input_val, date):
            if ddate != date_input_val:
                return False
    return True


# Apply filters, sort, limit
filtered = [d for d in subs if _passes_filters(d)]
reverse = (sort_choice == "Newest first")
filtered.sort(key=extract_ts_ms, reverse=reverse)
filtered = filtered[:limit_n]

# --- Debug info (optional) ---
with st.expander("Debug info"):
    st.write({
        "documents_found_total": len(subs),
        "after_filters": len(filtered),
        "last_seen_ts": st.session_state.get("last_seen_ts"),
    })

if not filtered:
    # Still trigger notifications against ALL docs so you don't miss anything
    if subs:
        notify_on_new(sorted(subs, key=extract_ts_ms, reverse=True))
    st.info("No drafts match your filters.")
else:
    # Fire notifications for fresh arrivals against the FULL set (not just filtered)
    notify_on_new(sorted(subs, key=extract_ts_ms, reverse=True))

    # Table or cards
    show_table = st.checkbox("Show as table", value=False)
    if show_table:
        import pandas as pd
        rows = []
        for d in filtered:
            ts_ms = extract_ts_ms(d)
            ts_str = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S") if ts_ms else ""
            rows.append({
                "Time": ts_str,
                "Student": d.get("student_code", ""),
                "Lesson": d.get("lesson") or d.get("assignment") or "",
                "Preview": (extract_text_from_doc(d) or "(empty)")[:200],
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True)
    else:
        # Grouped card view
        def _group_key(d):
            if group_by == "Student":
                return d.get("student_code", "(unknown)")
            if group_by == "Date":
                ts = extract_ts_ms(d)
                return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d") if ts else "(no-date)"
            return "All"

        # Build groups preserving order
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for d in filtered:
            k = _group_key(d)
            grouped.setdefault(k, []).append(d)

        for gkey, items in grouped.items():
            if group_by != "None":
                st.subheader(f"{gkey}  ·  {len(items)}")
            for doc in items:
                ts_ms = extract_ts_ms(doc)
                ts_str = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S") if ts_ms else "(no time)"
                lesson = doc.get("lesson") or doc.get("assignment") or ""
                student_code = doc.get("student_code", "")
                content = extract_text_from_doc(doc) or "(empty)"
                with st.container(border=True):
                    st.markdown(f"**{ts_str} — {lesson} — {student_code}**")
                    st.markdown(content)
