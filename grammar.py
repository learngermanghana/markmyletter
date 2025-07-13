import os
import random
import difflib
import sqlite3
import atexit
import json
from datetime import date, datetime
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import time
import requests
import io
from openai import OpenAI
from fpdf import FPDF
from streamlit_cookies_manager import EncryptedCookieManager

st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .st-emotion-cache-1v0mbdj {display: none;}
    </style>
    """,
    unsafe_allow_html=True
)


# ---- OpenAI Client Setup ----
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error(
        "Missing OpenAI API key. Please set OPENAI_API_KEY as an environment variable or in Streamlit secrets."
    )
    st.stop()
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
client = OpenAI()

# ==== DB CONNECTION ====
def get_connection():
    if "conn" not in st.session_state:
        st.session_state["conn"] = sqlite3.connect("vocab_progress.db", check_same_thread=False)
        atexit.register(st.session_state["conn"].close)
    return st.session_state["conn"]

# ==== INITIALIZE DB TABLES ====
def init_db():
    conn = get_connection()
    c = conn.cursor()
    # Vocab Progress Table (NO daily limit)
    c.execute("""
        CREATE TABLE IF NOT EXISTS vocab_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT,
            name TEXT,
            level TEXT,
            word TEXT,
            student_answer TEXT,
            is_correct INTEGER,
            date TEXT
        )
    """)
    # Schreiben Progress Table (DAILY LIMIT)
    c.execute("""
        CREATE TABLE IF NOT EXISTS schreiben_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT,
            name TEXT,
            level TEXT,
            essay TEXT,
            score INTEGER,
            feedback TEXT,
            date TEXT
        )
    """)
    # Sprechen Progress Table (DAILY LIMIT)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sprechen_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT,
            name TEXT,
            level TEXT,
            teil TEXT,
            message TEXT,
            score INTEGER,
            feedback TEXT,
            date TEXT
        )
    """)
    # Scores Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT,
            name TEXT,
            assignment TEXT,
            score REAL,
            comments TEXT,
            date TEXT,
            level TEXT
        )
    """)
    # Exam Progress Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS exam_progress (
            student_code TEXT,
            level        TEXT,
            teil         TEXT,
            remaining    TEXT,
            used         TEXT,
            PRIMARY KEY (student_code, level, teil)
        )
    """)
    # My Vocab Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS my_vocab (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT,
            level TEXT,
            word TEXT,
            translation TEXT,
            date_added TEXT
        )
    """)
    # Sprechen Daily Usage Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS sprechen_usage (
            student_code TEXT,
            date TEXT,
            count INTEGER,
            PRIMARY KEY (student_code, date)
        )
    """)
    # Schreiben Daily Usage Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS schreiben_usage (
            student_code TEXT,
            date TEXT,
            count INTEGER,
            PRIMARY KEY (student_code, date)
        )
    """)
    conn.commit()

init_db()  # <<-- Make sure this is before any other DB calls!

# ==== CONSTANTS ====
FALOWEN_DAILY_LIMIT = 20
VOCAB_DAILY_LIMIT = 20
SCHREIBEN_DAILY_LIMIT = 5

# ==== USAGE COUNTERS ====
def get_sprechen_usage(student_code):
    today = str(date.today())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT count FROM sprechen_usage WHERE student_code=? AND date=?",
        (student_code, today)
    )
    row = c.fetchone()
    return row[0] if row else 0

def inc_sprechen_usage(student_code):
    today = str(date.today())
    conn = get_connection()
    c = conn.cursor()
    usage = get_sprechen_usage(student_code)
    if usage == 0:
        c.execute(
            "INSERT INTO sprechen_usage (student_code, date, count) VALUES (?, ?, ?)",
            (student_code, today, 1)
        )
    else:
        c.execute(
            "UPDATE sprechen_usage SET count = ? WHERE student_code = ? AND date = ?",
            (usage + 1, student_code, today)
        )
    conn.commit()

def has_sprechen_quota(student_code, limit=FALOWEN_DAILY_LIMIT):
    return get_sprechen_usage(student_code) < limit

def get_schreiben_usage(student_code):
    today = str(date.today())
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT count FROM schreiben_usage WHERE student_code=? AND date=?",
        (student_code, today)
    )
    row = c.fetchone()
    return row[0] if row else 0

def inc_schreiben_usage(student_code):
    today = str(date.today())
    conn = get_connection()
    c = conn.cursor()
    usage = get_schreiben_usage(student_code)
    if usage == 0:
        c.execute(
            "INSERT INTO schreiben_usage (student_code, date, count) VALUES (?, ?, ?)",
            (student_code, today, 1)
        )
    else:
        c.execute(
            "UPDATE schreiben_usage SET count = ? WHERE student_code = ? AND date = ?",
            (usage + 1, student_code, today)
        )
    conn.commit()

def has_schreiben_quota(student_code, limit=SCHREIBEN_DAILY_LIMIT):
    return get_schreiben_usage(student_code) < limit

def get_writing_stats(student_code):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT COUNT(*), SUM(score>=17) FROM schreiben_progress WHERE student_code=?
    """, (student_code,))
    result = c.fetchone()
    attempted = result[0] or 0
    passed = result[1] if result[1] is not None else 0
    accuracy = round(100 * passed / attempted) if attempted > 0 else 0
    return attempted, passed, accuracy

def get_student_stats(student_code):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT level, SUM(score >= 17), COUNT(*) 
        FROM schreiben_progress 
        WHERE student_code=?
        GROUP BY level
    """, (student_code,))
    stats = {}
    for level, correct, attempted in c.fetchall():
        stats[level] = {"correct": int(correct or 0), "attempted": int(attempted or 0)}
    return stats


# -- ALIAS for legacy code (use this so your old code works without errors!) --
has_falowen_quota = has_sprechen_quota

# (Now your whole app can use has_falowen_quota(student_code, FALOWEN_DAILY_LIMIT)
# OR has_sprechen_quota(student_code, FALOWEN_DAILY_LIMIT) and it will always work.)



# --- Streamlit page config ---
st.set_page_config(
    page_title="Falowen – Your German Conversation Partner",
    layout="centered",
    initial_sidebar_state="expanded"
)

# ---- Falowen Header ----
st.markdown(
    """
    <div style='display: flex; align-items: center; justify-content: space-between; margin-bottom: 22px; width: 100%;'>
        <!-- Left Flag -->
        <span style='font-size:2.2rem; flex: 0 0 auto;'>🇬🇭</span>
        <!-- Center Block -->
        <div style='flex: 1; text-align: center;'>
            <span style='font-size:2.1rem; font-weight:bold; color:#17617a; letter-spacing:2px;'>
                Falowen App
            </span>
            <br>
            <span style='font-size:1.08rem; color:#ff9900; font-weight:600;'>Learn Language Education Academy</span>
            <br>
            <span style='font-size:1.05rem; color:#268049; font-weight:400;'>
                Your All-in-One German Learning Platform for Speaking, Writing, Exams, and Vocabulary
            </span>
            <br>
            <span style='font-size:1.01rem; color:#1976d2; font-weight:500;'>
                Website: <a href='https://www.learngermanghana.com' target='_blank' style='color:#1565c0; text-decoration:none;'>www.learngermanghana.com</a>
            </span>
            <br>
            <span style='font-size:0.98rem; color:#666; font-weight:500;'>
                Competent German Tutors Team
            </span>
        </div>
        <!-- Right Flag -->
        <span style='font-size:2.2rem; flex: 0 0 auto;'>🇩🇪</span>
    </div>
    """,
    unsafe_allow_html=True
)

# ==== 2) Helpers to load & save progress ====
def load_progress(student_code, level, teil):
    c.execute(
        "SELECT remaining, used FROM exam_progress WHERE student_code=? AND level=? AND teil=?",
        (student_code, level, teil)
    )
    row = c.fetchone()
    if row:
        return json.loads(row[0]), json.loads(row[1])
    return None, None

def save_progress(student_code, level, teil, remaining, used):
    c.execute(
        "REPLACE INTO exam_progress (student_code, level, teil, remaining, used) VALUES (?,?,?,?,?)",
        (student_code, level, teil, json.dumps(remaining), json.dumps(used))
    )
    conn.commit()

def save_schreiben_attempt(student_code, name, level, score):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO schreiben_progress (student_code, name, level, essay, score, feedback, date) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (student_code, name, level, "", score, "", str(date.today()))
    )
    conn.commit()

# Bubble CSS
bubble_user = "background:#e3f2fd;padding:12px 20px;border-radius:18px 18px 6px 18px;margin:8px 0;display:inline-block;"
bubble_assistant = "background:#fff9c4;padding:12px 20px;border-radius:18px 18px 18px 6px;margin:8px 0;display:inline-block;"

# Highlight function and words
highlight_words = ["correct", "should", "mistake", "improve", "tip"]
def highlight_keywords(text, words):
    import re
    pattern = r'(' + '|'.join(map(re.escape, words)) + r')'
    return re.sub(pattern, r"<span style='color:#d63384;font-weight:600'>\1</span>", text, flags=re.IGNORECASE)



# ====================================
# 5. CONSTANTS & VOCAB LISTS
# ====================================

FALOWEN_DAILY_LIMIT = 20
VOCAB_DAILY_LIMIT = 20
SCHREIBEN_DAILY_LIMIT = 5
max_turns = 25
    

# ====================================
# 1. Load student data from Google Sheet
# ====================================

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U/gviz/tq?tqx=out:csv"

def load_student_data():
    # 1) Fetch CSV
    try:
        resp = requests.get(GOOGLE_SHEET_CSV, timeout=10)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text), dtype=str)
    except Exception:
        st.error("❌ Could not load student data.")
        st.stop()

    # 2) Strip whitespace
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()

    # 3) Drop rows missing a ContractEnd
    df = df[df["ContractEnd"].notna() & (df["ContractEnd"] != "")]

    # 4) Parse ContractEnd into datetime (two formats)
    df["ContractEnd_dt"] = pd.to_datetime(
        df["ContractEnd"], format="%m/%d/%Y", errors="coerce", dayfirst=False
    )
    # Fallback European format where needed
    mask = df["ContractEnd_dt"].isna()
    df.loc[mask, "ContractEnd_dt"] = pd.to_datetime(
        df.loc[mask, "ContractEnd"], format="%d/%m/%Y", errors="coerce", dayfirst=True
    )

    # 5) Sort by latest ContractEnd_dt and drop duplicates
    df = df.sort_values("ContractEnd_dt", ascending=False)
    df = df.drop_duplicates(subset=["StudentCode"], keep="first")

    # 6) Clean up helper column
    df = df.drop(columns=["ContractEnd_dt"])

    return df

def is_contract_expired(row):
    expiry_str = str(row.get("ContractEnd", "")).strip()
    # Debug lines removed

    if not expiry_str or expiry_str.lower() == "nan":
        return True

    # Try known formats
    expiry_date = None
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            expiry_date = datetime.strptime(expiry_str, fmt)
            break
        except ValueError:
            continue

    # Fallback to pandas auto-parse
    if expiry_date is None:
        parsed = pd.to_datetime(expiry_str, errors="coerce")
        if pd.isnull(parsed):
            return True
        expiry_date = parsed.to_pydatetime()

    today = datetime.now().date()
    # Debug lines removed

    return expiry_date.date() < today


# ---- Cookie & Session Setup ----
COOKIE_SECRET = os.getenv("COOKIE_SECRET") or st.secrets.get("COOKIE_SECRET")
if not COOKIE_SECRET:
    raise ValueError("COOKIE_SECRET environment variable not set")

cookie_manager = EncryptedCookieManager(prefix="falowen_", password=COOKIE_SECRET)
cookie_manager.ready()
if not cookie_manager.ready():
    st.warning("Cookies are not ready. Please refresh.")
    st.stop()

for key, default in [("logged_in", False), ("student_row", None), ("student_code", ""), ("student_name", "")]:
    st.session_state.setdefault(key, default)

code_from_cookie = cookie_manager.get("student_code") or ""
code_from_cookie = str(code_from_cookie).strip().lower()

# --- Auto-login via Cookie ---
if not st.session_state["logged_in"] and code_from_cookie:
    df_students = load_student_data()
    # Normalize for matching
    df_students["StudentCode"] = df_students["StudentCode"].str.lower().str.strip()
    df_students["Email"] = df_students["Email"].str.lower().str.strip()

    found = df_students[df_students["StudentCode"] == code_from_cookie]
    if not found.empty:
        student_row = found.iloc[0]
        if is_contract_expired(student_row):
            st.error("Your contract has expired. Please contact the office for renewal.")
            cookie_manager["student_code"] = ""
            cookie_manager.save()
            st.stop()
        st.session_state.update({
            "logged_in": True,
            "student_row": student_row.to_dict(),
            "student_code": student_row["StudentCode"],
            "student_name": student_row["Name"]
        })

# --- Manual Login Form ---
if not st.session_state["logged_in"]:
    st.title("🔑 Student Login")
    login_input = st.text_input("Enter your Student Code or Email:", value=code_from_cookie).strip().lower()
    if st.button("Login"):
        df_students = load_student_data()
        df_students["StudentCode"] = df_students["StudentCode"].str.lower().str.strip()
        df_students["Email"]       = df_students["Email"].str.lower().str.strip()

        found = df_students[
            (df_students["StudentCode"] == login_input) |
            (df_students["Email"]       == login_input)
        ]
        if not found.empty:
            student_row = found.iloc[0]
            # Debug: show what we're checking
            st.write("DEBUG: raw ContractEnd for login:", repr(student_row["ContractEnd"]))
            if is_contract_expired(student_row):
                st.error("Your contract has expired. Please contact the office for renewal.")
                st.stop()
            st.session_state.update({
                "logged_in": True,
                "student_row": student_row.to_dict(),
                "student_code": student_row["StudentCode"],
                "student_name": student_row["Name"]
            })
            cookie_manager["student_code"] = student_row["StudentCode"]
            cookie_manager.save()
            st.success(f"Welcome, {student_row['Name']}! 🎉")
            st.rerun()
        else:
            st.error("Login failed. Please check your Student Code or Email.")

    # --- Add extra info for students below the login box ---
    st.markdown(
        """
        <div style='text-align:center; margin-top:20px; margin-bottom:12px;'>
            <span style='color:#ff9800;font-weight:600;'>
                🔒 <b>Data Privacy:</b> Your login details and activity are never shared. Only your teacher can see your learning progress.
            </span>
            <br>
            <span style='color:#1976d2;'>
                🆕 <b>Update:</b> New features have been added to help you prepare for your German exam! Practice as often as you want, within your daily quota.
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.stop()


# --- Logged In UI ---
st.write(f"👋 Welcome, **{st.session_state['student_name']}**")
if st.button("Log out"):
    cookie_manager["student_code"] = ""
    cookie_manager.save()
    for k in ["logged_in", "student_row", "student_code", "student_name"]:
        st.session_state[k] = False if k == "logged_in" else ""
    st.success("You have been logged out.")
    st.rerun()




# ======= Data Loading Functions =======
@st.cache_data
def load_student_data():
    SHEET_ID = "12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U"
    SHEET_NAME = "Sheet1"
    csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"
    df = pd.read_csv(csv_url)
    df.columns = df.columns.str.strip().str.replace(" ", "")
    return df

@st.cache_data
def load_stats_data():
    SHEET_ID = "1BRb8p3Rq0VpFCLSwL4eS9tSgXBo9hSWzfW_J_7W36NQ"
    SHEET_NAME = "Sheet1"
    csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"
    df = pd.read_csv(csv_url)
    # Clean columns for easier access
    df.columns = df.columns.str.strip().str.lower()
    return df

@st.cache_data
def load_reviews():
    SHEET_ID   = "137HANmV9jmMWJEdcA1klqGiP8nYihkDugcIbA-2V1Wc"
    SHEET_NAME = "Sheet1"
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
        f"/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"
    )
    df = pd.read_csv(url)
    df.columns = df.columns.str.strip().str.lower()
    return df

import time
import matplotlib.pyplot as plt

# ======= Dashboard Code =======
# ======= Dashboard Code =======
if st.session_state.get("logged_in"):
    student_code = st.session_state.get("student_code", "").strip().lower()
    student_name = st.session_state.get("student_name", "")

    tab = st.radio(
        "How do you want to practice?",
        [
            "Dashboard",
            "Course Book",
            "My Results and Resources",
            "Exams Mode & Custom Chat",
            "Vocab Trainer",
            "Schreiben Trainer",
        ],
        key="main_tab_select"
    )

    if tab == "Dashboard":
        # 🏠 Compact Dashboard header
        st.markdown(
            '''
            <div style="
                padding: 8px 12px;
                background: #343a40;
                color: #ffffff;
                border-radius: 6px;
                text-align: center;
                margin-bottom: 8px;
                font-size: 1.3rem;
            ">
                📊 Student Dashboard
            </div>
            ''',
            unsafe_allow_html=True
        )
        st.divider()

        # --- Get student_row first ---
        df_students = load_student_data()
        matches = df_students[df_students["StudentCode"].str.lower() == student_code]
        student_row = matches.iloc[0].to_dict() if not matches.empty else {}

        display_name = student_row.get('Name') or student_name or "Student"
        first_name = str(display_name).strip().split()[0].title() if display_name else "Student"

        # --- Minimal, super-visible greeting for mobile ---
        st.success(f"Hello, {first_name}! 👋")
        st.info("Great to see you. Let's keep learning!")

        # --- Student Info & Balance ---
        st.markdown(f"### 👤 {student_row.get('Name','')}")
        st.markdown(
            f"- **Level:** {student_row.get('Level','')}\n"
            f"- **Code:** `{student_row.get('StudentCode','')}`\n"
            f"- **Email:** {student_row.get('Email','')}\n"
            f"- **Phone:** {student_row.get('Phone','')}\n"
            f"- **Location:** {student_row.get('Location','')}\n"
            f"- **Contract:** {student_row.get('ContractStart','')} ➔ {student_row.get('ContractEnd','')}\n"
            f"- **Enroll Date:** {student_row.get('EnrollDate','')}\n"
            f"- **Status:** {student_row.get('Status','')}"
        )
        try:
            bal = float(student_row.get("Balance", 0))
            if bal > 0:
                st.warning(f"💸 Balance to pay: ₵{bal:.2f}")
        except:
            pass

        # --- Announcements & Ads (auto-rotating, reduced size) ---
        st.markdown("### 🖼️ Announcements & Ads")
        ad_images = [
            "https://i.imgur.com/9hLAScD.jpg",
            "https://i.imgur.com/2PzOOvn.jpg",
            "https://i.imgur.com/Q9mpvRY.jpg",
        ]
        ad_captions = [
            "New A2 Classes—Limited Seats!",
            "New B1 Classes—Limited Seats!",
            "Join our classes live in person or online!",
        ]
        if "ad_idx" not in st.session_state:
            st.session_state["ad_idx"] = 0
            st.session_state["ad_last_time"] = time.time()

        ROTATE_AD_SEC = 6
        now = time.time()
        if now - st.session_state["ad_last_time"] > ROTATE_AD_SEC:
            st.session_state["ad_idx"] = (st.session_state["ad_idx"] + 1) % len(ad_images)
            st.session_state["ad_last_time"] = now
            st.rerun()

        idx = st.session_state["ad_idx"]
        st.image(ad_images[idx], caption=ad_captions[idx], width=400)  # change width if needed

        # --- Simple Goethe Exam Section ---
        with st.expander("📅 Goethe Exam Dates & Fees", expanded=True):
            st.markdown(
                """
| Level | Date       | Fee (GHS) |
|-------|------------|-----------|
| A1    | 21.07.25   | 2,850     |
| A2    | 22.07.25   | 2,400     |
| B1    | 23.07.25   | 2,750     |
| B2    | 24.07.25   | 2,500     |
| C1    | 25.07.25   | 2,450     |

- [Register here](https://www.goethe.de/ins/gh/en/spr/prf/anm.html)
- After paying, send proof to registrations-accra@goethe.de
- Pay by Mobile Money or Ecobank (use your full name as reference)
                """,
                unsafe_allow_html=True
            )

        # --- Auto-Rotating Student Reviews ---
        st.markdown("### 🗣️ What Our Students Say")
        reviews = load_reviews()
        if reviews.empty:
            st.info("No reviews yet. Be the first to share your experience!")
        else:
            rev_list = reviews.to_dict("records")
            if "rev_idx" not in st.session_state:
                st.session_state["rev_idx"] = 0
                st.session_state["rev_last_time"] = time.time()

            ROTATE_REV_SEC = 8
            now = time.time()
            if now - st.session_state["rev_last_time"] > ROTATE_REV_SEC:
                st.session_state["rev_idx"] = (st.session_state["rev_idx"] + 1) % len(rev_list)
                st.session_state["rev_last_time"] = now
                st.rerun()

            r = rev_list[st.session_state["rev_idx"]]
            stars = "★" * int(r.get("rating", 5)) + "☆" * (5 - int(r.get("rating", 5)))
            st.markdown(
                f"> {r.get('review_text','')}\n"
                f"> — **{r.get('student_name','')}**  \n"
                f"> {stars}"
            )

def get_a1_schedule():
    return [
        # DAY 1
        {
            "day": 1,
            "topic": "Lesen & Hören 0.1",
            "chapter": "0.1",
            "goal": "You will learn to introduce yourself, greet others in German, and ask about people's well-being.",
            "instruction": "Watch the video, review grammar, do the workbook, submit assignment.",
            "assignment": True,
            "lesen_hören": {
                "video": "https://youtu.be/7QZhrb-gvxY",
                "grammarbook_link": "https://drive.google.com/file/d/1D9Pwg29qZ89xh6caAPBcLJ1K671VUc0_/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1wjtEyPphP0N7jLbF3AWb5wN_FuJZ5jUQ/view?usp=sharing"
            }
        },
        # DAY 2 – Multi chapter
        {
            "day": 2,
            "topic": "Lesen & Hören 0.2 and 1.1 ",
            "chapter": "0.2_1.1",
            "goal": "Understand the German alphabets, personal pronouns and verb conjugation in German.",
            "instruction": "You are doing Lesen and Hören chapter 0.2 and 1.1. Make sure to follow up attentively.",
            "lesen_hören": [
                {
                    "chapter": "0.2",
                    "video": "",
                    "grammarbook_link": "https://drive.google.com/file/d/1KtJCF15Ng4cLU88wdUCX5iumOLY7ZA0a/view?usp=sharing",
                    "assignment": True,
                    "workbook_link": "https://drive.google.com/file/d/1R6PqzgsPm9f5iVn7JZXSNVa_NttoPU9Q/view?usp=sharing",
                },
                {
                    "chapter": "1.1",
                    "video": "https://youtu.be/rNxu2uQZ_lc",
                    "grammarbook_link": "https://drive.google.com/file/d/1DKhyi-43HX1TNs8fxA9bgRvhylubilBf/view?usp=sharing",
                    "assignment": True,
                    "workbook_link": "https://drive.google.com/file/d/1A1D1pAssnoncF1JY0v54XT2npPb6mQZv/view?usp=sharing",
                }
            ]
        },
        # DAY 3
        {
            "day": 3,
            "topic": "Schreiben & Sprechen 1.1 and Lesen & Hören 1.2",
            "chapter": "1.1_1.2",
            "goal": "Introduce others and talk about your family.",
            "instruction": (
                "Begin with the practicals at **Schreiben & Sprechen** (writing & speaking). "
                "Then, move to **Lesen & Hören** (reading & listening). "
                "**Do assignments only at Lesen & Hören.**\n\n"
                "Schreiben & Sprechen activities are for self-practice and have answers provided for self-check. "
                "Main assignment to be marked is under Lesen & Hören below."
            ),
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": "https://drive.google.com/file/d/1GXWzy3cvbl_goP4-ymFuYDtX4X23D70j/view?usp=sharing",
                "assignment": False,
            },
            "lesen_hören": [
                {
                    "chapter": "1.2",
                    "video": "https://youtu.be/NVCN4fZXEk0",
                    "grammarbook_link": "https://drive.google.com/file/d/1OUJT9aSU1XABi3cdZlstUvfBIndyEOwb/view?usp=sharing",
                    "workbook_link": "https://drive.google.com/file/d/1Lubevhd7zMlbvPcvHHC1D0GzW7xqa4Mp/view?usp=sharing",
                    "assignment": True
                }
            ]
        },
        # DAY 4
        {
            "day": 4,
            "topic": "Lesen & Hören 2",
            "chapter": "2",
            "goal": "Learn numbers from one to 10 thousand. Also know the difference between city and street",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.",
            "assignment": True,
            "lesen_hören": {
                "video": "https://youtu.be/BzI2n4A8Oak",
                "grammarbook_link": "https://drive.google.com/file/d/1f2CJ492liO8ccudCadxHIISwGJkHP6st/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1C4VZDUj7VT27Qrn9vS5MNc3QfRqpmDGE/view?usp=sharing",
                "assignment": True
            }
        },
        # DAY 5
        {
            "day": 5,
            "topic": "Schreiben & Sprechen 1.2 (Recap)",
            "chapter": "1.2",
            "goal": "Consolidate your understanding of introductions.",
            "instruction": "Use self-practice workbook and review answers for self-check.",
            "assignment": False,
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": "https://drive.google.com/file/d/1ojXvizvJz_qGes7I39pjdhnmlul7xhxB/view?usp=sharing"
            }
        },
        # DAY 6
        {
            "day": 6,
            "topic": "Schreiben & Sprechen 2.3",
            "chapter": "2.3",
            "goal": "Learn about family and expressing your hobby",
            "assignment": False,
            "instruction": "Use self-practice workbook and review answers for self-check.",
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": "https://drive.google.com/file/d/1x_u_tyICY-8xFuxsuOW2tqTzs7g8TquM/view?usp=sharing"
            }
        },
        # DAY 7
        {
            "day": 7,
            "topic": "Lesen & Hören 3",
            "chapter": "3",
            "goal": "Know how to ask for a price and also the use of mogen and gern to express your hobby",
            "instruction": "Do schreiben and sprechen 2.3 before this chapter for better understanding",
            "assignment": True,
            "lesen_hören": {
                "video": "https://youtu.be/dGIj1GbK4sI",
                "grammarbook_link": "https://drive.google.com/file/d/1sCE5y8FVctySejSVNm9lrTG3slIucxqY/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1lL4yrZLMtKLnNuVTC2Sg_ayfkUZfIuak/view?usp=sharing"
            }
        },
        # DAY 8
        {
            "day": 8,
            "topic": "Lesen & Hören 4",
            "chapter": "4",
            "goal": "Learn about schon mal and noch nie, irregular verbs and all the personal pronouns",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.",
            "assignment": True,
            "lesen_hören": {
                "video": "https://youtu.be/JfTc1G9mubs",
                "grammarbook_link": "https://drive.google.com/file/d/1obsYT3dP3qT-i06SjXmqRzCT2pNoJJZp/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1woXksV9sTZ_8huXa8yf6QUQ8aUXPxVug/view?usp=sharing"
            }
        },
        # DAY 9
        {
            "day": 9,
            "topic": "Lesen & Hören 5",
            "chapter": "5",
            "goal": "Learn about the German articles and cases",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.",
            "assignment": True,
            "lesen_hören": {
                "video": "https://youtu.be/Yi5ZA-XD-GY?si=nCX_pceEYgAL-FU0",
                "grammarbook_link": "https://drive.google.com/file/d/17y5fGW8nAbfeVgolV7tEW4BLiLXZDoO6/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1zjAqvQqNb7iKknuhJ79bUclimEaTg-mt/view?usp=sharing"
            }
        },
        # DAY 10
        {
            "day": 10,
            "topic": "Lesen & Hören 6 and Schreiben & Sprechen 2.4",
            "chapter": "6_2.4",
            "goal": "Understand Possessive Determiners and its usage in connection with nouns",
            "instruction": "The assignment is the lesen and horen chapter 6 but you must also go through schreiben and sprechnen 2.4 for full understanding",         
            "lesen_hören": {
                "video": "https://youtu.be/SXwDqcwrR3k",
                "grammarbook_link": "https://drive.google.com/file/d/1Fy4bKhaHHb4ahS2xIumrLtuqdQ0YAFB4/view?usp=sharing",
                "assignment": True,
                "workbook_link": "https://drive.google.com/file/d/1Da1iw54oAqoaY-UIw6oyIn8tsDmIi1YR/view?usp=sharing"
            },
            "schreiben_sprechen": {
                "video": "https://youtu.be/5qnB2Gocp8s",
                "workbook_link": "https://drive.google.com/file/d/1GbIc44ToWh2upnHv6eX3ZjFrvnf4fcEM/view?usp=sharing",
                "assignment": False,
            }
        },
        # DAY 11
        {
            "day": 11,
            "topic": "Lesen & Hören 7",
            "chapter": "7",
            "goal": "Understand the 12 hour clock system",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.",
            "assignment": True,
            "lesen_hören": {
                "video": "https://youtu.be/uyvXoCoqjiE",
                "grammarbook_link": "https://drive.google.com/file/d/1pSaloRhfh8eTKK_r9mzwp6xkbfdkCVox/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1QyDdRae_1qv_umRb15dCJZTPdXi7zPWd/view?usp=sharing"
            }
        },
        # DAY 12
        {
            "day": 12,
            "topic": "Lesen & Hören 8",
            "chapter": "8",
            "goal": "Understand the 24 hour clock and date system in German",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.",
            "assignment": True,
            "lesen_hören": {
                "video": "https://youtu.be/hLpPFOthVkU",
                "grammarbook_link": "https://drive.google.com/file/d/1fW2ChjnDKW_5SEr65ZgE1ylJy1To46_p/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1onzokN8kQualNO6MSsPndFXiRwsnsVM9/view?usp=sharing"
            }
        },
        # DAY 13
        {
            "day": 13,
            "topic": "Schreiben & Sprechen 3.5",
            "chapter": "3.5",
            "goal": "Recap from the lesen and horen. Understand numbers, time, asking of price and how to formulate statements in German",
            "instruction": "Use the statement rule to talk about your weekly routine using the activities listed. Share with your tutor when done",
            "schreiben_sprechen": {
                "video": "https://youtu.be/PwDLGmfBUDw",
                "assignment": False,
                "workbook_link": "https://drive.google.com/file/d/12oFKrKrHBwSpSnzxLX_e-cjPSiYtCFVs/view?usp=sharing"
            }
        },
        # DAY 14
        {
            "day": 14,
            "topic": "Schreiben & Sprechen 3.6",
            "chapter": "3.6",
            "goal": "Understand how to use modal verbs with main verbs and separable verbs",
            "assignment": False,
            "instruction": "This is a practical exercise. All the answers are included in the document except for the last paragraph. You can send a screenshot of that to your tutor",
            "schreiben_sprechen": {
                "video": "https://youtu.be/XwFPjLjvDog",
                "workbook_link": "https://drive.google.com/file/d/1wnZehLNfkjgKMFw1V3BX8V399rZg6XLv/view?usp=sharing"
            }
        },
        # DAY 15
        {
            "day": 15,
            "topic": "Schreiben & Sprechen 4.7",
            "chapter": "4.7",
            "assignment": False,
            "goal": "Understand imperative statements and learn how to use them in your Sprechen exams, especially in Teil 3.",
            "instruction": "After completing this chapter, go to the Falowen Exam Chat Mode, select A1 Teil 3, and start practicing",
            "schreiben_sprechen": {
                "video": "https://youtu.be/IVtUc9T3o0Y",
                "workbook_link": "https://drive.google.com/file/d/1953B01hB9Ex7LXXU0qIaGU8xgCDjpSm4/view?usp=sharing"
            }
        },
        # DAY 16
        {
            "day": 16,
            "topic": "Lesen & Hören 9 and 10",
            "chapter": "9_10",
            "goal": "Understand how to negate statements using nicht,kein and nein",
            "instruction": "This chapter has two assignments. Do the assignments for chapter 9 and after chapter 10. Chapter 10 has no grammar",
            "lesen_hören": [
                {
                    "chapter": "9",
                    "video": "https://youtu.be/MrB3BPtQN6A",
                    "assignment": True,
                    "grammarbook_link": "https://drive.google.com/file/d/1g-qLEH1ZDnFZCT83TW-MPLxNt2nO7UAv/view?usp=sharing",
                    "workbook_link": "https://drive.google.com/file/d/1hKtQdXg5y3yJyFBQsCMr7fZ11cYbuG7D/view?usp=sharing"
                },
                {
                    "chapter": "10",
                    "video": "",
                    "grammarbook_link": "",
                    "assignment": True,
                    "workbook_link": "https://drive.google.com/file/d/1rJXshXQSS5Or4ipv1VmUMsoB0V1Vx4VK/view?usp=sharing"
                }
            ]
        },
        # DAY 17
        {
            "day": 17,
            "topic": "Lesen & Hören 11",
            "chapter": "11",
            "goal": "Understand instructions and request in German using the Imperative rule",
            "instruction": "",
            "lesen_hören": {
                "video": "https://youtu.be/k2ZC3rXPe1k",
                "assignment": True,
                "grammarbook_link": "https://drive.google.com/file/d/1lMzZrM4aAItO8bBmehODvT6gG7dz8I9s/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/17FNSfHBxyga9sKxzicT_qkP7PA4vB5-A/view?usp=sharing"
            }
        },
        # DAY 18
        {
            "day": 18,
            "topic": "Lesen & Hören 12.1 and 12.2 and Schreiben & Sprechen (including 5.8)",
            "chapter": "12.1_12.2",
            "goal": "Learn about German professions and how to use two-way prepositions",
            "instruction": "This lesson has two Lesen & Hören assignments (12.1 and 12.2) and one Schreiben & Sprechen practice (5.8) for practice to understand chapter 12",
            "lesen_hören": [
                {
                    "chapter": "12.1",
                    "video": "",
                    "assignment": True,
                    "grammarbook_link": "https://drive.google.com/file/d/1wdWYVxBhu4QtRoETDpDww-LjjzsGDYva/view?usp=sharing",
                    "workbook_link": "https://drive.google.com/file/d/1A0NkFl1AG68jHeqSytI3ygJ0k7H74AEX/view?usp=sharing"
                },
                {
                    "chapter": "12.2",
                    "video": "",
                    "assignment": True,
                    "grammarbook_link": "",
                    "workbook_link": "https://drive.google.com/file/d/1xojH7Tgb5LeJj3nzNSATUVppWnJgJLEF/view?usp=sharing"
                }
            ],
            "schreiben_sprechen": {
                "video": "",
                "assignment": False,
                "workbook_link": "https://drive.google.com/file/d/1iyYBuxu3bBEovxz0j9QeSu_1URX92fvN/view?usp=sharing"
            }
        },
        # DAY 19
        {
            "day": 19,
            "topic": "Schreiben & Sprechen 5.9",
            "chapter": "5.9",
            "goal": "Understand the difference between Erlaubt and Verboten and how to use it in the exams hall",
            "instruction": "",
            "schreiben_sprechen": {
                "video": "",
                "assignment": False,
                "workbook_link": "https://drive.google.com/file/d/1-bbY9zoos62U5jUAFrYCyxay_cvbk65N/view?usp=sharing"
            }
        },
        # DAY 20
        {
            "day": 20,
            "topic": "Schreiben & Sprechen 6.10 (Intro to letter writing)",
            "chapter": "6.10",
            "goal": "Practice how to write both formal and informal letters",
            "instruction": "Write all the two letters in this document and send to your tutor for corrections",
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": "https://drive.google.com/file/d/1SjaDH1bYR7O-BnIbM2N82XOEjeLCfPFb/view?usp=sharing"
            }
        },
        # DAY 21
        {
            "day": 21,
            "topic": "Lesen & Hören 13 and Schreiben & Sprechen 6.11",
            "chapter": "13_6.11",
            "goal": "",
            "instruction": "",
            "lesen_hören": {
                "video": "",
                "grammarbook_link": "https://drive.google.com/file/d/1PCXsTIg9iNlaAUkwH8BYekw_3v1HJjGq/view?usp=sharing",
                "assignment": True,
                "workbook_link": "https://drive.google.com/file/d/1zCnIoVHlfRwOQ9mX2NxVFuHgsqfHUkDK/view?usp=sharing"
            },
            "schreiben_sprechen": {
                "video": "",
                "assignment": False,
                "workbook_link": ""
            }
        },
        # DAY 22
        {
            "day": 22,
            "topic": "Lesen & Hören 14.1 and Schreiben & Sprechen 7.12",
            "chapter": "14.1_7.12",
            "goal": "",
            "instruction": "",
            "lesen_hören": {
                "video": "",
                "assignment": True,
                "grammarbook_link": "https://drive.google.com/file/d/1EFZA_oAeznMBEqIgTWyeFt9wLdmqA-Bp/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1_zEb4wmENI7szcepRz_CIjSo9aS7RHv-/view?usp=sharing"
            },
            "schreiben_sprechen": {
                "video": "",
                "assignment": False,
                "workbook_link": ""
            }
        },
        # DAY 23
        {
            "day": 23,
            "topic": "Lesen & Hören 14.2",
            "chapter": "14.2_7.12",
            "goal": "Understand adjective declension and dative verbs",
            "instruction": " This chapter has no assignment. Only grammar",
            "lesen_hören": {
                "video": "",
                "assignment": False,
                "grammarbook_link": "https://drive.google.com/file/d/16h-yS0gkB2_FL1zxCC4MaqRBbKne7GI1/view?usp=sharing",
                "workbook_link": ""
            },
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": ""
            }
        },
        # DAY 24
        {
            "day": 24,
            "topic": "Schreiben & Sprechen 8.13",
            "chapter": "8.13",
            "goal": "Learn about conjunctions and how to apply them in your exams",
            "instruction": "",
            "assignment": False,
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": "https://drive.google.com/file/d/1smb4IuRqSKndoGf_ujEi5IiaYyXOTj4t/view?usp=sharing"
            }
        },
        # DAY 25
        {
            "day": 25,
            "topic": "Goethe Mock Test",
            "chapter": "final",
            "goal": "This test should help the student have an idea about how the lesen and horen will look like",
            "instruction": "",
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": "https://forms.gle/FP8ZPNhwxcAZsTfY6"
            }
        }
    ]

def get_a2_schedule():
    return [
        # DAY 1
        {
            "day": 1,
            "topic": "Small Talk 1.1 (Exercise)",
            "chapter": "1.1",
            "goal": "Practice basic greetings and small talk.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "assignment": True,
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1NsCKO4K7MWI-queLWCeBuclmaqPN04YQ/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1LXDI1yyJ4aT4LhX5eGDbKnkCkJZ2EE2T/view?usp=sharing"
        },
        # DAY 2
        {
            "day": 2,
            "topic": "Personen Beschreiben 1.2 (Exercise)",
            "chapter": "1.2",
            "goal": "Describe people and their appearance.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1VB_nXEfdeTgkzCYjh0tvE75zFJleMlyU/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/128lWaKgCZ2V-3tActM-dwNy6igLLlzH3/view?usp=sharing"
        },
        # DAY 3
        {
            "day": 3,
            "topic": "Dinge und Personen vergleichen 1.3",
            "chapter": "1.3",
            "goal": "Learn to compare things and people.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1Z3sSDCxPQz27TDSpN9r8lQUpHhBVfhYZ/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/18YXe9mxyyKTars1gL5cgFsXrbM25kiN8/view?usp=sharing"
        },
        # DAY 4
        {
            "day": 4,
            "topic": "Wo möchten wir uns treffen? 2.4",
            "chapter": "2.4",
            "goal": "Arrange and discuss meeting places.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/14qE_XJr3mTNr6PF5aa0aCqauh9ngYTJ8/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1RaXTZQ9jHaJYwKrP728zevDSQHFKeR0E/view?usp=sharing"
        },
        # DAY 5
        {
            "day": 5,
            "topic": "Was machst du in deiner Freizeit? 2.5 ",
            "chapter": "2.5",
            "goal": "Talk about free time activities.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/11yEcMioSB9x1ZD-x5_67ApFzP53iau-N/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1dIsFg7wNaqyyOHm95h7xv4Ssll5Fm0V1/view?usp=sharing"
        },
        # DAY 6
        {
            "day": 6,
            "topic": "Möbel und Räume kennenlernen 3.6",
            "chapter": "3.6",
            "goal": "Identify furniture and rooms.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1clWbDAvLlXpgWx7pKc71Oq3H2p0_GZnV/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1EF87TdHa6Y-qgLFUx8S6GAom9g5EBQNP/view?usp=sharing"
        },
        # DAY 7
        {
            "day": 7,
            "topic": "Eine Wohnung suchen (Übung) 3.7",
            "chapter": "3.7",
            "goal": "Practice searching for an apartment.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "https://youtu.be/ScU6w8VQgNg",
            "grammarbook_link": "https://drive.google.com/file/d/1clWbDAvLlXpgWx7pKc71Oq3H2p0_GZnV/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1EF87TdHa6Y-qgLFUx8S6GAom9g5EBQNP/view?usp=sharing"
        },
        # DAY 8
        {
            "day": 8,
            "topic": "Rezepte und Essen (Exercise) 3.8",
            "chapter": "3.8",
            "assignment": True,
            "goal": "Learn about recipes and food. Practice using sequence words like zuerst', 'nachdem', and 'außerdem' to organize your letter.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "https://youtu.be/_xQMNp3qcDQ",
            "grammarbook_link": "https://drive.google.com/file/d/16lh8sPl_IDZ3dLwYNvL73PqOFCixidrI/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1c8JJyVlKYI2mz6xLZZ6RkRHLnH3Dtv0c/view?usp=sharing"
        },
        # DAY 9
        {
            "day": 9,
            "topic": "Urlaub 4.9",
            "chapter": "4.9",
            "goal": "Discuss vacation plans.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "https://youtu.be/NxoQH-BY9Js",
            "grammarbook_link": "https://drive.google.com/file/d/1kOb7c08Pkxf21OQE_xIGEaif7Xq7k-ty/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1NzRxbGUe306Vq0mq9kKsc3y3HYqkMhuA/view?usp=sharing"
        },
        # DAY 10
        {
            "day": 10,
            "topic": "Tourismus und Traditionelle Feste 4.10",
            "chapter": "4.10",
            "assignment": True,
            "goal": "Learn about tourism and festivals.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1snFsDYBK8RrPRq2n3PtWvcIctSph-zvN/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1vijZn-ryhT46cTzGmetuF0c4zys0yGlB/view?usp=sharing"
        },
        # DAY 11
        {
            "day": 11,
            "topic": "Unterwegs: Verkehrsmittel vergleichen 4.11",
            "chapter": "4.11",
            "assignment": True,
            "goal": "Compare means of transportation.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1Vl9UPeM2RaATafT8t539aOPrxnSkfr9A/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1c7ITea0iVbCaPO0piark9RnqJgZS-DOi/view?usp=sharing"
        },
        # DAY 12
        {
            "day": 12,
            "topic": "Ein Tag im Leben (Übung) 5.12",
            "chapter": "5.12",
            "assignment": True,
            "goal": "Describe a typical day.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/16l_UeUkxYNXD35o6hxPxV0xGVHyvvpqV/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/18u6FnHpd2nAh1Ev_2mVk5aV3GdVC6Add/view?usp=sharing"
        },
        # DAY 13
        {
            "day": 13,
            "topic": "Ein Vorstellungsgespräch (Exercise) 5.13",
            "chapter": "5.13",
            "assignment": True,
            "goal": "Prepare for a job interview.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "https://youtu.be/urKBrX5VAYU",
            "grammarbook_link": "https://drive.google.com/file/d/1tv2tYzn9mIG57hwWr_ilxV1My7kt-RKQ/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1sW2yKZptnYWPhS7ciYdi0hN5HV-ycsF0/view?usp=sharing"
        },
        # DAY 14
        {
            "day": 14,
            "topic": "Beruf und Karriere (Exercise) 5.14",
            "chapter": "5.14",
            "assignment": True,
            "goal": "Discuss jobs and careers.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "https://youtu.be/IyBvx-yVT-0",
            "grammarbook_link": "https://drive.google.com/file/d/13mVpVGfhY1NQn-BEb7xYUivnaZbhXJsK/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1rlZoo49bYBRjt7mu3Ydktzgfdq4IyK2q/view?usp=sharing"
        },
        # DAY 15
        {
            "day": 15,
            "topic": "Mein Lieblingssport 6.15",
            "chapter": "6.15",
            "assignment": True,
            "goal": "Talk about your favorite sport.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1UohFnTmCwjCJHQU1etaGOBzZJTk2kauz/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1iiExhUj66r5p0SJZfV7PsmCWOyaF360s/view?usp=sharing"
        },
        # DAY 16
        {
            "day": 16,
            "topic": "Wohlbefinden und Entspannung 6.16",
            "chapter": "6.16",
            "goal": "Express well-being and relaxation.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 17
        {
            "day": 17,
            "topic": "In die Apotheke gehen 6.17",
            "chapter": "6.17",
            "goal": "Learn phrases for the pharmacy.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 18
        {
            "day": 18,
            "topic": "Die Bank anrufen 7.18",
            "chapter": "7.18",
            "goal": "Practice calling the bank.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1qNHtY8MYOXjtBxf6wHi6T_P_X1DGFtPm/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1GD7cCPU8ZFykcwsFQZuQMi2fiNrvrCPg/view?usp=sharing"
        },
        # DAY 19
        {
            "day": 19,
            "topic": "Einkaufen? Wo und wie? (Exercise) 7.19",
            "chapter": "7.19",
            "goal": "Shop and ask about locations.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1Qt9oxn-74t8dFdsk-NjSc0G5OT7MQ-qq/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1CEFn14eYeomtf6CpZJhyW00CA2f_6VRc/view?usp=sharing"
        },
        # DAY 20
        {
            "day": 20,
            "topic": "Typische Reklamationssituationen üben 7.20",
            "chapter": "7.20",
            "goal": "Handle typical complaints.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1-72wZuNJE4Y92Luy0h5ygWooDnBd9PQW/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1_GTumT1II0E1PRoh6hMDwWsTPEInGeed/view?usp=sharing"
        },
        # DAY 21
        {
            "day": 21,
            "topic": "Ein Wochenende planen 8.21",
            "chapter": "8.21",
            "goal": "Plan a weekend.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1FcCg7orEizna4rAkX3_FCyd3lh_Bb3IT/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1mMtZza34QoJO_lfUiEX3kwTa-vsTN_RK/view?usp=sharing"
        },
        # DAY 22
        {
            "day": 22,
            "topic": "Die Woche Planung 8.22",
            "chapter": "8.22",
            "goal": "Make a weekly plan.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1dWr4QHw8zT1RPbuIEr_X13cPLYpH-mms/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1mg_2ytNAYF00_j-TFQelajAxgQpmgrhW/view?usp=sharing"
        },
        # DAY 23
        {
            "day": 23,
            "topic": "Wie kommst du zur Schule / zur Arbeit? 9.23",
            "chapter": "9.23",
            "goal": "Talk about your route to school or work.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1XbWKmc5P7ZAR-OqFce744xqCe7PQguXo/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1Ialg19GIE_KKHiLBDMm1aHbrzfNdb7L_/view?usp=sharing"
        },
        # DAY 24
        {
            "day": 24,
            "topic": "Einen Urlaub planen 9.24",
            "chapter": "9.24",
            "goal": "Plan a vacation.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1tFXs-DNKvt97Q4dsyXsYvKVQvT5Qqt0y/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1t3xqddDJp3-1XeJ6SesnsYsTO5xSm9vG/view?usp=sharing"
        },
        # DAY 25
        {
            "day": 25,
            "topic": "Tagesablauf (Exercise) 9.25",
            "chapter": "9.25",
            "goal": "Describe a daily routine.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "workbook_link": "https://drive.google.com/file/d/1jfWDzGfXrzhfGZ1bQe1u5MXVQkR5Et43/view?usp=sharing"
        },
        # DAY 26
        {
            "day": 26,
            "topic": "Gefühle in verschiedenen Situationen beschreiben 10.26",
            "chapter": "10.26",
            "goal": "Express feelings in various situations.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "workbook_link": "https://drive.google.com/file/d/126MQiti-lpcovP1TdyUKQAK6KjqBaoTx/view?usp=sharing"
        },
        # DAY 27
        {
            "day": 27,
            "topic": "Digitale Kommunikation 10.27",
            "chapter": "10.27",
            "goal": "Talk about digital communication.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "workbook_link": "https://drive.google.com/file/d/1UdBu6O2AMQ2g6Ot_abTsFwLvT87LHHwY/view?usp=sharing"
        },
        # DAY 28
        {
            "day": 28,
            "topic": "Über die Zukunft sprechen 10.28",
            "chapter": "10.28",
            "goal": "Discuss the future.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "workbook_link": "https://drive.google.com/file/d/1164aJFtkZM1AMb87s1-K59wuobD7q34U/view?usp=sharing"
        },
#
        # DAY 29
        {
            "day": 29,
            "topic": "Goethe Mock Test 10.29",
            "chapter": "10.29",
            "goal": "Practice how the final exams for the lesen will look like",
            "assignment": True,
            "instruction": "Answer everything on the phone and dont write in your book. The answers will be sent to your email",
            "video": "",
            "workbook_link": "https://forms.gle/YqCEMXTF5d3N9Q7C7"
        },
    ]

def get_b1_schedule():
    return [
        # DAY 1
        {
            "day": 1,
            "topic": "Traumwelten (Übung) 1.1",
            "chapter": "1.1",
            "goal": "Talk about dream worlds and imagination.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 2
        {
            "day": 2,
            "topic": "Freunde fürs Leben (Übung) 1.2",
            "chapter": "1.2",
            "goal": "Discuss friendships and important qualities.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 3
        {
            "day": 3,
            "topic": "Vergangenheit erzählen 1.3",
            "chapter": "1.3",
            "goal": "Tell stories about the past.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 4
        {
            "day": 4,
            "topic": "Wohnen und Zusammenleben 2.4",
            "chapter": "2.4",
            "goal": "Discuss housing and living together.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 5
        {
            "day": 5,
            "topic": "Feste feiern 2.5",
            "chapter": "2.5",
            "goal": "Talk about festivals and celebrations.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 6
        {
            "day": 6,
            "topic": "Mein Traumjob 2.6",
            "chapter": "2.6",
            "goal": "Describe your dream job.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 7
        {
            "day": 7,
            "topic": "Gesund bleiben 3.7",
            "chapter": "3.7",
            "goal": "Learn how to talk about health and fitness.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 8
        {
            "day": 8,
            "topic": "Arztbesuch und Gesundheitstipps 3.8",
            "chapter": "3.8",
            "goal": "Communicate with a doctor and give health tips.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 9
        {
            "day": 9,
            "topic": "Erinnerungen und Kindheit 3.9",
            "chapter": "3.9",
            "goal": "Talk about childhood memories.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 10
        {
            "day": 10,
            "topic": "Typisch deutsch? Kultur und Alltag 4.10",
            "chapter": "4.10",
            "goal": "Discuss cultural habits and everyday life.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 11
        {
            "day": 11,
            "topic": "Wünsche und Träume 4.11",
            "chapter": "4.11",
            "goal": "Express wishes and dreams.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 12
        {
            "day": 12,
            "topic": "Medien und Kommunikation 4.12",
            "chapter": "4.12",
            "goal": "Talk about media and communication.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 13
        {
            "day": 13,
            "topic": "Reisen und Verkehr 5.13",
            "chapter": "5.13",
            "goal": "Discuss travel and transportation.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 14
        {
            "day": 14,
            "topic": "Stadt oder Land 5.14",
            "chapter": "5.14",
            "goal": "Compare life in the city and the countryside.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 15
        {
            "day": 15,
            "topic": "Wohnungssuche und Umzug 5.15",
            "chapter": "5.15",
            "goal": "Talk about searching for an apartment and moving.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 16
        {
            "day": 16,
            "topic": "Natur und Umwelt 6.16",
            "chapter": "6.16",
            "goal": "Learn to discuss nature and the environment.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 17
        {
            "day": 17,
            "topic": "Probleme und Lösungen 6.17",
            "chapter": "6.17",
            "goal": "Describe problems and find solutions.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 18
        {
            "day": 18,
            "topic": "Arbeit und Finanzen 6.18",
            "chapter": "6.18",
            "goal": "Talk about work and finances.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 19
        {
            "day": 19,
            "topic": "Berufliche Zukunft 7.19",
            "chapter": "7.19",
            "goal": "Discuss future career plans.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 20
        {
            "day": 20,
            "topic": "Bildung und Weiterbildung 7.20",
            "chapter": "7.20",
            "goal": "Talk about education and further studies.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 21
        {
            "day": 21,
            "topic": "Familie und Gesellschaft 7.21",
            "chapter": "7.21",
            "goal": "Discuss family and society.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 22
        {
            "day": 22,
            "topic": "Konsum und Werbung 8.22",
            "chapter": "8.22",
            "goal": "Talk about consumption and advertising.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 23
        {
            "day": 23,
            "topic": "Globalisierung 8.23",
            "chapter": "8.23",
            "goal": "Discuss globalization and its effects.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 24
        {
            "day": 24,
            "topic": "Kulturelle Unterschiede 8.24",
            "chapter": "8.24",
            "goal": "Talk about cultural differences.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": "https://drive.google.com/file/d/1x8IM6xcjR2hv3jbnnNudjyxLWPiT0-VL/view?usp=sharing"
        },
        # DAY 25
        {
            "day": 25,
            "topic": "Lebenslauf schreiben 8.25",
            "chapter": "9.25",
            "goal": "Write a CV and cover letter.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": "https://drive.google.com/file/d/1If0R3cIT8KwjeXjouWlQ-VT03QGYOSZz/view?usp=sharing"
        },
        # DAY 26
        {
            "day": 26,
            "topic": "Präsentationen halten 9.26",
            "chapter": "9.26",
            "goal": "Learn to give presentations.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": "https://drive.google.com/file/d/1BMwDDkfPJVEhL3wHNYqGMAvjOts9tv24/view?usp=sharing"
        },
        # DAY 27
        {
            "day": 27,
            "topic": "Zusammenfassen und Berichten 9.27",
            "chapter": "9.27",
            "goal": "Practice summarizing and reporting.",
            "assignment": True,
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": "https://drive.google.com/file/d/15fjOKp_u75GfcbvRJVbR8UbHg-cgrgWL/view?usp=sharing"
        },
        # DAY 28
        {
            "day": 28,
            "topic": "Abschlussprüfungsvorbereitung 10.28",
            "chapter": "10.28",
            "goal": "Prepare for the final exam.",
            "assignment": True,
            "instruction": "Review all topics, watch the revision video, and complete your mock exam.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": "https://drive.google.com/file/d/1iBeZHMDq_FnusY4kkRwRQvyOfm51-COU/view?usp=sharing"
        },
    ]

# === B2 Schedule Template ===
def get_b2_schedule():
    return [
        {
            "day": 1,
            "topic": "B2 Welcome & Orientation",
            "chapter": "0.0",
            "goal": "Get familiar with the B2 curriculum and course expectations.",
            "instruction": "Read the course orientation material and introduce yourself in the chat.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        {
            "day": 2,
            "topic": "B2 Diagnostic Test (Optional)",
            "chapter": "0.1",
            "goal": "Assess your current level before starting.",
            "instruction": "Take the B2 diagnostic or placement test if available.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        }
        # You can add more B2 lessons here in the future
    ]

# === C1 Schedule Template ===
def get_c1_schedule():
    return [
        {
            "day": 1,
            "topic": "C1 Welcome & Orientation",
            "chapter": "0.0",
            "goal": "Get familiar with the C1 curriculum and expectations.",
            "instruction": "Read the C1 orientation, join the forum, and write a short self-intro.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        {
            "day": 2,
            "topic": "C1 Diagnostic Writing",
            "chapter": "0.1",
            "goal": "Write a sample essay for initial assessment.",
            "instruction": "Write and upload a short essay on the assigned topic.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        }
        # You can add more C1 lessons here in the future
    ]


# --- FORCE A MOCK LOGIN FOR TESTING ---
if "student_row" not in st.session_state:
    st.session_state["student_row"] = {
        "Name": "Test Student",
        "Level": "A1",
        "StudentCode": "demo001"
    }

# --------------------------------------
# Shared imports and context
from datetime import datetime
import urllib.parse
import streamlit as st

student_row = st.session_state.get("student_row", {})
student_level = student_row.get("Level", "A1").upper()

# --- Cache level schedules with TTL for periodic refresh ---
@st.cache_data(ttl=86400)
def load_level_schedules():
    return {
        "A1": get_a1_schedule(),
        "A2": get_a2_schedule(),
        "B1": get_b1_schedule(),
        "B2": get_b2_schedule(),
        "C1": get_c1_schedule(),
    }

# --- Helpers ---

def render_assignment_reminder():
    """
    Render a responsive, mobile-friendly assignment reminder box with clear contrast.
    """
    st.markdown(
        '''
        <div style="
            box-sizing: border-box;
            width: 100%;
            max-width: 600px;
            padding: 16px;
            background: #ffc107;
            color: #000;
            border-left: 6px solid #e0a800;
            margin: 16px auto;
            border-radius: 8px;
            font-size: 1.1rem;
            line-height: 1.4;
            text-align: center;
            overflow-wrap: break-word;
            word-wrap: break-word;
        ">
            ⬆️ <strong>Your Assignment:</strong><br>
            Complete the exercises in your <em>workbook</em> for this chapter.
        </div>
        ''',
        unsafe_allow_html=True
    )

def render_link(label, url):
    st.markdown(f"- [{label}]({url})")

@st.cache_data(ttl=86400)
def build_wa_message(name, code, level, day, chapter, answer):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"Learn Language Education Academy – Assignment Submission\n"
        f"Name: {name}\n"
        f"Code: {code}\n"
        f"Level: {level}\n"
        f"Day: {day}\n"
        f"Chapter: {chapter}\n"
        f"Date: {timestamp}\n"
        f"Answer: {answer if answer.strip() else '[See attached file/photo]'}"
    )

def filter_matches(lesson, sq):
    """Check if search query appears in lesson fields."""
    fields = [
        lesson.get('topic', ''),
        lesson.get('chapter', ''),
        lesson.get('goal', ''),
        lesson.get('instruction', ''),
        str(lesson.get('day', ''))
    ]
    return any(sq in str(f).lower() for f in fields)


def render_section(day_info, key, title, icon):
    content = day_info.get(key)
    if not content:
        return
    items = content if isinstance(content, list) else [content]
    st.markdown(f"#### {icon} {title}")
    for idx, part in enumerate(items):
        if len(items) > 1:
            st.markdown(f"###### {icon} Part {idx+1} of {len(items)}: Chapter {part.get('chapter','')}")
        if part.get('video'):
            st.video(part['video'])
        if part.get('grammarbook_link'):
            render_link("📘 Grammar Book (Notes)", part['grammarbook_link'])
            st.markdown(
                '<em>Further notice:</em> 📘 contains notes; 📒 is your workbook assignment.',
                unsafe_allow_html=True
            )
        if part.get('workbook_link'):
            render_link("📒 Workbook (Assignment)", part['workbook_link'])
            render_assignment_reminder()
        extras = part.get('extra_resources')
        if extras:
            for ex in (extras if isinstance(extras, list) else [extras]):
                render_link("🔗 Extra", ex)

RESOURCE_LABELS = {
    'video': '🎥 Video',
    'grammarbook_link': '📘 Grammar',
    'workbook_link': '📒 Workbook',
    'extra_resources': '🔗 Extra'
}

if tab == "Course Book":
    st.markdown(
        '''
        <div style="
            padding: 16px;
            background: #007bff;
            color: #ffffff;
            border-radius: 8px;
            text-align: center;
            margin-bottom: 16px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        ">
            <span style="font-size:1.8rem; font-weight:600;">📈 Course Book</span>
        </div>
        ''', unsafe_allow_html=True
    )
    st.divider()

    schedules = load_level_schedules()
    schedule = schedules.get(student_level, schedules.get('A1', []))

    query = st.text_input("🔍 Search for topic, chapter, or keyword:")
    if query:
        sq = query.strip().lower()
        matches = [(i, d) for i, d in enumerate(schedule) if filter_matches(d, sq)]
        if not matches:
            st.warning("No matching lessons.")
            st.stop()
        labels = [f"Day {d['day']}: {d['topic']}" for _, d in matches]
        sel = st.selectbox("Lessons:", list(range(len(matches))), format_func=lambda i: labels[i])
        idx = matches[sel][0]
    else:
        idx = st.selectbox(
            "Choose your lesson/day:",
            range(len(schedule)),
            format_func=lambda i: f"Day {schedule[i]['day']} - {schedule[i]['topic']}"
        )

    info = schedule[idx]
    st.markdown(f"### Day {info['day']}: {info['topic']} (Chapter {info['chapter']})")

    if info.get('goal'):
        st.markdown(f"**🎯 Goal:**  {info['goal']}")
    if info.get('instruction'):
        st.markdown(f"**📝 Instruction:**  {info['instruction']}")

    render_section(info, 'lesen_hören', 'Lesen & Hören', '📚')
    render_section(info, 'schreiben_sprechen', 'Schreiben & Sprechen', '📝')

    if student_level in ['A2', 'B1', 'B2', 'C1']:
        for res, label in RESOURCE_LABELS.items():
            val = info.get(res)
            if val:
                if res == 'video':
                    st.video(val)
                else:
                    st.markdown(f"- [{label}]({val})", unsafe_allow_html=True)
        st.markdown(
            '<em>Further notice:</em> 📘 contains notes; 📒 is your workbook assignment.',
            unsafe_allow_html=True
        )

    st.divider()
    st.header("📲 Submit Assignment (WhatsApp)")

    def render_whatsapp():
        st.subheader("👤 Your Name & Code")
        name = st.text_input("Name", value=student_row.get('Name',''))
        code = st.text_input("Code", value=student_row.get('StudentCode',''))
        st.subheader("✍️ Your Answer")
        ans = st.text_area("Answer (or attach on WhatsApp)", height=500)
        msg = build_wa_message(name, code, student_level, info['day'], info['chapter'], ans)
        url = "https://api.whatsapp.com/send?phone=233205706589&text=" + urllib.parse.quote(msg)
        if st.button("📤 Send via WhatsApp"):
            st.success("Click link below to open WhatsApp.")
            st.markdown(f"[📨 Open WhatsApp]({url})")
        st.text_area("📋 Copy message:", msg, height=500)
    render_whatsapp()

    st.info(
        """
- Tap the links above to open resources in a new tab.
- Mention which task you're submitting.
- Use your correct name and code.
        """
    )

#MyResults
if tab == "My Results and Resources":
    # 📊 Compact Results & Resources header
    st.markdown(
        '''
        <div style="
            padding: 8px 12px;
            background: #17a2b8;
            color: #fff;
            border-radius: 6px;
            text-align: center;
            margin-bottom: 8px;
            font-size: 1.3rem;
        ">
            📊 My Results & Resources
        </div>
        ''',
        unsafe_allow_html=True
    )
    st.divider()
    
    import requests, io, pandas as pd, re, base64
    from fpdf import FPDF
    from collections import Counter

    # ============ LEVEL SCHEDULES (make sure these functions are defined above) ============
    LEVEL_SCHEDULES = {
        "A1": get_a1_schedule(),
        "A2": get_a2_schedule(),
        "B1": get_b1_schedule(),
        "B2": get_b2_schedule(),
        "C1": get_c1_schedule(),
    }

    # --- LIVE GOOGLE SHEETS CSV LINK ---
    GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1BRb8p3Rq0VpFCLSwL4eS9tSgXBo9hSWzfW_J_7W36NQ/gviz/tq?tqx=out:csv"

    def get_pdf_download_link(pdf_bytes, filename="results.pdf"):
        b64 = base64.b64encode(pdf_bytes).decode()
        return f'<a href="data:application/pdf;base64,{b64}" download="{filename}" style="font-size:1.1em;font-weight:600;color:#2563eb;">📥 Click here to download PDF (manual)</a>'

    @st.cache_data
    def fetch_scores():
        response = requests.get(GOOGLE_SHEET_CSV, timeout=7)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text), engine='python')
        df.columns = [col.strip().lower().replace('studentcode', 'student_code') for col in df.columns]
        required_cols = ["student_code", "name", "assignment", "score", "date", "level"]
        df = df.dropna(subset=required_cols)
        return df

    # --- Session Vars ---
    student_code = st.session_state.get("student_code", "")
    student_name = st.session_state.get("student_name", "")
    st.header("📈 My Results and Resources Hub")
    st.markdown("View and download your assignment history. All results are private and only visible to you.")

    # ========== REFRESH BUTTON ==========
    if st.button("🔄 Refresh for your latest results"):
        st.cache_data.clear()
        st.success("Cache cleared! Reloading…")
        st.rerun()

    # ========== FETCH AND FILTER DATA ==========
    df_scores = fetch_scores()
    required_cols = {"student_code", "name", "assignment", "score", "date", "level"}
    if not required_cols.issubset(df_scores.columns):
        st.error("Data format error. Please contact support.")
        st.write("Columns found:", df_scores.columns.tolist())
        st.stop()

    code = student_code.lower().strip()
    df_user = df_scores[df_scores.student_code.str.lower().str.strip() == code]
    if df_user.empty:
        st.info("No results yet. Complete an assignment to see your scores!")
        st.stop()

    # --- Choose level
    df_user['level'] = df_user.level.str.upper().str.strip()
    levels = sorted(df_user['level'].unique())
    level = st.selectbox("Select level:", levels)
    df_lvl = df_user[df_user.level == level]

    # ========== METRICS ==========
    totals = {"A1": 18, "A2": 28, "B1": 28, "B2": 24, "C1": 24}
    total = totals.get(level, 0)
    completed = df_lvl.assignment.nunique()
    avg_score = df_lvl.score.mean() or 0
    best_score = df_lvl.score.max() or 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Assignments", total)
    col2.metric("Completed", completed)
    col3.metric("Average Score", f"{avg_score:.1f}")
    col4.metric("Best Score", best_score)

    # ========== DETAILED RESULTS (with comments) ==========
    st.markdown("---")
    st.info("🔎 **Scroll down and expand the box below to see your full assignment history and feedback!**")

    # --- Score label function ---
    def score_label(score):
        try:
            score = float(score)
        except:
            return ""
        if score >= 90:
            return "Excellent 🌟"
        elif score >= 75:
            return "Good 👍"
        elif score >= 60:
            return "Sufficient ✔️"
        else:
            return "Needs Improvement ❗"

    with st.expander("📋 SEE DETAILED RESULTS (ALL ASSIGNMENTS & FEEDBACK)", expanded=False):
        if 'comments' in df_lvl.columns:
            df_display = (
                df_lvl.sort_values(['assignment', 'score'], ascending=[True, False])
                [['assignment', 'score', 'date', 'comments']]
                .reset_index(drop=True)
            )
            for idx, row in df_display.iterrows():
                perf = score_label(row['score'])
                st.markdown(
                    f"""
                    <div style="margin-bottom: 18px;">
                    <span style="font-size:1.05em;font-weight:600;">{row['assignment']}</span>  
                    <br>Score: <b>{row['score']}</b> <span style='margin-left:12px;'>{perf}</span> | Date: {row['date']}<br>
                    <div style='margin:8px 0; padding:10px 14px; background:#f2f8fa; border-left:5px solid #007bff; border-radius:7px; color:#333; font-size:1em;'>
                    <b>Feedback:</b> {row['comments'] if pd.notnull(row['comments']) and str(row['comments']).strip().lower() != 'nan' else '<i>No feedback</i>'}
                    </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                st.divider()
        else:
            df_display = (
                df_lvl.sort_values(['assignment', 'score'], ascending=[True, False])
                [['assignment', 'score', 'date']]
                .reset_index(drop=True)
            )
            st.table(df_display)
    st.markdown("---") 

    # ========== BADGES & TROPHIES ==========
    st.markdown("### 🏅 Badges & Trophies")
    
    with st.expander("What badges can you earn?", expanded=False):
        st.markdown(
            """
            - 🏆 **Completion Trophy**: Finish all assignments for your level.
            - 🥇 **Gold Badge**: Maintain an average score above 80.
            - 🥈 **Silver Badge**: Average score above 70.
            - 🥉 **Bronze Badge**: Average score above 60.
            - 🌟 **Star Performer**: Score 85 or higher on any assignment.
            """
        )

    badge_count = 0

    if completed >= total and total > 0:
        st.success("🏆 **Congratulations!** You have completed all assignments for this level!")
        badge_count += 1

    if avg_score >= 90:
        st.info("🥇 **Gold Badge:** Average score above 90!")
        badge_count += 1
    elif avg_score >= 75:
        st.info("🥈 **Silver Badge:** Average score above 75!")
        badge_count += 1
    elif avg_score >= 60:
        st.info("🥉 **Bronze Badge:** Average score above 60!")
        badge_count += 1

    if best_score >= 95:
        st.info("🌟 **Star Performer:** You scored 95 or above on an assignment!")
        badge_count += 1

    if badge_count == 0:
        st.warning("No badges yet. Complete more assignments to earn badges!")

    # ========== SKIPPED ASSIGNMENTS LOGIC ==========
    def extract_all_chapter_nums(chapter_str):
        # Split by underscores, spaces, etc. and extract all numeric parts
        parts = re.split(r'[_\s,;]+', str(chapter_str))
        nums = []
        for part in parts:
            match = re.search(r'\d+(?:\.\d+)?', part)
            if match:
                nums.append(float(match.group()))
        return nums

    # Build a set of all chapter numbers completed by student
    completed_nums = set()
    for _, row in df_lvl.iterrows():
        nums = extract_all_chapter_nums(row['assignment'])
        completed_nums.update(nums)

    last_num = max(completed_nums) if completed_nums else 0

    schedule = LEVEL_SCHEDULES.get(level, [])
    skipped_assignments = []
    for lesson in schedule:
        chapter_field = lesson.get("chapter", "")
        lesson_nums = extract_all_chapter_nums(chapter_field)
        day = lesson.get("day", "")
        has_assignment = lesson.get("assignment", False)
        # If any required num is skipped (i.e., less than last_num and not in completed)
        for chap_num in lesson_nums:
            if (
                has_assignment
                and chap_num < last_num
                and chap_num not in completed_nums
            ):
                skipped_assignments.append(
                    f"Day {day}: Chapter {chapter_field} – {lesson.get('topic','')}"
                )
                break  # Only need to flag once per lesson

    if skipped_assignments:
        st.markdown(
            f"""
            <div style="
                background-color: #fff3cd;
                border-left: 6px solid #ffecb5;
                color: #7a6001;
                padding: 16px 18px 16px 16px;
                border-radius: 8px;
                margin: 12px 0;
                font-size: 1.05em;">
                <b>⚠️ You have skipped the following assignments.<br>
                Please complete them for full progress:</b><br>
                {"<br>".join(skipped_assignments)}
            </div>
            """,
            unsafe_allow_html=True
        )

    # ========== NEXT ASSIGNMENT RECOMMENDATION ==========
    def extract_chapter_num(chapter):
        nums = re.findall(r'\d+(?:\.\d+)?', str(chapter))
        if not nums:
            return None
        return max(float(n) for n in nums)

    completed_chapters = []
    for assignment in df_lvl['assignment']:
        num = extract_chapter_num(assignment)
        if num is not None:
            completed_chapters.append(num)
    last_num = max(completed_chapters) if completed_chapters else 0

    schedule = LEVEL_SCHEDULES.get(level, [])
    next_assignment = None
    for lesson in schedule:
        chap_num = extract_chapter_num(lesson.get("chapter", ""))
        if chap_num and chap_num > last_num:
            next_assignment = lesson
            break
    if next_assignment:
        st.success(
            f"**Your next recommended assignment:**\n\n"
            f"**Day {next_assignment['day']}: {next_assignment['chapter']} – {next_assignment['topic']}**\n\n"
            f"**Goal:** {next_assignment.get('goal','')}\n\n"
            f"**Instruction:** {next_assignment.get('instruction','')}"
        )
    else:
        st.info("🎉 Great Job!")

    # ========== DOWNLOAD PDF SUMMARY ==========
    if st.button("⬇️ Download PDF Summary"):
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(0, 10, "Learn Language Education Academy", ln=1, align='C')
        pdf.ln(5)
        pdf.set_font("Arial", '', 12)
        pdf.multi_cell(
            0, 8,
            f"Name: {df_user.name.iloc[0]}\n"
            f"Code: {code}\n"
            f"Level: {level}\n"
            f"Date: {pd.Timestamp.now():%Y-%m-%d %H:%M}"
        )
        pdf.ln(4)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 8, "Summary Metrics", ln=1)
        pdf.set_font("Arial", '', 11)
        pdf.cell(0, 8, f"Total: {total}, Completed: {completed}, Avg: {avg_score:.1f}, Best: {best_score}", ln=1)
        pdf.ln(4)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 8, "Detailed Results", ln=1)
        pdf.set_font("Arial", '', 10)
        for _, row in df_display.iterrows():
            feedback = row.get('comments', '')
            if (
                pd.isna(feedback) or
                not str(feedback).strip() or
                str(feedback).lower().strip() == "nan"
            ):
                feedback = "No feedback yet."
            pdf.cell(0, 7, f"{row['assignment']}: {row['score']} ({row['date']})", ln=1)
            if 'comments' in row and feedback:
                pdf.set_font("Arial", 'I', 9)
                pdf.multi_cell(0, 6, f"  Feedback: {feedback}")
                pdf.set_font("Arial", '', 10)
        pdf_bytes = pdf.output(dest='S').encode('latin1', 'replace')
        # Streamlit native download button
        st.download_button(
            label="Download PDF",
            data=pdf_bytes,
            file_name=f"{code}_results_{level}.pdf",
            mime="application/pdf"
        )
        # Manual fallback download
        st.markdown(
            get_pdf_download_link(pdf_bytes, f"{code}_results_{level}.pdf"),
            unsafe_allow_html=True
        )
        st.info("If you are on iPhone or computer and the button does not work, tap-and-hold or right-click on the blue link above and choose **Save link as...** to download your PDF.")

    # --- Resources Section ---
    st.markdown("---")
    st.subheader("📚 Useful Resources")
    st.markdown(
        """
**1. [A1 Schreiben Practice Questions](https://drive.google.com/file/d/1X_PFF2AnBXSrGkqpfrArvAnEIhqdF6fv/view?usp=sharing)**  
Practice writing tasks and sample questions for A1.

**2. [A1 Exams Sprechen Guide](https://drive.google.com/file/d/1UWvbCCCcrW3_j9x7pOuWug6_Odvzcvaa/view?usp=sharing)**  
Step-by-step guide to the A1 speaking exam.

**3. [German Writing Rules](https://drive.google.com/file/d/1o7_ez3WSNgpgxU_nEtp6EO1PXDyi3K3b/view?usp=sharing)**  
Tips and grammar rules for better writing.

**4. [A2 Sprechen Guide](https://drive.google.com/file/d/1TZecDTjNwRYtZXpEeshbWnN8gCftryhI/view?usp=sharing)**  
A2-level speaking exam guide.

**5. [B1 Sprechen Guide](https://drive.google.com/file/d/1snk4mL_Q9-xTBXSRfgiZL_gYRI9tya8F/view?usp=sharing)**  
How to prepare for your B1 oral exam.
        """
    )


# ================================
# 5a. EXAMS MODE & CUSTOM CHAT TAB (block start, pdf helper, prompt builders)
# ================================

# --- CONFIG ---
exam_sheet_id = "1zaAT5NjRGKiITV7EpuSHvYMBHHENMs9Piw3pNcyQtho"
exam_sheet_name = "exam_topics"   # <-- update if your tab is named differently
exam_csv_url = f"https://docs.google.com/spreadsheets/d/{exam_sheet_id}/gviz/tq?tqx=out:csv&sheet={exam_sheet_name}"

@st.cache_data
def load_exam_topics():
    df = pd.read_csv(exam_csv_url)
    # Fill missing columns for Teil 3 if you only have a prompt
    for col in ['Level', 'Teil', 'Topic', 'Keyword']:
        if col not in df.columns:
            df[col] = ""
    return df

df_exam = load_exam_topics()

if tab == "Exams Mode & Custom Chat":
    # 🗣️ Compact tab header
    st.markdown(
        '''
        <div style="
            padding: 8px 12px;
            background: #28a745;
            color: #fff;
            border-radius: 6px;
            text-align: center;
            margin-bottom: 8px;
            font-size: 1.3rem;
        ">
            🗣️ Exam Simulator & Custom Chat
        </div>
        ''',
        unsafe_allow_html=True
    )
    st.divider()

    # --- Daily Limit Check (NEW: persistent with SQLite) ---
    if not has_sprechen_quota(student_code, FALOWEN_DAILY_LIMIT):
        st.header("🗣️ Falowen – Speaking & Exam Trainer")
        st.warning("You have reached your daily practice limit for this section. Please come back tomorrow.")
        st.stop()


    # ---- PDF Helper ----
    def falowen_download_pdf(messages, filename):
        from fpdf import FPDF
        import os
        def safe_latin1(text):
            return text.encode("latin1", "replace").decode("latin1")
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        chat_text = ""
        for m in messages:
            role = "Herr Felix" if m["role"] == "assistant" else "Student"
            safe_msg = safe_latin1(m["content"])
            chat_text += f"{role}: {safe_msg}\n\n"
        pdf.multi_cell(0, 10, chat_text)
        pdf_output = f"{filename}.pdf"
        pdf.output(pdf_output)
        with open(pdf_output, "rb") as f:
            pdf_bytes = f.read()
        os.remove(pdf_output)
        return pdf_bytes

    # ---- PROMPT BUILDERS (ALL LOGIC) ----
    def build_a1_exam_intro():
        return (
            "**A1 – Teil 1: Basic Introduction**\n\n"
            "In the A1 exam's first part, you will be asked to introduce yourself. "
            "Typical information includes: your **Name, Land, Wohnort, Sprachen, Beruf, Hobby**.\n\n"
            "After your introduction, you will be asked 3 basic questions such as:\n"
            "- Haben Sie Geschwister?\n"
            "- Wie alt ist deine Mutter?\n"
            "- Bist du verheiratet?\n\n"
            "You might also be asked to spell your name (**Buchstabieren**). "
            "Please introduce yourself now using all the keywords above."
        )

    def build_exam_instruction(level, teil):
        if level == "A1":
            if "Teil 1" in teil:
                return build_a1_exam_intro()
            elif "Teil 2" in teil:
                return (
                    "**A1 – Teil 2: Question and Answer**\n\n"
                    "You will get a topic and a keyword. Your job: ask a question using the keyword, "
                    "then answer it yourself. Example: Thema: Geschäft – Keyword: schließen → "
                    "Wann schließt das Geschäft?\nLet's try one. Ready?"
                )
            elif "Teil 3" in teil:
                return (
                    "**A1 – Teil 3: Making a Request**\n\n"
                    "You'll receive a prompt (e.g. 'Radio anmachen'). Write a polite request or imperative. "
                    "Example: Können Sie bitte das Radio anmachen?\nReady?"
                )
        if level == "A2":
            if "Teil 1" in teil:
                return (
                    "**A2 – Teil 1: Fragen zu Schlüsselwörtern**\n\n"
                    "You'll get a topic (e.g. 'Wohnort'). Ask a question, then answer it yourself. "
                    "When you're ready, type 'Begin'."
                )
            elif "Teil 2" in teil:
                return (
                    "**A2 – Teil 2: Über das Thema sprechen**\n\n"
                    "Talk about the topic in 3–4 sentences. I'll correct and give tips. Start when ready."
                )
            elif "Teil 3" in teil:
                return (
                    "**A2 – Teil 3: Gemeinsam planen**\n\n"
                    "Let's plan something together. Respond and make suggestions. Start when ready."
                )
        if level == "B1":
            if "Teil 1" in teil:
                return (
                    "**B1 – Teil 1: Gemeinsam planen**\n\n"
                    "We'll plan an activity together (e.g., a trip or party). Give your ideas and answer questions."
                )
            elif "Teil 2" in teil:
                return (
                    "**B1 – Teil 2: Präsentation**\n\n"
                    "Give a short presentation on the topic (about 2 minutes). I'll ask follow-up questions."
                )
            elif "Teil 3" in teil:
                return (
                    "**B1 – Teil 3: Feedback & Fragen stellen**\n\n"
                    "Answer questions about your presentation. I'll give you feedback on your language and structure."
                )
        if level == "B2":
            if "Teil 1" in teil:
                return (
                    "**B2 – Teil 1: Diskussion**\n\n"
                    "We'll discuss a topic. Express your opinion and justify it."
                )
            elif "Teil 2" in teil:
                return (
                    "**B2 – Teil 2: Präsentation**\n\n"
                    "Present a topic in detail. I'll challenge your points and help you improve."
                )
            elif "Teil 3" in teil:
                return (
                    "**B2 – Teil 3: Argumentation**\n\n"
                    "Argue your perspective. I'll give feedback and counterpoints."
                )
        if level == "C1":
            if "Teil 1" in teil:
                return (
                    "**C1 – Teil 1: Vortrag**\n\n"
                    "Bitte halte einen kurzen Vortrag zum Thema. Ich werde anschließend Fragen stellen und deine Sprache bewerten."
                )
            elif "Teil 2" in teil:
                return (
                    "**C1 – Teil 2: Diskussion**\n\n"
                    "Diskutiere mit mir über das gewählte Thema. Ich werde kritische Nachfragen stellen."
                )
            elif "Teil 3" in teil:
                return (
                    "**C1 – Teil 3: Bewertung**\n\n"
                    "Bewerte deine eigene Präsentation. Was würdest du beim nächsten Mal besser machen?"
                )
        return ""

    def build_exam_system_prompt(level, teil):
        if level == "A1":
            if "Teil 1" in teil:
                return (
                    "You are Herr Felix, a supportive A1 German examiner. "
                    "Ask the student to introduce themselves using the keywords (Name, Land, Wohnort, Sprachen, Beruf, Hobby). "
                    "Check if all info is given, correct any errors (explain in English), and give the right way to say things in German. "
                    "1. Always explain errors and suggestion in english. Only next question should be German. They are just A1 student "
                    "After their intro, ask these three questions one by one: "
                    "'Haben Sie Geschwister?', 'Wie alt ist deine Mutter?', 'Bist du verheiratet?'. "
                    "Correct their answers (explain in English). At the end, mention they may be asked to spell their name ('Buchstabieren') and wish them luck."
                )
            elif "Teil 2" in teil:
                return (
                    "You are Herr Felix, an A1 examiner. Randomly give the student a Thema and Keyword from the official list. "
                    "Tell them to ask a question with the keyword and answer it themselves, then correct their German (explain errors in English, show the correct version), and move to the next topic."
                )
            elif "Teil 3" in teil:
                return (
                    "You are Herr Felix, an A1 examiner. Give the student a prompt (e.g. 'Radio anmachen'). "
                    "Ask them to write a polite request or imperative and answer themseves like their partners will do. Check if it's correct and polite, explain errors in English, and provide the right German version. Then give the next prompt."
                    " They respond using Ja gerne or In ordnung. They can also answer using Ja, Ich kann and the question of the verb at the end (e.g 'Ich kann das Radio anmachen'). "
                )
        if level == "A2":
            if "Teil 1" in teil:
                return (
                    "You are Herr Felix, a Goethe A2 examiner. Give a topic from the A2 list. "
                    "Ask the student to ask and answer a question on it. Always correct their German (explain errors in English), show the correct version, and encourage."
                )
            elif "Teil 2" in teil:
                return (
                    "You are Herr Felix, an A2 examiner. Give a topic. Student gives a short monologue. Correct errors (in English), give suggestions, and follow up with one question."
                )
            elif "Teil 3" in teil:
                return (
                    "You are Herr Felix, an A2 examiner. Plan something together (e.g., going to the cinema). Check student's suggestions, correct errors, and keep the conversation going."
                )
        if level == "B1":
            if "Teil 1" in teil:
                return (
                    "You are Herr Felix, a Goethe B1 examiner. You and the student plan an activity together. "
                    "Always give feedback in both German and English, correct mistakes, suggest improvements, and keep it realistic."
                )
            elif "Teil 2" in teil:
                return (
                    "You are Herr Felix, a Goethe B1 examiner. Student gives a presentation. Give constructive feedback in German and English, ask for more details, and highlight strengths and weaknesses."
                )
            elif "Teil 3" in teil:
                return (
                    "You are Herr Felix, a Goethe B1 examiner. Student answers questions about their presentation. "
                    "Give exam-style feedback (in German and English), correct language, and motivate."
                )
        if level == "B2":
            if "Teil 1" in teil:
                return (
                    "You are Herr Felix, a B2 examiner. Discuss a topic with the student. Challenge their points. Correct errors (mostly in German, but use English if it's a big mistake), and always provide the correct form."
                )
            elif "Teil 2" in teil:
                return (
                    "You are Herr Felix, a B2 examiner. Listen to the student's presentation. Give high-level feedback (mostly in German), ask probing questions, and always highlight advanced vocabulary and connectors."
                )
            elif "Teil 3" in teil:
                return (
                    "You are Herr Felix, a B2 examiner. Argue your perspective. Give detailed, advanced corrections (mostly German, use English if truly needed). Encourage native-like answers."
                )
        if level == "C1":
            if "Teil 1" in teil or "Teil 2" in teil or "Teil 3" in teil:
                return (
                    "Du bist Herr Felix, ein C1-Prüfer. Sprich nur Deutsch. "
                    "Stelle herausfordernde Fragen, gib ausschließlich auf Deutsch Feedback, und fordere den Studenten zu komplexen Strukturen auf."
                )
        return ""

    def build_custom_chat_prompt(level):
        if level == "C1":
            return (
                "Du bist Herr Felix, ein C1-Prüfer. Sprich nur Deutsch. "
                "Gib konstruktives Feedback, stelle schwierige Fragen, und hilf dem Studenten, auf C1-Niveau zu sprechen."
            )
        if level in ["A1", "A2", "B1", "B2"]:
            correction_lang = "in English" if level in ["A1", "A2"] else "half in English and half in German"
            return (
                f"You are Herr Felix, a supportive and innovative German teacher. "
                f"The student's first input is their chosen topic. Only give suggestions, phrases, tips and ideas at first in English, no corrections. "
                f"Pick 4 useful keywords related to the student's topic and use them as the focus for conversation. Give students ideas and how to build their points for the conversation in English. "
                f"For each keyword, ask the student up to 3 creative, diverse and interesting questions in German only based on student language level, one at a time, not all at once. Just ask the question and don't let student know this is the keyword you are using. "
                f"After each student answer, give feedback and a suggestion to extend their answer if it's too short. Feedback in English and suggestion in German. "
                f"1. Explain difficult words when level is A1,A2,B1,B2. "
                f"After keyword questions, continue with other random follow-up questions that reflect student selected level about the topic in German (until you reach 20 questions in total). "
                f"Never ask more than 3 questions about the same keyword. "
                f"After the student answers 18 questions, write a summary of their performance: what they did well, mistakes, and what to improve in English and end the chat with motivation and tips. "
                f"All feedback and corrections should be {correction_lang}. "
                f"Encourage the student and keep the chat motivating. "
            )
        return ""

    # ---- USAGE LIMIT CHECK ----
    if not has_falowen_quota(student_code):
        st.warning("You have reached your daily practice limit for this section. Please come back tomorrow.")
        st.stop()

# ---- SESSION STATE DEFAULTS ----
    default_state = {
        "falowen_stage": 1,
        "falowen_mode": None,
        "falowen_level": None,
        "falowen_teil": None,
        "falowen_messages": [],
        "falowen_turn_count": 0,
        "custom_topic_intro_done": False,
        "custom_chat_level": None,
        "falowen_exam_topic": None,
        "falowen_exam_keyword": None,
    }
    for key, val in default_state.items():
        if key not in st.session_state:
            st.session_state[key] = val


    # ---- STAGE 1: Mode Selection ----
    if st.session_state["falowen_stage"] == 1:
        st.subheader("Step 1: Choose Practice Mode")

        st.info(
            """
            **Which mode should you choose?**

            - 📝 **Exam Mode**:  
                Practice a real speaking exam simulation with real topics and an examiner.  
                _Use this if you want to prepare for your official speaking test!_

            - 💬 **Custom Chat**:  
                Chat about any topic! Great for practicing class presentations, your own ideas, or having an intelligent conversation partner.
            """,
            icon="ℹ️"
        )

        mode = st.radio(
            "How would you like to practice?",
            [
                "Geführte Prüfungssimulation (Exam Mode)",
                "Eigenes Thema/Frage (Custom Chat)"
            ],
            key="falowen_mode_center"
        )
        if st.button("Next ➡️", key="falowen_next_mode"):
            st.session_state["falowen_mode"] = mode
            st.session_state["falowen_stage"] = 2
            st.session_state["falowen_level"] = None
            st.session_state["falowen_teil"] = None
            st.session_state["falowen_messages"] = []
            st.session_state["custom_topic_intro_done"] = False
            st.rerun()
        st.stop()

    # ---- STAGE 2: Level Selection ----
    if st.session_state["falowen_stage"] == 2:
        st.subheader("Step 2: Choose Your Level")
        level = st.radio(
            "Select your level:",
            ["A1", "A2", "B1", "B2", "C1"],
            key="falowen_level_center"
        )
        if st.button("⬅️ Back", key="falowen_back1"):
            st.session_state["falowen_stage"] = 1
            st.rerun()
        if st.button("Next ➡️", key="falowen_next_level"):
            st.session_state["falowen_level"] = level
            if st.session_state["falowen_mode"] == "Geführte Prüfungssimulation (Exam Mode)":
                st.session_state["falowen_stage"] = 3
            else:
                st.session_state["falowen_stage"] = 4
            st.session_state["falowen_teil"] = None
            st.session_state["falowen_messages"] = []
            st.session_state["custom_topic_intro_done"] = False
            st.rerun()
        st.stop()

    
    # ---- STAGE 3: Exam Part & Topic (Exam Mode Only) ----
    if st.session_state["falowen_stage"] == 3:
        level = st.session_state["falowen_level"]

        # Dynamically build teil_options from your app logic
        teil_options = {
            "A1": ["Teil 1 – Basic Introduction", "Teil 2 – Question and Answer", "Teil 3 – Making A Request"],
            "A2": ["Teil 1 – Fragen zu Schlüsselwörtern", "Teil 2 – Über das Thema sprechen", "Teil 3 – Gemeinsam planen"],
            "B1": ["Teil 1 – Gemeinsam planen (Dialogue)", "Teil 2 – Präsentation (Monologue)", "Teil 3 – Feedback & Fragen stellen"],
            "B2": ["Teil 1 – Diskussion", "Teil 2 – Präsentation", "Teil 3 – Argumentation"],
            "C1": ["Teil 1 – Vortrag", "Teil 2 – Diskussion", "Teil 3 – Bewertung"]
        }
        st.subheader("Step 3: Choose Exam Part")
        teil = st.radio("Which exam part?", teil_options[level], key="falowen_teil_center")

        # Parse Teil for lookup (e.g., "Teil 2" from "Teil 2 – Question and Answer")
        teil_number = teil.split()[1]

        # Filter exam topics by level and teil
        exam_topics = df_exam[(df_exam["Level"] == level) & (df_exam["Teil"] == f"Teil {teil_number}")]

        # Some Teils (like Teil 3) may just have a prompt, not a topic+keyword
        topics_list = []
        if not exam_topics.empty:
            # If both Topic & Keyword: show as "Topic – Keyword", else just Topic
            for _, row in exam_topics.iterrows():
                if row['Keyword'] and not pd.isna(row['Keyword']):
                    topics_list.append(f"{row['Topic']} – {row['Keyword']}")
                else:
                    topics_list.append(row['Topic'])
        else:
            topics_list = []

        # Optional topic picker (auto-pick random, but always shuffle for fairness)
        picked = None
        random.shuffle(topics_list)  # Always shuffle!
        if topics_list:
            picked = st.selectbox("Choose a topic (optional):", ["(random)"] + topics_list)
            if picked == "(random)":
                # When random, set None and shuffle for Stage 4 auto-picking
                st.session_state["falowen_exam_topic"] = None
                st.session_state["falowen_exam_keyword"] = None
            else:
                # If picked includes ' – ', split out topic & keyword
                if " – " in picked:
                    topic, keyword = picked.split(" – ", 1)
                    st.session_state["falowen_exam_topic"] = topic
                    st.session_state["falowen_exam_keyword"] = keyword
                else:
                    st.session_state["falowen_exam_topic"] = picked
                    st.session_state["falowen_exam_keyword"] = None
        else:
            st.session_state["falowen_exam_topic"] = None
            st.session_state["falowen_exam_keyword"] = None

        if st.button("⬅️ Back", key="falowen_back2"):
            st.session_state["falowen_stage"] = 2
            st.stop()

        if st.button("Start Practice", key="falowen_start_practice"):
            st.session_state["falowen_teil"] = teil
            st.session_state["falowen_stage"] = 4
            st.session_state["falowen_messages"] = []
            st.session_state["custom_topic_intro_done"] = False

            # Save/shuffle deck for Stage 4 picking
            st.session_state["remaining_topics"] = topics_list.copy()
            random.shuffle(st.session_state["remaining_topics"])
            st.session_state["used_topics"] = []

    # =========================================
    # ---- STAGE 4: MAIN CHAT ----
    if st.session_state["falowen_stage"] == 4:
        import re

        level = st.session_state["falowen_level"]
        teil = st.session_state["falowen_teil"]
        mode = st.session_state["falowen_mode"]
        is_exam = mode == "Geführte Prüfungssimulation (Exam Mode)"
        is_custom_chat = mode == "Eigenes Thema/Frage (Custom Chat)"

        # ---- Show daily usage ----
        used_today = get_sprechen_usage(student_code)
        st.info(f"Today: {used_today} / {FALOWEN_DAILY_LIMIT} Falowen chat messages used.")
        if used_today >= FALOWEN_DAILY_LIMIT:
            st.warning("You have reached your daily practice limit for Falowen today. Please come back tomorrow.")
            st.stop()

        # ---- Session Controls ----
        def reset_chat():
            st.session_state.update({
                "falowen_stage": 1,
                "falowen_messages": [],
                "falowen_teil": None,
                "falowen_mode": None,
                "custom_topic_intro_done": False,
                "falowen_turn_count": 0,
                "falowen_exam_topic": None,
                "falowen_exam_keyword": None,
                "remaining_topics": [],
                "used_topics": [],
            })
            st.rerun()

        def back_step():
            st.session_state.update({
                "falowen_stage": max(1, st.session_state["falowen_stage"] - 1),
                "falowen_messages": []
            })
            st.rerun()

        def change_level():
            st.session_state.update({
                "falowen_stage": 2,
                "falowen_messages": []
            })
            st.rerun()

        # ---- Bubble Styles (MOBILE FRIENDLY) ----
        bubble_user = (
            "background: #1976d2;"
            "color: #fff;"
            "padding: 14px 16px;"
            "border-radius: 18px 6px 18px 18px;"
            "margin: 10px 0 10px auto;"
            "display: block;"
            "font-size: 1.13rem;"
            "word-break: break-word;"
            "max-width: 380px;"
            "width: fit-content;"
            "box-sizing: border-box;"
            "line-height: 1.6;"
            "text-align: left;"
            "font-weight: 500;"
            "box-shadow: 0 2px 8px rgba(0,0,0,0.06);"
        )
        bubble_assistant = (
            "background: #fff9c4;"
            "color: #333;"
            "padding: 14px 16px;"
            "border-radius: 18px 18px 18px 6px;"
            "margin: 10px auto 10px 0;"
            "display: block;"
            "font-size: 1.13rem;"
            "word-break: break-word;"
            "max-width: 380px;"
            "width: fit-content;"
            "box-sizing: border-box;"
            "line-height: 1.6;"
            "text-align: left;"
            "font-weight: 500;"
            "box-shadow: 0 2px 8px rgba(0,0,0,0.06);"
        )
        st.markdown("""
        <style>
        @media only screen and (max-width: 600px) {
            div[style*="background: #1976d2"] {
                font-size: 1.09rem !important;
                padding: 13px 9px !important;
                max-width: 94vw !important;
                width: 94vw !important;
            }
            div[style*="background: #fff9c4"] {
                font-size: 1.09rem !important;
                padding: 13px 9px !important;
                max-width: 94vw !important;
                width: 94vw !important;
            }
        }
        </style>
        """, unsafe_allow_html=True)

        # ---- Word Highlighting ----
        def highlight_keywords(text, keywords):
            if not keywords: return text
            def repl(match):
                word = match.group(0)
                return f"<span style='background:#fff3b0;border-radius:0.4em;padding:0.12em 0.4em'>{word}</span>"
            for word in keywords:
                text = re.sub(rf'\b{re.escape(word)}\b', repl, text, flags=re.IGNORECASE)
            return text

        highlight_words = []
        if is_exam:
            if st.session_state.get("falowen_exam_keyword"):
                highlight_words.append(st.session_state["falowen_exam_keyword"])
            highlight_words += ["weil", "möchte", "deshalb"]

        # ---- Render Chat History (bubbles and highlights) ----
        for msg in st.session_state["falowen_messages"]:
            if msg["role"] == "assistant":
                with st.chat_message("assistant", avatar="🧑‍🏫"):
                    st.markdown(
                        "<span style='color:#cddc39;font-weight:bold'>🧑‍🏫 Herr Felix:</span><br>"
                        f"<div style='{bubble_assistant}'>{highlight_keywords(msg['content'], highlight_words)}</div>",
                        unsafe_allow_html=True
                    )
            else:
                with st.chat_message("user"):
                    st.markdown(
                        f"<div style='display:flex;justify-content:flex-end;'>"
                        f"<div style='{bubble_user}'>🗣️ {msg['content']}</div></div>",
                        unsafe_allow_html=True
                    )

        # ---- PDF Download Button ----
        if st.session_state["falowen_messages"]:
            pdf_bytes = falowen_download_pdf(
                st.session_state["falowen_messages"],
                f"Falowen_Chat_{level}_{teil.replace(' ', '_') if teil else 'chat'}"
            )
            st.download_button(
                "⬇️ Download Chat as PDF",
                pdf_bytes,
                file_name=f"Falowen_Chat_{level}_{teil.replace(' ', '_') if teil else 'chat'}.pdf",
                mime="application/pdf"
            )

        # ---- Session Buttons ----
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Restart Chat"): reset_chat()
        with col2:
            if st.button("Back"): back_step()
        with col3:
            if st.button("Change Level"): change_level()

        # ---- Initial Instruction ----
        if not st.session_state["falowen_messages"]:
            instruction = build_exam_instruction(level, teil) if is_exam else (
                "Hallo! 👋 What would you like to talk about? Give me details of what you want so I can understand."
            )
            st.session_state["falowen_messages"].append({"role": "assistant", "content": instruction})

        # ---- Build System Prompt including topic/context ----
        if is_exam:
            if (not st.session_state.get("falowen_exam_topic")) and st.session_state.get("remaining_topics"):
                next_topic = st.session_state["remaining_topics"].pop(0)
                if " – " in next_topic:
                    topic, keyword = next_topic.split(" – ", 1)
                    st.session_state["falowen_exam_topic"] = topic
                    st.session_state["falowen_exam_keyword"] = keyword
                else:
                    st.session_state["falowen_exam_topic"] = next_topic
                    st.session_state["falowen_exam_keyword"] = None
                st.session_state["used_topics"].append(next_topic)
            base_prompt = build_exam_system_prompt(level, teil)
            topic = st.session_state.get("falowen_exam_topic")
            if topic:
                system_prompt = f"{base_prompt} Thema: {topic}."
            else:
                system_prompt = base_prompt
        else:
            system_prompt = build_custom_chat_prompt(level)

        # ---- Chat Input & Assistant Response ----
        user_input = st.chat_input("Type your answer or message here...", key="falowen_user_input")
        if user_input:
            st.session_state["falowen_messages"].append({"role": "user", "content": user_input})
            inc_sprechen_usage(student_code)

            with st.chat_message("user"):
                st.markdown(
                    f"<div style='display:flex;justify-content:flex-end;'>"
                    f"<div style='{bubble_user}'>🗣️ {user_input}</div></div>",
                    unsafe_allow_html=True
                )

            with st.chat_message(
                "assistant",
                avatar="https://i.imgur.com/aypyUjM_d.jpeg?maxwidth=520&shape=thumb&fidelity=high"
            ):
                with st.spinner("🧑‍🏫 Herr Felix is typing..."):
                    messages = [{"role": "system", "content": system_prompt}] + st.session_state["falowen_messages"]
                    try:
                        resp = client.chat.completions.create(
                            model="gpt-4o",
                            messages=messages,
                            temperature=0.15,
                            max_tokens=600
                        )
                        ai_reply = resp.choices[0].message.content.strip()
                    except Exception as e:
                        ai_reply = f"Sorry, an error occurred: {e}"

                st.markdown(
                    "<span style='color:#cddc39;font-weight:bold'>🧑‍🏫 Herr Felix:</span><br>"
                    f"<div style='{bubble_assistant}'>{highlight_keywords(ai_reply, highlight_words)}</div>",
                    unsafe_allow_html=True
                )

            st.session_state["falowen_messages"].append({"role": "assistant", "content": ai_reply})

        # ---- END SESSION BUTTON & SUMMARY ----
        st.divider()
        if st.button("✅ End Session & Show Summary"):
            st.session_state["falowen_stage"] = 5
            st.rerun()


    # ---- STAGE 5: End-of-Session Summary ----
    if st.session_state.get("falowen_stage") == 5:
        st.subheader("📝 End-of-Session Summary")

        messages = st.session_state.get("falowen_messages", [])

        # 1. Total Turns
        user_turns = len([m for m in messages if m["role"] == "user"])
        st.markdown(f"- **Total Messages Sent:** {user_turns}")

        # 2. Words Used
        import re
        user_text = " ".join([m["content"] for m in messages if m["role"] == "user"])
        user_words = set(re.findall(r'\b\w+\b', user_text.lower()))
        st.markdown(f"- **Unique Words Used:** {len(user_words)}")
        if user_words:
            st.markdown(f"`{', '.join(list(user_words)[:20])}`")

        # 3. Corrections/Highlights
        corrections = []
        for m in messages:
            if m["role"] == "assistant":
                # Simple extraction: lines mentioning 'correct', 'should', 'mistake', 'improve'
                lines = m["content"].split("\n")
                for line in lines:
                    if any(word in line.lower() for word in ["correct", "should", "mistake", "improve", "tip"]):
                        if len(line) < 130:  # avoid overly long
                            corrections.append(line)
        if corrections:
            st.markdown("**Common Corrections & Tips:**")
            for corr in corrections[:8]:
                st.markdown(f"- {corr}")

        # 4. Recent AI Feedback
        last_feedback = "\n\n".join([m["content"] for m in messages if m["role"] == "assistant"][-2:])
        st.markdown("**Recent Feedback:**")
        st.markdown(last_feedback)

        # 5. Download Chat as PDF
        pdf_bytes = falowen_download_pdf(messages, f"Falowen_Summary_{st.session_state.get('student_code','')}")
        st.download_button("⬇️ Download Chat as PDF", pdf_bytes, file_name="Falowen_Summary.pdf", mime="application/pdf")

        # 6. Start new session
        st.divider()
        if st.button("🔄 Start New Session"):
            for key in [
                "falowen_stage", "falowen_messages", "falowen_teil", "falowen_mode",
                "custom_topic_intro_done", "falowen_turn_count",
                "falowen_exam_topic", "falowen_exam_keyword", "remaining_topics", "used_topics"
            ]:
                st.session_state[key] = None
            st.session_state["falowen_stage"] = 1
            st.rerun()

# =========================================
# End
# =========================================



# =========================================
# VOCAB TRAINER TAB (A1–C1) — MOBILE OPTIMIZED
# =========================================

# Your Google Sheets link
sheet_id = "1I1yAnqzSh3DPjwWRh9cdRSfzNSPsi7o4r5Taj9Y36NU"
sheet_name = "Sheet1"

# Get export CSV link
csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}"

# ========== Mobile-friendly message bubble ==========
BUBBLE_STYLE = (
    "padding:6px 10px; border-radius:6px; max-width:98vw; "
    "margin-bottom:8px; text-align:{align}; background:{bgcolor}; "
    "font-size:1em; word-break:break-word;"
)

def render_message(role, msg):
    # Improved style for mobile readability!
    align = "left" if role == "assistant" else "right"
    # High-contrast light bubble for both themes
    bgcolor = "#FAFAFA" if role == "assistant" else "#D2F8D2"
    textcolor = "#222"  # nearly black text
    bordcol = "#cccccc"
    label = "Herr Felix" if role == "assistant" else "You"
    style = (
        f"padding:14px 14px 12px 14px; border-radius:12px; max-width:96vw; "
        f"margin:7px 0 7px 0; text-align:{align}; background:{bgcolor}; "
        f"border:1px solid {bordcol}; color:{textcolor}; font-size:1.12em;"
        "box-shadow: 0 2px 8px rgba(40,40,40,0.06);"
        "word-break:break-word;"
    )
    st.markdown(
        f"<div style='{style}'><b>{label}:</b> {msg}</div>",
        unsafe_allow_html=True
    )

# ====================================================

# Helper to normalize user input
def clean_text(text):
    return text.replace('the ', '').replace(',', '').replace('.', '').strip().lower()

# Load vocab lists once (cached)
@st.cache_data
def load_vocab_lists():
    df = pd.read_csv(csv_url)
    lists = {}
    for lvl in df['Level'].unique():
        sub = df[df['Level'] == lvl]
        lists[lvl] = list(zip(sub['German'], sub['English']))
    return lists

VOCAB_LISTS = load_vocab_lists()

if tab == "Vocab Trainer":
    # 📚 Compact Vocab Trainer header
    st.markdown(
        '''
        <div style="
            padding: 8px 12px;
            background: #6f42c1;
            color: #fff;
            border-radius: 6px;
            text-align: center;
            margin-bottom: 8px;
            font-size: 1.3rem;
        ">
            📚 Vocab Trainer
        </div>
        ''',
        unsafe_allow_html=True
    )
    st.divider()
    
    HERR_FELIX = "Herr Felix 👨‍🏫"
    defaults = {
        "vt_history": [],
        "vt_list": [],
        "vt_index": 0,
        "vt_score": 0,
        "vt_total": None,
    }
    for key, val in defaults.items():
        st.session_state.setdefault(key, val)

    # Choose level
    level = st.selectbox("Choose level", list(VOCAB_LISTS.keys()), key="vt_level")
    vocab_items = VOCAB_LISTS.get(level, [])
    max_words = len(vocab_items)

    if max_words == 0:
        st.warning(f"No vocabulary available for level {level}. Please add entries in your sheet.")
        st.stop()

    # Start new practice resets
    if st.button("🔁 Start New Practice", key="vt_reset"):
        for k in defaults:
            st.session_state[k] = defaults[k]

    
    # Show number of available words for the selected level
    st.info(f"There are {max_words} words available in {level}.")

    # Step 1: ask how many words to practice
    if st.session_state.vt_total is None:
        count = st.number_input(
            "How many words can you practice today. You can also type the number?",
            min_value=1,
            max_value=max_words,
            value=min(7, max_words),
            key="vt_count"
        )
        if st.button("Start Practice", key="vt_start"):
            shuffled = vocab_items.copy()
            random.shuffle(shuffled)
            st.session_state.vt_list = shuffled[:int(count)]
            st.session_state.vt_total = int(count)
            st.session_state.vt_index = 0
            st.session_state.vt_score = 0
            st.session_state.vt_history = [
                ("assistant", f"Hallo! Ich bin {HERR_FELIX}. Let's start with {count} words!")
            ]

    # Display chat history
    if st.session_state.vt_history:
        st.markdown("### 🗨️ Practice Chat")
        for who, message in st.session_state.vt_history:
            render_message(who, message)

    # Practice loop
    total = st.session_state.vt_total
    idx = st.session_state.vt_index
    if isinstance(total, int) and idx < total:
        word, answer = st.session_state.vt_list[idx]
        user_input = st.text_input(f"{word} = ?", key=f"vt_input_{idx}")
        if user_input and st.button("Check", key=f"vt_check_{idx}"):
            st.session_state.vt_history.append(("user", user_input))
            given = clean_text(user_input)
            correct = clean_text(answer)
            if given == correct:
                st.session_state.vt_score += 1
                fb = f"✅ Correct! '{word}' = '{answer}'"
            else:
                fb = f"❌ Not quite. '{word}' = '{answer}'"
            st.session_state.vt_history.append(("assistant", fb))
            st.session_state.vt_index += 1

    # Show results when done
    if isinstance(total, int) and idx >= total:
        score = st.session_state.vt_score
        st.markdown(f"### 🏁 Finished! You got {score}/{total} correct.")
        if st.button("Practice Again", key="vt_again"):
            for k in defaults:
                st.session_state[k] = defaults[k]
                

# ====================================
# SCHREIBEN TRAINER TAB (with Daily Limit, Mobile UI, persistent with SQLite)
# ====================================

if tab == "Schreiben Trainer":
    # ✍️ Compact Schreiben Trainer header
    st.markdown(
        '''
        <div style="
            padding: 8px 12px;
            background: #d63384;
            color: #fff;
            border-radius: 6px;
            text-align: center;
            margin-bottom: 8px;
            font-size: 1.3rem;
        ">
            ✍️ Schreiben Trainer (Writing Practice)
        </div>
        ''',
        unsafe_allow_html=True
    )
    st.divider()

    # 1. Choose Level (remember previous)
    schreiben_levels = ["A1", "A2", "B1", "B2"]
    prev_level = st.session_state.get("schreiben_level", "A1")
    schreiben_level = st.selectbox(
        "Choose your writing level:",
        schreiben_levels,
        index=schreiben_levels.index(prev_level) if prev_level in schreiben_levels else 0,
        key="schreiben_level_selector"
    )
    st.session_state["schreiben_level"] = schreiben_level

    # 2. Daily limit tracking (persistent in DB)
    student_code = st.session_state.get("student_code", "demo")
    student_name = st.session_state.get("student_name", "")
    daily_so_far = get_schreiben_usage(student_code)   # <-- DB-based!

    # 3. Show overall writing performance (DB-driven, mobile-first)
    attempted, passed, accuracy = get_writing_stats(student_code)
    st.markdown(f"""**📝 Your Overall Writing Performance**
- 📨 **Submitted:** {attempted}
- ✅ **Passed (≥17):** {passed}
- 📊 **Pass Rate:** {accuracy}%
- 📅 **Today:** {daily_so_far} / {SCHREIBEN_DAILY_LIMIT}
""")

    # 4. Level-Specific Stats (optional)
    stats = get_student_stats(student_code)
    lvl_stats = stats.get(schreiben_level, {}) if stats else {}
    if lvl_stats and lvl_stats["attempted"]:
        correct = lvl_stats.get("correct", 0)
        attempted_lvl = lvl_stats.get("attempted", 0)
        st.info(f"Level `{schreiben_level}`: {correct} / {attempted_lvl} passed")
    else:
        st.info("_No previous writing activity for this level yet._")

    st.divider()

    # 5. Input Box (disabled if limit reached)
    user_letter = st.text_area(
        "Paste or type your German letter/essay here.",
        key="schreiben_input",
        disabled=(daily_so_far >= SCHREIBEN_DAILY_LIMIT),
        height=180,
        placeholder="Write your German letter here..."
    )

    # --- Word and character count ---
    if user_letter.strip():
        import re
        words = re.findall(r'\b\w+\b', user_letter)
        chars = len(user_letter)
        st.info(f"**Word count:** {len(words)} &nbsp;|&nbsp; **Character count:** {chars}")

    # 6. AI prompt (always define before calling the API)
    ai_prompt = (
        f"You are Herr Felix, a supportive and innovative German letter writing trainer. "
        f"The student has submitted a {schreiben_level} German letter or essay. "
        "Write a brief comment in English about what the student did well and what they should improve while highlighting their points so they understand. "
        "Check if the letter matches their level. Talk as Herr Felix talking to a student and highlight the phrases with errors so they see it. "
        "Don't just say errors—show exactly where the mistakes are. "
        "1. Give a score out of 25 marks and always display the score clearly. "
        "2. If the score is 17 or more (17, 18, ..., 25), write: '**Passed: You may submit to your tutor!**'. "
        "3. If the score is 16 or less (16, 15, ..., 0), write: '**Keep improving before you submit.**'. "
        "4. Only write one of these two sentences, never both, and place it on a separate bolded line at the end of your feedback. "
        "5. Always explain why you gave the student that score based on grammar, spelling, vocabulary, coherence, and so on. "
        "6. Also check for AI usage or if the student wrote with their own effort. "
        "7. List and show the phrases to improve on with tips, suggestions, and what they should do. Let the student use your suggestions to correct the letter, but don't write the full corrected letter for them. "
        "Give scores by analyzing grammar, structure, vocabulary, etc. Explain to the student why you gave that score."
    )

    # 7. Submit & AI Feedback
    feedback = ""
    submit_disabled = daily_so_far >= SCHREIBEN_DAILY_LIMIT or not user_letter.strip()
    if submit_disabled and daily_so_far >= SCHREIBEN_DAILY_LIMIT:
        st.warning("You have reached today's writing practice limit. Please come back tomorrow.")

    if st.button("Get Feedback", type="primary", disabled=submit_disabled):
        with st.spinner("🧑‍🏫 Herr Felix is typing..."):
            try:
                completion = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": ai_prompt},
                        {"role": "user", "content": user_letter},
                    ],
                    temperature=0.6,
                )
                feedback = completion.choices[0].message.content
            except Exception as e:
                st.error("AI feedback failed. Please check your OpenAI setup.")
                feedback = None

        if feedback:
            # === Extract score and check if passed ===
            import re
            score_match = re.search(
                r"score\s*(?:[:=]|is)?\s*(\d+)\s*/\s*25",
                feedback,
                re.IGNORECASE,
            )
            if not score_match:
                score_match = re.search(r"Score[:\s]+(\d+)\s*/\s*25", feedback, re.IGNORECASE)
            if score_match:
                score = int(score_match.group(1))
            else:
                st.warning("Could not detect a score in the AI feedback.")
                score = 0

            # === Update usage (persistently in DB) and only save stats ===
            inc_schreiben_usage(student_code)
            save_schreiben_attempt(student_code, student_name, schreiben_level, score)

            # --- Show Feedback ---
            st.markdown("---")
            st.markdown("#### 📝 Feedback from Herr Felix")
            st.markdown(feedback)

            # === Download as PDF ===
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            pdf.multi_cell(0, 10, f"Your Letter:\n\n{user_letter}\n\nFeedback from Herr Felix:\n\n{feedback}")
            pdf_output = f"Feedback_{student_code}_{schreiben_level}.pdf"
            pdf.output(pdf_output)
            with open(pdf_output, "rb") as f:
                pdf_bytes = f.read()
            st.download_button(
                "⬇️ Download Feedback as PDF",
                pdf_bytes,
                file_name=pdf_output,
                mime="application/pdf"
            )
            import os
            os.remove(pdf_output)

            # === WhatsApp Share ===
            wa_message = f"Hi, here is my German letter and AI feedback:\n\n{user_letter}\n\nFeedback:\n{feedback}"
            wa_url = (
                "https://api.whatsapp.com/send"
                "?phone=233205706589"
                f"&text={urllib.parse.quote(wa_message)}"
            )
            st.markdown(
                f"[📲 Send to Tutor on WhatsApp]({wa_url})",
                unsafe_allow_html=True
            )


