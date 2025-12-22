# app.py
import io
import os
import re
import json
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

# Configure page immediately after importing Streamlit to avoid API exceptions.
st.set_page_config(page_title="📘 Marking Dashboard", page_icon="📘", layout="wide")

# ---------------- Firebase ----------------
from firebase_utils import get_firestore_client, save_row_to_firestore

db = get_firestore_client()

# ---------------- IDs / Config ----------------
# Students Google Sheet (tab now "Sheet1" unless you override in secrets)
STUDENTS_SHEET_ID = "12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U"
STUDENTS_SHEET_TAB = st.secrets.get("STUDENTS_SHEET_TAB", "Sheet1")
SCORES_SHEET_ID = st.secrets.get("SCORES_SHEET_ID")
SCORES_SHEET_TAB = st.secrets.get("SCORES_SHEET_TAB", "Scores")

# Apps Script webhook (fallbacks included)
WEBHOOK_URL = st.secrets.get(
    "G_SHEETS_WEBHOOK_URL",
    "https://script.google.com/macros/s/AKfycbzKWo9IblWZEgD_d7sku6cGzKofis_XQj3NXGMYpf_uRqu9rGe4AvOcB15E3bb2e6O4/exec",
)
WEBHOOK_TOKEN = st.secrets.get("G_SHEETS_WEBHOOK_TOKEN", "Xenomexpress7727/")

# Answers dictionary JSON paths (first existing will be used)
ANSWERS_JSON_PATHS = [
    "answers_dictionary.json",
    "data/answers_dictionary.json",
    "assets/answers_dictionary.json",
]

APP_PASSWORD = "Xenomexpress7727"  # move to st.secrets if you prefer not to hard-code

COOKIE_SALT = st.secrets.get("COOKIE_SALT", "markmyletter")
LOGIN_TOKEN = hashlib.sha256(f"{COOKIE_SALT}:{APP_PASSWORD}".encode("utf-8")).hexdigest()
LOCAL_STORAGE_KEY = "markmyletter_auth_token"
QUERY_PARAM_KEY = "auth_token"
AUTH_COOKIE_NAME = st.secrets.get("AUTH_COOKIE_NAME", "markmyletter_auth")
AUTH_COOKIE_SAMESITE = st.secrets.get("AUTH_COOKIE_SAMESITE", "Lax")
AUTH_COOKIE_SECURE = str(st.secrets.get("AUTH_COOKIE_SECURE", "false")).lower() in {
    "1",
    "true",
    "yes",
    "on",
}
try:
    _cookie_days = float(st.secrets.get("AUTH_COOKIE_MAX_AGE_DAYS", 30))
except (TypeError, ValueError):
    _cookie_days = 30.0
AUTH_COOKIE_MAX_AGE_SECONDS = max(int(_cookie_days * 24 * 60 * 60), 60)
AUTH_COOKIE_ATTRS = f"; Path=/; SameSite={AUTH_COOKIE_SAMESITE}" + (
    "; Secure" if AUTH_COOKIE_SECURE else ""
)


def _initialize_persistent_login_bridge():
    """Ensure the browser keeps query params in sync with local storage token."""
    components.html(
        f"""
        <script>
        (function() {{
            const storageKey = "{LOCAL_STORAGE_KEY}";
            const cookieName = "{AUTH_COOKIE_NAME}";
            const paramKey = "{QUERY_PARAM_KEY}";
            const expected = "{LOGIN_TOKEN}";
            const maxAge = {AUTH_COOKIE_MAX_AGE_SECONDS};
            const cookieAttrs = "{AUTH_COOKIE_ATTRS}";
            function readCookie(name) {{
                const prefix = name + '=';
                const parts = document.cookie ? document.cookie.split(';') : [];
                for (let i = 0; i < parts.length; i += 1) {{
                    const part = parts[i].trim();
                    if (part.startsWith(prefix)) {{
                        return decodeURIComponent(part.substring(prefix.length));
                    }}
                }}
                return null;
            }}
            function writeCookie(value) {{
                if (value) {{
                    document.cookie = cookieName + "=" + value + "; Max-Age=" + maxAge + cookieAttrs;
                }} else {{
                    document.cookie = cookieName + "=; Expires=Thu, 01 Jan 1970 00:00:00 GMT" + cookieAttrs;
                }}
            }}
            try {{
                const params = new URLSearchParams(window.location.search);
                let stored = window.localStorage.getItem(storageKey);
                if (stored && stored !== expected) {{
                    window.localStorage.removeItem(storageKey);
                    stored = null;
                }}
                let cookie = readCookie(cookieName);
                if (cookie && cookie !== expected) {{
                    writeCookie('');
                    cookie = null;
                }}
                if (!stored && cookie === expected) {{
                    window.localStorage.setItem(storageKey, expected);
                    stored = expected;
                }}
                const current = params.get(paramKey);
                if (stored === expected && cookie !== expected) {{
                    writeCookie(expected);
                    cookie = expected;
                }}
                if (stored === expected && current !== expected) {{
                    params.set(paramKey, stored);
                    const newUrl = window.location.pathname + '?' + params.toString();
                    window.history.replaceState(null, '', newUrl);
                    window.location.reload();
                    return;
                }}
                if (!stored && current === expected) {{
                    window.localStorage.setItem(storageKey, expected);
                    writeCookie(expected);
                    params.delete(paramKey);
                    const query = params.toString();
                    const newUrl = window.location.pathname + (query ? '?' + query : '');
                    window.history.replaceState(null, '', newUrl);
                }}
            }} catch (err) {{
                console.warn('Persistent login sync failed', err);
            }}
        }})();
        </script>
        """,
        height=0,
    )


def _set_persistent_login(enabled: bool) -> None:
    params = st.experimental_get_query_params()
    current = params.get(QUERY_PARAM_KEY)
    needs_update = False
    if enabled:
        if current != [LOGIN_TOKEN]:
            params[QUERY_PARAM_KEY] = [LOGIN_TOKEN]
            needs_update = True
    else:
        if current is not None:
            params.pop(QUERY_PARAM_KEY, None)
            needs_update = True
    if needs_update:
        st.experimental_set_query_params(**params)

    if enabled:
        storage_script = f"window.localStorage.setItem('{LOCAL_STORAGE_KEY}', '{LOGIN_TOKEN}');"
        cookie_script = (
            "document.cookie = \"{name}={token}; Max-Age={max_age}{attrs}\";".format(
                name=AUTH_COOKIE_NAME,
                token=LOGIN_TOKEN,
                max_age=AUTH_COOKIE_MAX_AGE_SECONDS,
                attrs=AUTH_COOKIE_ATTRS,
            )
        )
    else:
        storage_script = f"window.localStorage.removeItem('{LOCAL_STORAGE_KEY}');"
        cookie_script = (
            "document.cookie = \"{name}=; Expires=Thu, 01 Jan 1970 00:00:00 GMT{attrs}\";".format(
                name=AUTH_COOKIE_NAME,
                attrs=AUTH_COOKIE_ATTRS,
            )
        )

    components.html(
        f"<script>{{storage}}{{cookie}}</script>".format(
            storage=storage_script,
            cookie=cookie_script,
        ),
        height=0,
    )


_initialize_persistent_login_bridge()


def require_password():
    params = st.experimental_get_query_params()
    if params.get(QUERY_PARAM_KEY, [""])[0] == LOGIN_TOKEN:
        st.session_state["auth_ok"] = True

    def on_password_entered():
        if st.session_state["_password"] == APP_PASSWORD:
            st.session_state["auth_ok"] = True
            del st.session_state["_password"]
            _set_persistent_login(True)
        else:
            st.session_state["auth_ok"] = False

    if not st.session_state.get("auth_ok", False):
        st.text_input("Enter password", type="password", key="_password", on_change=on_password_entered)
        if st.session_state.get("auth_ok") is False:
            st.error("Incorrect password")
        st.stop()


def render_logout_button():
    if st.session_state.get("auth_ok", False):
        if st.sidebar.button("Log out"):
            st.session_state["auth_ok"] = False
            _set_persistent_login(False)
            st.rerun()


require_password()
render_logout_button()


# =========================================================
# Helpers
# =========================================================

def natural_key(s: str):
    """Return a sortable key that safely mixes numeric and text fragments."""
    parts = re.findall(r"\d+|\D+", str(s))
    normalized = []
    for part in parts:
        if part.isdigit():
            normalized.append((0, int(part)))
        else:
            normalized.append((1, part.lower()))
    return tuple(normalized)


@st.cache_data(show_spinner=False, ttl=300)
def load_sheet_csv(sheet_id: str, tab: str) -> pd.DataFrame:
    """Load a specific Google Sheet tab as CSV (no auth) with fallbacks."""
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"
        f"?tqx=out:csv&sheet={requests.utils.quote(tab)}"
        "&tq=select%20*%20limit%20100000"
    )

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        source = io.StringIO(response.text)
    except Exception as err:
        fallback_path = st.secrets.get("STUDENTS_FALLBACK_CSV", "students.csv")
        if os.path.exists(fallback_path):
            st.warning("Google Sheet unreachable, using local fallback CSV instead.")
            source = fallback_path
        else:
            st.error(f"Could not load Google Sheet and no fallback CSV found ({err}).")
            return pd.DataFrame()

    df = pd.read_csv(source, dtype=str)
    df.columns = df.columns.str.strip().str.lower()
    return df


@st.cache_data(show_spinner=False)
def load_answers_dictionary() -> Dict[str, Any]:
    for p in ANSWERS_JSON_PATHS:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    return {}


def find_col(df: pd.DataFrame, candidates: List[str], default: str = "") -> str:
    norm = {c: c.lower().strip().replace(" ", "").replace("_", "") for c in df.columns}
    want = [c.lower().strip().replace(" ", "").replace("_", "") for c in candidates]
    for raw, n in norm.items():
        if n in want:
            return raw
    if default and default not in df.columns:
        df[default] = ""
        return default
    raise KeyError(f"Missing columns: {candidates}")


def list_json_assignments(ans_dict: Dict[str, Any]) -> List[str]:
    return sorted(list(ans_dict.keys()), key=natural_key)


def build_reference_text_from_json(
    row_obj: Dict[str, Any]
) -> Tuple[str, str, str, Dict[int, str]]:
    """Return reference text, link, format and raw answers from JSON row."""
    answers: Dict[str, Any] = row_obj.get("answers") or {
        k: v for k, v in row_obj.items() if k.lower().startswith("answer")
    }

    def n_from(k: str) -> int:
        m = re.search(r"(\d+)", k)
        return int(m.group(1)) if m else 0

    chunks: List[str] = []
    answers_map: Dict[int, str] = {}

    if isinstance(answers, dict):
        part_keys = [k for k in answers if k.lower().startswith("teil")]
        if part_keys:
            idx = 1
            for part_key in sorted(part_keys, key=natural_key):
                part = answers.get(part_key) or {}
                if part:
                    chunks.append(part_key.replace("teil", "Teil "))
                    ordered = sorted(part.items(), key=lambda kv: n_from(kv[0]))
                    for k, v in ordered:
                        v = str(v).strip()
                        if v and v.lower() not in ("nan", "none"):
                            chunks.append(f"{idx}. {v}")
                            answers_map[idx] = v
                            idx += 1
        else:
            ordered = sorted(answers.items(), key=lambda kv: n_from(kv[0]))
            for k, v in ordered:
                v = str(v).strip()
                if v and v.lower() not in ("nan", "none"):
                    idx = n_from(k)
                    chunks.append(f"{idx}. {v}")
                    answers_map[idx] = v

    fmt = str(row_obj.get("format", "essay")).strip().lower() or "essay"
    return (
        "\n".join(chunks) if chunks else "No reference answers found.",
        str(row_obj.get("answer_url", "")).strip(),
        fmt,
        answers_map,
    )


def filter_any(df: pd.DataFrame, q: str) -> pd.DataFrame:
    if not q:
        return df
    mask = df.apply(lambda c: c.astype(str).str.contains(q, case=False, na=False))
    return df[mask.any(axis=1)]


def extract_text_from_doc(doc: Dict[str, Any]) -> str:
    preferred = [
        "content",
        "text",
        "answer",
        "body",
        "draft",
        "message",
        "submissionText",  # ✅ NEW: matches your Firestore screenshot
    ]
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


# =========================================================
# Firestore submissions fetch (UPDATED for your schema)
# =========================================================

def fetch_submissions(level: str, student_code: str) -> List[Dict[str, Any]]:
    if not db or not level or not student_code:
        return []
    items: List[Dict[str, Any]] = []

    def _ts_ms(doc: Dict[str, Any]) -> int:
        """Best-effort extraction of timestamp in milliseconds."""
        # ✅ UPDATED: your docs use createdAt, not timestamp
        ts: Optional[Any] = (
            doc.get("timestamp")
            or doc.get("createdAt")
            or doc.get("created_at")
            or doc.get("submittedAt")
            or doc.get("updatedAt")
        )

        try:
            if isinstance(ts, (int, float)):
                return int(ts if ts > 10_000_000_000 else ts * 1000)
            if isinstance(ts, datetime):
                return int(ts.timestamp() * 1000)
            if hasattr(ts, "to_datetime") and callable(ts.to_datetime):
                return int(ts.to_datetime().timestamp() * 1000)
            if hasattr(ts, "seconds") and hasattr(ts, "nanoseconds"):
                return int(int(ts.seconds) * 1000 + int(ts.nanoseconds) / 1_000_000)
            if hasattr(ts, "timestamp") and callable(ts.timestamp):
                return int(ts.timestamp() * 1000)
            if isinstance(ts, dict):
                if "_seconds" in ts:
                    seconds = int(ts.get("_seconds", 0))
                    nanos = int(ts.get("_nanoseconds", 0))
                    return int(seconds * 1000 + nanos / 1_000_000)
                for key in ("iso", "time", "date", "datetime"):
                    if key in ts and isinstance(ts[key], str):
                        try:
                            return int(datetime.fromisoformat(ts[key]).timestamp() * 1000)
                        except Exception:
                            pass
            if isinstance(ts, str):
                try:
                    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
                except Exception:
                    pass
        except Exception:
            pass
        return 0

    def _normalize_row(d: Dict[str, Any], doc_id: str) -> Dict[str, Any]:
        """Attach common metadata like path, level, timestamp and details."""
        d = dict(d)

        def pick(keys: List[str], default: str = "") -> Any:
            for k in keys:
                if k in d and d[k] not in (None, ""):
                    return d[k]
            return default

        d["id"] = doc_id

        # ✅ UPDATED: support camelCase keys from your Firestore docs
        d["student_name"] = pick(["student_name", "name", "student", "studentName"])
        d["student_code"] = pick(["student_code", "studentCode", "code", "studentcode"])
        d["chapter"] = pick(["chapter", "chapter_name", "unit"])
        d["assignment"] = pick(["assignment", "assignmentTitle", "assignment_name", "task", "topic"])
        d["level"] = pick(["level", "student_level", "level_key"], level)

        d["_ts_ms"] = _ts_ms(d)

        path_from_doc = d.get("_path") or d.get("path")
        if isinstance(path_from_doc, str) and path_from_doc.strip():
            d["_path"] = path_from_doc.strip()
        else:
            d["_path"] = d.get("_path") or d.get("path") or f"submissions/{doc_id}"

        return d

    # 1) Try your OLD nested layout (keep for backwards compatibility)
    try:
        lessons_ref = db.collection("submissions").document(level).collection(student_code)
        for snap in lessons_ref.stream():
            d = snap.to_dict() or {}
            items.append(_normalize_row(d, snap.id))
    except Exception:
        pass

    # 2) ✅ UPDATED: your CURRENT layout is flat collection: submissions/{autoId}
    if not items:
        # Try camelCase schema first
        try:
            root_query = db.collection("submissions").where("studentCode", "==", student_code)
            root_query = root_query.where("level", "==", str(level).strip())
            for snap in root_query.stream():
                d = snap.to_dict() or {}
                normalized = _normalize_row(d, snap.id)
                normalized["_path"] = d.get("_path") or d.get("path") or f"submissions/{snap.id}"
                items.append(normalized)
        except Exception:
            pass

    # 2b) Fallback snake_case if any legacy docs exist
    if not items:
        try:
            root_query = db.collection("submissions").where("student_code", "==", student_code)
            root_query = root_query.where("level", "==", str(level).strip())
            for snap in root_query.stream():
                d = snap.to_dict() or {}
                normalized = _normalize_row(d, snap.id)
                normalized["_path"] = d.get("_path") or d.get("path") or f"submissions/{snap.id}"
                items.append(normalized)
        except Exception:
            pass

    # 3) Backward compatibility with old posts layout
    if not items:
        try:
            legacy_ref = db.collection("submissions").document(level).collection("posts")
            legacy_ref = legacy_ref.where("studentCode", "==", student_code)
            for snap in legacy_ref.stream():
                d = snap.to_dict() or {}
                normalized = _normalize_row(d, snap.id)
                normalized["_path"] = f"submissions/{level}/posts/{snap.id}"
                items.append(normalized)
        except Exception:
            pass

    items.sort(key=lambda d: d.get("_ts_ms", 0), reverse=True)
    return items


# ---------- PRE-NORMALIZER: turn "Teil 3/4" local numbers into global 1..N ----------

def globalize_objective_numbers(student_text: str) -> str:
    """
    Reads a student's mixed submission (may contain 'Teil 3', 'Teil 4', essays, etc.),
    extracts objective answers, and rewrites them to GLOBAL numbering (1..N).
    Output is one-per-line: '1. B', '2. A', ...
    """
    if not student_text:
        return ""

    def parse_pairs_freeform_with_teil_offsets(text: str) -> Dict[int, str]:
        res: Dict[int, str] = {}
        offset = 0

        for raw_line in text.splitlines():
            line = raw_line.strip()

            if re.search(r"^\s*teil\s*\d+\s*$", line, flags=re.I):
                offset = max(res.keys() or [0])
                continue

            m = re.match(r"\s*(?:q\s*)?(\d+)\s*[\\.\):=\-]?\s*(.+?)\s*$", line, flags=re.I)
            if m:
                local_n = int(m.group(1))
                token = m.group(2).strip().strip("()[]{}.:=,;")
                gnum = local_n + offset if offset else local_n
                res.setdefault(gnum, token)
                continue

            anchors = list(re.finditer(r"(?i)(?:q\s*)?(\d+)\s*[\\.\):=\-]*\s*", line))
            for i, am in enumerate(anchors):
                local_n = int(am.group(1))
                start = am.end()
                end = anchors[i + 1].start() if i + 1 < len(anchors) else len(line)
                chunk = line[start:end].strip()
                if not chunk:
                    continue
                token = re.split(r"[,\|\n;/\t ]+", chunk, maxsplit=1)[0].strip("()[]{}.:=")
                if token:
                    gnum = local_n + offset if offset else local_n
                    res.setdefault(gnum, token)

        return res

    pairs = parse_pairs_freeform_with_teil_offsets(student_text)
    if not pairs:
        return ""

    lines = [f"{k}. {v}" for k, v in sorted(pairs.items())]
    return "\n".join(lines)


# ===================== AI MARKING (OBJECTIVES ONLY, WITH GLOBALIZATION) =====================

def _count_words(s: str) -> int:
    return len(re.findall(r"\b[\wÄÖÜäöüß]+(?:'[A-Za-z]+)?\b", s or ""))


def _canonical_token(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    if re.fullmatch(r"[a-dA-D]", s):
        return s.upper()
    s = (
        s.lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    if s in {"t", "true", "ja", "j", "y", "yes"}:
        return "true"
    if s in {"f", "false", "nein", "n", "no"}:
        return "false"
    return re.sub(r"[^\w]+", "", s)


def _parse_ref_map(ref_text: str) -> Dict[int, str]:
    m: Dict[int, str] = {}
    for line in (ref_text or "").splitlines():
        hit = re.match(r"\s*(\d+)\s*[\.\)-]?\s*(.+)$", line)
        if hit:
            n = int(hit.group(1))
            tok = hit.group(2).strip()
            m[n] = tok
    return m


def _parse_student_global_map(student_text: str) -> Dict[int, str]:
    g = globalize_objective_numbers(student_text or "")
    out: Dict[int, str] = {}
    for line in g.splitlines():
        hit = re.match(r"\s*(\d+)\s*[\.\)-]?\s*(.+)$", line)
        if hit:
            out[int(hit.group(1))] = hit.group(2).strip()
    return out


def _compute_objective_diffs(student_text: str, ref_text: str) -> Tuple[int, int, List[Tuple[int, str, str]]]:
    ref_map = _parse_ref_map(ref_text)
    stu_map = _parse_student_global_map(student_text)
    total = len(ref_map) or 1
    wrong: List[Tuple[int, str, str]] = []
    correct = 0
    for n in sorted(ref_map.keys()):
        ref_tok = ref_map[n]
        stu_tok_raw = stu_map.get(n, "")
        if _canonical_token(stu_tok_raw) == _canonical_token(ref_tok):
            correct += 1
        else:
            wrong.append((n, ref_tok, stu_tok_raw))
    return correct, total, wrong


def _build_feedback_40_60(correct: int, total: int, wrong: List[Tuple[int, str, str]]) -> str:
    pieces = [f"Good effort for A1 objectives—you answered {correct} of {total} correctly."]
    if wrong:
        shown = ", ".join(f"{n}→{corr} (you wrote {stu or '—'})" for n, corr, stu in wrong[:6])
        pieces.append(f"Check these items: {shown}.")
    tips = [
        "Slow down, read each stem fully, and match letters carefully.",
        "Use umlauts (ä/ö/ü) and verify meaning before choosing.",
        "Underline keywords, compare similar options, and double-check B/C confusions.",
    ]
    for t in tips:
        pieces.append(t)
        if _count_words(" ".join(pieces)) >= 40:
            break
    text = " ".join(pieces)
    i = 0
    while _count_words(text) < 40 and i < len(tips):
        text = text + " " + tips[i]
        i += 1
    while _count_words(text) > 60:
        text = re.sub(r"\s*[^.?!]*[.?!]\s*$", "", text).strip()
        if not re.search(r"[.?!]$", text):
            break
    return text


# ===================== LOCAL MARKING (OBJECTIVES ONLY) =====================

def objective_mark(student_answer: str, ref_answers: Dict[int, str]) -> Tuple[int, str]:
    """
    Robust objective marking without AI.
    - Parses messy "Qn -> answer" formats with Teil section offsets.
    - Normalizes umlauts/ß to ASCII equivalents for comparison.
    - Accepts synonyms for True/False and Ja/Nein.
    """

    def canonical_word(s: str) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        if re.fullmatch(r"[a-dA-D]", s):
            return s.upper()

        s = s.lower()
        s = (
            s.replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )
        if s in {"t", "true", "ja", "j", "y", "yes"}:
            return "true"
        if s in {"f", "false", "nein", "n", "no"}:
            return "false"

        s = re.sub(r"[^\w]+", "", s)
        return s

    def parse_pairs_freeform_with_teil_offsets(text: str) -> Dict[int, str]:
        res: Dict[int, str] = {}
        offset = 0
        lines = text.splitlines()

        for line in lines:
            if re.search(r"^\s*teil\s*\d+\s*$", line, flags=re.I):
                offset = max(res.keys() or [0])
                continue

            m = re.match(r"\s*(?:q\s*)?(\d+)\s*[\\.\):=\-]?\s*(.+?)\s*$", line, flags=re.I)
            if m:
                local_n = int(m.group(1))
                token = m.group(2).strip().strip("()[]{}.:=,;")
                gnum = local_n + offset if offset else local_n
                res.setdefault(gnum, token)
                continue

            for m in re.finditer(r"(?i)(?:q\s*)?(\d+)\s*[\\.\):=\-]*\s*", line):
                local_n = int(m.group(1))
                tail = line[m.end():].strip()
                token = re.split(r"[,\|\n;/\t ]+", tail, maxsplit=1)[0].strip("()[]{}.:=")
                if token:
                    gnum = local_n + offset if offset else local_n
                    res.setdefault(gnum, token)
                    break
        return res

    ref_canon: Dict[int, str] = {int(idx): canonical_word(str(ans)) for idx, ans in (ref_answers or {}).items()}

    stu_raw = parse_pairs_freeform_with_teil_offsets(student_answer or "")
    stu_canon: Dict[int, str] = {qn: canonical_word(tok) for qn, tok in stu_raw.items()}

    total = len(ref_canon) or 1
    correct = 0
    wrong_bits: List[str] = []

    for idx in sorted(ref_canon.keys()):
        ref_tok = ref_canon[idx]
        stu_tok = stu_canon.get(idx, "")
        ok = (stu_tok == ref_tok)
        if ok:
            correct += 1
        else:
            stu_disp = stu_raw.get(idx, "") or "—"
            wrong_bits.append(f"{idx}→{ref_answers.get(idx, '')} (you wrote {stu_disp})")

    score = int(round(100 * correct / total))
    feedback = (
        "Great job — all correct!"
        if not wrong_bits
        else (
            "Keep going. Check these: "
            + ", ".join(wrong_bits)
            + ". Tip: match section numbering (Teil), read each stem carefully, and watch umlauts (ä/ö/ü)."
        )
    )
    return score, feedback


def save_row_to_scores(row: dict) -> dict:
    try:
        r = requests.post(
            WEBHOOK_URL,
            json={"token": WEBHOOK_TOKEN, "row": row},
            timeout=15,
        )

        raw = r.text

        if not (200 <= r.status_code < 300):
            return {"ok": False, "status": r.status_code, "raw": raw}

        if r.headers.get("content-type", "").startswith("application/json"):
            data: Dict[str, Any]
            try:
                data = r.json()
            except Exception:
                data = {}

            if isinstance(data, dict):
                field = data.get("field")
                if not data.get("ok") and field:
                    return {"ok": False, "why": "validation", "field": field, "raw": raw}

                data.setdefault("raw", raw)
                data.setdefault("ok", True)
                data.setdefault("message", "Saved to Scores sheet")
                return data

        if "violates the data validation rules" in raw:
            return {"ok": False, "why": "validation", "raw": raw}
        return {"ok": True, "raw": raw, "message": "Saved to Scores sheet"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def save_row(row: dict, to_sheet: bool = True, to_firestore: bool = False) -> dict:
    row = dict(row)

    score_val = row.get("score")
    try:
        score_int = int(score_val)
    except (TypeError, ValueError):
        score_int = None

    if score_int is not None:
        row["score"] = score_int
        if score_int < 60:
            row["link"] = ""

    result: Dict[str, Any] = {"ok": True}
    messages: List[str] = []

    if to_sheet:
        sheet_res = save_row_to_scores(row)
        if not sheet_res.get("ok"):
            return sheet_res
        result.update(sheet_res)
        messages.append(sheet_res.get("message", "Scores sheet").replace("Saved to ", ""))

    if to_firestore:
        fs_res = save_row_to_firestore(row)
        if not fs_res.get("ok"):
            return fs_res
        result.update(fs_res)
        messages.append(fs_res.get("message", "Firestore").replace("Saved to ", ""))

    result["message"] = "Saved to " + " and ".join(messages) if messages else "Saved"
    return result


# =========================================================
# UI
# =========================================================

message = st.session_state.pop("last_save_success", None)
if message:
    st.success("✅ " + message)

st.title("📘 Marking Dashboard")

if st.button("🔄 Refresh caches"):
    st.cache_data.clear()
    st.rerun()

# --- Load students
students_df = load_sheet_csv(STUDENTS_SHEET_ID, STUDENTS_SHEET_TAB)
if students_df.empty:
    st.error("Unable to load student roster. Please try again later.")
    st.stop()

code_col = find_col(students_df, ["studentcode", "student_code", "code"], default="studentcode")
name_col = find_col(students_df, ["name", "fullname"], default="name")
level_col = find_col(students_df, ["level"], default="level")

# Pick student
st.subheader("1) Pick Student")
q = st.text_input("Search student (code / name / any field)")
df_filtered = filter_any(students_df, q)
if df_filtered.empty:
    st.warning("No students match your search.")
    st.stop()

labels = [f"{r.get(code_col,'')} — {r.get(name_col,'')} ({r.get(level_col,'')})" for _, r in df_filtered.iterrows()]
choice = st.selectbox("Select student", labels)
srow = df_filtered.iloc[labels.index(choice)]
studentcode = str(srow.get(code_col, "")).strip()
student_name = str(srow.get(name_col, "")).strip()
student_level = str(srow.get(level_col, "")).strip()

c1, c2 = st.columns(2)
with c1:
    st.text_input("Name (auto)", value=student_name, disabled=True)
with c2:
    st.text_input("Level (auto)", value=student_level, disabled=True)

# ---------------- Reference chooser (Tabs) ----------------
st.subheader("2) Reference source")

if "ref_assignment" not in st.session_state:
    st.session_state.ref_assignment = ""
if "ref_text" not in st.session_state:
    st.session_state.ref_text = ""
if "ref_link" not in st.session_state:
    st.session_state.ref_link = ""
if "ref_format" not in st.session_state:
    st.session_state.ref_format = "essay"
if "ref_answers" not in st.session_state:
    st.session_state.ref_answers = {}

(tab_json,) = st.tabs(["📦 JSON dictionary"])

with tab_json:
    ans_dict = load_answers_dictionary()
    if not ans_dict:
        st.info("answers_dictionary.json not found in repo.")
    else:
        all_assignments_json = list_json_assignments(ans_dict)
        st.caption(f"{len(all_assignments_json)} assignments in JSON")
        qj = st.text_input("Search assignment", key="search_json")
        pool_json = [a for a in all_assignments_json if qj.lower() in a.lower()] if qj else all_assignments_json
        pick_json = st.selectbox("Select assignment", pool_json, key="pick_json")
        ref_text_json, link_json, fmt_json, ans_map_json = build_reference_text_from_json(ans_dict.get(pick_json, {}))
        st.markdown("**Reference preview (JSON):**")
        st.code(ref_text_json or "(none)", language="markdown")
        st.caption(f"Format: {fmt_json}")
        if link_json:
            st.caption(f"Reference link: {link_json}")
        if st.button("✅ Use this JSON reference"):
            st.session_state.ref_assignment = pick_json
            st.session_state.ref_text = ref_text_json
            st.session_state.ref_link = link_json
            st.session_state.ref_format = fmt_json
            st.session_state.ref_answers = ans_map_json
            st.success("Using JSON reference")

if not st.session_state.ref_assignment:
    ans = load_answers_dictionary()
    if ans:
        first = list_json_assignments(ans)[0]
        txt, ln, fmt, ans_map = build_reference_text_from_json(ans[first])
        st.session_state.ref_assignment = first
        st.session_state.ref_text = txt
        st.session_state.ref_link = ln
        st.session_state.ref_format = fmt
        st.session_state.ref_answers = ans_map

st.info(
    f"Currently selected reference → **{st.session_state.ref_assignment or '—'}** (format: {st.session_state.ref_format})"
)

# ---------------- Submissions & Marking ----------------
st.subheader("3) Student submission (local storage)")
student_text = ""
student_note = ""
subs = fetch_submissions(student_level, studentcode)

if not subs:
    st.warning(
        "No submissions found. I checked:\n"
        f"- submissions/{student_level}/{studentcode} (old nested layout)\n"
        f"- submissions collection where studentCode={studentcode} and level={student_level} (current layout)"
    )
else:
    def label_for(d: Dict[str, Any]) -> str:
        txt = extract_text_from_doc(d)
        preview = (txt[:80] + "…") if len(txt) > 80 else txt
        ts = datetime.fromtimestamp(d.get("_ts_ms", 0) / 1000).strftime("%Y-%m-%d %H:%M")
        return (
            f"{ts} • {d.get('student_name','')} • {d.get('student_code','')} "
            f"• {d.get('level','')} • {d.get('chapter','')} "
            f"• {d.get('assignment','')} • {preview}"
        )

    labels_sub = [label_for(d) for d in subs]
    pick = st.selectbox("Pick submission", labels_sub)
    chosen = subs[labels_sub.index(pick)]
    student_text = extract_text_from_doc(chosen)
    st.markdown(f"**Student:** {chosen.get('student_name','')}")
    st.markdown(f"**Level:** {chosen.get('level','')}")
    st.markdown(f"**Chapter:** {chosen.get('chapter','')}")
    st.markdown(f"**Assignment:** {chosen.get('assignment','')}")

    note_keys = ["student_note", "studentnote", "student_notes", "note", "notes"]
    for key in note_keys:
        raw_note = chosen.get(key)
        if isinstance(raw_note, str):
            candidate = raw_note.strip()
        elif raw_note is not None:
            candidate = str(raw_note).strip()
        else:
            candidate = ""
        if candidate:
            student_note = candidate
            break

    if student_note:
        st.caption(f"📝 Student note: {student_note}")

st.markdown("**Student Submission**")
st.code(student_text or "(empty)", language="markdown")

st.markdown("**Reference Answer (chosen)**")
st.code(st.session_state.ref_text or "(not set)", language="markdown")
st.caption(f"Format: {st.session_state.ref_format}")
if st.session_state.ref_link:
    st.caption(f"Reference link: {st.session_state.ref_link}")

# Combined copy block
st.subheader("4) Combined (copyable)")
combined_sections = ["# Student Submission", student_text]
if student_note:
    combined_sections.extend(["", "# Student Note", student_note])
combined_sections.extend(["", "# Reference Answer", st.session_state.ref_text])
combined = "\n".join(combined_sections)
st.text_area("Combined", value=combined, height=200)

# Manual scoring
if "ai_score" not in st.session_state:
    st.session_state.ai_score = 0
if "feedback" not in st.session_state:
    st.session_state.feedback = ""

if st.button("Reset"):
    st.session_state.ai_score = 0
    st.session_state.feedback = ""

score = st.number_input("Score", 0, 100, value=int(st.session_state.ai_score))
st.session_state.ai_score = score

feedback = st.text_area("Feedback", key="feedback", height=80)

# Save to Scores
st.subheader("5) Save to Scores sheet")
save_to_firestore = st.checkbox("also save to Firestore")
if st.button("💾 Save", type="primary", use_container_width=True):
    if not studentcode:
        st.error("Pick a student first.")
    elif not st.session_state.ref_assignment:
        st.error("Pick a JSON reference and click its 'Use this JSON reference' button.")
    elif not feedback.strip():
        st.error("Feedback is required.")
    else:
        try:
            studentcode_val = int(studentcode)
        except ValueError:
            studentcode_val = studentcode

        score_int = int(score)
        link_value = st.session_state.ref_link if score_int >= 60 else ""

        row = {
            "studentcode": studentcode_val,
            "name": student_name,
            "assignment": st.session_state.ref_assignment,
            "score": score_int,
            "comments": feedback.strip(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "level": student_level,
            "link": link_value,
        }

        result = save_row(row, to_firestore=save_to_firestore)
        if result.get("ok"):
            message = result.get("message", "Saved")
            st.session_state["last_save_success"] = message
            st.success("✅ " + message)
            load_sheet_csv.clear()
            st.rerun()
        elif result.get("why") == "validation":
            field = result.get("field")
            if field:
                st.error(f"❌ Sheet blocked the write due to data validation ({field}).")
            else:
                st.error("❌ Sheet blocked the write due to data validation.")
                if result.get("raw"):
                    st.caption(result["raw"])
        else:
            st.error(f"❌ Failed to save: {result}")
