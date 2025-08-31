# app.py
import os
import re
import json
from datetime import datetime
from typing import Dict, Any, List, Tuple

import pandas as pd
import requests
import streamlit as st

# ---------------- OpenAI (optional) ----------------
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY"))
try:
    from openai import OpenAI
    ai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception:
    ai_client = None

# ---------------- Firebase ----------------
import firebase_admin
from firebase_admin import credentials, firestore

if not firebase_admin._apps:
    fb_cfg = st.secrets.get("firebase")
    if fb_cfg:
        cred = credentials.Certificate(dict(fb_cfg))
        firebase_admin.initialize_app(cred)
db = firestore.client() if firebase_admin._apps else None

# ---------------- IDs / Config ----------------
# Students Google Sheet (tab now "Sheet1" unless you override in secrets)
STUDENTS_SHEET_ID   = "12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U"
STUDENTS_SHEET_TAB  = st.secrets.get("STUDENTS_SHEET_TAB", "Sheet1")

# Reference Google Sheet (answers) and tab name (default Sheet1)
REF_ANSWERS_SHEET_ID = "1CtNlidMfmE836NBh5FmEF5tls9sLmMmkkhewMTQjkBo"
REF_ANSWERS_TAB      = st.secrets.get("REF_ANSWERS_TAB", "Sheet1")

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

# Default reference source: "json" or "sheet" (configurable via Streamlit
# secrets or environment variable "ANSWER_SOURCE")
ANSWER_SOURCE = (
    st.secrets.get("ANSWER_SOURCE")
    or os.environ.get("ANSWER_SOURCE", "")
).lower()
if ANSWER_SOURCE not in ("json", "sheet"):
    ANSWER_SOURCE = ""

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

def list_sheet_assignments(ref_df: pd.DataFrame, assignment_col: str) -> List[str]:
    vals = ref_df[assignment_col].astype(str).fillna("").str.strip()
    vals = [v for v in vals if v]
    return sorted(vals, key=natural_key)

def ordered_answer_cols(cols: List[str]) -> List[str]:
    pairs = []
    for c in cols:
        if c.lower().startswith("answer"):
            m = re.search(r"(\d+)", c)
            if m: pairs.append((int(m.group(1)), c))
    return [c for _, c in sorted(pairs, key=lambda x: x[0])]

def build_reference_text_from_sheet(ref_df: pd.DataFrame, assignment_col: str, assignment_value: str) -> Tuple[str, str]:
    row = ref_df[ref_df[assignment_col] == assignment_value]
    if row.empty:
        return "No reference answers found.", ""
    row = row.iloc[0]
    ans_cols = ordered_answer_cols(list(ref_df.columns))
    chunks = []
    for c in ans_cols:
        v = str(row.get(c, "")).strip()
        if v and v.lower() not in ("nan", "none"):
            m = re.search(r"(\d+)", c)
            n = int(m.group(1)) if m else 0
            chunks.append(f"{n}. {v}")
    link = str(row.get("answer_url", "")).strip()  # ignore sheet_url by request
    return ("\n".join(chunks) if chunks else "No reference answers found."), link

def list_json_assignments(ans_dict: Dict[str, Any]) -> List[str]:
    return sorted(list(ans_dict.keys()), key=natural_key)

def build_reference_text_from_json(row_obj: Dict[str, Any]) -> Tuple[str, str]:
    answers: Dict[str, str] = row_obj.get("answers") or {
        k: v for k, v in row_obj.items() if k.lower().startswith("answer")
    }
    def n_from(k: str) -> int:
        m = re.search(r"(\d+)", k)
        return int(m.group(1)) if m else 0
    ordered = sorted(answers.items(), key=lambda kv: n_from(kv[0]))
    chunks = []
    for k, v in ordered:
        v = str(v).strip()
        if v and v.lower() not in ("nan", "none"):
            chunks.append(f"{n_from(k)}. {v}")
    return ("\n".join(chunks) if chunks else "No reference answers found."), str(row_obj.get("answer_url", "")).strip()

def filter_any(df: pd.DataFrame, q: str) -> pd.DataFrame:
    if not q: return df
    mask = df.apply(lambda c: c.astype(str).str.contains(q, case=False, na=False))
    return df[mask.any(axis=1)]

def extract_text_from_doc(doc: Dict[str, Any]) -> str:
    preferred = ["content", "text", "answer", "body", "draft", "message"]
    for k in preferred:
        v = doc.get(k)
        if isinstance(v, str) and v.strip(): return v.strip()
        if isinstance(v, list):
            parts = []
            for item in v:
                if isinstance(item, str): parts.append(item)
                elif isinstance(item, dict):
                    for kk in ["text", "content", "value"]:
                        if kk in item and isinstance(item[kk], str): parts.append(item[kk])
            if parts: return "\n".join(parts).strip()
        if isinstance(v, dict):
            for kk in ["text", "content", "value"]:
                vv = v.get(kk)
                if isinstance(vv, str) and vv.strip(): return vv.strip()
    strings = [str(v).strip() for v in doc.values() if isinstance(v, str) and str(v).strip()]
    return "\n".join(strings).strip()

def fetch_submissions(student_code: str) -> List[Dict[str, Any]]:
    if not db or not student_code: return []
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
    if not items: pull("lessens")
    return items

def ai_mark(student_answer: str, ref_text: str) -> Tuple[int | None, str]:
    if not ai_client:
        return None, "⚠️ OpenAI key missing."
    prompt = f"""
You are a German teacher. Compare the student's answer with the reference answer.
Return STRICT JSON with:
- score: integer 0-100
- feedback: ~40 words, constructive.

Student answer:
{student_answer}

Reference answer:
{ref_text}

Return only JSON.
"""
    try:
        resp = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=220,
        )
        text = resp.choices[0].message.content.strip()
        m = re.search(r"\{.*\}", text, flags=re.S)
        text = m.group(0) if m else text
        data = json.loads(text)
        score = int(data.get("score", 0))
        fb = str(data.get("feedback", "")).strip()
        return max(0, min(100, score)), (fb or "(no feedback)")
    except Exception as e:
        return None, f"(AI error: {e})"

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
if "ref_source" not in st.session_state:
    st.session_state.ref_source = ANSWER_SOURCE or None
if "ref_assignment" not in st.session_state:
    st.session_state.ref_assignment = ""
if "ref_text" not in st.session_state:
    st.session_state.ref_text = ""
if "ref_link" not in st.session_state:
    st.session_state.ref_link = ""

tab_titles = ["📦 JSON dictionary", "🔗 Google Sheet"]
if st.session_state.ref_source == "sheet":
    tab_sheet, tab_json = st.tabs(tab_titles[::-1])
else:
    tab_json, tab_sheet = st.tabs(tab_titles)

# ---- JSON tab
with tab_json:
    ans_dict = load_answers_dictionary()
    if not ans_dict:
        st.info("answers_dictionary.json not found in repo.")
    else:
        all_assignments_json = list_json_assignments(ans_dict)
        st.caption(f"{len(all_assignments_json)} assignments in JSON")
        qj = st.text_input("Search assignment (JSON)", key="search_json")
        pool_json = [a for a in all_assignments_json if qj.lower() in a.lower()] if qj else all_assignments_json
        pick_json = st.selectbox("Select assignment (JSON)", pool_json, key="pick_json")
        ref_text_json, link_json = build_reference_text_from_json(ans_dict.get(pick_json, {}))
        st.markdown("**Reference preview (JSON):**")
        st.code(ref_text_json or "(none)", language="markdown")
        if link_json: st.caption(f"Reference link: {link_json}")
        if st.button("✅ Use this JSON reference"):
            st.session_state.ref_source = "json"
            st.session_state.ref_assignment = pick_json
            st.session_state.ref_text = ref_text_json
            st.session_state.ref_link = link_json
            st.success("Using JSON reference")

# ---- Sheet tab
with tab_sheet:
    ref_df = load_sheet_csv(REF_ANSWERS_SHEET_ID, REF_ANSWERS_TAB)
    try:
        assign_col = find_col(ref_df, ["assignment"])
    except KeyError:
        st.error("The reference sheet must have an 'assignment' column.")
        assign_col = None
    if assign_col:
        all_assignments_sheet = list_sheet_assignments(ref_df, assign_col)
        st.caption(f"{len(all_assignments_sheet)} assignments in sheet tab “{REF_ANSWERS_TAB}”")
        qs = st.text_input("Search assignment (Sheet)", key="search_sheet")
        pool_sheet = [a for a in all_assignments_sheet if qs.lower() in a.lower()] if qs else all_assignments_sheet
        pick_sheet = st.selectbox("Select assignment (Sheet)", pool_sheet, key="pick_sheet")
        ref_text_sheet, link_sheet = build_reference_text_from_sheet(ref_df, assign_col, pick_sheet)
        st.markdown("**Reference preview (Sheet):**")
        st.code(ref_text_sheet or "(none)", language="markdown")
        if link_sheet: st.caption(f"Reference link: {link_sheet}")
        if st.button("✅ Use this SHEET reference"):
            st.session_state.ref_source = "sheet"
            st.session_state.ref_assignment = pick_sheet
            st.session_state.ref_text = ref_text_sheet
            st.session_state.ref_link = link_sheet
            st.success("Using Sheet reference")

# Ensure default reference choice based on config/availability
if st.session_state.ref_source == "json" and not load_answers_dictionary():
    st.session_state.ref_source = None
if st.session_state.ref_source == "sheet":
    try:
        find_col(load_sheet_csv(REF_ANSWERS_SHEET_ID, REF_ANSWERS_TAB), ["assignment"])
    except Exception:
        st.session_state.ref_source = None

if not st.session_state.ref_source:
    if load_answers_dictionary():
        st.session_state.ref_source = "json"
    else:
        try:
            find_col(load_sheet_csv(REF_ANSWERS_SHEET_ID, REF_ANSWERS_TAB), ["assignment"])
            st.session_state.ref_source = "sheet"
        except Exception:
            pass

if st.session_state.ref_source == "json" and not st.session_state.ref_assignment:
    ans = load_answers_dictionary()
    if ans:
        first = list_json_assignments(ans)[0]
        txt, ln = build_reference_text_from_json(ans[first])
        st.session_state.ref_assignment, st.session_state.ref_text, st.session_state.ref_link = first, txt, ln
elif st.session_state.ref_source == "sheet" and not st.session_state.ref_assignment:
    ref_df_tmp = load_sheet_csv(REF_ANSWERS_SHEET_ID, REF_ANSWERS_TAB)
    try:
        ac = find_col(ref_df_tmp, ["assignment"])
        first = list_sheet_assignments(ref_df_tmp, ac)[0]
        txt, ln = build_reference_text_from_sheet(ref_df_tmp, ac, first)
        st.session_state.ref_assignment, st.session_state.ref_text, st.session_state.ref_link = first, txt, ln
    except Exception:
        pass

st.info(f"Currently using **{st.session_state.ref_source or '—'}** reference → **{st.session_state.ref_assignment or '—'}**")

# ---------------- Submissions & Marking ----------------
st.subheader("3) Student submission (Firestore)")
subs = fetch_submissions(studentcode)
if not subs:
    st.warning("No submissions found under drafts_v2/{code}/lessons (or lessens).")
    student_text = ""
else:
    def label_for(i: int, d: Dict[str, Any]) -> str:
        txt = extract_text_from_doc(d)
        preview = (txt[:80] + "…") if len(txt) > 80 else txt
        return f"{i+1} • {d.get('id','(no-id)')} • {preview}"
    labels_sub = [label_for(i, d) for i, d in enumerate(subs)]
    pick = st.selectbox("Pick submission", labels_sub)
    student_text = extract_text_from_doc(subs[labels_sub.index(pick)])

st.markdown("**Student Submission**")
st.code(student_text or "(empty)", language="markdown")

st.markdown("**Reference Answer (chosen)**")
st.code(st.session_state.ref_text or "(not set)", language="markdown")
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

# AI generate (override allowed)
if "ai_score" not in st.session_state:    st.session_state.ai_score = 0
if "ai_feedback" not in st.session_state: st.session_state.ai_feedback = ""
cur_key = f"{studentcode}|{st.session_state.ref_assignment}|{student_text[:60]}"
if ai_client and student_text.strip() and st.session_state.ref_text.strip() and st.session_state.get("ai_key") != cur_key:
    s, fb = ai_mark(student_text, st.session_state.ref_text)
    if s is not None: st.session_state.ai_score = s
    st.session_state.ai_feedback = fb
    st.session_state.ai_key = cur_key

colA, colB = st.columns(2)
with colA:
    if st.button("🔁 Regenerate AI"):
        s, fb = ai_mark(student_text, st.session_state.ref_text)
        if s is not None: st.session_state.ai_score = s
        st.session_state.ai_feedback = fb

score = st.number_input("Score", 0, 100, value=int(st.session_state.ai_score))
feedback = st.text_area("Feedback (you can edit)", value=st.session_state.ai_feedback, height=140)

# Save to Scores
st.subheader("5) Save to Scores sheet")
if st.button("💾 Save", type="primary", use_container_width=True):
    if not studentcode:
        st.error("Pick a student first.")
    elif not st.session_state.ref_assignment:
        st.error("Pick a reference (JSON or Sheet) and click its 'Use this … reference' button.")
    elif not feedback.strip():
        st.error("Feedback is required.")
    else:
        row = {
            "studentcode": studentcode,
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
