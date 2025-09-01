import streamlit as st
from streamlit.components.v1 import html as st_html
from datetime import datetime
from typing import Any, Dict, List, Optional

# Optional: nicer page metadata
st.set_page_config(page_title="New Drafts", page_icon="🛎️", layout="wide")

try:
    from streamlit_autorefresh import st_autorefresh
except Exception:  # pragma: no cover
    def st_autorefresh(*args, **kwargs):
        return None

# --- Firebase setup ---
import firebase_admin
from firebase_admin import credentials, firestore

if not firebase_admin._apps:
    fb_cfg = st.secrets.get("firebase")
    if fb_cfg:
        cred = credentials.Certificate(dict(fb_cfg))
        firebase_admin.initialize_app(cred)

db = firestore.client() if firebase_admin._apps else None


# --- Helpers ---
def extract_text_from_doc(doc: Dict[str, Any]) -> str:
    """Extract a best-guess text body from heterogeneous Firestore docs."""
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


def _extract_ts_ms(doc: Dict[str, Any]) -> int:
    """Return a timestamp in milliseconds for a submission doc, robust to types."""
    ts: Optional[Any] = doc.get("timestamp", 0)

    try:
        # Numeric millis already
        if isinstance(ts, (int, float)):
            # If it's suspiciously small (e.g., seconds), try scaling to ms
            return int(ts if ts > 10_000_000_000 else ts * 1000)

        # Datetime object
        if isinstance(ts, datetime):
            return int(ts.timestamp() * 1000)

        # Firestore Timestamp-like objects
        # (google.cloud.firestore_v1._helpers.Timestamp has .seconds/.nanoseconds or .to_datetime())
        if hasattr(ts, "to_datetime") and callable(ts.to_datetime):
            return int(ts.to_datetime().timestamp() * 1000)
        if hasattr(ts, "seconds") and hasattr(ts, "nanoseconds"):
            return int(int(ts.seconds) * 1000 + int(ts.nanoseconds) / 1_000_000)
        if hasattr(ts, "timestamp") and callable(ts.timestamp):
            return int(ts.timestamp() * 1000)

        # Dict-ish timestamp: {"_seconds": ..., "_nanoseconds": ...}
        if isinstance(ts, dict):
            if "_seconds" in ts:
                seconds = int(ts.get("_seconds", 0))
                nanos = int(ts.get("_nanoseconds", 0))
                return int(seconds * 1000 + nanos / 1_000_000)

            # ISO8601 string in dict?
            for key in ("iso", "time", "date", "datetime"):
                if key in ts and isinstance(ts[key], str):
                    try:
                        return int(datetime.fromisoformat(ts[key]).timestamp() * 1000)
                    except Exception:
                        pass

        # ISO8601 string
        if isinstance(ts, str):
            try:
                return int(datetime.fromisoformat(ts).timestamp() * 1000)
            except Exception:
                pass
    except Exception:
        pass

    return 0


def fetch_submissions(student_code: str) -> List[Dict[str, Any]]:
    """Fetch submissions for a single student code from drafts_v2."""
    if not db or not student_code:
        return []
    items: List[Dict[str, Any]] = []

    def pull(coll: str):
        try:
            for snap in db.collection("drafts_v2").document(student_code).collection(coll).stream():
                d = snap.to_dict() or {}
                d["id"] = snap.id
                items.append(d)
        except Exception:
            pass

    pull("lessons")
    if not items:
        pull("lessens")
    return items


def fetch_all_submissions() -> List[Dict[str, Any]]:
    """Fetch submissions for all students under drafts_v2."""
    if not db:
        return []

    items: List[Dict[str, Any]] = []
    try:
        for doc in db.collection("drafts_v2").stream():
            code = doc.id
            for coll in ["lessons", "lessens"]:
                try:
                    for snap in doc.reference.collection(coll).stream():
                        d = snap.to_dict() or {}
                        d["id"] = snap.id
                        d["student_code"] = code
                        items.append(d)
                except Exception:
                    pass
    except Exception:
        pass
    return items


def notify_on_new(subs: List[Dict[str, Any]]) -> None:
    """Show toast + desktop notification + short beep if newer drafts arrived.

    Desktop notification will attempt to request permission automatically and
    always show when new items are detected (no visibility check).
    """
    if not subs:
        return

    times = [_extract_ts_ms(d) for d in subs]
    times = [t for t in times if t > 0]
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
              try {{
                await Notification.requestPermission();
              }} catch (e) {{}}
            }}
            if (Notification.permission === "granted") {{
              new Notification("{new_count} new draft{'s' if new_count>1 else ''}", {{
                body: "Open the New Drafts page to review.",
                tag: "drafts_v2",   // same tag collapses into a single updated notification
                renotify: true
              }});
            }}
          }} catch (e) {{}}
        }})();
        </script>
        """, height=0)

        # Short beep as an extra cue (may require a prior user interaction on some browsers)
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

    # Update last seen AFTER notifying
    st.session_state["last_seen_ts"] = max(last_seen, newest)


# --- UI ---
st.title("New Drafts")

# Auto-refresh every 5 seconds
st_autorefresh(interval=5000, key="new_drafts_refresh")

# Pull data
subs = fetch_all_submissions()

if not subs:
    st.info("No drafts found.")
else:
    # Sort using robust timestamp extractor
    subs = sorted(subs, key=_extract_ts_ms, reverse=True)

    # Fire notifications for fresh arrivals
    notify_on_new(subs)

    # Toggle view
    show_table = st.checkbox("Show as table", value=False)
    if show_table:
        import pandas as pd
        st.dataframe(pd.DataFrame(subs))
    else:
        for doc in subs:
            ts_ms = _extract_ts_ms(doc)
            if ts_ms:
                ts_str = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
            else:
                # Fall back to raw string if provided
                ts_raw = doc.get("timestamp", "")
                ts_str = str(ts_raw)

            lesson = doc.get("lesson") or doc.get("assignment") or ""
            student_code = doc.get("student_code", "")
            content = extract_text_from_doc(doc) or "(empty)"

            with st.container(border=True):
                st.markdown(f"**{ts_str} — {lesson} — {student_code}**")
                st.markdown(content)
