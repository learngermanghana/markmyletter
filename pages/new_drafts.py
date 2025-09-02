import re
import streamlit as st
from streamlit.components.v1 import html as st_html
from datetime import datetime, date
from typing import Any, Dict, List

# ---- Page setup ----
st.set_page_config(page_title="New Drafts", page_icon="🛎️", layout="wide")

try:
    from streamlit_autorefresh import st_autorefresh
except Exception:  # pragma: no cover
    def st_autorefresh(*args, **kwargs):
        return None

# ---- Firebase setup ----
import firebase_admin
from firebase_admin import credentials, firestore

if not firebase_admin._apps:
    fb_cfg = st.secrets.get("firebase")
    if fb_cfg:
        cred = credentials.Certificate(dict(fb_cfg))
        firebase_admin.initialize_app(cred)

db = firestore.client() if firebase_admin._apps else None
if db:
    st.caption(f"Firestore project: {getattr(db, 'project', '?')}")

# ----------------- helpers -----------------
def extract_text_from_doc(doc: Dict[str, Any]) -> str:
    preferred = ["content", "text", "answer", "body", "draft", "message"]
    for k in preferred:
        v = doc.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list):
            parts = []
            for item in v:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    for kk in ["text", "content", "value"]:
                        if kk in item and isinstance(item[kk], str):
                            parts.append(item[kk])
            if parts:
                return "\n".join(parts).strip()
        if isinstance(v, dict):
            for kk in ["text", "content", "value"]:
                vv = v.get(kk)
                if isinstance(vv, str) and vv.strip():
                    return vv.strip()
    strings = [str(v).strip() for v in doc.values() if isinstance(v, str) and str(v).strip()]
    return "\n".join(strings).strip()

def _coerce_dt_to_ms(dt: Any) -> int:
    try:
        if isinstance(dt, datetime):
            return int(dt.timestamp() * 1000)
        if hasattr(dt, "to_datetime") and callable(dt.to_datetime):
            return int(dt.to_datetime().timestamp() * 1000)  # Firestore Timestamp
        if hasattr(dt, "seconds") and hasattr(dt, "nanoseconds"):
            return int(int(dt.seconds) * 1000 + int(dt.nanoseconds) / 1_000_000)
        if hasattr(dt, "timestamp") and callable(dt.timestamp):
            return int(dt.timestamp() * 1000)
    except Exception:
        pass
    return 0

def _coerce_any_ts_to_ms(ts: Any) -> int:
    try:
        if isinstance(ts, (int, float)):
            return int(ts if ts > 10_000_000_000 else ts * 1000)  # s→ms
        if isinstance(ts, datetime):
            return int(ts.timestamp() * 1000)
        if isinstance(ts, dict):
            if "_seconds" in ts:
                seconds = int(ts.get("_seconds", 0)); nanos = int(ts.get("_nanoseconds", 0))
                return int(seconds * 1000 + nanos / 1_000_000)
            for key in ("iso", "time", "date", "datetime"):
                if key in ts and isinstance(ts[key], str):
                    try:
                        return int(datetime.fromisoformat(ts[key]).timestamp() * 1000)
                    except Exception:
                        pass
        if hasattr(ts, "to_datetime") or hasattr(ts, "seconds") or hasattr(ts, "timestamp"):
            return _coerce_dt_to_ms(ts)
        if isinstance(ts, str):
            try:
                return int(datetime.fromisoformat(ts).timestamp() * 1000)
            except Exception:
                pass
    except Exception:
        pass
    return 0

def _best_ts_ms(doc: Dict[str, Any]) -> int:
    candidates: List[int] = []
    for key in ("submitted_at", "timestamp", "created_at", "updated_at"):
        if key in doc:
            candidates.append(_coerce_any_ts_to_ms(doc.get(key)))
    if "_meta_update_ms" in doc:
        candidates.append(int(doc["_meta_update_ms"]))
    if "_meta_create_ms" in doc:
        candidates.append(int(doc["_meta_create_ms"]))
    candidates = [c for c in candidates if c and c > 0]
    return max(candidates) if candidates else 0

LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

def parse_level_from(lesson_like: str | None) -> str | None:
    """Infer level from lesson/doc id only (never from student code)."""
    if not lesson_like:
        return None
    s = str(lesson_like)
    m = re.search(r"^(A1|A2|B1|B2|C1|C2)(?=_|-|\.|$)", s, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    m = re.search(r"(?:^|[^A-Za-z0-9])(A1|A2|B1|B2|C1|C2)(?=[^A-Za-z0-9]|$)", s, re.IGNORECASE)
    return m.group(1).upper() if m else None

def _normalize_row(d: Dict[str, Any]) -> Dict[str, Any]:
    """Compute normalized lesson/level + best timestamp + display path."""
    d = dict(d)
    d["_lesson"] = d.get("lesson") or d.get("assignment") or d.get("lesson_key") or d.get("id")
    d["_level"]  = d.get("level") or parse_level_from(d.get("_lesson"))
    d["_best_ts_ms"] = _best_ts_ms(d)
    # optional nice path (if we captured it in fetch)
    if "_path" not in d and d.get("student_code") and d.get("id"):
        d["_path"] = f"drafts_v2/{d['student_code']}/lessons/{d['id']}"
    return d

# ----------------- data fetch -----------------
def _collect_group(name: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for snap in db.collection_group(name).stream():
        d = snap.to_dict() or {}
        d["id"] = snap.id
        try:
            parent_doc = snap.reference.parent.parent
            if parent_doc:
                d["student_code"] = parent_doc.id
                d["_path"] = f"{parent_doc.path}/{name}/{snap.id}"
        except Exception:
            pass
        upd = getattr(snap, "update_time", None)
        crt = getattr(snap, "create_time", None)
        d["_meta_update_ms"] = _coerce_dt_to_ms(upd)
        d["_meta_create_ms"] = _coerce_dt_to_ms(crt)
        items.append(_normalize_row(d))
    return items

def fetch_all_submissions() -> List[Dict[str, Any]]:
    if not db:
        return []
    items: List[Dict[str, Any]] = []
    try:
        items.extend(_collect_group("lessons"))
    except Exception as e:
        st.error(f"collection_group('lessons') failed: {e}")
    # also read the misspelled subcollection if some students still use it
    try:
        items.extend(_collect_group("lessens"))
    except Exception:
        pass
    return items

# ----------------- notifications -----------------
def notify_on_new(subs: List[Dict[str, Any]]) -> None:
    if not subs:
        return
    times = [int(d.get("_best_ts_ms", 0)) for d in subs if int(d.get("_best_ts_ms", 0)) > 0]
    newest = max(times) if times else 0

    if "last_seen_ts" not in st.session_state:
        st.session_state["last_seen_ts"] = newest
        return

    last_seen = int(st.session_state.get("last_seen_ts", 0))
    new_count = sum(1 for t in times if t > last_seen)

    if new_count > 0:
        st.toast(f"🔔 {new_count} new draft{'s' if new_count > 1 else ''}")
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
                tag: "drafts_v2", renotify: true
              }});
            }}
          }} catch (e) {{}}
        }})();
        </script>
        """, height=0)
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

# ----------------- quick debug -----------------
def quick_debug_student(student_code: str):
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

# ----------------- UI -----------------
st.title("New Drafts")
top = st.columns([1.2, 1.2, 1.2, 6.4])
with top[0]:
    if st.button("Reload now", use_container_width=True):
        st.rerun()
with top[1]:
    if st.button("Reset last-seen", use_container_width=True):
        st.session_state.pop("last_seen_ts", None)
        st.toast("Last-seen timestamp reset.")
with top[2]:
    if st.button("Test notification", use_container_width=True):
        st_html("""
        <script>
        (async function () {
          try {
            if (!("Notification" in window)) return;
            if (Notification.permission !== "granted") {
              try { await Notification.requestPermission(); } catch (e) {}
            }
            if (Notification.permission === "granted") {
              new Notification("Test: New drafts", {
                body: "Notifications are working.",
                tag: "drafts_v2_test", renotify: true
              });
            }
          } catch (e) {}
        })();
        </script>
        """, height=0)
with top[3]:
    st.caption(datetime.now().strftime("Last refresh: %Y-%m-%d %H:%M:%S"))

st_autorefresh(interval=5000, key="new_drafts_refresh")

with st.expander("Quick debug"):
    default_code = "akentenga1"
    code = st.text_input("Student code", value=default_code)
    if st.button("Test read"):
        if not db:
            st.error("Firestore is not initialized. Check your `st.secrets['firebase']` JSON.")
        else:
            quick_debug_student(code)

if not db:
    st.error("Firestore is not initialized. Check your `st.secrets['firebase']` JSON.")
    st.stop()

subs = fetch_all_submissions()

# ----- Filters & view -----
with st.expander("Filters & view", expanded=True):
    all_students = sorted({d.get("student_code", "") for d in subs if d.get("student_code")})
    all_levels   = sorted({d.get("_level") for d in subs if d.get("_level")})
    colA, colB, colC = st.columns([2, 2, 2])
    selected_students = colA.multiselect("Students", options=all_students, default=[])
    selected_levels   = colB.multiselect("Levels", options=all_levels or LEVELS, default=all_levels or LEVELS)
    text_query = colC.text_input("Search (lesson/content)", value="")

    colD, colE, colF = st.columns([2, 2, 2])
    group_by = colD.radio("Group by", options=["None", "Student", "Date", "Level"], horizontal=True, index=0)
    sort_choice = colE.selectbox("Sort", options=["Newest first", "Oldest first"], index=0)
    limit_n = int(colF.number_input("Show latest N", min_value=10, max_value=1000, value=200, step=10))

def _passes_filters(d: Dict[str, Any]) -> bool:
    if selected_students and d.get("student_code", "") not in selected_students:
        return False
    if selected_levels and (d.get("_level") or "UNKNOWN") not in set(selected_levels):
        return False
    if text_query:
        hay = " ".join([
            str(d.get("_lesson") or ""),
            extract_text_from_doc(d)
        ]).lower()
        if text_query.lower() not in hay:
            return False
    return True

filtered = [d for d in subs if _passes_filters(d)]
reverse = (sort_choice == "Newest first")
filtered.sort(key=lambda d: int(d.get("_best_ts_ms", 0)), reverse=reverse)
filtered = filtered[:limit_n]

with st.expander("Debug info"):
    st.write({
        "documents_found_total": len(subs),
        "after_filters": len(filtered),
        "last_seen_ts": st.session_state.get("last_seen_ts"),
    })

if not filtered:
    if subs:
        notify_on_new(sorted(subs, key=lambda d: int(d.get("_best_ts_ms", 0)), reverse=True))
    st.info("No drafts match your filters.")
else:
    notify_on_new(sorted(subs, key=lambda d: int(d.get("_best_ts_ms", 0)), reverse=True))

    show_table = st.checkbox("Show as table", value=False)
    if show_table:
        import pandas as pd
        rows = []
        for d in filtered:
            ts_ms = int(d.get("_best_ts_ms", 0))
            ts_str = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S") if ts_ms else ""
            rows.append({
                "Time": ts_str,
                "Student": d.get("student_code", ""),
                "Level": d.get("_level", ""),
                "Lesson": d.get("_lesson", ""),
                "Doc ID": d.get("id", ""),
                "Path": d.get("_path", ""),
                "Preview": (extract_text_from_doc(d) or "(empty)")[:200],
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True)
    else:
        def _group_key(d):
            if group_by == "Student":
                return d.get("student_code", "(unknown)")
            if group_by == "Date":
                ts = int(d.get("_best_ts_ms", 0))
                return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d") if ts else "(no-date)"
            if group_by == "Level":
                return d.get("_level", "(no-level)")
            return "All"

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for d in filtered:
            grouped.setdefault(_group_key(d), []).append(d)

        for gkey, items in grouped.items():
            if group_by != "None":
                st.subheader(f"{gkey}  ·  {len(items)}")
            for doc in items:
                ts_ms = int(doc.get("_best_ts_ms", 0))
                ts_str = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S") if ts_ms else "(no time)"
                header = f"{ts_str} — {doc.get('_lesson','')} {(f'({doc.get('_level')})' if doc.get('_level') else '')} — {doc.get('student_code','')}"
                content = extract_text_from_doc(doc) or "(empty)"
                with st.container(border=True):
                    st.markdown(f"**{header}**")
                    if doc.get("_path"):
                        st.caption(doc["_path"])
                    st.markdown(content)
