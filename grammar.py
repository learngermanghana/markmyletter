import os
import random
import difflib
import sqlite3
import atexit
import json
from datetime import date, datetime
import pandas as pd
import streamlit as st
import requests
import io
from openai import OpenAI
from fpdf import FPDF
from streamlit_cookies_manager import EncryptedCookieManager

# ---- OpenAI Client Setup ----
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error(
        "Missing OpenAI API key. Please set OPENAI_API_KEY as an environment variable or in Streamlit secrets."
    )
    st.stop()
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY   # <- Set for OpenAI client!
client = OpenAI()  # <-- Do NOT pass api_key here for openai>=1.0

# ---- DB connection helper ----
def get_connection():
    if "conn" not in st.session_state:
        st.session_state["conn"] = sqlite3.connect("vocab_progress.db", check_same_thread=False)
        atexit.register(st.session_state["conn"].close)
    return st.session_state["conn"]

conn = get_connection()
c = conn.cursor()

# --- Create/verify tables if not exist (run once per app startup) ---
def init_db():
    conn = get_connection()
    c = conn.cursor()
    # Vocab Progress Table
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
    # Schreiben Progress Table
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
    # Sprechen Progress Table
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
            remaining    TEXT,    -- JSON list of topics still to do
            used         TEXT,    -- JSON list of already done
            PRIMARY KEY (student_code, level, teil)
        )
    """)
    # My Vocab Table (STUDENT PERSONAL VOCAB)
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
    conn.commit()

# Call DB initialization ONCE after imports
init_db()

# ====== DB HELPERS (for all tables) ======

def save_vocab_submission(student_code, name, level, word, student_answer, is_correct):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO vocab_progress (student_code, name, level, word, student_answer, is_correct, date) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (student_code, name, level, word, student_answer, int(is_correct), str(date.today()))
    )
    conn.commit()

def save_schreiben_submission(student_code, name, level, essay, score, feedback):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO schreiben_progress (student_code, name, level, essay, score, feedback, date) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (student_code, name, level, essay, score, feedback, str(date.today()))
    )
    conn.commit()

def save_sprechen_submission(student_code, name, level, teil, message, score, feedback):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO sprechen_progress (student_code, name, level, teil, message, score, feedback, date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (student_code, name, level, teil, message, score, feedback, str(date.today()))
    )
    conn.commit()

# ====== PERSONAL VOCAB HELPERS ======
def get_personal_vocab_stats(student_code):
    """
    Returns a dict: {level: count} for all levels where this student has personal vocab,
    and total.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT level, COUNT(*) FROM my_vocab WHERE student_code=? GROUP BY level",
        (student_code,)
    )
    rows = c.fetchall()
    stats = {row[0]: row[1] for row in rows}
    stats['total'] = sum(stats.values())
    return stats

def add_my_vocab(student_code, level, word, translation):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO my_vocab (student_code, level, word, translation, date_added) VALUES (?, ?, ?, ?, ?)",
        (student_code, level, word, translation, str(date.today()))
    )
    conn.commit()

def get_my_vocab(student_code, level=None):
    conn = get_connection()
    c = conn.cursor()
    if level:
        c.execute(
            "SELECT id, word, translation, date_added FROM my_vocab WHERE student_code=? AND level=? ORDER BY date_added DESC",
            (student_code, level)
        )
    else:
        c.execute(
            "SELECT id, word, translation, date_added FROM my_vocab WHERE student_code=? ORDER BY date_added DESC",
            (student_code,)
        )
    return c.fetchall()

def delete_my_vocab(vocab_id, student_code):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM my_vocab WHERE id=? AND student_code=?", (vocab_id, student_code))
    conn.commit()

def count_my_vocab(student_code, level=None):
    conn = get_connection()
    c = conn.cursor()
    if level:
        c.execute("SELECT COUNT(*) FROM my_vocab WHERE student_code=? AND level=?", (student_code, level))
    else:
        c.execute("SELECT COUNT(*) FROM my_vocab WHERE student_code=?", (student_code,))
    return c.fetchone()[0]

# ====== OTHER HELPERS (existing, no change) ======

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
    """Return writing stats per level for a student."""
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

def get_falowen_usage(student_code):
    today_str = str(date.today())
    key = f"{student_code}_falowen_{today_str}"
    if "falowen_usage" not in st.session_state:
        st.session_state["falowen_usage"] = {}
    st.session_state["falowen_usage"].setdefault(key, 0)
    return st.session_state["falowen_usage"][key]

def inc_falowen_usage(student_code):
    today_str = str(date.today())
    key = f"{student_code}_falowen_{today_str}"
    if "falowen_usage" not in st.session_state:
        st.session_state["falowen_usage"] = {}
    st.session_state["falowen_usage"].setdefault(key, 0)
    st.session_state["falowen_usage"][key] += 1

def has_falowen_quota(student_code):
    return get_falowen_usage(student_code) < FALOWEN_DAILY_LIMIT

def get_vocab_streak(student_code):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT date FROM vocab_progress WHERE student_code=? ORDER BY date DESC",
        (student_code,),
    )
    rows = c.fetchall()
    if not rows:
        return 0
    dates = [date.fromisoformat(r[0]) for r in rows]
    if (date.today() - dates[0]).days > 1:
        return 0
    streak = 1
    prev = dates[0]
    for d in dates[1:]:
        if (prev - d).days == 1:
            streak += 1
            prev = d
        else:
            break
    return streak

# --- Streamlit page config ---
st.set_page_config(
    page_title="Falowen – Your German Conversation Partner",
    layout="centered",
    initial_sidebar_state="expanded"
)

# ---- Falowen Header ----
st.markdown(
    """
    <div style='display:flex;align-items:center;gap:18px;margin-bottom:22px;'>
        <img src='https://cdn-icons-png.flaticon.com/512/323/323329.png' width='50' style='border-radius:50%;border:2.5px solid #d2b431;box-shadow:0 2px 8px #e4c08d;'/>
        <div>
            <span style='font-size:2.0rem;font-weight:bold;color:#17617a;letter-spacing:2px;'>Falowen App</span>
            <span style='font-size:1.6rem;margin-left:12px;'>🇩🇪</span>
            <br>
            <span style='font-size:1.02rem;color:#ff9900;font-weight:600;'>Learn Language Education Academy</span><br>
            <span style='font-size:1.01rem;color:#268049;font-weight:400;'>
                Your All-in-One German Learning Platform for Speaking, Writing, Exams, and Vocabulary
            </span>
        </div>
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
    


# ====================================
# 1. STUDENT DATA LOADING
# ====================================

@st.cache_data
def load_student_data():
    GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/12NXf5FeVHr7JJT47mRHh7Jp-TC1yhPS7ZG6nzZVTt1U/gviz/tq?tqx=out:csv"
    import requests, io, pandas as pd
    try:
        response = requests.get(GOOGLE_SHEET_CSV, timeout=7)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text), engine='python')
        df.columns = [c.strip() for c in df.columns]
        for col in ["StudentCode", "Email"]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip().str.lower()
        return df
    except Exception as e:
        st.warning(f"Could not load student data from Google Sheets: {e}")
        return pd.DataFrame()

# ====================================
# 2. STUDENT LOGIN LOGIC
# ====================================

COOKIE_SECRET = os.getenv("COOKIE_SECRET") or st.secrets.get("COOKIE_SECRET")
if not COOKIE_SECRET:
    raise ValueError("COOKIE_SECRET environment variable not set")

cookie_manager = EncryptedCookieManager(
    prefix="falowen_",
    password=COOKIE_SECRET
)
cookie_manager.ready()

# -- SAFETY CHECK: COOKIES READY? --
if not cookie_manager.ready():
    st.warning("Cookies are not ready. Please refresh the page.")
    st.stop()

# --- Session State Initialization ---
for k, v in [
    ("logged_in", False), 
    ("student_row", None), 
    ("student_code", ""), 
    ("student_name", "")
]:
    if k not in st.session_state:
        st.session_state[k] = v

# --- Safe Cookie Read ---
code_from_cookie = cookie_manager.get("student_code") or ""
if not isinstance(code_from_cookie, str):
    code_from_cookie = str(code_from_cookie or "")
code_from_cookie = code_from_cookie.strip().lower()

# --- Auto-login via Cookie ---
if not st.session_state["logged_in"] and code_from_cookie:
    df_students = load_student_data()
    found = df_students[df_students["StudentCode"] == code_from_cookie]
    if not found.empty:
        st.session_state["student_row"] = found.iloc[0].to_dict()
        st.session_state["student_code"] = found.iloc[0]["StudentCode"].lower()
        st.session_state["student_name"] = found.iloc[0]["Name"]
        st.session_state["logged_in"] = True

# --- Login UI (only if not logged in) ---
if not st.session_state["logged_in"]:
    st.title("🔑 Student Login")
    login_input = st.text_input(
        "Enter your Student Code or Email to begin:",
        value=code_from_cookie
    ).strip().lower()
    if st.button("Login"):
        df_students = load_student_data()
        found = df_students[
            (df_students["StudentCode"] == login_input) | 
            (df_students["Email"] == login_input)
        ]
        if not found.empty:
            st.session_state["logged_in"] = True
            st.session_state["student_row"] = found.iloc[0].to_dict()
            st.session_state["student_code"] = found.iloc[0]["StudentCode"].lower()
            st.session_state["student_name"] = found.iloc[0]["Name"]
            cookie_manager["student_code"] = st.session_state["student_code"]
            cookie_manager.save()
            st.success(f"Welcome, {st.session_state['student_name']}! Login successful.")
            st.rerun()
        else:
            st.error("Login failed. Please check your Student Code or Email and try again.")
    st.stop()

# --- Log out button (visible when logged in) ---
if st.session_state["logged_in"]:
    st.write(f"👋 Welcome, **{st.session_state['student_name']}**")
    if st.button("Log out"):
        # Clear cookie and session
        cookie_manager["student_code"] = ""
        cookie_manager.save()
        for k in ["logged_in", "student_row", "student_code", "student_name"]:
            st.session_state[k] = False if k == "logged_in" else "" if "code" in k or "name" in k else None
        st.success("You have been logged out.")
        st.rerun()


# ====================================
# 4. FLEXIBLE ANSWER CHECKERS
# ====================================

def is_close_answer(student, correct):
    student = student.strip().lower()
    correct = correct.strip().lower()
    if correct.startswith("to "):
        correct = correct[3:]
    if len(student) < 3 or len(student) < 0.6 * len(correct):
        return False
    similarity = difflib.SequenceMatcher(None, student, correct).ratio()
    return similarity > 0.80

def is_almost(student, correct):
    student = student.strip().lower()
    correct = correct.strip().lower()
    if correct.startswith("to "):
        correct = correct[3:]
    similarity = difflib.SequenceMatcher(None, student, correct).ratio()
    return 0.60 < similarity <= 0.80

def validate_translation_openai(word, student_answer):
    """Use OpenAI to verify if the student's answer is a valid translation."""
    prompt = (
        f"Is '{student_answer.strip()}' an accurate English translation of the German word '{word}'? "
        "Reply with 'True' or 'False' only."
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1,
            temperature=0,
        )
        reply = resp.choices[0].message.content.strip().lower()
        return reply.startswith("true")
    except Exception:
        return False


# ====================================
# 5. CONSTANTS & VOCAB LISTS
# ====================================

FALOWEN_DAILY_LIMIT = 20
VOCAB_DAILY_LIMIT = 20
SCHREIBEN_DAILY_LIMIT = 5
max_turns = 25




if st.session_state["logged_in"]:
    # === Context: Always define at the top ===
    student_code = st.session_state.get("student_code", "")
    student_name = st.session_state.get("student_name", "")

    # === MAIN TAB SELECTOR ===
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

    # --- DASHBOARD TAB ---
    if tab == "Dashboard":
        st.header("📊 Student Dashboard")
        
        # Always fetch latest student data
        df_students = load_student_data()
        code = student_code
        found = df_students[df_students["StudentCode"].str.lower().str.strip() == code]
        student_row = found.iloc[0].to_dict() if not found.empty else {}

        streak = get_vocab_streak(code)
        total_attempted, total_passed, accuracy = get_writing_stats(code)

        # --- Usage calculation
        today_str = str(date.today())
        limit_key = f"{code}_schreiben_{today_str}"
        if "schreiben_usage" not in st.session_state:
            st.session_state["schreiben_usage"] = {}
        st.session_state["schreiben_usage"].setdefault(limit_key, 0)
        daily_so_far = st.session_state["schreiben_usage"][limit_key]

        # --- Student Info ---
        st.markdown(f"### 👤 {student_row.get('Name', '')}")
        st.markdown(
            f"**Level:** {student_row.get('Level', '')}  \n"
            f"**Code:** `{student_row.get('StudentCode', '')}`  \n"
            f"**Email:** {student_row.get('Email', '')}  \n"
            f"**Phone:** {student_row.get('Phone', '')}  \n"
            f"**Location:** {student_row.get('Location', '')}  \n"
            f"**Contract:** {student_row.get('ContractStart', '')} ➔ {student_row.get('ContractEnd', '')}  \n"
            f"**Enroll Date:** {student_row.get('EnrollDate', '')}  \n"
            f"**Status:** {student_row.get('Status', '')}"
        )

        # --- Payment info ---
        balance = student_row.get('Balance', '0.0')
        try:
            balance_float = float(balance)
        except Exception:
            balance_float = 0.0
        if balance_float > 0:
            st.warning(f"💸 Balance to pay: **₵{balance_float:.2f}** (update when paid)")

        # --- Contract End reminder ---
        contract_end = student_row.get('ContractEnd')
        if contract_end:
            try:
                contract_end_date = datetime.strptime(str(contract_end), "%Y-%m-%d")
                days_left = (contract_end_date - datetime.now()).days
                if 0 < days_left <= 30:
                    st.info(f"⚠️ Contract ends in {days_left} days. Please renew soon.")
                elif days_left < 0:
                    st.error("⏰ Contract expired. Contact the office to renew.")
            except Exception:
                pass

        # --- Progress stats ---
        st.markdown(f"🔥 **Vocab Streak:** {streak} days")
        goal_remain = max(0, 2 - (total_attempted or 0))
        if goal_remain > 0:
            st.success(f"🎯 Your next goal: Write {goal_remain} more letter(s) this week!")
        else:
            st.success("🎉 Weekly goal reached! Keep practicing!")
        st.markdown(
            f"**📝 Letters submitted:** {total_attempted}  \n"
            f"**✅ Passed (score ≥17):** {total_passed}  \n"
            f"**🏅 Pass rate:** {accuracy}%  \n"
            f"**Today:** {daily_so_far} / {SCHREIBEN_DAILY_LIMIT} used"
        )

        # --- UPCOMING EXAMS (dashboard only) ---
        with st.expander("📅 Upcoming Goethe Exams & Registration (Tap for details)", expanded=True):
            st.markdown(
                """
**Registration for Aug./Sept. 2025 Exams:**

| Level | Date       | Fee (GHS) | Per Module (GHS) |
|-------|------------|-----------|------------------|
| A1    | 21.07.2025 | 2,850     | —                |
| A2    | 22.07.2025 | 2,400     | —                |
| B1    | 23.07.2025 | 2,750     | 880              |
| B2    | 24.07.2025 | 2,500     | 840              |
| C1    | 25.07.2025 | 2,450     | 700              |

---

### 📝 Registration Steps

1. [**Register Here (9–10am, keep checking!)**](https://www.goethe.de/ins/gh/en/spr/prf/anm.html)
2. Fill the form and choose **extern**
3. Submit and get payment confirmation
4. Pay by Mobile Money or Ecobank (**use full name as reference**)
    - Email proof to: [registrations-accra@goethe.de](mailto:registrations-accra@goethe.de)
5. Wait for response. If not, send polite reminders by email.

---

**Payment Details:**  
**Ecobank Ghana**  
Account Name: **GOETHE-INSTITUT GHANA**  
Account No.: **1441 001 701 903**  
Branch: **Ring Road Central**  
SWIFT: **ECOCGHAC**
                """,
                unsafe_allow_html=True,
            )


def get_a1_schedule():
    return [
        # DAY 1
        {
            "day": 1,
            "topic": "Lesen & Hören",
            "chapter": "0.1",
            "goal": "You will learn to introduce yourself and greet others in German.",
            "instruction": "Watch the video, review grammar, do the workbook, submit assignment.",
            "lesen_hören": {
                "video": "",
                "grammarbook_link": "https://drive.google.com/file/d/1D9Pwg29qZ89xh6caAPBcLJ1K671VUc0_/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1wjtEyPphP0N7jLbF3AWb5wN_FuJZ5jUQ/view?usp=sharing"
            }
        },
        # DAY 2 – Multi chapter
        {
            "day": 2,
            "topic": "Lesen & Hören",
            "chapter": "0.2_1.1",
            "goal": "Understand the German alphabets and know the special characters called Umlaut.",
            "instruction": "You are doing Lesen and Hören chapter 0.2 and 1.1. Make sure to follow up attentively.",
            "lesen_hören": [
                {
                    "chapter": "0.2",
                    "video": "",
                    "grammarbook_link": "https://drive.google.com/file/d/1KtJCF15Ng4cLU88wdUCX5iumOLY7ZA0a/view?usp=sharing",
                    "workbook_link": "https://drive.google.com/file/d/1R6PqzgsPm9f5iVn7JZXSNVa_NttoPU9Q/view?usp=sharing",
                    "extra_resources": "https://youtu.be/wpBPaDI5IgI"
                },
                {
                    "chapter": "1.1",
                    "video": "",
                    "grammarbook_link": "https://drive.google.com/file/d/1DKhyi-43HX1TNs8fxA9bgRvhylubilBf/view?usp=sharing",
                    "workbook_link": "https://drive.google.com/file/d/1A1D1pAssnoncF1JY0v54XT2npPb6mQZv/view?usp=sharing",
                    "extra_resources": "https://youtu.be/_Hy9_tDhgtc?si=xbfW31T4aUHeJNa_"
                }
            ]
        },
        # DAY 3
        {
            "day": 3,
            "topic": "Schreiben & Sprechen and Lesen & Hören",
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
                "workbook_link": "https://drive.google.com/file/d/1GXWzy3cvbl_goP4-ymFuYDtX4X23D70j/view?usp=sharing"
            },
            "lesen_hören": [
                {
                    "chapter": "1.2",
                    "video": "https://youtu.be/NVCN4fZXEk0",
                    "grammarbook_link": "https://drive.google.com/file/d/1OUJT9aSU1XABi3cdZlstUvfBIndyEOwb/view?usp=sharing",
                    "workbook_link": "https://drive.google.com/file/d/1Lubevhd7zMlbvPcvHHC1D0GzW7xqa4Mp/view?usp=sharing",
                }
            ]
        },
        # DAY 4
        {
            "day": 4,
            "topic": "Lesen & Hören",
            "chapter": "2",
            "goal": "Learn numbers from one to 10 thousand. Also know the difference between city and street",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.",
            "lesen_hören": {
                "video": "",
                "grammarbook_link": "https://drive.google.com/file/d/1f2CJ492liO8ccudCadxHIISwGJkHP6st/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1C4VZDUj7VT27Qrn9vS5MNc3QfRqpmDGE/view?usp=sharing"
            }
        },
        # DAY 5
        {
            "day": 5,
            "topic": "Schreiben & Sprechen (Recap)",
            "chapter": "1.2",
            "goal": "Consolidate your understanding of introductions.",
            "instruction": "Use self-practice workbook and review answers for self-check.",
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": "https://drive.google.com/file/d/1ojXvizvJz_qGes7I39pjdhnmlul7xhxB/view?usp=sharing"
            }
        },
        # DAY 6
        {
            "day": 6,
            "topic": "Schreiben & Sprechen",
            "chapter": "2.3",
            "goal": "Learn about family and expressing your hobby",
            "instruction": "Use self-practice workbook and review answers for self-check.",
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": "https://drive.google.com/file/d/1x_u_tyICY-8xFuxsuOW2tqTzs7g8TquM/view?usp=sharing"
            }
        },
        # DAY 7
        {
            "day": 7,
            "topic": "Lesen & Hören",
            "chapter": "3",
            "goal": "Know how to ask for a price and also the use of mogen and gern to express your hobby",
            "instruction": "Do schreiben and sprechen 2.3 before this chapter for better understanding",
            "lesen_hören": {
                "video": "https://youtu.be/dGIj1GbK4sI",
                "grammarbook_link": "https://drive.google.com/file/d/1sCE5y8FVctySejSVNm9lrTG3slIucxqY/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1lL4yrZLMtKLnNuVTC2Sg_ayfkUZfIuak/view?usp=sharing"
            }
        },
        # DAY 8
        {
            "day": 8,
            "topic": "Lesen & Hören",
            "chapter": "4",
            "goal": "Learn about schon mal and noch nie, irregular verbs and all the personal pronouns",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.",
            "lesen_hören": {
                "video": "https://youtu.be/JfTc1G9mubs",
                "grammarbook_link": "https://drive.google.com/file/d/1obsYT3dP3qT-i06SjXmqRzCT2pNoJJZp/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1woXksV9sTZ_8huXa8yf6QUQ8aUXPxVug/view?usp=sharing"
            }
        },
        # DAY 9
        {
            "day": 9,
            "topic": "Lesen & Hören",
            "chapter": "5",
            "goal": "Learn about the German articles and cases",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.",
            "lesen_hören": {
                "video": "https://youtu.be/Yi5ZA-XD-GY?si=nCX_pceEYgAL-FU0",
                "grammarbook_link": "https://drive.google.com/file/d/17y5fGW8nAbfeVgolV7tEW4BLiLXZDoO6/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1zjAqvQqNb7iKknuhJ79bUclimEaTg-mt/view?usp=sharing"
            }
        },
        # DAY 10
        {
            "day": 10,
            "topic": "Lesen & Hören and Schreiben & Sprechen",
            "chapter": "6_2.4",
            "goal": "Understand Possessive Determiners and its usage in connection with nouns",
            "instruction": "The assignment is the lesen and horen chapter 6 but you must also go through schreiben and sprechnen 2.4 for full understanding",
            "lesen_hören": {
                "video": "https://youtu.be/SXwDqcwrR3k",
                "grammarbook_link": "https://drive.google.com/file/d/1Fy4bKhaHHb4ahS2xIumrLtuqdQ0YAFB4/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1Da1iw54oAqoaY-UIw6oyIn8tsDmIi1YR/view?usp=sharing"
            },
            "schreiben_sprechen": {
                "video": "https://youtu.be/5qnB2Gocp8s",
                "workbook_link": "https://drive.google.com/file/d/1GbIc44ToWh2upnHv6eX3ZjFrvnf4fcEM/view?usp=sharing"
            }
        },
        # DAY 11
        {
            "day": 11,
            "topic": "Lesen & Hören",
            "chapter": "7",
            "goal": "Understand the 12 hour clock system",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.",
            "lesen_hören": {
                "video": "https://youtu.be/uyvXoCoqjiE",
                "grammarbook_link": "https://drive.google.com/file/d/1pSaloRhfh8eTKK_r9mzwp6xkbfdkCVox/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/1QyDdRae_1qv_umRb15dCJZTPdXi7zPWd/view?usp=sharing"
            }
        },
        # DAY 12
        {
            "day": 12,
            "topic": "Lesen & Hören",
            "chapter": "8",
            "goal": "Understand the 24 hour clock and date system in German",
            "instruction": "Watch the video, study the grammar, complete the workbook, and send your answers.",
            "lesen_hören": {
                "video": "https://youtu.be/aWvIHjV3e_I",
                "grammarbook_link": "",
                "workbook_link": ""
            }
        },
        # DAY 13
        {
            "day": 13,
            "topic": "Schreiben & Sprechen",
            "chapter": "3.5",
            "goal": "Recap from the lesen and horen. Understand numbers, time, asking of price and how to formulate statements in German",
            "instruction": "Use the statement rule to talk about your weekly routine using the activities listed. Share with your tutor when done",
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": "https://drive.google.com/file/d/12oFKrKrHBwSpSnzxLX_e-cjPSiYtCFVs/view?usp=sharing"
            }
        },
        # DAY 14
        {
            "day": 14,
            "topic": "Schreiben & Sprechen",
            "chapter": "3.6",
            "goal": "",
            "instruction": "",
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": "https://drive.google.com/file/d/1wnZehLNfkjgKMFw1V3BX8V399rZg6XLv/view?usp=sharing"
            }
        },
        # DAY 15
        {
            "day": 15,
            "topic": "Schreiben & Sprechen",
            "chapter": "4.7",
            "goal": "",
            "instruction": "",
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": ""
            }
        },
        # DAY 16
        {
            "day": 16,
            "topic": "Lesen & Hören",
            "chapter": "9_10",
            "goal": "Understand how to negate statements using nicht,kein and nein",
            "instruction": "This chapter has two assignments. Do the assignments for chapter 9 and after chapter 10. Chapter 10 has no grammar",
            "lesen_hören": [
                {
                    "chapter": "9",
                    "video": "https://youtu.be/MrB3BPtQN6A",
                    "grammarbook_link": "https://drive.google.com/file/d/1g-qLEH1ZDnFZCT83TW-MPLxNt2nO7UAv/view?usp=sharing",
                    "workbook_link": "https://drive.google.com/file/d/1hKtQdXg5y3yJyFBQsCMr7fZ11cYbuG7D/view?usp=sharing"
                },
                {
                    "chapter": "10",
                    "video": "",
                    "grammarbook_link": "",
                    "workbook_link": "https://drive.google.com/file/d/1rJXshXQSS5Or4ipv1VmUMsoB0V1Vx4VK/view?usp=sharing"
                }
            ]
        },
        # DAY 17
        {
            "day": 17,
            "topic": "Lesen & Hören",
            "chapter": "11",
            "goal": "Understand instructions and request in German using the Imperative rule",
            "instruction": "",
            "lesen_hören": {
                "video": "https://youtu.be/k2ZC3rXPe1k",
                "grammarbook_link": "https://drive.google.com/file/d/1lMzZrM4aAItO8bBmehODvT6gG7dz8I9s/view?usp=sharing",
                "workbook_link": "https://drive.google.com/file/d/17FNSfHBxyga9sKxzicT_qkP7PA4vB5-A/view?usp=sharing"
            }
        },
        # DAY 18
        {
            "day": 18,
            "topic": "Lesen & Hören and Schreiben & Sprechen (including 5.8)",
            "chapter": "12.1_12.2",
            "goal": "Learn about German professions and how to use two-way prepositions",
            "instruction": "This lesson has two Lesen & Hören assignments (12.1 and 12.2) and one Schreiben & Sprechen practice (5.8)",
            "lesen_hören": [
                {
                    "chapter": "12.1",
                    "video": "",
                    "grammarbook_link": "https://drive.google.com/file/d/1wdWYVxBhu4QtRoETDpDww-LjjzsGDYva/view?usp=sharing",
                    "workbook_link": "https://drive.google.com/file/d/1A0NkFl1AG68jHeqSytI3ygJ0k7H74AEX/view?usp=sharing"
                },
                {
                    "chapter": "12.2",
                    "video": "",
                    "grammarbook_link": "",
                    "workbook_link": "https://drive.google.com/file/d/1xojH7Tgb5LeJj3nzNSATUVppWnJgJLEF/view?usp=sharing"
                }
            ],
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": "https://drive.google.com/file/d/1iyYBuxu3bBEovxz0j9QeSu_1URX92fvN/view?usp=sharing"
            }
        },
        # DAY 19
        {
            "day": 19,
            "topic": "Schreiben & Sprechen",
            "chapter": "5.9",
            "goal": "Understand the difference between Erlaubt and Verboten and how to use it in the exams hall",
            "instruction": "",
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": "https://drive.google.com/file/d/1-bbY9zoos62U5jUAFrYCyxay_cvbk65N/view?usp=sharing"
            }
        },
        # DAY 20
        {
            "day": 20,
            "topic": "Schreiben & Sprechen (Intro to letter writing)",
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
            "topic": "Lesen & Hören and Schreiben & Sprechen",
            "chapter": "13_6.11",
            "goal": "",
            "instruction": "",
            "lesen_hören": {
                "video": "",
                "grammarbook_link": "",
                "workbook_link": ""
            },
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": ""
            }
        },
        # DAY 22
        {
            "day": 22,
            "topic": "Lesen & Hören and Schreiben & Sprechen",
            "chapter": "14.1_7.12",
            "goal": "",
            "instruction": "",
            "lesen_hören": {
                "video": "",
                "grammarbook_link": "",
                "workbook_link": ""
            },
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": ""
            }
        },
        # DAY 23
        {
            "day": 23,
            "topic": "Lesen & Hören and Schreiben & Sprechen",
            "chapter": "14.2_7.12",
            "goal": "",
            "instruction": "",
            "lesen_hören": {
                "video": "",
                "grammarbook_link": "",
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
            "topic": "Schreiben & Sprechen",
            "chapter": "8.13",
            "goal": "",
            "instruction": "",
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": ""
            }
        },
        # DAY 25
        {
            "day": 25,
            "topic": "Exam tips - Schreiben & Sprechen recap",
            "chapter": "final",
            "goal": "",
            "instruction": "",
            "schreiben_sprechen": {
                "video": "",
                "workbook_link": ""
            }
        }
    ]

def get_a2_schedule():
    return [
        # DAY 1
        {
            "day": 1,
            "topic": "Small Talk (Exercise)",
            "chapter": "1.1",
            "goal": "Practice basic greetings and small talk.",
            "instruction": (
                "Today's lesson has 4 parts:\n\n"
                "**1. Sprechen (Group Practice):** Practice the daily question using the brain map provided. Use the chat feature in the Falowen app to speak for at least 1 minute.\n\n"
                "**2. Schreiben:** Reframe your group practice as a short letter (assignment).\n\n"
                "**3. Lesen:** Complete the reading exercise (7 questions).\n\n"
                "**4. Hören:** Do the listening exercise (5 questions).\n\n"
                "**Assignments to be submitted:** Schreiben, Lesen, and Hören.\n\n"
                "Finish all sections before submitting your answers."
            ),
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1NsCKO4K7MWI-queLWCeBuclmaqPN04YQ/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1LXDI1yyJ4aT4LhX5eGDbKnkCkJZ2EE2T/view?usp=sharing"
        },
        # DAY 2
        {
            "day": 2,
            "topic": "Personen Beschreiben (Exercise)",
            "chapter": "1.2",
            "goal": "Describe people and their appearance.",
            "instruction": (
                "Today's lesson has 4 parts:\n\n"
                "**1. Sprechen (Group Practice):** Practice describing people using the brain map and discuss in the Falowen chat for at least 1 minute.\n\n"
                "**2. Schreiben:** Write a short letter about a person.\n\n"
                "**3. Lesen:** Do the reading exercise (7 questions).\n\n"
                "**4. Hören:** Complete the listening exercise (5 questions).\n\n"
                "**Assignments to be submitted:** Schreiben, Lesen, and Hören.\n\n"
                "Finish all sections before submitting your answers."
            ),
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1VB_nXEfdeTgkzCYjh0tvE75zFJleMlyU/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/128lWaKgCZ2V-3tActM-dwNy6igLLlzH3/view?usp=sharing"
        },
        # DAY 3
        {
            "day": 3,
            "topic": "Dinge und Personen vergleichen",
            "chapter": "1.3",
            "goal": "Learn to compare things and people.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1Z3sSDCxPQz27TDSpN9r8lQUpHhBVfhYZ/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/18YXe9mxyyKTars1gL5cgFsXrbM25kiN8/view?usp=sharing"
        },
        # DAY 4
        {
            "day": 4,
            "topic": "Wo möchten wir uns treffen?",
            "chapter": "2.4",
            "goal": "Arrange and discuss meeting places.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/14qE_XJr3mTNr6PF5aa0aCqauh9ngYTJ8/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1RaXTZQ9jHaJYwKrP728zevDSQHFKeR0E/view?usp=sharing"
        },
        # DAY 5
        {
            "day": 5,
            "topic": "Was machst du in deiner Freizeit?",
            "chapter": "2.5",
            "goal": "Talk about free time activities.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/11yEcMioSB9x1ZD-x5_67ApFzP53iau-N/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1dIsFg7wNaqyyOHm95h7xv4Ssll5Fm0V1/view?usp=sharing"
        },
        # DAY 6
        {
            "day": 6,
            "topic": "Möbel und Räume kennenlernen",
            "chapter": "3.6",
            "goal": "Identify furniture and rooms.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1clWbDAvLlXpgWx7pKc71Oq3H2p0_GZnV/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1EF87TdHa6Y-qgLFUx8S6GAom9g5EBQNP/view?usp=sharing"
        },
        # DAY 7
        {
            "day": 7,
            "topic": "Eine Wohnung suchen (Übung)",
            "chapter": "3.7",
            "goal": "Practice searching for an apartment.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1clWbDAvLlXpgWx7pKc71Oq3H2p0_GZnV/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/16UfBIrL0jxCqWtqqZaLhKWflosNQkwF4/view?usp=sharing"
        },
        # DAY 8
        {
            "day": 8,
            "topic": "Rezepte und Essen (Exercise)",
            "chapter": "3.8",
            "goal": "Learn about recipes and food.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/16lh8sPl_IDZ3dLwYNvL73PqOFCixidrI/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1c8JJyVlKYI2mz6xLZZ6RkRHLnH3Dtv0c/view?usp=sharing"
        },
        # DAY 9
        {
            "day": 9,
            "topic": "Urlaub",
            "chapter": "4.9",
            "goal": "Discuss vacation plans.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1kOb7c08Pkxf21OQE_xIGEaif7Xq7k-ty/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1NzRxbGUe306Vq0mq9kKsc3y3HYqkMhuA/view?usp=sharing"
        },
        # DAY 10
        {
            "day": 10,
            "topic": "Tourismus und Traditionelle Feste",
            "chapter": "4.10",
            "goal": "Learn about tourism and festivals.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1snFsDYBK8RrPRq2n3PtWvcIctSph-zvN/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1vijZn-ryhT46cTzGmetuF0c4zys0yGlB/view?usp=sharing"
        },
        # DAY 11
        {
            "day": 11,
            "topic": "Unterwegs: Verkehrsmittel vergleichen",
            "chapter": "4.11",
            "goal": "Compare means of transportation.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1Vl9UPeM2RaATafT8t539aOPrxnSkfr9A/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1snFsDYBK8RrPRq2n3PtWvcIctSph-zvN/view?usp=sharing"
        },
        # DAY 12
        {
            "day": 12,
            "topic": "Ein Tag im Leben (Übung)",
            "chapter": "5.12",
            "goal": "Describe a typical day.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1ayExWDJ8rTEL8hsuMgbil5_ddDPO8z29/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/18u6FnHpd2nAh1Ev_2mVk5aV3GdVC6Add/view?usp=sharing"
        },
        # DAY 13
        {
            "day": 13,
            "topic": "Ein Vorstellungsgespräch (Exercise)",
            "chapter": "5.13",
            "goal": "Prepare for a job interview.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 14
        {
            "day": 14,
            "topic": "Beruf und Karriere (Exercise)",
            "chapter": "5.14",
            "goal": "Discuss jobs and careers.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 15
        {
            "day": 15,
            "topic": "Mein Lieblingssport",
            "chapter": "6.15",
            "goal": "Talk about your favorite sport.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 16
        {
            "day": 16,
            "topic": "Wohlbefinden und Entspannung",
            "chapter": "6.16",
            "goal": "Express well-being and relaxation.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 17
        {
            "day": 17,
            "topic": "In die Apotheke gehen",
            "chapter": "6.17",
            "goal": "Learn phrases for the pharmacy.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 18
        {
            "day": 18,
            "topic": "Die Bank anrufen",
            "chapter": "7.18",
            "goal": "Practice calling the bank.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 19
        {
            "day": 19,
            "topic": "Einkaufen? Wo und wie? (Exercise)",
            "chapter": "7.19",
            "goal": "Shop and ask about locations.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 20
        {
            "day": 20,
            "topic": "Typische Reklamationssituationen üben",
            "chapter": "7.20",
            "goal": "Handle typical complaints.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1-72wZuNJE4Y92Luy0h5ygWooDnBd9PQW/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1_GTumT1II0E1PRoh6hMDwWsTPEInGeed/view?usp=sharing"
        },
        # DAY 21
        {
            "day": 21,
            "topic": "Ein Wochenende planen",
            "chapter": "8.21",
            "goal": "Plan a weekend.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1FcCg7orEizna4rAkX3_FCyd3lh_Bb3IT/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1mMtZza34QoJO_lfUiEX3kwTa-vsTN_RK/view?usp=sharing"
        },
        # DAY 22
        {
            "day": 22,
            "topic": "Die Woche Planung",
            "chapter": "8.22",
            "goal": "Make a weekly plan.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1dWr4QHw8zT1RPbuIEr_X13cPLYpH-mms/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1mg_2ytNAYF00_j-TFQelajAxgQpmgrhW/view?usp=sharing"
        },
        # DAY 23
        {
            "day": 23,
            "topic": "Wie kommst du zur Schule / zur Arbeit?",
            "chapter": "9.23",
            "goal": "Talk about your route to school or work.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1XbWKmc5P7ZAR-OqFce744xqCe7PQguXo/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1Ialg19GIE_KKHiLBDMm1aHbrzfNdb7L_/view?usp=sharing"
        },
        # DAY 24
        {
            "day": 24,
            "topic": "Einen Urlaub planen",
            "chapter": "9.24",
            "goal": "Plan a vacation.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "https://drive.google.com/file/d/1tFXs-DNKvt97Q4dsyXsYvKVQvT5Qqt0y/view?usp=sharing",
            "workbook_link": "https://drive.google.com/file/d/1t3xqddDJp3-1XeJ6SesnsYsTO5xSm9vG/view?usp=sharing"
        },
        # DAY 25
        {
            "day": 25,
            "topic": "Tagesablauf (Exercise)",
            "chapter": "9.25",
            "goal": "Describe a daily routine.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "workbook_link": "https://drive.google.com/file/d/1jfWDzGfXrzhfGZ1bQe1u5MXVQkR5Et43/view?usp=sharing"
        },
        # DAY 26
        {
            "day": 26,
            "topic": "Gefühle in verschiedenen Situationen beschreiben",
            "chapter": "10.26",
            "goal": "Express feelings in various situations.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "workbook_link": "https://drive.google.com/file/d/126MQiti-lpcovP1TdyUKQAK6KjqBaoTx/view?usp=sharing"
        },
        # DAY 27
        {
            "day": 27,
            "topic": "Digitale Kommunikation",
            "chapter": "10.27",
            "goal": "Talk about digital communication.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "workbook_link": "https://drive.google.com/file/d/1UdBu6O2AMQ2g6Ot_abTsFwLvT87LHHwY/view?usp=sharing"
        },
        # DAY 28
        {
            "day": 28,
            "topic": "Über die Zukunft sprechen",
            "chapter": "10.28",
            "goal": "Discuss the future.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "workbook_link": "https://drive.google.com/file/d/1164aJFtkZM1AMb87s1-K59wuobD7q34U/view?usp=sharing"
        },
    ]

def get_b1_schedule():
    return [
        # DAY 1
        {
            "day": 1,
            "topic": "Traumwelten (Übung)",
            "chapter": "1.1",
            "goal": "Talk about dream worlds and imagination.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 2
        {
            "day": 2,
            "topic": "Freunde fürs Leben (Übung)",
            "chapter": "1.2",
            "goal": "Discuss friendships and important qualities.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 3
        {
            "day": 3,
            "topic": "Vergangenheit erzählen",
            "chapter": "1.3",
            "goal": "Tell stories about the past.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 4
        {
            "day": 4,
            "topic": "Wohnen und Zusammenleben",
            "chapter": "2.1",
            "goal": "Discuss housing and living together.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 5
        {
            "day": 5,
            "topic": "Feste feiern",
            "chapter": "2.2",
            "goal": "Talk about festivals and celebrations.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 6
        {
            "day": 6,
            "topic": "Mein Traumjob",
            "chapter": "2.3",
            "goal": "Describe your dream job.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 7
        {
            "day": 7,
            "topic": "Gesund bleiben",
            "chapter": "3.1",
            "goal": "Learn how to talk about health and fitness.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 8
        {
            "day": 8,
            "topic": "Arztbesuch und Gesundheitstipps",
            "chapter": "3.2",
            "goal": "Communicate with a doctor and give health tips.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 9
        {
            "day": 9,
            "topic": "Erinnerungen und Kindheit",
            "chapter": "3.3",
            "goal": "Talk about childhood memories.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 10
        {
            "day": 10,
            "topic": "Typisch deutsch? Kultur und Alltag",
            "chapter": "4.1",
            "goal": "Discuss cultural habits and everyday life.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 11
        {
            "day": 11,
            "topic": "Wünsche und Träume",
            "chapter": "4.2",
            "goal": "Express wishes and dreams.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 12
        {
            "day": 12,
            "topic": "Medien und Kommunikation",
            "chapter": "4.3",
            "goal": "Talk about media and communication.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 13
        {
            "day": 13,
            "topic": "Reisen und Verkehr",
            "chapter": "5.1",
            "goal": "Discuss travel and transportation.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 14
        {
            "day": 14,
            "topic": "Stadt oder Land",
            "chapter": "5.2",
            "goal": "Compare life in the city and the countryside.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 15
        {
            "day": 15,
            "topic": "Wohnungssuche und Umzug",
            "chapter": "5.3",
            "goal": "Talk about searching for an apartment and moving.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 16
        {
            "day": 16,
            "topic": "Natur und Umwelt",
            "chapter": "6.1",
            "goal": "Learn to discuss nature and the environment.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 17
        {
            "day": 17,
            "topic": "Probleme und Lösungen",
            "chapter": "6.2",
            "goal": "Describe problems and find solutions.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 18
        {
            "day": 18,
            "topic": "Arbeit und Finanzen",
            "chapter": "6.3",
            "goal": "Talk about work and finances.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 19
        {
            "day": 19,
            "topic": "Berufliche Zukunft",
            "chapter": "7.1",
            "goal": "Discuss future career plans.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 20
        {
            "day": 20,
            "topic": "Bildung und Weiterbildung",
            "chapter": "7.2",
            "goal": "Talk about education and further studies.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 21
        {
            "day": 21,
            "topic": "Familie und Gesellschaft",
            "chapter": "7.3",
            "goal": "Discuss family and society.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 22
        {
            "day": 22,
            "topic": "Konsum und Werbung",
            "chapter": "8.1",
            "goal": "Talk about consumption and advertising.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 23
        {
            "day": 23,
            "topic": "Globalisierung",
            "chapter": "8.2",
            "goal": "Discuss globalization and its effects.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 24
        {
            "day": 24,
            "topic": "Kulturelle Unterschiede",
            "chapter": "8.3",
            "goal": "Talk about cultural differences.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 25
        {
            "day": 25,
            "topic": "Lebenslauf schreiben",
            "chapter": "9.1",
            "goal": "Write a CV and cover letter.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 26
        {
            "day": 26,
            "topic": "Präsentationen halten",
            "chapter": "9.2",
            "goal": "Learn to give presentations.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 27
        {
            "day": 27,
            "topic": "Zusammenfassen und Berichten",
            "chapter": "9.3",
            "goal": "Practice summarizing and reporting.",
            "instruction": "Watch the video, review grammar, and complete your workbook.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
        # DAY 28
        {
            "day": 28,
            "topic": "Abschlussprüfungsvorbereitung",
            "chapter": "10.1",
            "goal": "Prepare for the final exam.",
            "instruction": "Review all topics, watch the revision video, and complete your mock exam.",
            "video": "",
            "grammarbook_link": "",
            "workbook_link": ""
        },
    ]



# --------------------------------------

# --- FORCE A MOCK LOGIN FOR TESTING ---
if "student_row" not in st.session_state:
    st.session_state["student_row"] = {
        "Name": "Test Student",
        "Level": "A1",
        "StudentCode": "demo001"
    }

# --------------------------------------
# Shared at top so all tabs can access
student_row = st.session_state.get('student_row', {})
student_level = student_row.get('Level', 'A1').upper()

# --------------------------------------

if tab == "Course Book":

    import streamlit as st
    import datetime, urllib.parse

    # --------------------------------------
    # Compute level schedule mapping once at module load for efficiency
    # --------------------------------------
    LEVEL_SCHEDULES = {
        "A1": get_a1_schedule(),
        "A2": get_a2_schedule(),
        "B1": get_b1_schedule(),
    }

    # 1. Pick schedule based on student (cache avoids repeated calls)
    student_row = st.session_state.get('student_row', {})
    student_level = student_row.get('Level', 'A1').upper()
    schedule = LEVEL_SCHEDULES.get(student_level, LEVEL_SCHEDULES['A1'])

    if not schedule:
        st.warning("No schedule found for your level. Please contact the admin.")
        st.stop()

    selected_day_idx = st.selectbox(
        "Choose your lesson/day:",
        range(len(schedule)),
        format_func=lambda i: f"Day {schedule[i]['day']} - {schedule[i]['topic']}"
    )
    day_info = schedule[selected_day_idx]

    st.markdown(f"### Day {day_info['day']}: {day_info['topic']} (Chapter {day_info['chapter']})")

    # Display optional metadata
    if day_info.get("goal"):
        st.markdown(f"**🎯 Goal:**<br>{day_info['goal']}", unsafe_allow_html=True)
    if day_info.get("instruction"):
        st.markdown(f"**📝 Instruction:**<br>{day_info['instruction']}", unsafe_allow_html=True)

    # --------- Show Lesen & Hören ----------
    def render_lh_section(item, idx=None, total=None):
        """
        Renders a single Lesen & Hören assignment with optional numbering.
        """
        # Title for multi-part lessons
        if idx is not None and total and total > 1:
            st.markdown(f"#### 📚 Assignment {idx+1} of {total}: Chapter {item.get('chapter','')}")
        # Video
        if item.get('video'):
            st.video(item['video'])
        # Link rendering util avoids duplication
        def link(label, url):
            st.markdown(f"- [{label}]({url})")
        # Grammar book
        if item.get('grammarbook_link'):
            link('📘 Grammar Book', item['grammarbook_link'])
        # Workbook
        if item.get('workbook_link'):
            link('📒 Workbook', item['workbook_link'])
        # Extras
        extras = item.get('extra_resources')
        if extras:
            if isinstance(extras, list):
                for ex in extras:
                    link('🔗 Extra', ex)
            else:
                link('🔗 Extra', extras)

    # Normalize and render Lesen & Hören to always use list format
    if 'lesen_hören' in day_info:
        lh = day_info['lesen_hören']
        lh_items = lh if isinstance(lh, list) else [lh]
        if len(lh_items) > 1:
            st.markdown(
                '<div style="padding:8px; background:#f8f9fa; border-left:4px solid #007bff; margin:8px 0;">'
                '<strong>Note:</strong> Multiple Lesen & Hören tasks below. Complete all before submitting.'
                '</div>', unsafe_allow_html=True
            )
        for i, part in enumerate(lh_items):
            render_lh_section(part, idx=i, total=len(lh_items))

    # --- Show Schreiben & Sprechen (if present) ---
    if 'schreiben_sprechen' in day_info:
        ss = day_info['schreiben_sprechen']
        st.markdown('#### 📝 Schreiben & Sprechen')
        if ss.get('video'):
            st.video(ss['video'])
        def sp_link(label, url): st.markdown(f"- [{label}]({url})")
        if ss.get('grammarbook_link'):
            sp_link('📘 Grammar Book', ss['grammarbook_link'])
        if ss.get('workbook_link'):
            sp_link('📒 Workbook', ss['workbook_link'])
        extras = ss.get('extra_resources')
        if extras:
            if isinstance(extras, list):
                for ex in extras: sp_link('🔗 Extra', ex)
            else: sp_link('🔗 Extra', extras)

    # ---------- Top-level resources for A2/B1/B2 ----------
    if student_level in ['A2','B1','B2']:
        for res in ['video','grammarbook_link','workbook_link','extra_resources']:
            if day_info.get(res):
                url = day_info[res]
                # choose label based on key
                label = (
                    '🎥 Video' if res=='video' else
                    '📘 Grammar' if 'grammar' in res else
                    '📒 Workbook' if 'workbook' in res else
                    '🔗 Extra'
                )
                if res == 'video':
                    st.video(url)
                else:
                    st.markdown(f"- [{label}]({url})", unsafe_allow_html=True)

    # --- Assignment Submission Section (WhatsApp) ---
    st.divider()
    st.markdown("## 📲 Submit Assignment (WhatsApp)")

    with st.container():
        student_name = st.text_input("👤 Your Name", value=student_row.get('Name', ''))
        student_code = st.text_input("🆔 Student Code", value=student_row.get('StudentCode', ''))

        # Wider mobile-friendly text area
        st.markdown("#### ✍️ Your Answer")
        answer = st.text_area("Type your answer here (leave blank if sending a file/photo on WhatsApp)", height=400, label_visibility="collapsed")

        wa_message = f"""Learn Language Education Academy – Assignment Submission
Name: {student_name}
Code: {student_code}
Level: {student_level}
Day: {day_info['day']}
Chapter: {day_info['chapter']}
Date: {datetime.datetime.now():%Y-%m-%d %H:%M}
Answer: {answer if answer.strip() else '[See attached file/photo]'}
"""
        wa_url = "https://api.whatsapp.com/send?phone=233205706589&text=" + urllib.parse.quote(wa_message)

        if st.button("📤 Submit via WhatsApp"):
            st.success("✅ Now click the button below to open WhatsApp and send your assignment.")
            st.markdown(
                f"""<a href="{wa_url}" target="_blank" style="display:block; text-align:center; font-size:1.15em; font-weight:600; background:#25D366; color:white; padding:14px; border-radius:10px; margin-top:10px;">📨 Open WhatsApp</a>""",
                unsafe_allow_html=True
            )
            st.text_area("📋 Copy this message if needed:", wa_message, height=400, label_visibility="visible")

    st.info("""
    - Tap the links above to open books in a new tab (no in-app preview).
    - If multiple tasks are assigned, mention which one you're submitting.
    - Always use your correct name and student code!
    """)


#Myresults

if tab == "My Results and Resources":
    # --- Refresh Button ---
    if st.button("🔄 Refresh for your latest results"):
        st.cache_data.clear()
        st.success("Cache cleared! Reloading…")
        st.rerun()

    # Always define these at the top
    student_code = st.session_state.get("student_code", "")
    student_name = st.session_state.get("student_name", "")
    st.header("📈 My Results and Resources Hub")
    st.markdown("View and download your assignment history. All results are private and only visible to you.")

    # === LIVE GOOGLE SHEETS CSV LINK ===
    GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1BRb8p3Rq0VpFCLSwL4eS9tSgXBo9hSWzfW_J_7W36NQ/gviz/tq?tqx=out:csv"

    import requests
    import io
    import pandas as pd
    from fpdf import FPDF


    @st.cache_data
    def fetch_scores():
        response = requests.get(GOOGLE_SHEET_CSV, timeout=7)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text), engine='python')

        # Clean and validate columns
        df.columns = [col.strip().lower().replace('studentcode', 'student_code') for col in df.columns]

        # Drop rows with missing *required* fields
        required_cols = ["student_code", "name", "assignment", "score", "date", "level"]
        df = df.dropna(subset=required_cols)

        return df

    df_scores = fetch_scores()
    required_cols = {"student_code", "name", "assignment", "score", "date", "level"}
    if not required_cols.issubset(df_scores.columns):
        st.error("Data format error. Please contact support.")
        st.write("Columns found:", df_scores.columns.tolist())  # <-- for debugging
        st.stop()

    # Filter for current student
    code = st.session_state.get("student_code", "").lower().strip()
    df_user = df_scores[df_scores.student_code.str.lower().str.strip() == code]
    if df_user.empty:
        st.info("No results yet. Complete an assignment to see your scores!")
        st.stop()

    # Choose level
    df_user['level'] = df_user.level.str.upper().str.strip()
    levels = sorted(df_user['level'].unique())
    level = st.selectbox("Select level:", levels)
    df_lvl = df_user[df_user.level == level]

    # Summary metrics
    totals = {"A1": 18, "A2": 28, "B1": 26, "B2": 24}
    total = totals.get(level, 0)
    completed = df_lvl.assignment.nunique()
    avg_score = df_lvl.score.mean() or 0
    best_score = df_lvl.score.max() or 0

    # Display metrics in columns
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Assignments", total)
    col2.metric("Completed", completed)
    col3.metric("Average Score", f"{avg_score:.1f}")
    col4.metric("Best Score", best_score)

    # Detailed results
    with st.expander("See detailed results", expanded=False):
        df_display = (
            df_lvl.sort_values(['assignment', 'score'], ascending=[True, False])
                 [['assignment', 'score', 'date']]
                 .reset_index(drop=True)
        )
        st.table(df_display)

    # Download PDF summary
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
            pdf.cell(0, 7, f"{row['assignment']}: {row['score']} ({row['date']})", ln=1)
        pdf_bytes = pdf.output(dest='S').encode('latin1', 'replace')
        st.download_button(
            label="Download PDF",
            data=pdf_bytes,
            file_name=f"{code}_results_{level}.pdf",
            mime="application/pdf"
        )

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
    # --- Daily Limit Check ---
    # You can use a helper like: has_falowen_quota(student_code) or get_falowen_remaining(student_code)
    if not has_falowen_quota(student_code):
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
                f"After the student answers 18 questions, write a summary of their performance: what they did well, mistakes, and what to improve in English. "
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
        mode = st.radio(
            "How would you like to practice?",
            ["Geführte Prüfungssimulation (Exam Mode)", "Eigenes Thema/Frage (Custom Chat)"],
            key="falowen_mode_center"
        )
        if st.button("Next ➡️", key="falowen_next_mode"):
            st.session_state["falowen_mode"] = mode
            st.session_state["falowen_stage"] = 2
            st.session_state["falowen_level"] = None
            st.session_state["falowen_teil"] = None
            st.session_state["falowen_messages"] = []
            st.session_state["custom_topic_intro_done"] = False
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
            st.stop()
        if st.button("Next ➡️", key="falowen_next_level"):
            st.session_state["falowen_level"] = level
            if st.session_state["falowen_mode"] == "Geführte Prüfungssimulation (Exam Mode)":
                st.session_state["falowen_stage"] = 3
            else:
                st.session_state["falowen_stage"] = 4
            st.session_state["falowen_teil"] = None
            st.session_state["falowen_messages"] = []
            st.session_state["custom_topic_intro_done"] = False
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

        # Optional topic picker
        picked = None
        if topics_list:
            picked = st.selectbox("Choose a topic (optional):", ["(random)"] + topics_list)
            if picked == "(random)":
                st.session_state["falowen_exam_topic"] = None
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

            # Shuffle or save deck if needed (optional)
            st.session_state["remaining_topics"] = topics_list.copy()
            random.shuffle(st.session_state["remaining_topics"])
            st.session_state["used_topics"] = []


    # ---- STAGE 4: MAIN CHAT ----
    if st.session_state["falowen_stage"] == 4:
        level = st.session_state["falowen_level"]
        teil = st.session_state["falowen_teil"]
        mode = st.session_state["falowen_mode"]
        is_exam = mode == "Geführte Prüfungssimulation (Exam Mode)"
        is_custom_chat = mode == "Eigenes Thema/Frage (Custom Chat)"

        # ---- Show daily usage ----
        used_today = get_falowen_usage(student_code)
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
                "falowen_exam_topic": None
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

        # ---- Render Chat History ----
        for msg in st.session_state["falowen_messages"]:
            if msg["role"] == "assistant":
                with st.chat_message("assistant", avatar="🧑‍🏫"):
                    st.markdown(
                        "<span style='color:#33691e;font-weight:bold'>🧑‍🏫 Herr Felix:</span>",
                        unsafe_allow_html=True
                    )
                    st.markdown(msg["content"])
            else:
                with st.chat_message("user"):
                    st.markdown(f"🗣️ {msg['content']}")

        # ---- Auto-scroll to bottom ----
        st.markdown("<script>window.scrollTo(0, document.body.scrollHeight);</script>", unsafe_allow_html=True)

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
            inc_falowen_usage(student_code)

            # render user message
            with st.chat_message("user"):
                st.markdown(f"🗣️ {user_input}")

            # AI response
            with st.chat_message("assistant", avatar="🧑‍🏫"):
                with st.spinner("🧑‍🏫 Herr Felix is typing..."):
                    messages = [{"role": "system", "content": system_prompt}] + st.session_state["falowen_messages"]
                    try:
                        resp = client.chat.completions.create(
                            model="gpt-4o", messages=messages, temperature=0.15, max_tokens=600
                        )
                        ai_reply = resp.choices[0].message.content.strip()
                    except Exception as e:
                        ai_reply = f"Sorry, an error occurred: {e}"
                st.markdown(
                    "<span style='color:#33691e;font-weight:bold'>🧑‍🏫 Herr Felix:</span>",
                    unsafe_allow_html=True
                )
                st.markdown(ai_reply)

            # save assistant reply
            st.session_state["falowen_messages"].append({"role": "assistant", "content": ai_reply})

# =========================================
#End
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

# --------- Main Vocab Trainer Tab logic -------------
if tab == "Vocab Trainer":
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

#


# ====================================
# SCHREIBEN TRAINER TAB (with Daily Limit and Mobile UI)
# ====================================
import urllib.parse

if tab == "Schreiben Trainer":
    st.header("✍️ Schreiben Trainer (Writing Practice)")

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

    # 2. Daily limit tracking (by student & date)
    student_code = st.session_state.get("student_code", "demo")
    student_name = st.session_state.get("student_name", "")
    today_str = str(date.today())
    limit_key = f"{student_code}_schreiben_{today_str}"
    if "schreiben_usage" not in st.session_state:
        st.session_state["schreiben_usage"] = {}
    st.session_state["schreiben_usage"].setdefault(limit_key, 0)
    daily_so_far = st.session_state["schreiben_usage"][limit_key]

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
            # Robust regex for score detection
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

            # === Update usage and save to DB ===
            st.session_state["schreiben_usage"][limit_key] += 1
            save_schreiben_submission(
                student_code, student_name, schreiben_level, user_letter, score, feedback
            )

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



