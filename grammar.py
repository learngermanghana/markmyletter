import os
import random
import difflib
import sqlite3
import atexit
from datetime import date  # Only once!
import pandas as pd
import streamlit as st
from openai import OpenAI
from fpdf import FPDF
from streamlit_cookies_manager import EncryptedCookieManager
import urllib.parse


# ---- OpenAI Client Setup ----
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("Missing OpenAI API key. Please set OPENAI_API_KEY in your Streamlit secrets.")
    st.stop()
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY   # <- Set for OpenAI client!
client = OpenAI()  # <-- Do NOT pass api_key here for openai>=1.0

# ---- Paste the DB connection helper here ----

def get_connection():
    if "conn" not in st.session_state:
        st.session_state["conn"] = sqlite3.connect("vocab_progress.db", check_same_thread=False)
        atexit.register(st.session_state["conn"].close)
    return st.session_state["conn"]

conn = get_connection()
c = conn.cursor()

def get_student_stats(student_code):
    conn = get_connection()
    c = conn.cursor()
    # Group by level, count correct and attempted for each
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
    # Placeholder: return a fake streak for now
    return 3

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
    conn.commit()

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
        <img src='https://cdn-icons-png.flaticon.com/512/6815/6815043.png' width='54' style='border-radius:50%;border:2.5px solid #51a8d2;box-shadow:0 2px 8px #cbe7fb;'/>
        <div>
            <span style='font-size:2.1rem;font-weight:bold;color:#17617a;letter-spacing:2px;'>Falowen</span><br>
            <span style='font-size:1.08rem;color:#268049;'>Your personal German speaking coach (Herr Felix)</span>
        </div>
    </div>
    """, unsafe_allow_html=True
)
# ====================================
# 2. STUDENT DATA LOADING
# ====================================

STUDENTS_CSV = "students.csv"
CODES_FILE = "student_codes.csv"

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
            cookie_manager.set("student_code", st.session_state["student_code"])  # <-- Set cookie!
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

# ====================================
# 5. CONSTANTS & VOCAB LISTS
# ====================================

FALOWEN_DAILY_LIMIT = 25
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


# ====================================
# 6. MAIN TAB SELECTOR (with Dashboard)
# ====================================

if st.session_state["logged_in"]:
    student_code = st.session_state.get("student_code", "")

    st.header("Choose Practice Mode")
    tab = st.radio(
        "How do you want to practice?",
        ["Dashboard", "Falowen Chat", "Vocab Trainer", "Schreiben Trainer", "Admin"],
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
        daily_so_far = st.session_state.get("schreiben_usage", {}).get(
            f"{student_code}_schreiben_{str(date.today())}", 0
        )
        SCHREIBEN_DAILY_LIMIT = 5

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



# ==========================
# FALOWEN CHAT TAB (Exam Mode & Custom Chat)
# ==========================
from datetime import date

if tab == "Falowen Chat":
    st.header("🗣️ Falowen – Speaking & Exam Trainer")

    # --- Set up session state (first run only) ---
    for key, default in [
        ("falowen_stage", 1), ("falowen_mode", None), ("falowen_level", None),
        ("falowen_teil", None), ("falowen_messages", []), ("custom_topic_intro_done", False),
        ("custom_chat_level", None)
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # Step 1: Mode selection
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

    # Step 2: Level selection
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

    # Step 3: Exam part selection
    if st.session_state["falowen_stage"] == 3:
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
            teil_options[st.session_state["falowen_level"]],
            key="falowen_teil_center"
        )
        if st.button("⬅️ Back", key="falowen_back2"):
            st.session_state["falowen_stage"] = 2
            st.stop()
        if st.button("Start Practice", key="falowen_start_practice"):
            st.session_state["falowen_teil"] = teil
            st.session_state["falowen_stage"] = 4
            st.session_state["falowen_messages"] = []
            st.session_state["custom_topic_intro_done"] = False
        st.stop()

    # -------------------------
    # Step 4: Main Chat
    # -------------------------
    if st.session_state["falowen_stage"] == 4:

        falowen_usage_key = f"{st.session_state['student_code']}_falowen_{str(date.today())}"
        if "falowen_usage" not in st.session_state:
            st.session_state["falowen_usage"] = {}
        st.session_state["falowen_usage"].setdefault(falowen_usage_key, 0)

        # --- Display usage and turn count
        turns_so_far = st.session_state.get("falowen_turn_count", 0)
        st.info(
            f"Today's practice: {st.session_state['falowen_usage'][falowen_usage_key]}/{FALOWEN_DAILY_LIMIT} | Turns: {turns_so_far}/{max_turns}"
        )

        # --- Initial assistant message if chat is empty
        if not st.session_state["falowen_messages"]:
            st.session_state["falowen_turn_count"] = 0  # Reset turn count
            mode  = st.session_state.get("falowen_mode", "")
            level = st.session_state.get("falowen_level", "A1")
            teil  = st.session_state.get("falowen_teil", "")

            if mode == "Geführte Prüfungssimulation (Exam Mode)":
                # ... [Your exam mode first prompts as above]
                pass  # <-- Paste your AI initial prompts block here
            elif mode == "Eigenes Thema/Frage (Custom Chat)":
                ai_first = (
                    "Hallo! 👋 What would you like to talk about? Give me details of what you want so I can understand. "
                    "You can enter a topic, a question, or a keyword. I'll help you prepare for your class presentation."
                )
            else:
                ai_first = "Hallo! Womit möchtest du heute üben?"
            st.session_state["falowen_messages"].append({"role": "assistant", "content": ai_first})

        # --- Show chat history
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

        # --- Enforce daily usage and turn limit ---
        turns_so_far = st.session_state.get("falowen_turn_count", 0)
        turn_limit_reached = turns_so_far >= max_turns
        usage_limit_reached = st.session_state["falowen_usage"][falowen_usage_key] >= FALOWEN_DAILY_LIMIT

        session_ended = usage_limit_reached or turn_limit_reached

        if session_ended:
            if turn_limit_reached:
                st.warning(
                    "You have reached the maximum number of chat turns for this session. Please start a new session to continue."
                )
            else:
                st.warning(
                    "You have reached today's practice limit for Falowen Chat. Come back tomorrow!"
                )
        else:
            user_input = st.chat_input("💬 Type your answer here...", key="falowen_input")
            if user_input:
                st.session_state["falowen_messages"].append({"role": "user", "content": user_input})
                st.session_state["falowen_turn_count"] = turns_so_far + 1
                st.session_state["falowen_usage"][falowen_usage_key] += 1

                # --- BUILD AI SYSTEM PROMPT LOGIC ---
                mode = st.session_state.get("falowen_mode", "")
                level = st.session_state.get("falowen_level", "A1")
                teil = st.session_state.get("falowen_teil", "")
                is_exam = (mode == "Geführte Prüfungssimulation (Exam Mode)")
                is_custom_chat = (mode == "Eigenes Thema/Frage (Custom Chat)")

                ai_system_prompt = ""
                # ---- EXAM MODE PROMPT LOGIC ----
                if is_exam:
                    # (You can add more logic here to keep track of current keyword/question for each teil)
                    if level == "A1":
                        if teil.startswith("Teil 1"):
                            ai_system_prompt = (
                                "You are Herr Felix, a Goethe A1 examiner. "
                                "After the student introduction, ask three random personal questions based on their introduction (about name, age, job, etc.). "
                                "Mark their response, give gentle correction (English), and provide tips for improvement. "
                                "After three questions, summarize strengths and suggest how to improve further."
                            )
                        elif teil.startswith("Teil 2"):
                            ai_system_prompt = (
                                "You are Herr Felix, an A1 examiner. For each round, pick the next topic and keyword from the exam list. "
                                "The student should ask a question using the keyword (e.g., 'Geschäft – schließen'). "
                                "Check if it's a proper question. If yes, answer briefly, then recommend the next keyword and ask the next question."
                            )
                        elif teil.startswith("Teil 3"):
                            ai_system_prompt = (
                                "You are Herr Felix, an A1 examiner. The student should write a polite request (using modal verbs or imperative). "
                                "Check if the sentence is correct and polite, then recommend the next prompt from the official list (e.g., 'Radio anmachen')."
                            )
                    elif level == "A2":
                        if teil.startswith("Teil 1"):
                            ai_system_prompt = (
                                "You are Herr Felix, a Goethe A2 examiner. "
                                "Student gives a topic and asks a question. Check if the question is correct and relates to the topic. "
                                "Reply with a short answer, correction in English, and suggest another topic/question from the exam list."
                            )
                        elif teil.startswith("Teil 2"):
                            ai_system_prompt = (
                                "You are Herr Felix, an A2 examiner. Student talks about a topic (e.g., Reisen, Essen). "
                                "Give correction and English explanation, then ask a new question on the same topic."
                            )
                        elif teil.startswith("Teil 3"):
                            ai_system_prompt = (
                                "You are Herr Felix, an A2 examiner. Plan something together (e.g., ins Kino gehen). "
                                "Respond to student suggestion, ask what, when, where, and why, and check their ability to suggest and plan."
                            )
                    elif level == "B1":
                        if teil.startswith("Teil 1"):
                            ai_system_prompt = (
                                "You are Herr Felix, a B1 examiner. Student suggests an activity to plan. "
                                "Ask about details, advantages, and possible problems. Give gentle correction, tips, and always suggest the next step to plan."
                            )
                        elif teil.startswith("Teil 2"):
                            ai_system_prompt = (
                                "You are Herr Felix, a B1 examiner. Student is giving a presentation. "
                                "After their message, ask for 1-2 details, correct errors, and give exam feedback."
                            )
                        elif teil.startswith("Teil 3"):
                            ai_system_prompt = (
                                "You are Herr Felix, a B1 examiner. Student has finished a presentation. "
                                "Ask questions about their talk, give positive and constructive feedback (in English), and suggest one exam tip."
                            )
                    elif level == "B2":
                        if teil.startswith("Teil 1"):
                            ai_system_prompt = (
                                "You are Herr Felix, a B2 examiner. Student gives their opinion on a topic. "
                                "Challenge their opinion, ask for reasons/examples, and give advanced corrections."
                            )
                        elif teil.startswith("Teil 2"):
                            ai_system_prompt = (
                                "You are Herr Felix, a B2 examiner. Student presents a topic. "
                                "After each answer, give C1-style questions, correct errors, and encourage deeper arguments."
                            )
                        elif teil.startswith("Teil 3"):
                            ai_system_prompt = (
                                "You are Herr Felix, a B2 examiner. Argue with the student about the topic, ask for evidence, and provide feedback on advanced language use."
                            )
                    elif level == "C1":
                        if teil.startswith("Teil 1"):
                            ai_system_prompt = (
                                "You are Herr Felix, a C1 examiner. Listen to student's lecture. "
                                "Ask probing questions, correct advanced grammar, and comment on structure and vocabulary."
                            )
                        elif teil.startswith("Teil 2"):
                            ai_system_prompt = (
                                "You are Herr Felix, a C1 examiner. Lead a formal discussion. "
                                "Challenge student's argument, give critical feedback, and suggest native-like phrases."
                            )
                        elif teil.startswith("Teil 3"):
                            ai_system_prompt = (
                                "You are Herr Felix, a C1 examiner. Summarize the topic, ask the student to reflect, and give advice for future improvement."
                            )

                # ---- CUSTOM CHAT PROMPT LOGIC (Your Structure) ----
                elif is_custom_chat:
                    lvl = st.session_state.get('custom_chat_level', level)
                    # FIRST MESSAGE = TOPIC ONLY, GIVE IDEAS/TIPS/QUESTION
                    if not st.session_state.get("custom_topic_intro_done", False):
                        st.session_state["custom_topic_intro_done"] = True
                        if lvl == "A1":
                            ai_system_prompt = (
                                "You are Herr Felix, a friendly A1 tutor. "
                                "Student's first input is their topic or keyword. Greet them and suggest a few A1-level phrases, then ask a simple question about the topic. No correction yet."
                            )
                        elif lvl == "A2":
                            ai_system_prompt = (
                                "You are Herr Felix, a friendly but creative A2 German teacher and exam trainer. "
                                "Greet and give students ideas and examples about how to talk about the topic in English and ask only question. No correction or answer in the statement but only tip and possible phrases to use. This stage only when the student input their first question and not anyother input. "
                                "The first input from the student is their topic and not their reply or sentence or answer. It is always their presentation topic. Only the second and further repliers it their response to your question "
                                "Use simple English and German to correct the student's last answer. Tip and necessary suggestions should be explained in English with German supporting for student to understand. They are A2 beginners student. "
                                "You can also suggest keywords when needed. Ask one question only. Format your reply with answer, correction explanation in english, tip in english, and next question in German."
                            )
                        elif lvl == "B1":
                            ai_system_prompt = (
                                "You are Herr Felix, a supportive and creative B1 German teacher. "
                                "The first input from the student is their topic and not their reply or sentence or answer. It is always their presentation topic. Only the second and further repliers it their response to your question "
                                "Provide practical ideas/opinions/advantages/disadvantages/situation in their homeland for the topic in German and English, then ask one opinion question. No correction or answer in the statement but only tip and possible phrases to use. This stage only when the student input their first question and not anyother input. "
                                "Support ideas and opinions explanation in English and German as these students are new B1 students. "
                                "Ask creative question that helps student to learn how to answer opinions,advantages,disadvantages,situation in their country and so on. "
                                "Always put the opinion question on a separate line so the student can notice the question from the ideas and examples"
                            )
                        elif lvl == "B2":
                            ai_system_prompt = (
                                "You are Herr Felix, a creative and demanding B2 exam trainer. "
                                "For the student's first input (the topic): suggest main points, arguments, and advanced connectors they should use (both in English and German), then ask a thought-provoking question on a new line. No correction yet."
                            )
                        elif lvl == "C1":
                            ai_system_prompt = (
                                "You are Herr Felix, a C1-level examiner. "
                                "After student's topic: suggest academic phrases and argumentative structures, show how to deepen analysis, then ask a challenging question. No correction or evaluation on the first input."
                            )
                    else:
                        # SUBSEQUENT MESSAGES: FEEDBACK + CORRECTION + NEXT QUESTION
                        if lvl == "A1":
                            ai_system_prompt = (
                                "You are Herr Felix, a supportive A1 tutor. "
                                "Correct grammar and vocabulary mistakes in English, give a short tip, and ask another simple question about the same topic."
                            )
                        elif lvl == "A2":
                            ai_system_prompt = (
                                "You are Herr Felix, a friendly but creative A2 German teacher and exam trainer. "
                                "For each student answer: correct the answer in English and German, give a tip, and ask a follow-up question related to their topic or previous answer."
                            )
                        elif lvl == "B1":
                            ai_system_prompt = (
                                "You are Herr Felix, a supportive B1 German teacher. "
                                "Give constructive feedback in both German and English, highlight strengths and weaknesses, and ask a new opinion or experience question about the student's topic."
                            )
                        elif lvl == "B2":
                            ai_system_prompt = (
                                "You are Herr Felix, a B2 examiner. "
                                "For each student reply: correct for advanced grammar, explain in English and German, ask a more difficult, exam-like question about their topic, and suggest academic vocabulary."
                            )
                        elif lvl == "C1":
                            ai_system_prompt = (
                                "You are Herr Felix, a C1 examiner. "
                                "Correct for academic style, suggest how to add complexity and depth, and always finish with an open-ended, reflective question about the topic."
                            )

                # --- Compose conversation for OpenAI API ---
                conversation = [{"role": "system", "content": ai_system_prompt}]
                for m in st.session_state["falowen_messages"]:
                    if m["role"] == "user":
                        conversation.append({"role": "user", "content": m["content"]})
                    else:
                        conversation.append({"role": "assistant", "content": m["content"]})

                with st.spinner("🧑‍🏫 Herr Felix is typing..."):
                    try:
                        resp = client.chat.completions.create(model="gpt-4o", messages=conversation)
                        ai_reply = resp.choices[0].message.content
                    except Exception as e:
                        ai_reply = f"Sorry, there was a problem: {str(e)}"
                        st.error(str(e))

                st.session_state["falowen_messages"].append({"role": "assistant", "content": ai_reply})
                st.rerun()  # To refresh the chat UI after reply



# =========================================
# VOCAB TRAINER TAB (A1–C1, with Progress, Streak, Goal, Gamification)
# =========================================

if tab == "Vocab Trainer":
    st.header("🧠 Vocab Trainer")

    student_code = st.session_state.get("student_code", "demo")
    student_name = st.session_state.get("student_name", "Demo")
    today_str = str(date.today())

    # --- Daily Streak (fetch from your helper/db, or fake if not available) ---
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
    st.progress(min(used_today, VOCAB_DAILY_LIMIT) / VOCAB_DAILY_LIMIT, text=f"{used_today} / {VOCAB_DAILY_LIMIT} words practiced today")

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
            is_correct = is_close_answer(user_answer, correct_answer) if is_tuple else bool(user_answer.strip())
            # Show feedback
            if is_correct:
                st.success("✅ Correct!")
                completed_words.add(idx)
            else:
                st.error(f"❌ Not quite. The correct answer is: <b>{correct_answer}</b>", icon="❗️")

            # Save to DB
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
    if lvl_stats and lvl_stats.get("attempted", 0):
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
                client = OpenAI(api_key=OPENAI_API_KEY)
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
            score_match = re.search(r"Score[:\s]+(\d+)\s*/\s*25", feedback, re.IGNORECASE)
            score = int(score_match.group(1)) if score_match else 0

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
                st.download_button(
                    "⬇️ Download Feedback as PDF",
                    f,
                    file_name=pdf_output,
                    mime="application/pdf"
                )

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
