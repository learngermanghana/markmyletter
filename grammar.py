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

# ---- DB connection helper ----
def get_connection():
    if "conn" not in st.session_state:
        st.session_state["conn"] = sqlite3.connect("vocab_progress.db", check_same_thread=False)
        atexit.register(st.session_state["conn"].close)
    return st.session_state["conn"]

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
    conn.commit()

# Call DB initialization ONCE after imports
init_db()

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
# 2. STUDENT DATA LOADING
# ====================================

STUDENTS_CSV = "students.csv"
CODES_FILE = "student_codes.csv"

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
# 3. STUDENT LOGIN LOGIC (single, clean block!)
# ====================================

# Use a secret from env or .streamlit/secrets.toml (RECOMMENDED, DO NOT HARD-CODE)
COOKIE_SECRET = os.getenv("COOKIE_SECRET") or st.secrets.get("COOKIE_SECRET")
if not COOKIE_SECRET:
    raise ValueError("COOKIE_SECRET environment variable not set")

cookie_manager = EncryptedCookieManager(
    prefix="falowen_",
    password=COOKIE_SECRET
)
cookie_manager.ready()

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "student_row" not in st.session_state:
    st.session_state["student_row"] = None
if "student_code" not in st.session_state:
    st.session_state["student_code"] = ""
if "student_name" not in st.session_state:
    st.session_state["student_name"] = ""

# --- 1. Check for cookie before showing login ---
code_from_cookie = cookie_manager.get("student_code")
if not st.session_state.get("logged_in", False) and code_from_cookie:
    st.session_state["student_code"] = code_from_cookie
    st.session_state["logged_in"] = True
    # Optional: Fill in other fields
    df_students = load_student_data()
    found = df_students[
        (df_students["StudentCode"].astype(str).str.lower().str.strip() == code_from_cookie)
    ]
    if not found.empty:
        st.session_state["student_row"] = found.iloc[0].to_dict()
        st.session_state["student_name"] = found.iloc[0]["Name"]
# --- 2. Show login if not logged in ---
if not st.session_state["logged_in"]:
    st.title("🔑 Student Login")
    login_input = st.text_input(
        "Enter your Student Code or Email to begin:",
        value=code_from_cookie if code_from_cookie else ""
    ).strip().lower()
    if st.button("Login"):
        df_students = load_student_data()
        found = df_students[
            (df_students["StudentCode"].astype(str).str.lower().str.strip() == login_input) |
            (df_students["Email"].astype(str).str.lower().str.strip() == login_input)
        ]
        if not found.empty:
            st.session_state["logged_in"] = True
            st.session_state["student_row"] = found.iloc[0].to_dict()
            st.session_state["student_code"] = found.iloc[0]["StudentCode"].lower()
            st.session_state["student_name"] = found.iloc[0]["Name"]
            # ← Replace .set() with dict assignment and save()
            cookie_manager["student_code"] = st.session_state["student_code"]
            cookie_manager.save()
            st.success(f"Welcome, {st.session_state['student_name']}! Login successful.")
            st.rerun()
        else:
            st.error("Login failed. Please check your Student Code or Email and try again.")
    st.stop()

# --- 1. Always check if cookie manager is ready ---
if not cookie_manager.ready():
    st.warning("Cookies are not ready. Please refresh this page.")
    st.stop()

# --- 2. Try to load student code from cookie safely ---
code_from_cookie = cookie_manager.get("student_code") or ""

# --- 3. Check if user is logged in (via session) ---
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "student_row" not in st.session_state:
    st.session_state["student_row"] = None
if "student_code" not in st.session_state:
    st.session_state["student_code"] = ""
if "student_name" not in st.session_state:
    st.session_state["student_name"] = ""

# --- 4. Try auto-login if cookie exists ---
if not st.session_state["logged_in"] and code_from_cookie:
    df_students = load_student_data()
    if not df_students.empty and "StudentCode" in df_students.columns:
        found = df_students[df_students["StudentCode"].str.lower().str.strip() == code_from_cookie]
        if not found.empty:
            st.session_state["student_code"] = code_from_cookie
            st.session_state["logged_in"] = True
            st.session_state["student_row"] = found.iloc[0].to_dict()
            st.session_state["student_name"] = found.iloc[0]["Name"]

# --- 5. If not logged in, show login UI ---
if not st.session_state["logged_in"]:
    st.title("🔑 Student Login")
    login_input = st.text_input(
        "Enter your Student Code or Email to begin:",
        value=code_from_cookie
    ).strip().lower()
    if st.button("Login"):
        df_students = load_student_data()
        if not df_students.empty:
            found = df_students[
                (df_students["StudentCode"].str.lower().str.strip() == login_input) |
                (df_students["Email"].str.lower().str.strip() == login_input)
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
        else:
            st.error("Student list is not available.")
    st.stop()

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


# --- Vocab lists for all levels ---

a1_vocab = [
    ("Südseite", "south side"), ("3. Stock", "third floor"), ("Geschenk", "present/gift"),
    ("Buslinie", "bus line"), ("Ruhetag", "rest day (closed)"), ("Heizung", "heating"),
    ("Hälfte", "half"), ("die Wohnung", "apartment"), ("das Zimmer", "room"), ("die Miete", "rent"),
    ("der Balkon", "balcony"), ("der Garten", "garden"), ("das Schlafzimmer", "bedroom"),
    ("das Wohnzimmer", "living room"), ("das Badezimmer", "bathroom"), ("die Garage", "garage"),
    ("der Tisch", "table"), ("der Stuhl", "chair"), ("der Schrank", "cupboard"), ("die Tür", "door"),
    ("das Fenster", "window"), ("der Boden", "floor"), ("die Wand", "wall"), ("die Lampe", "lamp"),
    ("der Fernseher", "television"), ("das Bett", "bed"), ("die Küche", "kitchen"), ("die Toilette", "toilet"),
    ("die Dusche", "shower"), ("das Waschbecken", "sink"), ("der Ofen", "oven"),
    ("der Kühlschrank", "refrigerator"), ("die Mikrowelle", "microwave"), ("die Waschmaschine", "washing machine"),
    ("die Spülmaschine", "dishwasher"), ("das Haus", "house"), ("die Stadt", "city"), ("das Land", "country"),
    ("die Straße", "street"), ("der Weg", "way"), ("der Park", "park"), ("die Ecke", "corner"),
    ("die Bank", "bank"), ("der Supermarkt", "supermarket"), ("die Apotheke", "pharmacy"),
    ("die Schule", "school"), ("die Universität", "university"), ("das Geschäft", "store"),
    ("der Markt", "market"), ("der Flughafen", "airport"), ("der Bahnhof", "train station"),
    ("die Haltestelle", "bus stop"), ("die Fahrt", "ride"), ("das Ticket", "ticket"), ("der Zug", "train"),
    ("der Bus", "bus"), ("das Taxi", "taxi"), ("das Auto", "car"), ("die Ampel", "traffic light"),
    ("die Kreuzung", "intersection"), ("der Parkplatz", "parking lot"), ("der Fahrplan", "schedule"),
    ("zumachen", "to close"), ("aufmachen", "to open"), ("ausmachen", "to turn off"),
    ("übernachten", "to stay overnight"), ("anfangen", "to begin"), ("vereinbaren", "to arrange"),
    ("einsteigen", "to get in / board"), ("umsteigen", "to change (trains)"), ("aussteigen", "to get out / exit"),
    ("anschalten", "to switch on"), ("ausschalten", "to switch off"), ("Anreisen", "to arrive"), ("Ankommen", "to arrive"),
    ("Abreisen", "to depart"), ("Absagen", "to cancel"), ("Zusagen", "to agree"), ("günstig", "cheap"),
    ("billig", "inexpensive")
]

a2_vocab = [
    ("die Verantwortung", "responsibility"), ("die Besprechung", "meeting"), ("die Überstunden", "overtime"),
    ("laufen", "to run"), ("das Fitnessstudio", "gym"), ("die Entspannung", "relaxation"),
    ("der Müll", "waste, garbage"), ("trennen", "to separate"), ("der Umweltschutz", "environmental protection"),
    ("der Abfall", "waste, rubbish"), ("der Restmüll", "residual waste"), ("die Anweisung", "instruction"),
    ("die Gemeinschaft", "community"), ("der Anzug", "suit"), ("die Beförderung", "promotion"),
    ("die Abteilung", "department"), ("drinnen", "indoors"), ("die Vorsorgeuntersuchung", "preventive examination"),
    ("die Mahlzeit", "meal"), ("behandeln", "to treat"), ("Hausmittel", "home remedies"),
    ("Salbe", "ointment"), ("Tropfen", "drops"), ("nachhaltig", "sustainable"),
    ("berühmt / bekannt", "famous / well-known"), ("einleben", "to settle in"), ("sich stören", "to be bothered"),
    ("liefern", "to deliver"), ("zum Mitnehmen", "to take away"), ("erreichbar", "reachable"),
    ("bedecken", "to cover"), ("schwanger", "pregnant"), ("die Impfung", "vaccination"),
    ("am Fluss", "by the river"), ("das Guthaben", "balance / credit"), ("kostenlos", "free of charge"),
    ("kündigen", "to cancel / to terminate"), ("der Anbieter", "provider"), ("die Bescheinigung", "certificate / confirmation"),
    ("retten", "rescue"), ("die Falle", "trap"), ("die Feuerwehr", "fire department"),
    ("der Schreck", "shock, fright"), ("schwach", "weak"), ("verletzt", "injured"),
    ("der Wildpark", "wildlife park"), ("die Akrobatik", "acrobatics"), ("bauen", "to build"),
    ("extra", "especially"), ("der Feriengruß", "holiday greeting"), ("die Pyramide", "pyramid"),
    ("regnen", "to rain"), ("schicken", "to send"), ("das Souvenir", "souvenir"),
    ("wahrscheinlich", "probably"), ("das Chaos", "chaos"), ("deutlich", "clearly"),
    ("der Ohrring", "earring"), ("verlieren", "to lose"), ("der Ärger", "trouble"),
    ("besorgt", "worried"), ("deprimiert", "depressed"), ("der Streit", "argument"),
    ("sich streiten", "to argue"), ("dagegen sein", "to be against"), ("egal", "doesn't matter"),
    ("egoistisch", "selfish"), ("kennenlernen", "to get to know"), ("nicht leiden können", "to dislike"),
    ("der Mädchentag", "girls' day"), ("der Ratschlag", "advice"), ("tun", "to do"),
    ("zufällig", "by chance"), ("ansprechen", "to approach"), ("plötzlich", "suddenly"),
    ("untrennbar", "inseparable"), ("sich verabreden", "to make an appointment"),
    ("versprechen", "to promise"), ("weglaufen", "to run away"), ("ab (+ Dativ)", "from, starting from"),
    ("das Aquarium", "aquarium"), ("der Flohmarkt", "flea market"), ("der Jungentag", "boys' day"),
    ("kaputt", "broken"), ("kostenlos", "free"), ("präsentieren", "to present"),
    ("das Quiz", "quiz"), ("schwitzen", "to sweat"), ("das Straßenfest", "street festival"),
    ("täglich", "daily"), ("vorschlagen", "to suggest"), ("wenn", "if, when"),
    ("die Bühne", "stage"), ("dringend", "urgently"), ("die Reaktion", "reaction"),
    ("unterwegs", "on the way"), ("vorbei", "over, past"), ("die Bauchschmerzen", "stomach ache"),
    ("der Busfahrer", "bus driver"), ("die Busfahrerin", "female bus driver"),
    ("der Fahrplan", "schedule"), ("der Platten", "flat tire"), ("die Straßenbahn", "tram"),
    ("streiken", "to strike"), ("der Unfall", "accident"), ("die Ausrede", "excuse"),
    ("baden", "to bathe"), ("die Grillwurst", "grilled sausage"), ("klingeln", "to ring"),
    ("die Mitternacht", "midnight"), ("der Nachbarhund", "neighbor's dog"),
    ("verbieten", "to forbid"), ("wach", "awake"), ("der Wecker", "alarm clock"),
    ("die Wirklichkeit", "reality"), ("zuletzt", "lastly, finally"), ("das Bandmitglied", "band member"),
    ("loslassen", "to let go"), ("der Strumpf", "stocking"), ("anprobieren", "to try on"),
    ("aufdecken", "to uncover / flip over"), ("behalten", "to keep"), ("der Wettbewerb", "competition"),
    ("schmutzig", "dirty"), ("die Absperrung", "barricade"), ("böse", "angry, evil"),
    ("trocken", "dry"), ("aufbleiben", "to stay up"), ("hässlich", "ugly"),
    ("ausweisen", "to identify"), ("erfahren", "to learn, find out"), ("entdecken", "to discover"),
    ("verbessern", "to improve"), ("aufstellen", "to set up"), ("die Notaufnahme", "emergency department"),
    ("das Arzneimittel", "medication"), ("die Diagnose", "diagnosis"), ("die Therapie", "therapy"),
    ("die Rehabilitation", "rehabilitation"), ("der Chirurg", "surgeon"), ("die Anästhesie", "anesthesia"),
    ("die Infektion", "infection"), ("die Entzündung", "inflammation"), ("die Unterkunft", "accommodation"),
    ("die Sehenswürdigkeit", "tourist attraction"), ("die Ermäßigung", "discount"), ("die Verspätung", "delay"),
    ("die Quittung", "receipt"), ("die Veranstaltung", "event"), ("die Bewerbung", "application")
]

# --- Short starter lists for B1/B2/C1 (add more later as you wish) ---
b1_vocab = [
    "Fortschritt", "Eindruck", "Unterschied", "Vorschlag", "Erfahrung", "Ansicht", "Abschluss", "Entscheidung"
]

b2_vocab = [
    "Umwelt", "Entwicklung", "Auswirkung", "Verhalten", "Verhältnis", "Struktur", "Einfluss", "Kritik"
]

c1_vocab = [
    "Ausdruck", "Beziehung", "Erkenntnis", "Verfügbarkeit", "Bereich", "Perspektive", "Relevanz", "Effizienz"
]

# --- Vocab list dictionary for your app ---
VOCAB_LISTS = {
    "A1": a1_vocab,
    "A2": a2_vocab,
    "B1": b1_vocab,
    "B2": b2_vocab,
    "C1": c1_vocab
}

# Exam topic lists
# --- A1 Exam Topic Lists (Teil 1, 2, 3) ---

A1_TEIL1 = [
    "Name", "Alter", "Wohnort", "Land", "Sprache", "Familie", "Beruf", "Hobby"
]

A1_TEIL2 = [
    ("Geschäft", "schließen"),
    ("Uhr", "Uhrzeit"),
    ("Arbeit", "Kollege"),
    ("Hausaufgabe", "machen"),
    ("Küche", "kochen"),
    ("Freizeit", "lesen"),
    ("Telefon", "anrufen"),
    ("Reise", "Hotel"),
    ("Auto", "fahren"),
    ("Einkaufen", "Obst"),
    ("Schule", "Lehrer"),
    ("Geburtstag", "Geschenk"),
    ("Essen", "Frühstück"),
    ("Arzt", "Termin"),
    ("Zug", "Abfahrt"),
    ("Wetter", "Regen"),
    ("Buch", "lesen"),
    ("Computer", "E-Mail"),
    ("Kind", "spielen"),
    ("Wochenende", "Plan"),
    ("Bank", "Geld"),
    ("Sport", "laufen"),
    ("Abend", "Fernsehen"),
    ("Freunde", "Besuch"),
    ("Bahn", "Fahrkarte"),
    ("Straße", "Stau"),
    ("Essen gehen", "Restaurant"),
    ("Hund", "Futter"),
    ("Familie", "Kinder"),
    ("Post", "Brief"),
    ("Nachbarn", "laut"),
    ("Kleid", "kaufen"),
    ("Büro", "Chef"),
    ("Urlaub", "Strand"),
    ("Kino", "Film"),
    ("Internet", "Seite"),
    ("Bus", "Abfahrt"),
    ("Arztpraxis", "Wartezeit"),
    ("Kuchen", "backen"),
    ("Park", "spazieren"),
    ("Bäckerei", "Brötchen"),
    ("Geldautomat", "Karte"),
    ("Buchladen", "Roman"),
    ("Fernseher", "Programm"),
    ("Tasche", "vergessen"),
    ("Stadtplan", "finden"),
    ("Ticket", "bezahlen"),
    ("Zahnarzt", "Schmerzen"),
    ("Museum", "Öffnungszeiten"),
    ("Handy", "Akku leer"),
]

A1_TEIL3 = [
    "Radio anmachen",
    "Fenster zumachen",
    "Licht anschalten",
    "Tür aufmachen",
    "Tisch sauber machen",
    "Hausaufgaben schicken",
    "Buch bringen",
    "Handy ausmachen",
    "Stuhl nehmen",
    "Wasser holen",
    "Fenster öffnen",
    "Musik leiser machen",
    "Tafel sauber wischen",
    "Kaffee kochen",
    "Deutsch üben",
    "Auto waschen",
    "Kind abholen",
    "Tisch decken",
    "Termin machen",
    "Nachricht schreiben",
]

A2_TEIL1 = [
    "Wohnort", "Tagesablauf", "Freizeit", "Sprachen", "Essen & Trinken", "Haustiere",
    "Lieblingsmonat", "Jahreszeit", "Sport", "Kleidung (Sommer)", "Familie", "Beruf",
    "Hobbys", "Feiertage", "Reisen", "Lieblingsessen", "Schule", "Wetter", "Auto oder Fahrrad", "Perfekter Tag"
]
A2_TEIL2 = [
    "Was machen Sie mit Ihrem Geld?",
    "Was machen Sie am Wochenende?",
    "Wie verbringen Sie Ihren Urlaub?",
    "Wie oft gehen Sie einkaufen und was kaufen Sie?",
    "Was für Musik hören Sie gern?",
    "Wie feiern Sie Ihren Geburtstag?",
    "Welche Verkehrsmittel nutzen Sie?",
    "Wie bleiben Sie gesund?",
    "Was machen Sie gern mit Ihrer Familie?",
    "Wie sieht Ihr Traumhaus aus?",
    "Welche Filme oder Serien mögen Sie?",
    "Wie oft gehen Sie ins Restaurant?",
    "Was ist Ihr Lieblingsfeiertag?",
    "Was machen Sie morgens als Erstes?",
    "Wie lange schlafen Sie normalerweise?",
    "Welche Hobbys hatten Sie als Kind?",
    "Machen Sie lieber Urlaub am Meer oder in den Bergen?",
    "Wie sieht Ihr Lieblingszimmer aus?",
    "Was ist Ihr Lieblingsgeschäft?",
    "Wie sieht ein perfekter Tag für Sie aus?"
]
A2_TEIL3 = [
    "Zusammen ins Kino gehen", "Ein Café besuchen", "Gemeinsam einkaufen gehen",
    "Ein Picknick im Park organisieren", "Eine Fahrradtour planen",
    "Zusammen in die Stadt gehen", "Einen Ausflug ins Schwimmbad machen",
    "Eine Party organisieren", "Zusammen Abendessen gehen",
    "Gemeinsam einen Freund/eine Freundin besuchen", "Zusammen ins Museum gehen",
    "Einen Spaziergang im Park machen", "Ein Konzert besuchen",
    "Zusammen eine Ausstellung besuchen", "Einen Wochenendausflug planen",
    "Ein Theaterstück ansehen", "Ein neues Restaurant ausprobieren",
    "Einen Kochabend organisieren", "Einen Sportevent besuchen", "Eine Wanderung machen"
]

B1_TEIL1 = [
    "Mithilfe beim Sommerfest", "Eine Reise nach Köln planen",
    "Überraschungsparty organisieren", "Kulturelles Ereignis (Konzert, Ausstellung) planen",
    "Museumsbesuch organisieren"
]
B1_TEIL2 = [
    "Ausbildung", "Auslandsaufenthalt", "Behinderten-Sport", "Berufstätige Eltern",
    "Berufswahl", "Bio-Essen", "Chatten", "Computer für jeden Kursraum", "Das Internet",
    "Einkaufen in Einkaufszentren", "Einkaufen im Internet", "Extremsport", "Facebook",
    "Fertigessen", "Freiwillige Arbeit", "Freundschaft", "Gebrauchte Kleidung",
    "Getrennter Unterricht für Jungen und Mädchen", "Haushalt", "Haustiere", "Heiraten",
    "Hotel Mama", "Ich bin reich genug", "Informationen im Internet", "Kinder und Fernsehen",
    "Kinder und Handys", "Kinos sterben", "Kreditkarten", "Leben auf dem Land oder in der Stadt",
    "Makeup für Kinder", "Marken-Kleidung", "Mode", "Musikinstrument lernen",
    "Musik im Zeitalter des Internets", "Rauchen", "Reisen", "Schokolade macht glücklich",
    "Sport treiben", "Sprachenlernen", "Sprachenlernen mit dem Internet",
    "Stadtzentrum ohne Autos", "Studenten und Arbeit in den Ferien", "Studium", "Tattoos",
    "Teilzeitarbeit", "Unsere Idole", "Umweltschutz", "Vegetarische Ernährung", "Zeitungslesen"
]
B1_TEIL3 = [
    "Fragen stellen zu einer Präsentation", "Positives Feedback geben",
    "Etwas überraschend finden oder planen", "Weitere Details erfragen"
]
b2_teil1_topics = [
    "Sollten Smartphones in der Schule erlaubt sein?",
    "Wie wichtig ist Umweltschutz in unserem Alltag?",
    "Wie beeinflusst Social Media unser Leben?",
    "Welche Rolle spielt Sport für die Gesundheit?",
]

b2_teil2_presentations = [
    "Die Bedeutung von Ehrenamt",
    "Vorteile und Nachteile von Homeoffice",
    "Auswirkungen der Digitalisierung auf die Arbeitswelt",
    "Mein schönstes Reiseerlebnis",
]

b2_teil3_arguments = [
    "Sollte man in der Stadt oder auf dem Land leben?",
    "Sind E-Autos die Zukunft?",
    "Brauchen wir mehr Urlaubstage?",
    "Muss Schule mehr praktische Fächer anbieten?",
]

c1_teil1_lectures = [
    "Die Zukunft der künstlichen Intelligenz",
    "Internationale Migration: Herausforderungen und Chancen",
    "Wandel der Arbeitswelt im 21. Jahrhundert",
    "Digitalisierung und Datenschutz",
]

c1_teil2_discussions = [
    "Sollten Universitäten Studiengebühren verlangen?",
    "Welchen Einfluss haben soziale Medien auf die Demokratie?",
    "Ist lebenslanges Lernen notwendig?",
    "Die Bedeutung von Nachhaltigkeit in der Wirtschaft",
]

c1_teil3_evaluations = [
    "Die wichtigsten Kompetenzen für die Zukunft",
    "Vor- und Nachteile globaler Zusammenarbeit",
    "Welchen Einfluss hat Technik auf unser Leben?",
    "Wie verändert sich die Familie?",
]

if st.session_state["logged_in"]:
    # === Context: Always define at the top ===
    student_code = st.session_state.get("student_code", "")
    student_name = st.session_state.get("student_name", "")

    # === MAIN TAB SELECTOR ===
    tab = st.radio(
        "How do you want to practice?",
        [
            "Dashboard",
            "Exams Mode & Custom Chat",
            "Vocab Trainer",
            "Schreiben Trainer",
            "My Results and Resources",
            "Admin"
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

# ================================
# 5a. EXAMS MODE & CUSTOM CHAT TAB (block start, pdf helper, prompt builders)
# ================================

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
        teil_options = {
            "A1": ["Teil 1 – Basic Introduction", "Teil 2 – Question and Answer", "Teil 3 – Making A Request"],
            "A2": ["Teil 1 – Fragen zu Schlüsselwörtern", "Teil 2 – Über das Thema sprechen", "Teil 3 – Gemeinsam planen"],
            "B1": ["Teil 1 – Gemeinsam planen (Dialogue)", "Teil 2 – Präsentation (Monologue)", "Teil 3 – Feedback & Fragen stellen"],
            "B2": ["Teil 1 – Diskussion", "Teil 2 – Präsentation", "Teil 3 – Argumentation"],
            "C1": ["Teil 1 – Vortrag", "Teil 2 – Diskussion", "Teil 3 – Bewertung"]
        }

        # build exam_topics list
        exam_topics = []
        if level == "A2":
            exam_topics = A2_TEIL1 + A2_TEIL2 + A2_TEIL3
        elif level == "B1":
            exam_topics = B1_TEIL1 + B1_TEIL2 + B1_TEIL3
        elif level == "B2":
            exam_topics = b2_teil1_topics + b2_teil2_presentations + b2_teil3_arguments
        elif level == "C1":
            exam_topics = c1_teil1_lectures + c1_teil2_discussions + c1_teil3_evaluations

        st.subheader("Step 3: Choose Exam Part")
        teil = st.radio("Which exam part?", teil_options[level], key="falowen_teil_center")

        # optional topic picker
        if level != "A1" and exam_topics:
            picked = st.selectbox("Choose a topic (optional):", ["(random)"] + exam_topics)
            st.session_state["falowen_exam_topic"] = None if picked == "(random)" else picked
        else:
            st.session_state["falowen_exam_topic"] = None

        if st.button("⬅️ Back", key="falowen_back2"):
            st.session_state["falowen_stage"] = 2
            st.stop()

        if st.button("Start Practice", key="falowen_start_practice"):
            # initialize exam part
            st.session_state["falowen_teil"] = teil
            st.session_state["falowen_stage"] = 4
            st.session_state["falowen_messages"] = []
            st.session_state["custom_topic_intro_done"] = False

            # initialize or load shuffled deck
            rem, used = load_progress(student_code, level, teil)
            if rem is None:
                deck = exam_topics.copy()
                random.shuffle(deck)
                st.session_state["remaining_topics"] = deck
                st.session_state["used_topics"] = []
            else:
                st.session_state["remaining_topics"] = rem
                st.session_state["used_topics"] = used

            # persist initial state
            save_progress(
                student_code, level, teil,
                st.session_state["remaining_topics"],
                st.session_state["used_topics"]
            )
        st.stop()

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
# VOCAB TRAINER TAB (A1–C1 + "My Words" with Progress, Add, Delete, Practice)
# =========================================

# === Ensure "personal_vocab" table exists ===
def ensure_personal_vocab_table():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS personal_vocab (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT,
            word TEXT,
            translation TEXT,
            date_added TEXT
        )
    """)
    conn.commit()
ensure_personal_vocab_table()

# ----------- Helper function: AI Vocab Feedback -----------
def ai_vocab_feedback(word, student, correct):
    student_ans = student.strip().lower()
    if correct is not None:
        valid = ([c.strip().lower() for c in correct]
                 if isinstance(correct, (list, tuple))
                 else [correct.strip().lower()])
        if student_ans in valid:
            return "<span style='color:green;font-weight:bold'>✅ Correct!</span>", True, False

    target = correct or word
    prompt = (
        f"The student answered '{student.strip()}' for the German word '{word.strip()}'. "
        f"The expected answer is '{target.strip()}'.\n"
        "1. Reply 'True' or 'False' on the first line if the student's answer is correct.\n"
        "2. If False, write: 'Correct answer: {target}'.\n"
        "3. If the student's answer is close, include 'You were close!'.\n"
        "4. Provide 1–2 simple German and English example sentences using the correct answer for A1/A2 learners."
    )
    try:
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.2,
        )
        reply = resp.choices[0].message.content.strip()
        lines = reply.splitlines()
        is_correct = lines[0].strip().lower().startswith("true")
        is_close = "close" in reply.lower()
        if is_correct:
            prefix = "<span style='color:green;font-weight:bold'>✅ Correct!</span>\n\n"
        elif is_close:
            prefix = "<span style='color:orange;font-weight:bold'>⚠️ You were close!</span>\n\n"
        else:
            prefix = "<span style='color:red;font-weight:bold'>❌ Not quite.</span>\n\n"
        feedback = prefix + "\n".join(lines[1:])
        return feedback, is_correct, is_close
    except Exception as e:
        return f"<span style='color:red'>AI check failed: {e}</span>", False, False

# ----------- Vocab Trainer Tab -----------
if tab == "Vocab Trainer":
    st.header("🧠 Vocab Trainer")

    student_code = st.session_state.get("student_code", "demo")
    student_name = st.session_state.get("student_name", "Demo")
    today_str = date.today().isoformat()

    # Initialize session state (fixes post-reset problem: always re-initialize)
    default_states = {
        "vocab_level": "A1",
        "vocab_feedback": "",
        "show_next_button": False,
        "vocab_completed": set(),
        "current_vocab_idx": None,
        "last_was_correct": False,
        "mywords_last_word_id": None
    }
    for key, value in default_states.items():
        if key not in st.session_state or (key == "vocab_completed" and not isinstance(st.session_state[key], set)):
            st.session_state[key] = value

    # Level selection
    level_opts = ["A1", "A2", "B1", "B2", "C1", "My Words"]
    selected = st.selectbox("Choose level", level_opts, key="vocab_level_select")
    if selected != st.session_state["vocab_level"]:
        # Reset state when switching levels
        for k in ["vocab_feedback", "show_next_button", "vocab_completed", "current_vocab_idx", "last_was_correct", "mywords_last_word_id"]:
            st.session_state[k] = set() if k == "vocab_completed" else False if k in ["show_next_button", "last_was_correct"] else None if k in ["current_vocab_idx", "mywords_last_word_id"] else ""
        st.session_state["vocab_level"] = selected

    # Streak and usage
    streak = get_vocab_streak(student_code)
    if streak > 0:
        st.success(f"🔥 {streak}-day streak! Keep it up!")
    else:
        st.warning("You lost your streak. Start practicing today!")

    usage_key = f"{student_code}_vocab_{today_str}"
    st.session_state.setdefault("vocab_usage", {})
    st.session_state["vocab_usage"].setdefault(usage_key, 0)
    used_today = st.session_state["vocab_usage"][usage_key]

    st.progress(min(used_today, VOCAB_DAILY_LIMIT)/VOCAB_DAILY_LIMIT, text=f"{used_today}/{VOCAB_DAILY_LIMIT} today")

    # Reset progress
    if st.button("🔄 Reset Progress"):
        for k in ["vocab_feedback", "show_next_button", "vocab_completed", "current_vocab_idx", "last_was_correct", "mywords_last_word_id"]:
            st.session_state[k] = set() if k == "vocab_completed" else False if k in ["show_next_button", "last_was_correct"] else None if k in ["current_vocab_idx", "mywords_last_word_id"] else ""
        st.success("Progress reset.")
        st.rerun()  # Ensures UI and input return immediately

    # Daily limit check
    if used_today >= VOCAB_DAILY_LIMIT:
        st.balloons()
        st.success("✅ Daily goal complete!")
        st.stop()

    # ========== MY WORDS ("personal_vocab") MODE ==========
    if selected == "My Words":
        st.subheader("📒 Practice & Save Your Own Words")

        # Add new word form
        with st.form("add_personal_vocab"):
            word = st.text_input("German Word")
            translation = st.text_input("Your Translation")
            add_submit = st.form_submit_button("Add Word")
            if add_submit and word and translation:
                conn = get_connection()
                c = conn.cursor()
                c.execute(
                    "INSERT INTO personal_vocab (student_code, word, translation, date_added) VALUES (?, ?, ?, ?)",
                    (student_code, word.strip(), translation.strip(), str(date.today()))
                )
                conn.commit()
                st.success(f"Added: {word} – {translation}")
                st.rerun()  # Refresh immediately

        # List and allow deleting
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT id, word, translation, date_added FROM personal_vocab WHERE student_code=? ORDER BY date_added DESC",
            (student_code,)
        )
        rows = c.fetchall()
        if rows:
            df = pd.DataFrame(rows, columns=["ID", "German Word", "Translation", "Date Added"])
            # Option to delete a word
            delete_word_id = st.selectbox("Delete a word (optional):", ["None"] + [f"{r[1]} ({r[2]})" for r in rows], key="delete_mywords")
            if delete_word_id != "None":
                idx = [f"{r[1]} ({r[2]})" for r in rows].index(delete_word_id)
                word_id = rows[idx][0]
                if st.button("Delete Selected Word"):
                    c.execute("DELETE FROM personal_vocab WHERE id=?", (word_id,))
                    conn.commit()
                    st.success("Word deleted.")
                    st.experimental_rerun()
            st.dataframe(df[["German Word", "Translation", "Date Added"]], use_container_width=True)

            # Practice logic: pick a random personal vocab not yet completed today
            done_ids = st.session_state["vocab_completed"]
            not_done = [r for r in rows if r[0] not in done_ids]
            if not_done:
                r = random.choice(not_done)
                st.session_state["mywords_last_word_id"] = r[0]
                vocab_word = r[1]
                vocab_tr = r[2]
                st.markdown(f"**Translate:** {vocab_word}")
                ans = st.text_input("Your translation", key=f"mywords_ans_{r[0]}")
                if st.button("Check", key=f"mywords_check_{r[0]}"):
                    if ans.strip().lower() == vocab_tr.strip().lower():
                        st.success("✅ Correct!")
                        st.session_state["vocab_usage"][usage_key] += 1
                        st.session_state["vocab_completed"].add(r[0])
                    else:
                        st.warning(f"❌ Not quite. Correct: {vocab_tr}")
                    st.experimental_rerun()
            else:
                st.success("🎉 All your words done for today!")
        else:
            st.info("No words saved yet. Add your first word above!")
        st.stop()  # Prevents A1–C1 block from running

    # ========== STANDARD VOCAB PRACTICE (A1–C1) ==========
    vocab_list = VOCAB_LISTS.get(st.session_state["vocab_level"], [])
    is_tuple = bool(vocab_list and isinstance(vocab_list[0], (list, tuple)))
    completed = st.session_state["vocab_completed"]
    pending_idxs = [i for i in range(len(vocab_list)) if i not in completed]

    # Feedback from last check, Next button
    if st.session_state["vocab_feedback"] and st.session_state["show_next_button"]:
        st.markdown(st.session_state["vocab_feedback"], unsafe_allow_html=True)
        if st.button("➡️ Next"):
            if st.session_state["last_was_correct"]:
                st.session_state["vocab_completed"].add(st.session_state["current_vocab_idx"])
            for k in ["vocab_feedback", "show_next_button", "current_vocab_idx", "last_was_correct"]:
                st.session_state[k] = False if isinstance(st.session_state[k], bool) else None if k == "current_vocab_idx" else ""
            st.experimental_rerun()
        st.stop()

    # New word practice
    if pending_idxs:
        idx = st.session_state["current_vocab_idx"] if st.session_state["current_vocab_idx"] is not None else random.choice(pending_idxs)
        st.session_state["current_vocab_idx"] = idx
        word = vocab_list[idx][0] if is_tuple else vocab_list[idx]
        corr = vocab_list[idx][1] if is_tuple else None
        st.markdown(f"**Translate:** {word}")
        ans = st.text_input("Your answer:", key=f"vocab_ans_{idx}")
        if st.button("Check", key=f"vocab_check_{idx}"):
            fb, correct, close = ai_vocab_feedback(word, ans, corr)
            st.session_state["vocab_feedback"] = fb
            st.session_state["show_next_button"] = True
            st.session_state["last_was_correct"] = correct
            if correct or close:
                st.session_state["vocab_usage"][usage_key] += 1
            save_vocab_submission(
                student_code, student_name, st.session_state["vocab_level"], word, ans, correct
            )
            st.experimental_rerun()
    else:
        st.success("🎉 All words done for today!")

    # Summary prompt
    if completed:
        st.info(f"Completed {len(completed)}/{len(vocab_list)} words. Come back tomorrow or switch level!")



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

#Myresults

if tab == "My Results and Resources":
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

if tab == "Admin":
    # --- Admin Auth ---
    if not st.session_state.get("is_admin", False):
        admin_pw = st.text_input("Enter admin password:", type="password", key="admin_pw")
        if st.button("Login as Admin"):
            ADMIN_PASSWORD = "Felix029"
            if admin_pw == ADMIN_PASSWORD:
                st.session_state["is_admin"] = True
                st.success("Welcome, Admin!")
                st.rerun()
            else:
                st.error("Incorrect password.")
        st.stop()
    else:
        st.info("You are logged in as admin.")

        # --- Force Refresh Button ---
        if st.button("🔄 Force Refresh All Data"):
            st.cache_data.clear()
            st.success("Cache cleared! Reloading…")
            st.rerun()

        st.subheader("Student Data Backup & Restore")

        # ===== Download/Backup Section =====
        import pandas as pd

        # --- Student Scores Backup ---
        st.markdown("### 📥 Download Backups")

        # Scores (assignment marking) backup
        try:
            conn_scores = sqlite3.connect('scores.db')
            df_scores = pd.read_sql_query("SELECT * FROM scores", conn_scores)
            csv_scores = df_scores.to_csv(index=False).encode('utf-8')
            st.download_button("⬇️ Download Scores Backup", csv_scores, file_name="scores_backup.csv", mime="text/csv")
        except Exception as e:
            st.warning(f"Could not load scores: {e}")

        # Vocab Progress backup
        try:
            conn_vocab = sqlite3.connect('vocab_progress.db')
            df_vocab = pd.read_sql_query("SELECT * FROM vocab_progress", conn_vocab)
            csv_vocab = df_vocab.to_csv(index=False).encode('utf-8')
            st.download_button("⬇️ Download Vocab Progress", csv_vocab, file_name="vocab_progress_backup.csv", mime="text/csv")
        except Exception as e:
            st.warning(f"Could not load vocab progress: {e}")

        # Schreiben Progress backup
        try:
            conn_schreiben = sqlite3.connect('vocab_progress.db')
            df_schreiben = pd.read_sql_query("SELECT * FROM schreiben_progress", conn_schreiben)
            csv_schreiben = df_schreiben.to_csv(index=False).encode('utf-8')
            st.download_button("⬇️ Download Schreiben Progress", csv_schreiben, file_name="schreiben_progress_backup.csv", mime="text/csv")
        except Exception as e:
            st.warning(f"Could not load schreiben progress: {e}")

        # Sprechen Progress backup (if table exists)
        try:
            conn_sprechen = sqlite3.connect('vocab_progress.db')
            df_sprechen = pd.read_sql_query("SELECT * FROM sprechen_progress", conn_sprechen)
            csv_sprechen = df_sprechen.to_csv(index=False).encode('utf-8')
            st.download_button("⬇️ Download Sprechen Progress", csv_sprechen, file_name="sprechen_progress_backup.csv", mime="text/csv")
        except Exception as e:
            st.info("No Sprechen Progress table found. (If not used, ignore this warning.)")

        # ===== Upload/Restore Section =====
        st.markdown("### 📤 Restore from Backup (Upload, overwrites current data)")

        # --- Scores Upload ---
        uploaded_scores = st.file_uploader("Upload Scores CSV", type="csv", key="up_scores")
        if uploaded_scores:
            try:
                df_new = pd.read_csv(uploaded_scores)
                conn_scores = sqlite3.connect('scores.db')
                df_new.to_sql('scores', conn_scores, if_exists='replace', index=False)
                st.success("Scores data uploaded & replaced.")
            except Exception as e:
                st.error(f"Upload failed: {e}")

        # --- Vocab Progress Upload ---
        uploaded_vocab = st.file_uploader("Upload Vocab Progress CSV", type="csv", key="up_vocab")
        if uploaded_vocab:
            try:
                df_new = pd.read_csv(uploaded_vocab)
                conn_vocab = sqlite3.connect('vocab_progress.db')
                df_new.to_sql('vocab_progress', conn_vocab, if_exists='replace', index=False)
                st.success("Vocab Progress uploaded & replaced.")
            except Exception as e:
                st.error(f"Upload failed: {e}")

        # --- Schreiben Progress Upload ---
        uploaded_schreiben = st.file_uploader("Upload Schreiben Progress CSV", type="csv", key="up_schreiben")
        if uploaded_schreiben:
            try:
                df_new = pd.read_csv(uploaded_schreiben)
                conn_schreiben = sqlite3.connect('vocab_progress.db')
                df_new.to_sql('schreiben_progress', conn_schreiben, if_exists='replace', index=False)
                st.success("Schreiben Progress uploaded & replaced.")
            except Exception as e:
                st.error(f"Upload failed: {e}")

        # --- Sprechen Progress Upload ---
        uploaded_sprechen = st.file_uploader("Upload Sprechen Progress CSV", type="csv", key="up_sprechen")
        if uploaded_sprechen:
            try:
                df_new = pd.read_csv(uploaded_sprechen)
                conn_sprechen = sqlite3.connect('vocab_progress.db')
                df_new.to_sql('sprechen_progress', conn_sprechen, if_exists='replace', index=False)
                st.success("Sprechen Progress uploaded & replaced.")
            except Exception as e:
                st.error(f"Upload failed: {e}")

        # --- Show all students table (as before) ---
        st.markdown("---")
        st.markdown("### 👀 View All Student Records")
        df_students = load_student_data()
        st.dataframe(df_students)

