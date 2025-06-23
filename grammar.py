import os
import random
import difflib
import sqlite3
import atexit
from datetime import date
import pandas as pd
import streamlit as st
from openai import OpenAI
from fpdf import FPDF
from streamlit_cookies_manager import EncryptedCookieManager  # Persistent login

# ---- OpenAI Client Setup ----
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error(
        "Missing OpenAI API key. Please set OPENAI_API_KEY as an environment variable or in Streamlit secrets."
    )
    st.stop()

client = OpenAI(api_key=OPENAI_API_KEY)  # Correct for openai>=1.0.0


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
    # Oral Topic Progress Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS oral_topic_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT,
            level TEXT,
            teil TEXT,
            topic TEXT,
            date TEXT
        )
    """)
    conn.commit()

init_db()  # <--- Call this ONCE after defining the function!

# --- Data saving helpers ---
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

def save_oral_topic_progress(student_code, level, teil, topic):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO oral_topic_progress (student_code, level, teil, topic, date) VALUES (?, ?, ?, ?, ?)",
        (student_code, level, teil, topic, str(date.today()))
    )
    conn.commit()

# --- Stats helpers ---
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

# --- Falowen usage for daily quota ---
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

# --- Oral Topic Helpers ---
def get_completed_oral_topics(student_code, level, teil):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT topic FROM oral_topic_progress WHERE student_code=? AND level=? AND teil=?",
        (student_code, level, teil)
    )
    return set([r[0] for r in c.fetchall()])

def mark_topic_completed(student_code, level, teil, topic):
    """
    Record that a student has completed an oral exam topic.
    Only saves if not already present, ensuring one record per topic.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM oral_topic_progress WHERE student_code=? AND level=? AND teil=? AND topic=?",
        (student_code, level, teil, topic)
    )
    if not c.fetchone():
        save_oral_topic_progress(student_code, level, teil, topic)

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


# ====================================
# 2. STUDENT DATA LOADING
# ====================================

STUDENTS_CSV = "students.csv"

@st.cache_data
def load_student_data():
    """Load student data from STUDENTS_CSV.
    If missing or empty, return empty DataFrame so app still runs."""
    path = globals().get("STUDENTS_CSV", "students.csv")
    if not os.path.exists(path):
        st.warning("Students file not found. Using empty data.")
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        st.warning("Students file is empty. Using empty data.")
        return pd.DataFrame()

    df.columns = [c.strip() for c in df.columns]
    for col in ["StudentCode", "Email"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.lower()
    return df


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

def get_exam_topics(level):
    """
    Return a flat list of possible oral exam topics for the given level.

    Args:
        level (str): "A1", "A2", "B1", "B2", or "C1"

    Returns:
        List[str]: All possible topics for oral exam for that level.
    """
    if level == "A1":
        # A1_TEIL2 is a list of (Thema, Keyword) tuples, flatten as "Thema – Keyword"
        topics = (
            A1_TEIL1
            + [f"{t[0]} – {t[1]}" for t in A1_TEIL2]
            + A1_TEIL3
        )
    elif level == "A2":
        topics = A2_TEIL1 + A2_TEIL2 + A2_TEIL3
    elif level == "B1":
        topics = B1_TEIL1 + B1_TEIL2 + B1_TEIL3
    elif level == "B2":
        topics = b2_teil1_topics + b2_teil2_presentations + b2_teil3_arguments
    elif level == "C1":
        topics = c1_teil1_lectures + c1_teil2_discussions + c1_teil3_evaluations
    else:
        topics = []
    return topics



# ====================================
# 6. MAIN TAB SELECTOR (with Dashboard)
# ====================================

if st.session_state["logged_in"]:
    student_code = st.session_state.get("student_code", "")

    st.header("Choose Practice Mode")
    tab = st.radio(
        "How do you want to practice?",
        ["Dashboard", "Exams Mode & Custom Chat", "Vocab Trainer", "Schreiben Trainer", "Admin"],
        key="main_tab_select"
    )

    # --- Mobile-friendly Active Tab Indicator ---
    st.markdown(
        f"""
        <div style='
            display: flex; 
            justify-content: center; 
            align-items: center;
            margin-bottom: 10px;
        '>
            <span style='
                background: #3498db;
                color: #fff;
                padding: 6px 18px;
                border-radius: 22px;
                font-size: 1.1rem;
                font-weight: 600;
                letter-spacing: 1px;
                box-shadow: 0 1px 4px #bbc;
                white-space: nowrap;
            '>
                {tab}
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )


    # --- DASHBOARD TAB, MOBILE-FRIENDLY ---
    if tab == "Dashboard":
        st.header("📊 Student Dashboard")

        student_row = st.session_state.get("student_row") or {}
        streak = get_vocab_streak(student_code)
        total_attempted, total_passed, accuracy = get_writing_stats(student_code)

        # --- Compute today's writing usage for Dashboard ---
        from datetime import date
        today_str = str(date.today())
        limit_key = f"{student_code}_schreiben_{today_str}"
        if "schreiben_usage" not in st.session_state:
            st.session_state["schreiben_usage"] = {}
        st.session_state["schreiben_usage"].setdefault(limit_key, 0)
        daily_so_far = st.session_state["schreiben_usage"][limit_key]

        # Student name and essentials
        st.markdown(f"### 👤 {student_row.get('Name', '')}")
        st.markdown(
            f"**Level:** {student_row.get('Level', '')}\n\n"
            f"**Code:** `{student_row.get('StudentCode', '')}`\n\n"
            f"**Email:** {student_row.get('Email', '')}\n\n"
            f"**Phone:** {student_row.get('Phone', '')}\n\n"
            f"**Location:** {student_row.get('Location', '')}\n\n"
            f"**Contract:** {student_row.get('ContractStart', '')} ➔ {student_row.get('ContractEnd', '')}\n\n"
            f"**Enroll Date:** {student_row.get('EnrollDate', '')}\n\n"
            f"**Status:** {student_row.get('Status', '')}"
        )

        # --- Payment info, clear message ---
        balance = student_row.get('Balance', '0.0')
        try:
            balance_float = float(balance)
        except Exception:
            balance_float = 0.0
        if balance_float > 0:
            st.warning(
                f"💸 Balance to pay: **₵{balance_float:.2f}** (update when paid)"
            )

        # --- Contract End reminder ---
        from datetime import datetime
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

        # --- Vocab streak ---
        st.markdown(f"🔥 **Vocab Streak:** {streak} days")

        # --- Writing goal tracker ---
        goal_remain = max(0, 2 - (total_attempted or 0))
        if goal_remain > 0:
            st.success(f"🎯 Your next goal: Write {goal_remain} more letter(s) this week!")
        else:
            st.success("🎉 Weekly goal reached! Keep practicing!")

        # --- Writing stats, big and clear ---
        st.markdown(
            f"**📝 Letters submitted:** {total_attempted}\n\n"
            f"**✅ Passed (score ≥17):** {total_passed}\n\n"
            f"**🏅 Pass rate:** {accuracy}%\n\n"
            f"**Today:** {daily_so_far} / {SCHREIBEN_DAILY_LIMIT} used"
        )

        # --- Exam Registration Dates & Fees (only in Dashboard) ---
        st.markdown("""
**📢 Registration: Aug./Sept. 2025 Goethe-Institut Exams**

**Exam Dates and Fees (Extern):**
- **A1:** 21.07.2025 — 2800 GHS
- **A2:** 22.07.2025 — 2400 GHS
- **B1:** 23.07.2025 — 2750 GHS (full) / 840 GHS (per module)
- **B2:** 24.07.2025 — 2500 GHS (full) / 840 GHS (per module)
- **C1:** 25.07.2025 — 2450 GHS (full) / 700 GHS (per module)

[🔗 Click here to register now](https://www.goethe.de/ins/gh/en/spr/prf/anm.html)

**How to Register:**
1. Tap the link above and click **register** on the Goethe page.
2. Select **Extern** and your exam level.
3. Wait for the confirmation email.
4. Pay via Mobile Money or bank to Ecobank Ghana (use your full name as reference).
5. Email your payment receipt to [registrations-accra@goethe.de](mailto:registrations-accra@goethe.de).
6. Wait for your final confirmation in a few days.

**Payment Details:**  
Bank: Ecobank Ghana  
Account Name: GOETHE-INSTITUT GHANA  
Account Number: 1441 001 701 903  
Branch: Ring Road Central  
SWIFT: ECOCGHAC
""")


if tab == "Exams Mode & Custom Chat":
    # --- Daily Limit Check ---
    # You can use a helper like: has_falowen_quota(student_code) or get_falowen_remaining(student_code)
    if not has_falowen_quota(student_code):
        st.header("🗣️ Falowen – Speaking & Exam Trainer")
        st.warning("You have reached your daily practice limit for this section. Please come back tomorrow.")
        st.stop()


# ==========================
# FALOWEN CHAT TAB (Exam Mode & Custom Chat)
# ==========================

def falowen_download_pdf(messages, filename):
    import os
    def safe_latin1(text):
        # Replaces all unsupported characters with '?'
        return text.encode("latin1", "replace").decode("latin1")
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    chat_text = ""
    for m in messages:
        role = "Herr Felix" if m["role"] == "assistant" else "Student"
        safe_msg = safe_latin1(m['content'])
        chat_text += f"{role}: {safe_msg}\n\n"
    pdf.multi_cell(0, 10, chat_text)
    pdf_output = f"{filename}.pdf"
    pdf.output(pdf_output)
    with open(pdf_output, "rb") as f:
        pdf_bytes = f.read()
    os.remove(pdf_output)
    return pdf_bytes


# ---- Helper Functions for AI prompts ----

def build_a1_exam_intro():
    return (
        "**A1 – Teil 1: Basic Introduction**\n\n"
        "In the A1 exam's first part, you will be asked to introduce yourself. "
        "Typical information includes: your **Name, Land, Wohnort, Sprachen, Beruf, Hobby** (name, country, city, languages, job, hobby).\n\n"
        "After your introduction, you will be asked 3 basic questions such as:\n"
        "- Haben Sie Geschwister? (Do you have siblings?)\n"
        "- Wie alt ist deine Mutter? (How old is your mother?)\n"
        "- Bist du verheiratet? (Are you married?)\n\n"
        "You might also be asked to spell your name (**Buchstabieren**), so practice your alphabet!\n"
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
                "and then answer it yourself like your partner will do in the exams hall. For example: "
                "Thema: Geschäft – Keyword: schließen → You: Wann schließt das Geschäft?\n"
                "Let's try one. I'll give you a random topic now! Are you ready"
                
            )
        elif "Teil 3" in teil:
            return (
                "**A1 – Teil 3: Making a Request**\n\n"
                "You'll receive a prompt (e.g. 'Radio anmachen'). Write a polite request or use the imperative. "
                "Example: Können Sie bitte das Radio anmachen? or Machen Sie bitte das Radio an.\n"
                "Responding to request you can use ('Ja gerne or In Ordnung'). \n"
                "I'll give you a random prompt now! Are you ready"
            )
    if level == "A2":
        if "Teil 1" in teil:
            return (
                "**A2 – Teil 1: Fragen zu Schlüsselwörtern**\n\n"
                "You'll get a topic (e.g. 'Wohnort'). Ask a question about it, then answer it yourself like your partner will do."
                "You'll get a topic (e.g. 'Wohnort'). Ask a question about it, then answer it yourself like your partner will do."
                "Give me a prompt like ('Yes, okay,begin) then i will start. Always let me know when you want the next question after answering"
            )
        elif "Teil 2" in teil:
            return (
                "**A2 – Teil 2: Über das Thema sprechen**\n\n"
                "Talk about the topic in 3-4 sentences. I'll help with correction and tips. "
                "Should we begin. "
            )
        elif "Teil 3" in teil:
            return (
                "**A2 – Teil 3: Gemeinsam planen**\n\n"
                "Let's plan something together, like an activity. Respond to my suggestions and make your own. "
                "Should we begin. "
            )
    if level == "B1":
        if "Teil 1" in teil:
            return (
                "**B1 – Teil 1: Gemeinsam planen**\n\n"
                "We'll plan an activity together (e.g., a trip). If you are ready just type ready so we start. "
            )
        elif "Teil 2" in teil:
            return (
                "**B1 – Teil 2: Präsentation**\n\n"
                "Give a short presentation on the topic (2-3 minutes). I'll ask follow-up questions."
                "Should we begin."
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
                "1. Instructions,compliments and suggestions after students input should be English. They are just beginners. "
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
                "Ask them to write a polite request or imperative. Check if it's correct and polite, explain errors in English, and provide the right German version. Then give the next prompt."
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
            f"For each keyword, ask the student up to 3 creative, diverse and interesting questions in German only based on student language level, one at a time, not all at once. Just ask the question and don't let the student know this is the keyword you are using. "
            f"After each student answer, give feedback and a suggestion to extend their answer if it's too short. Feedback in English and suggestion in German. "
            f"After keyword questions, continue with other random follow-up questions that reflect the student's selected level about the topic in German (until you reach 20 questions in total). "
            f"Never ask more than 3 questions about the same keyword. "
            f"After the student answers 20 questions, write a summary of their performance: what they did well, mistakes, and what to improve in English. "
            f"All feedback and corrections should be {correction_lang}. "
            f"Encourage the student and keep the chat motivating. "
        )
    return ""

# ==========================
# FALOWEN CHAT TAB (Exam Mode & Custom Chat)
# ==========================

# --- Initialize variables from session state safely ---
level = st.session_state.get("falowen_level", "")
teil = st.session_state.get("falowen_teil", "")
mode = st.session_state.get("falowen_mode", "")
is_exam = mode == "Geführte Prüfungssimulation (Exam Mode)"
is_custom_chat = mode == "Eigenes Thema/Frage (Custom Chat)"
stage = st.session_state.get("falowen_stage", 1)

# ---- Session Navigation Helpers ----
def reset_chat():
    """Clear the current chat history and restart the conversation."""
    st.session_state["falowen_messages"] = []
    st.session_state["falowen_exam_topic"] = None
    st.session_state["falowen_user_input"] = ""
    st.rerun()

def back_step():
    """Go back to the level selection step (Step 2)."""
    st.session_state["falowen_stage"] = 2
    st.session_state["falowen_messages"] = []
    st.session_state["falowen_exam_topic"] = None
    st.session_state["falowen_user_input"] = ""
    st.rerun()

def change_level():
    """Allow the user to pick a different level."""
    st.session_state["falowen_level"] = ""
    st.session_state["falowen_teil"] = ""
    st.session_state["falowen_stage"] = 2
    st.session_state["falowen_messages"] = []
    st.session_state["falowen_exam_topic"] = None
    st.session_state["falowen_user_input"] = ""
    st.rerun()

# ====== FALOWEN CHAT STAGE SELECTOR ======

if stage == 1:
    st.subheader("Step 1: Choose Practice Mode")
    mode = st.radio(
        "How would you like to practice?",
        ["Geführte Prüfungssimulation (Exam Mode)", "Eigenes Thema/Frage (Custom Chat)"],
        key="falowen_mode_center"
    )
    if st.button("Next ➡️", key="falowen_next_mode"):
        st.session_state["falowen_mode"] = mode
        st.session_state["falowen_stage"] = 2
        st.session_state["falowen_level"] = ""
        st.session_state["falowen_teil"] = ""
        st.session_state["falowen_messages"] = []
        st.session_state["falowen_exam_topic"] = None
        st.rerun()
    st.stop()

if stage == 2:
    st.subheader("Step 2: Choose Your Level")
    level = st.radio(
        "Select your level:",
        ["A1", "A2", "B1", "B2", "C1"],
        key="falowen_level_center"
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("⬅️ Back", key="falowen_back1"):
            st.session_state["falowen_stage"] = 1
            st.rerun()
    with col2:
        if st.button("Next ➡️", key="falowen_next_level"):
            st.session_state["falowen_level"] = level
            if st.session_state["falowen_mode"] == "Geführte Prüfungssimulation (Exam Mode)":
                st.session_state["falowen_stage"] = 3
            else:
                st.session_state["falowen_stage"] = 4
            st.session_state["falowen_teil"] = ""
            st.session_state["falowen_messages"] = []
            st.session_state["falowen_exam_topic"] = None
            st.rerun()
    st.stop()

if stage == 3:
    teil_options = {
        "A1": [
            "Teil 1 – Basic Introduction", "Teil 2 – Question and Answer", "Teil 3 – Making A Request"
        ],
        "A2": [
            "Teil 1 – Fragen zu Schlüsselwörtern", "Teil 2 – Über das Thema sprechen", "Teil 3 – Gemeinsam planen"
        ],
        "B1": [
            "Teil 1 – Gemeinsam planen (Dialogue)", "Teil 2 – Präsentation (Monologue)", "Teil 3 – Feedback & Fragen stellen"
        ],
        "B2": [
            "Teil 1 – Diskussion", "Teil 2 – Präsentation", "Teil 3 – Argumentation"
        ],
        "C1": [
            "Teil 1 – Vortrag", "Teil 2 – Diskussion", "Teil 3 – Bewertung"
        ]
    }
    st.subheader("Step 3: Choose Exam Part")
    teil = st.radio(
        "Which exam part?",
        teil_options.get(level, []),
        key="falowen_teil_center"
    )

    # -------- Assign exam_topics based on level and teil --------
    exam_topics = []
    if level == "A1":
        if "Teil 1" in teil:
            exam_topics = A1_TEIL1
        elif "Teil 2" in teil:
            exam_topics = [f"{t[0]} – {t[1]}" for t in A1_TEIL2]
        elif "Teil 3" in teil:
            exam_topics = A1_TEIL3
    elif level == "A2":
        if "Teil 1" in teil:
            exam_topics = A2_TEIL1
        elif "Teil 2" in teil:
            exam_topics = A2_TEIL2
        elif "Teil 3" in teil:
            exam_topics = A2_TEIL3
    elif level == "B1":
        if "Teil 1" in teil:
            exam_topics = B1_TEIL1
        elif "Teil 2" in teil:
            exam_topics = B1_TEIL2
        elif "Teil 3" in teil:
            exam_topics = B1_TEIL3
    elif level == "B2":
        if "Teil 1" in teil:
            exam_topics = b2_teil1_topics
        elif "Teil 2" in teil:
            exam_topics = b2_teil2_presentations
        elif "Teil 3" in teil:
            exam_topics = b2_teil3_arguments
    elif level == "C1":
        if "Teil 1" in teil:
            exam_topics = c1_teil1_lectures
        elif "Teil 2" in teil:
            exam_topics = c1_teil2_discussions
        elif "Teil 3" in teil:
            exam_topics = c1_teil3_evaluations

    # Optionally cache for use in stage 4
    st.session_state["falowen_exam_topics_cache"] = exam_topics

    picked_topic = None
    if level != "A1":
        picked_topic = st.selectbox("Choose a topic (optional):", ["(random)"] + exam_topics)
        if picked_topic != "(random)":
            st.session_state["falowen_exam_topic"] = picked_topic
        else:
            st.session_state["falowen_exam_topic"] = None
    else:
        st.session_state["falowen_exam_topic"] = None

    col1, col2 = st.columns(2)
    with col1:
        if st.button("⬅️ Back", key="falowen_back2"):
            st.session_state["falowen_stage"] = 2
            st.rerun()
    with col2:
        if st.button("Start Practice", key="falowen_start_practice"):
            st.session_state["falowen_teil"] = teil
            st.session_state["falowen_stage"] = 4
            st.session_state["falowen_messages"] = []
            st.session_state["custom_topic_intro_done"] = False
            st.rerun()
    st.stop()

# --- Handle random topic assignment for non-A1, when starting practice and no topic picked ---
if stage == 4 and level != "A1" and st.session_state.get("falowen_exam_topic") is None:
    exam_topics = st.session_state.get("falowen_exam_topics_cache", [])
    if exam_topics:
        st.session_state["falowen_exam_topic"] = random.choice(exam_topics)

if stage == 4:
    # === Download as PDF Button (optional) ===
    if st.session_state.get("falowen_messages", []):
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

    # --- Show session controls (optional) ---
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Restart Chat"):
            reset_chat()
    with col2:
        if st.button("Back"):
            back_step()
    with col3:
        if st.button("Change Level"):
            change_level()

    # --- Choose topics for the relevant exam parts ---
    cycle_teils = (
        (level == "A1" and ("Teil 2" in teil or "Teil 3" in teil)) or
        (level == "A2" and ("Teil 1" in teil or "Teil 2" in teil or "Teil 3" in teil))
        # Extend for B1/B2 as needed
    )

    if cycle_teils and is_exam:
        exam_topics = st.session_state.get("falowen_exam_topics_cache", [])
        idx_key = f"{level}_{teil}_idx"
        awaiting_key = f"{level}_{teil}_awaiting"

        if idx_key not in st.session_state:
            st.session_state[idx_key] = 0
        if awaiting_key not in st.session_state:
            st.session_state[awaiting_key] = False

        # Show intro if chat is empty
        if not st.session_state.get("falowen_messages"):
            intro = build_exam_instruction(level, teil)
            st.session_state["falowen_messages"] = [{"role": "assistant", "content": intro}]
            st.session_state[awaiting_key] = False

        # Display chat history
        for m in st.session_state["falowen_messages"]:
            who = "🧑‍🏫 Herr Felix" if m["role"] == "assistant" else "🙋 Student"
            with st.chat_message(m["role"], avatar="🧑‍🏫" if m["role"] == "assistant" else "🙂"):
                st.markdown(m["content"])

        user_input = st.chat_input("Type your answer here...", key="falowen_user_input")

        # If waiting for a "yes"/"okay"/start confirmation, start with topic 0
        if user_input and not st.session_state[awaiting_key]:
            if user_input.strip().lower() in ("yes", "ok", "okay", "begin", "start"):
                topic = exam_topics[st.session_state[idx_key]]
                st.session_state["falowen_messages"].append({"role": "assistant", "content": f"Das Thema ist: {topic}. Bitte stelle eine Frage dazu und beantworte sie selbst."})
                st.session_state[awaiting_key] = True
            else:
                st.session_state["falowen_messages"].append({"role": "assistant", "content": "Bitte antworte mit 'Yes', 'Okay' oder 'Begin', um zu starten."})

        elif user_input and st.session_state[awaiting_key]:
            # User answered for the topic, send to OpenAI for correction
            topic = exam_topics[st.session_state[idx_key]]
            messages = [
                {"role": "system", "content": f"You are a supportive examiner. Correct the student's German answer for the topic: {topic}. Give feedback in English, show the right German, then ask if they want the next topic."},
                {"role": "user", "content": user_input}
            ]
            try:
                completion = client.chat.completions.create(
                    model="gpt-4o",
                    messages=messages,
                    temperature=0.15,
                    max_tokens=400,
                )
                ai_reply = completion.choices[0].message.content.strip()
            except Exception as e:
                ai_reply = f"Sorry, an error occurred: {e}"
            st.session_state["falowen_messages"].append({"role": "user", "content": user_input})
            st.session_state["falowen_messages"].append({"role": "assistant", "content": ai_reply})
            # Mark topic completed in DB
            mark_topic_completed(student_code, level, teil, topic)
            st.session_state[awaiting_key] = False

            # Only increment topic if more remain, else finish
            if st.session_state[idx_key] + 1 < len(exam_topics):
                st.session_state[idx_key] += 1
                # Show "Next" button or accept "yes" to continue
                st.session_state["falowen_messages"].append({"role": "assistant", "content": "Möchtest du das nächste Thema machen? Antworte mit 'Yes' oder 'Okay'."})
            else:
                st.session_state["falowen_messages"].append({"role": "assistant", "content": "Super! Du hast alle Themen bearbeitet!"})

    else:
        # ========== Default Chat/Exam Mode (old logic) ==========
        # Show initial instruction if chat is empty
        if not st.session_state.get("falowen_messages"):
            instruction = ""
            if is_exam:
                instruction = build_exam_instruction(level, teil)
            elif is_custom_chat:
                instruction = (
                    "Hallo! 👋 What would you like to talk about? Give me details of what you want so I can understand. "
                    "You can enter a topic, a question, or a keyword. I'll help you prepare for your class presentation."
                )
            if instruction:
                st.session_state["falowen_messages"] = [{"role": "assistant", "content": instruction}]

        for m in st.session_state["falowen_messages"]:
            who = "🧑‍🏫 Herr Felix" if m["role"] == "assistant" else "🙋 Student"
            with st.chat_message(m["role"], avatar="🧑‍🏫" if m["role"] == "assistant" else "🙂"):
                st.markdown(m["content"])

        user_input = st.chat_input("Type your answer or message here...", key="falowen_user_input")
        if user_input:
            st.session_state["falowen_messages"].append({"role": "user", "content": user_input})
            inc_falowen_usage(student_code)
            with st.chat_message("assistant", avatar="🧑‍🏫"):
                with st.spinner("🧑‍🏫 Herr Felix is typing..."):
                    # Choose prompt
                    if is_exam:
                        system_prompt = build_exam_system_prompt(level, teil)
                    else:
                        system_prompt = build_custom_chat_prompt(level)
                    messages = [{"role": "system", "content": system_prompt}] + [
                        {"role": m["role"], "content": m["content"]}
                        for m in st.session_state["falowen_messages"]
                    ]
                    try:
                        completion = client.chat.completions.create(
                            model="gpt-4o",
                            messages=messages,
                            temperature=0.15,
                            max_tokens=600,
                        )
                        ai_reply = completion.choices[0].message.content.strip()
                    except Exception as e:
                        ai_reply = f"Sorry, an error occurred: {e}"
                    st.markdown(ai_reply)
            st.session_state["falowen_messages"].append({"role": "assistant", "content": ai_reply})

            if is_exam and st.session_state.get("falowen_exam_topic"):
                mark_topic_completed(
                    student_code,
                    level,
                    teil,
                    st.session_state["falowen_exam_topic"]
                )

# ========================== END FALOWEN CHAT TAB ==========================







# =========================================
# VOCAB TRAINER TAB (A1–C1, with Progress, Streak, Goal, Gamification)
# =========================================

if tab == "Vocab Trainer":
    st.header("🧠 Vocab Trainer")

    student_code = st.session_state.get("student_code", "demo")
    student_name = st.session_state.get("student_name", "Demo")
    today_str = str(date.today())

    # --- Daily Streak (fetch from your helper/db) ---
    streak = get_vocab_streak(student_code)
    if streak >= 1:
        st.success(f"🔥 {streak}-day streak! Keep it up!")
    else:
        st.warning("You lost your streak. Start practicing today to get it back!")

    # --- Daily usage tracking ---
    vocab_usage_key = f"{student_code}_vocab_{today_str}"
    if "vocab_usage" not in st.session_state:
        st.session_state["vocab_usage"] = {}
    st.session_state["vocab_usage"].setdefault(vocab_usage_key, 0)
    used_today = st.session_state["vocab_usage"][vocab_usage_key]

    # --- Level selection ---
    if "vocab_level" not in st.session_state:
        st.session_state["vocab_level"] = "A1"
    vocab_level = st.selectbox("Choose level", ["A1", "A2", "B1", "B2", "C1"], key="vocab_level_select")
    if vocab_level != st.session_state["vocab_level"]:
        st.session_state["vocab_level"] = vocab_level
        st.session_state["vocab_feedback"] = ""
        st.session_state["show_next_button"] = False
        st.session_state["vocab_completed"] = set()

    # --- Track completed words (fetch from DB if you want to persist) ---
    if "vocab_completed" not in st.session_state:
        st.session_state["vocab_completed"] = set()
    completed_words = st.session_state["vocab_completed"]

    vocab_list = VOCAB_LISTS.get(vocab_level, [])
    is_tuple = isinstance(vocab_list[0], tuple) if vocab_list else False

    # --- List of words not yet completed ---
    new_words = [i for i in range(len(vocab_list)) if i not in completed_words]
    random.shuffle(new_words)

    # --- Visual progress bar for today's goal ---
    st.progress(
        min(used_today, VOCAB_DAILY_LIMIT) / VOCAB_DAILY_LIMIT,
        text=f"{used_today} / {VOCAB_DAILY_LIMIT} words practiced today"
    )

    # --- Badge if daily goal reached ---
    if used_today >= VOCAB_DAILY_LIMIT:
        st.balloons()
        st.success("✅ Daily Goal Complete! You’ve finished your vocab goal for today.")
        st.stop()

    # --- Main vocab practice ---
    if new_words:
        idx = new_words[0]
        word = vocab_list[idx][0] if is_tuple else vocab_list[idx]
        correct_answer = vocab_list[idx][1] if is_tuple else None

        st.markdown(f"🔤 **Translate this German word to English:** <b>{word}</b>", unsafe_allow_html=True)
        user_answer = st.text_input("Your English translation", key=f"vocab_answer_{idx}")

        if st.button("Check", key=f"vocab_check_{idx}"):
            # --- New answer logic ---
            if is_tuple:
                is_correct = is_close_answer(user_answer, correct_answer)
                almost = is_almost(user_answer, correct_answer)
            else:
                # For single-word vocab (e.g., advanced levels), use OpenAI for validation
                is_correct = validate_translation_openai(word, user_answer)
                almost = False

            # --- Show feedback ---
            if is_correct:
                st.success("✅ Correct!")
                completed_words.add(idx)
            elif almost:
                st.warning(
                    f"Almost! The correct answer is: <b>{correct_answer}</b>",
                    icon="⚠️",
                )
            else:
                st.error(
                    f"❌ Not quite. The correct answer is: <b>{correct_answer}</b>" if is_tuple else "❌ Not quite.",
                    icon="❗️",
                )

            # --- Save to DB ---
            save_vocab_submission(
                student_code=student_code,
                name=student_name,
                level=vocab_level,
                word=word,
                student_answer=user_answer,
                is_correct=is_correct,
            )
            st.session_state["vocab_usage"][vocab_usage_key] += 1
            st.rerun()
    else:
        st.success("🎉 You've finished all new words for this level today!")

    # --- Optionally: show summary of all words completed so far for this level ---
    if completed_words:
        st.info(f"You have completed {len(completed_words)} words in {vocab_level} so far. Try another level or come back tomorrow!")

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

if tab == "Admin":
    # --- Password protection ---
    if "admin_unlocked" not in st.session_state:
        st.session_state["admin_unlocked"] = False

    if not st.session_state["admin_unlocked"]:
        admin_pw = st.text_input("Enter Admin Password:", type="password")
        if st.button("Unlock Admin"):
            if admin_pw == "Felix029":
                st.success("✅ Access granted.")
                st.session_state["admin_unlocked"] = True
                st.rerun()
            else:
                st.error("❌ Incorrect password.")
        st.stop()

    st.header("👨‍🏫 Admin & Teacher Settings")

    # View all students
    st.markdown("### 👩‍🎓 Student List")
    students_df = load_student_data()
    if not students_df.empty:
        st.dataframe(students_df, use_container_width=True)
    else:
        st.info("No students found.")

    # Export/import vocab progress
    st.markdown("---")
    st.markdown("### 📤 Export & Import: Vocab Progress")
    conn = get_connection()
    df_vocab = pd.read_sql_query("SELECT * FROM vocab_progress", conn)
    st.download_button(
        "⬇️ Download All Vocab Progress (CSV)",
        df_vocab.to_csv(index=False).encode('utf-8'),
        "vocab_progress_backup.csv",
        "text/csv"
    )
    uploaded_vocab = st.file_uploader("Upload vocab_progress_backup.csv", type="csv")
    if uploaded_vocab is not None:
        df = pd.read_csv(uploaded_vocab)
        c = conn.cursor()
        c.execute("DELETE FROM vocab_progress")
        for _, row in df.iterrows():
            c.execute("""
                INSERT INTO vocab_progress (id, student_code, name, level, word, student_answer, is_correct, date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                tuple(row)
            )
        conn.commit()
        st.success("Vocab progress restored! Refresh the app to see updates.")

    # Export/import schreiben progress
    st.markdown("---")
    st.markdown("### 📤 Export & Import: Schreiben Progress (Letters)")
    df_schreiben = pd.read_sql_query("SELECT * FROM schreiben_progress", conn)
    st.download_button(
        "⬇️ Download All Schreiben Progress (CSV)",
        df_schreiben.to_csv(index=False).encode('utf-8'),
        "schreiben_progress_backup.csv",
        "text/csv"
    )
    uploaded_schreiben = st.file_uploader("Upload schreiben_progress_backup.csv", type="csv")
    if uploaded_schreiben is not None:
        df = pd.read_csv(uploaded_schreiben)
        c = conn.cursor()
        c.execute("DELETE FROM schreiben_progress")
        for _, row in df.iterrows():
            c.execute("""
                INSERT INTO schreiben_progress (id, student_code, name, level, essay, score, feedback, date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                tuple(row)
            )
        conn.commit()
        st.success("Schreiben progress restored! Refresh the app to see updates.")

    # View, filter, and export student letters for AI training
    st.markdown("---")
    st.markdown("### 📄 All Student Letters (for Review & AI Training)")

    df_letters = pd.read_sql_query(
        "SELECT id, student_code, name, level, essay, score, feedback, date FROM schreiben_progress ORDER BY date DESC", conn
    )

    if not df_letters.empty:
        st.markdown("**Filter by student (optional):**")
        selected_student = st.selectbox(
            "Student:",
            options=["(All)"] + sorted(df_letters['name'].unique().tolist()),
            key="filter_admin_student"
        )
        if selected_student != "(All)":
            filtered = df_letters[df_letters['name'] == selected_student]
        else:
            filtered = df_letters
        st.dataframe(filtered, use_container_width=True)
    else:
        st.info("No student letters found.")

    st.download_button(
        "⬇️ Download All Student Letters for AI Training (CSV)",
        df_letters[["level", "essay", "score", "feedback"]].to_csv(index=False).encode("utf-8"),
        file_name="german_letters_ai_training.csv",
        mime="text/csv"
    )


