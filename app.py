# app.py
import os
import re
import json
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

import pandas as pd
import requests
import streamlit as st

# ---------------- Firebase ----------------
from firebase_utils import get_firestore_client

db = get_firestore_client()

# ---------------- IDs / Config ----------------
# Students Google Sheet (tab now "Sheet1" unless you override in secrets)
STUDENTS_SHEET_ID   = "12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U"
STUDENTS_SHEET_TAB  = st.secrets.get("STUDENTS_SHEET_TAB", "Sheet1")

# Apps Script webhook (fallbacks included)
WEBHOOK_URL   = st.secrets.get(
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


# =========================================================
# Helpers
# =========================================================

def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.findall(r"\d+|\D+", str(s))]


@st.cache_data(show_spinner=False, ttl=300)
def load_sheet_csv(sheet_id: str, tab: str) -> pd.DataFrame:
    """Load a specific Google Sheet tab as CSV (no auth)."""
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"
        f"?tqx=out:csv&sheet={requests.utils.quote(tab)}"
        "&tq=select%20*%20limit%20100000"
    )
    df = pd.read_csv(url, dtype=str)
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


def fetch_submissions(student_code: str) -> List[Dict[str, Any]]:
    if not db or not student_code:
        return []
    items: List[Dict[str, Any]] = []

    def _ts_ms(doc: Dict[str, Any]) -> int:
        """Best-effort extraction of timestamp in milliseconds."""
        ts: Optional[Any] = doc.get("timestamp")
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
                    return int(datetime.fromisoformat(ts).timestamp() * 1000)
                except Exception:
                    pass
        except Exception:
            pass
        return 0

    def pull(coll: str):
        try:
            for snap in db.collection("drafts_v2").document(student_code).collection(coll).stream():
                d = snap.to_dict() or {}
                d["id"] = snap.id
                d["_ts_ms"] = _ts_ms(d)
                items.append(d)
        except Exception:
            pass

    pull("lessons")
    if not items:
        pull("lessens")

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

            # Detect new section headings like "Teil 3", "TEIL 4", etc.
            if re.search(r"^\s*teil\s*\d+\s*$", line, flags=re.I):
                # When a new Teil starts, bump the offset to the max global index seen so far
                offset = max(res.keys() or [0])
                continue

            # First, try standard "n. token" per-line formats
            m = re.match(r"\s*(?:q\s*)?(\d+)\s*[\\.\):=\-]?\s*(.+?)\s*$", line, flags=re.I)
            if m:
                local_n = int(m.group(1))
                token = m.group(2).strip().strip("()[]{}.:=,;")
                gnum = local_n + offset if offset else local_n
                res.setdefault(gnum, token)
                continue

            # Also handle multiple Qs on one line: "... 1) B ... 2. A ..."
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

    # Emit clean, sorted global lines
    lines = [f"{k}. {v}" for k, v in sorted(pairs.items())]
    return "\n".join(lines)


# ===================== AI MARKING (OBJECTIVES ONLY, WITH GLOBALIZATION) =====================

# --- Feedback + scoring utilities to guarantee 40–60 words and correct diffs ---

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
    """Uses the globalizer, then parses 'n. token' lines."""
    g = globalize_objective_numbers(student_text or "")
    out: Dict[int, str] = {}
    for line in g.splitlines():
        hit = re.match(r"\s*(\d+)\s*[\.\)-]?\s*(.+)$", line)
        if hit:
            out[int(hit.group(1))] = hit.group(2).strip()
    return out


def _compute_objective_diffs(student_text: str, ref_text: str) -> Tuple[int, int, List[Tuple[int, str, str]]]:
    """Returns (correct, total, wrong_list) where wrong_list items are (n, correct_token, student_token_raw)."""
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
        # Letter option? Keep A-D uppercase
        if re.fullmatch(r"[a-dA-D]", s):
            return s.upper()

        # Lowercase words, normalize umlauts to ASCII
        s = s.lower()
        s = (
            s.replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )
        # Common boolean/YN synonyms
        if s in {"t", "true", "ja", "j", "y", "yes"}:
            return "true"
        if s in {"f", "false", "nein", "n", "no"}:
            return "false"

        # Remove non-word characters
        s = re.sub(r"[^\w]+", "", s)
        return s

    def parse_pairs_freeform_with_teil_offsets(text: str) -> Dict[int, str]:
        """
        Parse "1 A", "1: B", "1)C", "Q1=B", "1. Uhr", and also compact streams.
        Apply offsets whenever a new 'Teil <n>' heading is encountered.
        """
        res: Dict[int, str] = {}
        offset = 0
        lines = text.splitlines()

        for line in lines:
            # Detect new section headings like "Teil 3" (case-insensitive)
            if re.search(r"^\s*teil\s*\d+\s*$", line, flags=re.I):
                offset = max(res.keys() or [0])
                continue

            # Standard per-line "n .... token"
            m = re.match(r"\s*(?:q\s*)?(\d+)\s*[\\.\):=\-]?\s*(.+?)\s*$", line, flags=re.I)
            if m:
                local_n = int(m.group(1))
                token = m.group(2).strip().strip("()[]{}.:=,;")
                gnum = local_n + offset if offset else local_n
                res.setdefault(gnum, token)
                continue

            # Fallback: scan inline anchors
            for m in re.finditer(r"(?i)(?:q\s*)?(\d+)\s*[\\.\):=\-]*\s*", line):
                local_n = int(m.group(1))
                tail = line[m.end():].strip()
                token = re.split(r"[,\|\n;/\t ]+", tail, maxsplit=1)[0].strip("()[]{}.:=")
                if token:
                    gnum = local_n + offset if offset else local_n
                    res.setdefault(gnum, token)
                    break
        return res

    # Build canonical reference map
    ref_canon: Dict[int, str] = {int(idx): canonical_word(str(ans)) for idx, ans in (ref_answers or {}).items()}

    # Parse student's freeform text WITH section offsets
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

        raw = r.text  # keep a copy for troubleshooting

        # ---------------- Structured JSON ----------------
        if r.headers.get("content-type", "").startswith("application/json"):
            data: Dict[str, Any]
            try:
                data = r.json()
            except Exception:
                data = {}

            if isinstance(data, dict):
                # Apps Script may return structured error information
                field = data.get("field")
                if not data.get("ok") and field:
                    return {
                        "ok": False,
                        "why": "validation",
                        "field": field,
                        "raw": raw,
                    }

                # Ensure raw message is included for debugging
                data.setdefault("raw", raw)
                return data

        # ---------------- Fallback: plain text ----------------
        if "violates the data validation rules" in raw:
            return {"ok": False, "why": "validation", "raw": raw}
        return {"ok": False, "raw": raw}

    except Exception as e:
        return {"ok": False, "error": str(e)}



# =========================================================
# UI
# =========================================================
st.set_page_config(page_title="📘 Marking Dashboard", page_icon="📘", layout="wide")
st.title("📘 Marking Dashboard")

if st.button("🔄 Refresh caches"):
    st.cache_data.clear()
    st.rerun()

# --- Load students
students_df = load_sheet_csv(STUDENTS_SHEET_ID, STUDENTS_SHEET_TAB)
code_col  = find_col(students_df, ["studentcode", "student_code", "code"], default="studentcode")
name_col  = find_col(students_df, ["name", "fullname"], default="name")
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
studentcode = str(srow.get(code_col,"")).strip()
student_name = str(srow.get(name_col,"")).strip()
student_level = str(srow.get(level_col,"")).strip()

c1, c2 = st.columns(2)
with c1: st.text_input("Name (auto)",  value=student_name,  disabled=True)
with c2: st.text_input("Level (auto)", value=student_level, disabled=True)

# ---------------- Reference chooser (Tabs) ----------------
st.subheader("2) Reference source")

# Session holder for the *chosen* reference
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

tab_json, = st.tabs(["📦 JSON dictionary"])

# ---- JSON tab
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
        ref_text_json, link_json, fmt_json, ans_map_json = build_reference_text_from_json(
            ans_dict.get(pick_json, {})
        )
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

# Ensure a default reference is selected
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
st.subheader("3) Student submission (Firestore)")
student_text = ""
subs = fetch_submissions(studentcode)
if not subs:
    st.warning(
        "No submissions found under drafts_v2/{code}/lessons (or lessens)."
    )
else:
    def label_for(d: Dict[str, Any]) -> str:
        txt = extract_text_from_doc(d)
        preview = (txt[:80] + "…") if len(txt) > 80 else txt
        ts = datetime.fromtimestamp(d.get("_ts_ms", 0) / 1000).strftime("%Y-%m-%d %H:%M")
        return f"{ts} • {d.get('id','(no-id)')} • {preview}"

    labels_sub = [label_for(d) for d in subs]
    pick = st.selectbox("Pick submission", labels_sub)
    student_text = extract_text_from_doc(subs[labels_sub.index(pick)])

st.markdown("**Student Submission**")
st.code(student_text or "(empty)", language="markdown")

st.markdown("**Reference Answer (chosen)**")
st.code(st.session_state.ref_text or "(not set)", language="markdown")
st.caption(f"Format: {st.session_state.ref_format}")
if st.session_state.ref_link:
    st.caption(f"Reference link: {st.session_state.ref_link}")

# Combined copy block
st.subheader("4) Combined (copyable)")
combined = f"""# Student Submission
{student_text}

# Reference Answer
{st.session_state.ref_text}
"""
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

        row = {
            "studentcode": studentcode_val,
            "name":        student_name,
            "assignment":  st.session_state.ref_assignment,
            "score":       int(score),
            "comments":    feedback.strip(),
            "date":        datetime.now().strftime("%Y-%m-%d"),
            "level":       student_level,
            "link":        st.session_state.ref_link,  # uses answer_url only
        }

        result = save_row_to_scores(row)
        if result.get("ok"):
            st.success("✅ Saved to Scores sheet.")
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
