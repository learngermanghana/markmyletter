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
    """Return the number of consecutive days with vocab submissions."""
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

    # If the most recent submission wasn't today or yesterday, streak is lost
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



# ==========================
# FALOWEN CHAT TAB (Exam Mode & Custom Chat)
# ==========================

def falowen_download_pdf(messages, filename):
    def safe_latin1(text):
        # Replaces all unsupported characters with '?'
        return text.encode("latin1", "replace").decode("latin1")
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    chat_text = ""
    for m in messages:
        role = "Herr Felix" if m["role"] == "assistant" else "Student"
        # Safely encode each message
        safe_msg = safe_latin1(m['content'])
        chat_text += f"{role}: {safe_msg}\n\n"
    # Also encode the entire block for safety (double insurance)
    safe_chat_text = safe_latin1(chat_text)
    pdf.multi_cell(0, 10, safe_chat_text)
    pdf_output = f"{filename}.pdf"
    pdf.output(pdf_output)
    with open(pdf_output, "rb") as f:
        pdf_bytes = f.read()
    os.remove(pdf_output)
    return pdf_bytes


# ==========================
# EXAMS MODE & CUSTOM CHAT TAB
# ==========================
if tab == "Exams Mode & Custom Chat":
    st.header("🗣️ Falowen – Speaking & Exam Trainer")

    # --- Init session state for chat controls ---
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

    # === Step 1: Mode selection ===
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

    # === Step 2: Level selection ===
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

    # === Step 3: Exam part selection (with dropdown for exam topics, as discussed) ===
    if st.session_state["falowen_stage"] == 3:
        level = st.session_state["falowen_level"]
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
        # Exam topics for dropdown
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
        teil = st.radio(
            "Which exam part?",
            teil_options[st.session_state["falowen_level"]],
            key="falowen_teil_center"
        )

        # Optional: topic picker (for Teil 2/3)
        picked_topic = None
        if st.session_state["falowen_level"] != "A1":
            picked_topic = st.selectbox("Choose a topic (optional):", ["(random)"] + exam_topics)
            if picked_topic != "(random)":
                st.session_state["falowen_exam_topic"] = picked_topic
        else:
            st.session_state["falowen_exam_topic"] = None

        if st.button("⬅️ Back", key="falowen_back2"):
            st.session_state["falowen_stage"] = 2
            st.stop()
        if st.button("Start Practice", key="falowen_start_practice"):
            st.session_state["falowen_teil"] = teil
            st.session_state["falowen_stage"] = 4
            st.session_state["falowen_messages"] = []
            st.session_state["custom_topic_intro_done"] = False
        st.stop()

    # === Step 4: Main Chat ===
    if st.session_state["falowen_stage"] == 4:
        level = st.session_state["falowen_level"]
        teil = st.session_state.get("falowen_teil", "")
        mode = st.session_state.get("falowen_mode", "")
        is_exam = mode == "Geführte Prüfungssimulation (Exam Mode)"
        is_custom_chat = mode == "Eigenes Thema/Frage (Custom Chat)"

        # -- Handle reset/back/change logic --
        def reset_chat():
            st.session_state["falowen_stage"] = 1
            st.session_state["falowen_messages"] = []
            st.session_state["falowen_teil"] = None
            st.session_state["falowen_mode"] = None
            st.session_state["custom_topic_intro_done"] = False
            st.session_state["falowen_turn_count"] = 0
            st.session_state["falowen_exam_topic"] = None
            st.rerun()

        def back_step():
            if st.session_state["falowen_stage"] > 1:
                st.session_state["falowen_stage"] -= 1
                st.session_state["falowen_messages"] = []
                st.rerun()

        def change_level():
            st.session_state["falowen_stage"] = 2
            st.session_state["falowen_messages"] = []
            st.rerun()

        # ---- Show chat history ----
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

        # === Download as PDF Button ===
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

        # === Session controls: Restart, Back, Change Level ===
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

        # === Build instructions and system prompt logic ===

        def build_a1_exam_prompt(teil):
            if "Teil 1" in teil:
                return (
"""You are Herr Felix, an official Goethe A1 German examiner.
You are running a real Teil 1 exam session with a beginner student.
Your job is to strictly follow the steps below:

1. At the beginning, explain in English what Teil 1 is:
    - "In Teil 1 of the A1 exam, you will introduce yourself in German using these keywords: Name, Land, Wohnort, Sprachen, Beruf, Hobby.
      Please write your full introduction now. I will check your answer and then ask you some basic questions."

2. When the student replies with their introduction, check if they included ALL required information (name, country, city, languages, profession, hobby).
    - For any part missing, tell the student in English what is missing.
    - For any mistake, show the correct German version, and explain briefly in English what was wrong.
    - If the student made mistakes, ask them to try again or add the missing parts.
    - Only move on when everything is complete and correct.

3. After the introduction is fully correct, ask these three follow-up questions in German, one at a time. Wait for the student’s reply before each next question:
    - 1. Haben Sie Geschwister?
    - 2. Wie alt ist deine Mutter?
    - 3. Bist du verheiratet?

4. For each answer, if there are mistakes, write the correct answer in German and explain the error in simple English.

5. After all questions, summarize the student's performance in English:
    - Highlight what they did well, what they should practice more, and encourage them.

6. Remind them at the start or end that they might also be asked to spell their name (Buchstabieren), and should practice the German alphabet.

- Always keep explanations simple and positive.
- All feedback and instructions are in English, but model answers and questions are in German.
- Never do the full task for the student; always let them try again.

Begin the session now.
""")
            elif "Teil 2" in teil:
                return (
"""You are Herr Felix, a Goethe A1 examiner for Teil 2.
1. At the start, explain in English: "You will get a topic and a keyword. Your job: ask a question using the keyword, and then answer it yourself as if you are the examiner. For example: Thema: Geschäft – Keyword: schließen → You: Wann schließt das Geschäft? Now I'll give you your topic and keyword!"
2. Randomly pick a topic and keyword from the official list, present both, and tell the student to form and answer a question.
3. After each student message, mark if their question starts with a correct W-word or verb, and if the answer is reasonable. Correct any mistakes and explain in English.
4. After one round, you may ask if they want to try another or end the session.
""")
            elif "Teil 3" in teil:
                return (
"""You are Herr Felix, a Goethe A1 examiner for Teil 3.
1. At the start, explain in English: "You'll receive a prompt (e.g. 'Radio anmachen'). Write a polite request or use the imperative. Example: Können Sie bitte das Radio anmachen? or Machen Sie bitte das Radio an."
2. Randomly pick a prompt from the official list, give it to the student, and let them write a polite request.
3. Check if they use a modal verb (like können, dürfen) or the imperative form. Mark any mistakes, show the correct way, and explain in English.
4. You may give more prompts, or end with encouragement and tips.
""")
            return ""

        def build_exam_prompt(level, teil):
            if level == "A1":
                return build_a1_exam_prompt(teil)
            # For other levels, you can expand with similarly detailed logic
            elif level == "A2":
                # Example structure
                if "Teil 1" in teil:
                    return (
"""You are Herr Felix, a Goethe A2 examiner. 
1. At the start, explain in English: "You'll get a topic (e.g. 'Wohnort'). Ask a question about it, then answer it yourself."
2. Use the student's chosen or a random topic, check if their question is correct, and mark/feedback in English.
3. For every answer, give corrections and ask another question if needed.
""")
                elif "Teil 2" in teil:
                    return (
"""You are Herr Felix, a Goethe A2 examiner. 
Ask the student to speak about their chosen or a random topic for 3-4 sentences. Give clear corrections and suggestions in English. 
Ask a follow-up question to encourage deeper answers.
""")
                elif "Teil 3" in teil:
                    return (
"""You are Herr Felix, a Goethe A2 examiner. 
Work together to plan an activity (e.g., an outing). Alternate suggestions with the student. Give feedback and language support in English.
""")
                return ""
            elif level == "B1":
                if "Teil 1" in teil:
                    return (
"""You are Herr Felix, a B1 examiner. 
Guide the student to plan something (e.g. a trip) with you, ask for details, and help correct and improve their answers. 
Use English for explanations and German for the conversation.
""")
                elif "Teil 2" in teil:
                    return (
"""You are Herr Felix, a B1 examiner. 
Let the student present a topic for 2-3 minutes. Afterward, ask 1-2 detailed follow-up questions and give feedback in English.
""")
                elif "Teil 3" in teil:
                    return (
"""You are Herr Felix, a B1 examiner. 
Ask the student questions about their presentation and give constructive feedback. English for feedback, German for model questions.
""")
                return ""
            elif level == "B2":
                if "Teil 1" in teil:
                    return (
"""You are Herr Felix, a B2 examiner. 
Engage the student in a debate or discussion. Ask for opinions and justifications. Correct in English, reply in German.
""")
                elif "Teil 2" in teil:
                    return (
"""You are Herr Felix, a B2 examiner. 
Have the student present a complex topic. Ask challenging questions and give advanced corrections. Feedback in English, conversation in German.
""")
                elif "Teil 3" in teil:
                    return (
"""You are Herr Felix, a B2 examiner. 
Engage in argumentation with the student. Provide counterpoints and feedback in English.
""")
                return ""
            elif level == "C1":
                # All-German exam instructions for C1
                if "Teil 1" in teil:
                    return (
"""Du bist Herr Felix, ein C1-Prüfer. 
Bitte leite eine Prüfung auf hohem Sprachniveau, gib Fragen, fordere zur Reflexion auf, und gib Korrekturen und Feedback nur auf Deutsch.
""")
                elif "Teil 2" in teil:
                    return (
"""Du bist Herr Felix, ein C1-Prüfer. 
Führe eine formelle Diskussion mit kritischen Nachfragen auf Deutsch. 
""")
                elif "Teil 3" in teil:
                    return (
"""Du bist Herr Felix, ein C1-Prüfer. 
Bitte leite die Bewertungsphase, stelle Fragen zur Selbstreflexion, und gib Hinweise auf Deutsch.
""")
                return ""
            return ""

        def build_custom_chat_prompt(level):
            # 50/50 English instructions, German support up to B2. C1 in German only.
            if level in ["A1", "A2", "B1", "B2"]:
                return (
                    "You are Herr Felix, a supportive German teacher. "
                    "When the student gives a topic or keyword, start with a greeting and simple suggestions in English about what to say. "
                    "Give examples in German, ask a simple question in German, and always give feedback in English after each reply. "
                    "Correct mistakes, show the right answer, and ask a next question about the same topic. "
                    "Keep instructions 50% English, 50% German for levels A1–B2. Use only German for C1."
                )
            elif level == "C1":
                return (
                    "Du bist Herr Felix, ein C1-Dozent. Sprich nur auf Deutsch, fordere den Studenten mit komplexen Fragen heraus, und gib präzises, fortgeschrittenes Feedback."
                )

        # === Show initial instruction if chat is empty ===
        if not st.session_state["falowen_messages"]:
            if is_exam:
                system_prompt = build_exam_prompt(level, teil)
                first_instruction = build_exam_instruction(level, teil)
            elif is_custom_chat:
                system_prompt = build_custom_chat_prompt(level)
                first_instruction = (
                    f"Hallo! 👋 What would you like to talk about? Give me details of what you want so I can understand. "
                    f"You can enter a topic, a question, or a keyword. I'll help you prepare for your class presentation."
                )
            else:
                system_prompt = ""
                first_instruction = ""
            st.session_state["falowen_messages"].append({"role": "assistant", "content": first_instruction})

        # === User input box (only if session not ended) ===
        user_input = st.chat_input("💬 Type your answer here...", key="falowen_input")
        if user_input:
            st.session_state["falowen_messages"].append({"role": "user", "content": user_input})
            st.session_state["falowen_turn_count"] += 1

            # --- AI System Prompt logic for current mode and level ---
            if is_exam:
                system_prompt = build_exam_prompt(level, teil)
            elif is_custom_chat:
                system_prompt = build_custom_chat_prompt(level)
            else:
                system_prompt = ""

            # --- Build conversation for OpenAI API ---
            conversation = [{"role": "system", "content": system_prompt}]
            for m in st.session_state["falowen_messages"]:
                if m["role"] == "user":
                    conversation.append({"role": "user", "content": m["content"]})
                else:
                    conversation.append({"role": "assistant", "content": m["content"]})

            with st.spinner("🧑‍🏫 Herr Felix is typing..."):
                try:
                    resp = client.chat.completions.create(
                        model="gpt-4o", messages=conversation
                    )
                    ai_reply = resp.choices[0].message.content
                except Exception as e:
                    ai_reply = f"Sorry, there was a problem: {str(e)}"
                    st.error(str(e))

            st.session_state["falowen_messages"].append({"role": "assistant", "content": ai_reply})
            st.rerun()


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
from fpdf import FPDF

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

