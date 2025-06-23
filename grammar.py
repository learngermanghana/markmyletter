# ====================================
# STAGE 1 – IMPORTS, SETUP, DATABASE, SAVE FUNCTIONS
# ====================================

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
from streamlit_cookies_manager import EncryptedCookieManager

# ---- OpenAI Client Setup ----
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("Missing OpenAI API key. Please set OPENAI_API_KEY as an environment variable or in Streamlit secrets.")
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
            topic TEXT,
            messages TEXT,
            score INTEGER,
            feedback TEXT,
            date TEXT
        )
    """)
    conn.commit()

init_db()

# --- SAVE FUNCTIONS ---

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

def save_sprechen_session(student_code, name, level, teil, topic, messages, score, feedback):
    """messages should be saved as a str, e.g. via json.dumps(list_of_dicts)"""
    import json
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO sprechen_progress (student_code, name, level, teil, topic, messages, score, feedback, date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (student_code, name, level, teil, topic, json.dumps(messages), score, feedback, str(date.today()))
    )
    conn.commit()

def get_sprechen_attempted_topics(student_code, level, teil):
    """
    Returns a set of topic names the student has ALREADY practiced for a given level & teil (exam part).
    Use this to avoid giving the same topic again!
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT topic FROM sprechen_progress WHERE student_code=? AND level=? AND teil=?",
        (student_code, level, teil)
    )
    rows = c.fetchall()
    return set(r[0] for r in rows if r[0])

# ====================================

# ====================================
# STAGE 2 – FLEXIBLE CHECKERS & PROGRESS HELPERS
# ====================================

# --- Flexible answer checkers ---
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

# --- Streaks and stats helpers ---

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

# --- Usage limiters (daily message count for Falowen chat etc) ---
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
    FALOWEN_DAILY_LIMIT = 20  # Move this to your constants stage!
    return get_falowen_usage(student_code) < FALOWEN_DAILY_LIMIT

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
    student_code = st.session_state.get("student_code", "")

    st.header("Choose Practice Mode")
    tab = st.radio(
        "How do you want to practice?",
        ["Dashboard", "Exams Mode & Custom Chat", "Vocab Trainer", "Schreiben Trainer", "Admin"],
        key="main_tab_select"
    )

    # --- DASHBOARD TAB, MOBILE-FRIENDLY ---
    if tab == "Dashboard":
        st.header("📊 Student Dashboard")

        student_row = st.session_state.get("student_row") or {}
        streak = get_vocab_streak(student_code)
        total_attempted, total_passed, accuracy = get_writing_stats(student_code)

        # --- Student name and essentials ---
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
            f"**🏅 Pass rate:** {accuracy}%"
        )

        st.divider()
        # --- Upcoming Goethe Exams, Prices & Registration Info ---
        st.markdown("#### 📝 Upcoming Goethe Exam Dates, Prices, and Registration Info")

        goethe_exam_data = [
            {"Level": "A1", "Date": "2024-07-12", "Registration Deadline": "2024-06-30", "Price (GHS)": "1,100"},
            {"Level": "A2", "Date": "2024-07-19", "Registration Deadline": "2024-07-07", "Price (GHS)": "1,250"},
            {"Level": "B1", "Date": "2024-08-16", "Registration Deadline": "2024-08-01", "Price (GHS)": "1,300"},
            {"Level": "B2", "Date": "2024-09-20", "Registration Deadline": "2024-09-07", "Price (GHS)": "1,400"},
            # Add more dates as needed
        ]
        df_exams = pd.DataFrame(goethe_exam_data)
        st.table(df_exams)

        st.markdown("""
        **How to register for the Goethe exam:**

        1. Visit [this website](https://www.goethe.de/ins/gh/en/spr/prf/anm.html) and click "register".
        2. Fill in your information and select your exam level. Choose **extern** if you are not a Goethe student.
        3. After registration, you will receive a confirmation email.
        4. Make payment via Mobile Money or Bank Account. Bank details:

           - **ECOBANK GHANA**
           - **Account Name:** GOETHE-INSTITUT GHANA
           - **Account Number:** 1441 001 701 903
           - **Branch:** RING ROAD CENTRAL
           - **SWIFT CODE:** ECOCGHAC

        5. Send your payment slip by email to [registrations-accra@goethe.de](mailto:registrations-accra@goethe.de).
        6. Wait for the reply (it usually takes 3 days). Follow up if no reply is received.

        **Remember:** Bring your passport or a valid national ID on exam day. If you need help, talk to your tutor or contact the school office.
        """)
# ====================================
# STAGE 3 – EXAM MODE, CUSTOM CHAT, PDF HELPERS
# ====================================

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
        safe_msg = safe_latin1(m['content'])
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
    # Add similar logic for other levels (A2, B1, B2, C1) following the pattern above

def build_exam_system_prompt(level, teil):
    if level == "A1":
        if "Teil 1" in teil:
            return (
                "You are Herr Felix, a supportive A1 German examiner. "
                "Ask the student to introduce themselves using the keywords (Name, Land, Wohnort, Sprachen, Beruf, Hobby). "
                "Check if all info is given, correct any errors (explain in English), and give the right way to say things in German. "
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
    # Add similar logic for other levels (A2, B1, B2, C1) following the pattern above

def build_custom_chat_prompt(level):
    if level == "C1":
        return (
            "Du bist Herr Felix, ein C1-Prüfer. Sprich nur Deutsch. "
            "Gib konstruktives Feedback, stelle schwierige Fragen, und hilf dem Studenten, auf C1-Niveau zu sprechen."
        )
    # Adjust for other levels accordingly

# ====================================
# STAGE 4 – FALOWEN CHAT FLOW, MESSAGES & SESSION MANAGEMENT
# ====================================

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
        st.session_state["falowen_stage"] = 3 if st.session_state["falowen_mode"] == "Geführte Prüfungssimulation (Exam Mode)" else 4
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
    teil = st.radio("Which exam part?", teil_options[st.session_state["falowen_level"]], key="falowen_teil_center")

    # Optional: topic picker (for Teil 2/3, not A1)
    picked_topic = None
    if st.session_state["falowen_level"] != "A1" and exam_topics:
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
    st.stop()

# ====================================
# STAGE 4 – FALOWEN MAIN CHAT
# ====================================

# ---- STAGE 4: MAIN CHAT ----
if st.session_state["falowen_stage"] == 4:
    level = st.session_state["falowen_level"]
    teil = st.session_state.get("falowen_teil", "")
    mode = st.session_state.get("falowen_mode", "")
    is_exam = mode == "Geführte Prüfungssimulation (Exam Mode)"
    is_custom_chat = mode == "Eigenes Thema/Frage (Custom Chat)"

    # ---- Show daily usage ----
    used_today = get_falowen_usage(student_code)
    st.info(f"Today: {used_today} / {FALOWEN_DAILY_LIMIT} Falowen chat messages used.")
    if used_today >= FALOWEN_DAILY_LIMIT:
        st.warning("You have reached your daily practice limit for Falowen today. Please come back tomorrow.")
        st.stop()

    # -- Controls: reset, back, change level
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

    def change_level():
        st.session_state["falowen_stage"] = 2
        st.session_state["falowen_messages"] = []
        st.rerun()

    # ---- Show chat history ----
    for msg in st.session_state["falowen_messages"]:
        if msg["role"] == "assistant":
            with st.chat_message("assistant", avatar="🧑‍🏫"):
                st.markdown("<span style='color:#33691e;font-weight:bold'>🧑‍🏫 Herr Felix:</span>", unsafe_allow_html=True)
                st.markdown(msg["content"])
        else:
            with st.chat_message("user"):
                st.markdown(f"🗣️ {msg['content']}")

    # ---- PDF Download Button ----
    if st.session_state["falowen_messages"]:
        pdf_bytes = falowen_download_pdf(st.session_state["falowen_messages"], f"Falowen_Chat_{level}_{teil.replace(' ', '_') if teil else 'chat'}")
        st.download_button("⬇️ Download Chat as PDF", pdf_bytes, file_name=f"Falowen_Chat_{level}_{teil.replace(' ', '_') if teil else 'chat'}.pdf", mime="application/pdf")

    # ---- Session Controls
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

    # ---- Initial instruction (only if chat is empty) ----
    if not st.session_state["falowen_messages"]:
        instruction = ""
        if is_exam:
            instruction = build_exam_instruction(level, teil)
        elif is_custom_chat:
            instruction = (
                "Hallo! 👋 What would you like to talk about? Give me details of what you want so I can understand. "
                "You can enter a topic, a question, or a keyword. I'll help you prepare for your class presentation."
            )
        if instruction:
            st.session_state["falowen_messages"].append({"role": "assistant", "content": instruction})

    # ---- Chat Input Box & OpenAI Response ----
    user_input = st.chat_input("Type your answer or message here...", key="falowen_user_input")

    if user_input:
        st.session_state["falowen_messages"].append({"role": "user", "content": user_input})
        inc_falowen_usage(student_code)  # increment daily usage

        # Spinner and OpenAI call
        with st.chat_message("assistant", avatar="🧑‍🏫"):
            st.markdown("<span style='color:#33691e;font-weight:bold'>🧑‍🏫 Herr Felix:</span>", unsafe_allow_html=True)
            with st.spinner("🧑‍🏫 Herr Felix is typing..."):
                # System prompt logic
                if is_exam:
                    system_prompt = build_exam_system_prompt(level, teil)
                else:
                    system_prompt = build_custom_chat_prompt(level)

                # Compose full history for OpenAI
                messages = [{"role": "system", "content": system_prompt}]
                messages += [{"role": m["role"], "content": m["content"]} for m in st.session_state["falowen_messages"]]

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

                st.markdown("<span style='color:#33691e;font-weight:bold'>🧑‍🏫 Herr Felix:</span>", unsafe_allow_html=True)
                st.markdown(ai_reply)

        # Save AI reply to session for next turn
        st.session_state["falowen_messages"].append({"role": "assistant", "content": ai_reply})
# ====================================
# STAGE 4 – VOCABULARY PROGRESS & PREVENT REPETITION
# ====================================

# ---- Daily Limit Check for Vocabulary ----
if not has_falowen_quota(student_code):
    st.warning("You have reached your daily practice limit for Falowen today. Please come back tomorrow.")
    st.stop()

# ---- SESSION STATE DEFAULTS ----
default_state_vocab = {
    "falowen_vocab_stage": 1,
    "falowen_vocab_level": None,
    "falowen_vocab_progress": set(),
    "falowen_vocab_used_today": 0,
    "falowen_vocab_max": FALOWEN_DAILY_LIMIT,
}

for key, val in default_state_vocab.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ---- STAGE 1: Vocabulary Mode Selection ----
if st.session_state["falowen_vocab_stage"] == 1:
    st.subheader("Step 1: Choose Vocabulary Practice Mode")
    mode = st.radio(
        "How would you like to practice your vocabulary?",
        ["Random Practice", "Level-Specific Practice"],
        key="falowen_vocab_mode_center"
    )

    if st.button("Next ➡️", key="falowen_vocab_next_mode"):
        st.session_state["falowen_vocab_mode"] = mode
        st.session_state["falowen_vocab_stage"] = 2
        st.session_state["falowen_vocab_level"] = None
        st.session_state["falowen_vocab_progress"] = set()
        st.session_state["falowen_vocab_used_today"] = 0
        st.session_state["falowen_vocab_max"] = FALOWEN_DAILY_LIMIT
    st.stop()

# ---- STAGE 2: Vocabulary Level Selection ----
if st.session_state["falowen_vocab_stage"] == 2:
    st.subheader("Step 2: Choose Your Vocabulary Level")
    vocab_level = st.radio(
        "Select your vocabulary level:",
        ["A1", "A2", "B1", "B2", "C1"],
        key="falowen_vocab_level_center"
    )
    if st.button("⬅️ Back", key="falowen_vocab_back1"):
        st.session_state["falowen_vocab_stage"] = 1
        st.stop()
    if st.button("Next ➡️", key="falowen_vocab_next_level"):
        st.session_state["falowen_vocab_level"] = vocab_level
        st.session_state["falowen_vocab_stage"] = 3
        st.session_state["falowen_vocab_used_today"] = 0
        st.session_state["falowen_vocab_max"] = FALOWEN_DAILY_LIMIT
    st.stop()

# ---- STAGE 3: Vocabulary Practice ----
if st.session_state["falowen_vocab_stage"] == 3:
    vocab_level = st.session_state["falowen_vocab_level"]
    vocab_list = VOCAB_LISTS.get(vocab_level, [])
    completed_words = st.session_state["falowen_vocab_progress"]

    # Prevent repetition of words
    new_words = [i for i in range(len(vocab_list)) if i not in completed_words]
    random.shuffle(new_words)

    # Visual progress bar for today's goal
    st.progress(
        min(st.session_state["falowen_vocab_used_today"], FALOWEN_DAILY_LIMIT) / FALOWEN_DAILY_LIMIT,
        text=f"{st.session_state['falowen_vocab_used_today']} / {FALOWEN_DAILY_LIMIT} words practiced today"
    )

    if st.session_state["falowen_vocab_used_today"] >= FALOWEN_DAILY_LIMIT:
        st.balloons()
        st.success("✅ Daily Goal Complete! You’ve finished your vocabulary goal for today.")
        st.stop()

    if new_words:
        idx = new_words[0]
        word = vocab_list[idx][0]
        correct_answer = vocab_list[idx][1] if isinstance(vocab_list[idx], tuple) else None

        st.markdown(f"🔤 **Translate this German word to English:** <b>{word}</b>", unsafe_allow_html=True)
        user_answer = st.text_input("Your English translation", key=f"vocab_answer_{idx}")

        if st.button("Check", key=f"vocab_check_{idx}"):
            is_correct = validate_translation_openai(word, user_answer)

            if is_correct:
                st.success("✅ Correct!")
                completed_words.add(idx)
                st.session_state["falowen_vocab_used_today"] += 1
            else:
                st.warning(f"❌ Incorrect. The correct answer is: <b>{correct_answer}</b>", unsafe_allow_html=True)

            # Save progress
            st.session_state["falowen_vocab_progress"] = completed_words

            # Check if user reached the daily limit and display success message
            if st.session_state["falowen_vocab_used_today"] >= FALOWEN_DAILY_LIMIT:
                st.balloons()
                st.success("✅ Daily Vocabulary Goal Achieved!")
                st.stop()

    else:
        st.success("🎉 You've finished all new words for this level today!")

# ---- Vocabulary Progress Tracking ----
def get_vocab_streak(student_code):
    # Placeholder for actual streak calculation, example returns 5-day streak
    return 5

def get_falowen_usage(student_code):
    # Placeholder for tracking daily usage
    return st.session_state.get("falowen_vocab_used_today", 0)

# ---- Vocabulary Completion Tracking ----
def save_vocab_submission(student_code, name, level, word, student_answer, is_correct):
    # This function will save the student's progress for later analysis
    pass
# ====================================
# STAGE 4 CONTINUED – VOCABULARY AND SESSION UPDATES
# ====================================

# ---- Session Update After Each Vocabulary Interaction ----
def update_vocab_session(student_code, level, word, user_answer, is_correct):
    vocab_usage_key = f"{student_code}_vocab_{str(date.today())}"
    if "vocab_usage" not in st.session_state:
        st.session_state["vocab_usage"] = {}

    st.session_state["vocab_usage"].setdefault(vocab_usage_key, 0)
    st.session_state["vocab_usage"][vocab_usage_key] += 1

    save_vocab_submission(student_code, student_name, level, word, user_answer, is_correct)
    st.rerun()

# ---- Saving to Database ----
def save_vocab_submission(student_code, name, level, word, student_answer, is_correct):
    # Example function to log submission to a database or an external file
    pass

# ---- Vocabulary Daily Limit Update ----
def update_vocab_progress(student_code):
    used_today = get_falowen_usage(student_code)
    if used_today >= FALOWEN_DAILY_LIMIT:
        st.warning("You have reached your daily vocabulary practice limit. Please come back tomorrow.")
        st.stop()

    # Increment counter and save progress to session
    st.session_state["falowen_vocab_used_today"] += 1
    st.session_state["falowen_vocab_progress"].add(st.session_state.get("vocab_current_word_index", -1))

# ====================================
# STAGE 5 – VOCABULARY SESSION END, PDF, AND EXPORT
# ====================================

# ---- Vocabulary PDF Download ----
def falowen_download_vocab_pdf(student_code):
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    used_today = get_falowen_usage(student_code)
    total_words = len(st.session_state["falowen_vocab_progress"])

    # Add vocabulary completion progress to PDF
    pdf.multi_cell(0, 10, f"Today's Vocabulary Practice Summary:\n")
    pdf.multi_cell(0, 10, f"Total words completed: {total_words}/{FALOWEN_DAILY_LIMIT}")
    pdf_output = f"Falowen_Vocab_Summary_{student_code}.pdf"
    pdf.output(pdf_output)

    with open(pdf_output, "rb") as f:
        pdf_bytes = f.read()
    os.remove(pdf_output)
    return pdf_bytes

# ---- Vocabulary PDF Export Button ----
if st.session_state["falowen_vocab_used_today"] >= FALOWEN_DAILY_LIMIT:
    pdf_bytes = falowen_download_vocab_pdf(student_code)
    st.download_button("⬇️ Download Your Vocabulary Progress", pdf_bytes, file_name=f"Falowen_Vocab_{student_code}.pdf", mime="application/pdf")


