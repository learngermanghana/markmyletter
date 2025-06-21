# 1. IMPORTS, CONSTANTS, AND PAGE SETUP
import os
import random
import difflib
import sqlite3
import atexit
from datetime import date
import pandas as pd
import streamlit as st
from openai import OpenAI    # <--- Here

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])   

# ---- Paste the DB connection helper here ----

def get_connection():
    if "conn" not in st.session_state:
        st.session_state["conn"] = sqlite3.connect("vocab_progress.db", check_same_thread=False)
        atexit.register(st.session_state["conn"].close)
    return st.session_state["conn"]

conn = get_connection()
c = conn.cursor()

def get_student_stats(student_code):
    # Placeholder/example structure—replace with your real logic!
    return {
        "A1": {"correct": 7, "attempted": 10},
        "A2": {"correct": 5, "attempted": 10}
    }

def get_vocab_streak(student_code):
    # Placeholder: return a fake streak for now
    return 3

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
    path = globals().get("STUDENTS_CSV", "students.csv")
    if not os.path.exists(path):
        st.error("Students file not found!")
        return pd.DataFrame()
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    for col in ["StudentCode", "Email"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.lower()
    return df

df_students = load_student_data()

# ====================================
# 3. STUDENT LOGIN LOGIC (single, clean block!)
# ====================================

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "student_row" not in st.session_state:
    st.session_state["student_row"] = None
if "student_code" not in st.session_state:
    st.session_state["student_code"] = ""
if "student_name" not in st.session_state:
    st.session_state["student_name"] = ""

if not st.session_state["logged_in"]:
    st.title("🔑 Student Login")
    login_input = st.text_input("Enter your Student Code or Email to begin:").strip().lower()
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
    # Always fetch from session_state and define as a local variable
    student_code = st.session_state.get("student_code", "")

    st.header("Choose Practice Mode")
    tab = st.radio(
        "How do you want to practice?",
        ["Dashboard", "Falowen Chat", "Vocab Trainer", "Schreiben Trainer"],
        key="main_tab_select"
    )
    st.markdown(
        f"<div style='background:#e0f2ff;border-radius:12px;padding:12px 18px;margin-bottom:12px;font-size:1.2rem;'>"
        f"🔹 <b>Active:</b> {tab}</div>",
        unsafe_allow_html=True
    )

    if tab == "Dashboard":
        st.header("📊 Student Dashboard")

        # --- Student Info Card (contract etc) ---
        student_row = st.session_state.get("student_row") or {}
        st.markdown(f"""
        <div style='background:#f9f9ff;padding:18px 24px;border-radius:15px;margin-bottom:18px;box-shadow:0 2px 10px #eef;'>
            <h3 style='margin:0;color:#17617a;'>{student_row.get('Name', '')}</h3>
            <ul style='list-style:none;padding:0;font-size:1.08rem;'>
                <li><b>Level:</b> {student_row.get('Level', '')}</li>
                <li><b>Student Code:</b> {student_row.get('StudentCode', '')}</li>
                <li><b>Email:</b> {student_row.get('Email', '')}</li>
                <li><b>Phone:</b> {student_row.get('Phone', '')}</li>
                <li><b>Location:</b> {student_row.get('Location', '')}</li>
                <li><b>Paid:</b> {student_row.get('Paid', '')}</li>
                <li><b>Balance:</b> {student_row.get('Balance', '')}</li>
                <li><b>Contract Start:</b> {student_row.get('ContractStart', '')}</li>
                <li><b>Contract End:</b> {student_row.get('ContractEnd', '')}</li>
                <li><b>Status:</b> {student_row.get('Status', '')}</li>
                <li><b>Enroll Date:</b> {student_row.get('EnrollDate', '')}</li>
                <li><b>Emergency Contact:</b> {student_row.get('Emergency Contact (Phone Number)', '')}</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)

        # --- Show main stats ---
        stats = get_student_stats(student_code)
        streak = get_vocab_streak(student_code)
        st.info(f"🔥 **Vocab Streak:** {streak} days")
        if stats:
            st.markdown("**Today's Vocab Progress:**")
            for lvl, d in stats.items():
                st.markdown(
                    f"- `{lvl}`: {d['correct'] or 0} / {d['attempted']} correct"
                )
        else:
            st.markdown("_No vocab activity today yet!_")

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
                        client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
                        resp = client.chat.completions.create(model="gpt-4o", messages=conversation)
                        ai_reply = resp.choices[0].message.content
                    except Exception as e:
                        ai_reply = f"Sorry, there was a problem: {str(e)}"
                        st.error(str(e))

                st.session_state["falowen_messages"].append({"role": "assistant", "content": ai_reply})
                st.rerun()  # To refresh the chat UI after reply

# =========================================
# VOCAB TRAINER TAB (A1–C1, with Progress)
# =========================================

if tab == "Vocab Trainer":
    st.header("🧠 Vocab Trainer")

    vocab_usage_key = f"{st.session_state['student_code']}_vocab_{str(date.today())}"
    if "vocab_usage" not in st.session_state:
        st.session_state["vocab_usage"] = {}
    st.session_state["vocab_usage"].setdefault(vocab_usage_key, 0)
    if "vocab_level" not in st.session_state:
        st.session_state["vocab_level"] = "A1"
    if "vocab_idx" not in st.session_state:
        st.session_state["vocab_idx"] = 0
    if "vocab_feedback" not in st.session_state:
        st.session_state["vocab_feedback"] = ""
    if "show_next_button" not in st.session_state:
        st.session_state["show_next_button"] = False

    # --- Level select ---
    vocab_level = st.selectbox("Choose level", ["A1", "A2", "B1", "B2", "C1"], key="vocab_level_select")
    if vocab_level != st.session_state["vocab_level"]:
        st.session_state["vocab_level"] = vocab_level
        st.session_state["vocab_idx"] = 0
        st.session_state["vocab_feedback"] = ""
        st.session_state["show_next_button"] = False

    vocab_list = VOCAB_LISTS.get(st.session_state["vocab_level"], [])
    # If list is (word, english) tuples
    is_tuple = isinstance(vocab_list[0], tuple) if vocab_list else False

    st.info(
        f"Today's vocab attempts: {st.session_state['vocab_usage'][vocab_usage_key]}/{VOCAB_DAILY_LIMIT}"
    )

    if st.session_state["vocab_usage"][vocab_usage_key] >= VOCAB_DAILY_LIMIT:
        st.warning("You've reached your daily vocab limit. Come back tomorrow!")
    elif vocab_list:
        idx = st.session_state["vocab_idx"] % len(vocab_list)
        word = vocab_list[idx][0] if is_tuple else vocab_list[idx]
        correct_answer = vocab_list[idx][1] if is_tuple else None

        st.markdown(f"🔤 **Translate this German word to English:** <b>{word}</b>", unsafe_allow_html=True)

        if not st.session_state["show_next_button"]:
            user_answer = st.text_input("Your English translation", key=f"vocab_answer_{idx}")
            if st.button("Check", key=f"vocab_check_{idx}"):
                if is_tuple:
                    if is_close_answer(user_answer, correct_answer):
                        st.session_state["vocab_feedback"] = f"✅ Correct!"
                    elif is_almost(user_answer, correct_answer):
                        st.session_state["vocab_feedback"] = f"🟡 Almost! The correct answer is: <b>{correct_answer}</b>"
                    else:
                        st.session_state["vocab_feedback"] = f"❌ Not quite. The correct answer is: <b>{correct_answer}</b>"
                    # Optional: show example
                    example = ""
                    if word == "der Fahrplan":
                        example = "Example: Der Fahrplan zeigt die Abfahrtszeiten."
                    if example:
                        st.session_state["vocab_feedback"] += "<br><i>" + example + "</i>"
                else:
                    # B1/B2/C1 just check word exists (could show explanation if you want)
                    if user_answer.strip():
                        st.session_state["vocab_feedback"] = "✅ Good, next!"
                    else:
                        st.session_state["vocab_feedback"] = "❌ Try to type something."

                st.session_state["vocab_usage"][vocab_usage_key] += 1
                st.session_state["show_next_button"] = True

        if st.session_state["vocab_feedback"]:
            st.markdown(st.session_state["vocab_feedback"], unsafe_allow_html=True)

        if st.session_state["show_next_button"]:
            if st.button("Next ➡️"):
                st.session_state["vocab_idx"] += 1
                st.session_state["vocab_feedback"] = ""
                st.session_state["show_next_button"] = False

# ====================================
# SCHREIBEN TRAINER TAB (with Level, Stats, and AI Feedback)
# ====================================

from fpdf import FPDF
import urllib.parse

if tab == "Schreiben Trainer":
    st.header("✍️ Schreiben Trainer (Writing Practice)")

    # --- Level Selection ---
    schreiben_levels = ["A1", "A2", "B1", "B2"]
    prev_schreiben_level = st.session_state.get("schreiben_level", "A1")
    st.selectbox(
        "Choose your writing level:",
        schreiben_levels,
        index=schreiben_levels.index(prev_schreiben_level) if prev_schreiben_level in schreiben_levels else 0,
        key="schreiben_level"
    )
    schreiben_level = st.session_state["schreiben_level"]

    # --- Overall Performance Summary ---
    stats = get_student_stats(student_code)
    all_attempted = sum(v.get("attempted", 0) for v in stats.values()) if stats else 0
    all_correct = sum(v.get("correct", 0) for v in stats.values()) if stats else 0
    st.subheader("📊 Your Overall Writing Performance")
    st.markdown(f"**Total Attempts:** {all_attempted} &nbsp; | &nbsp; **Total Correct:** {all_correct}")

    # --- Level-specific stats: strengths/weaknesses (example) ---
    lvl_stats = stats.get(schreiben_level, {}) if stats else {}
    if lvl_stats:
        correct = lvl_stats.get("correct", 0)
        attempted = lvl_stats.get("attempted", 0)
        strong = lvl_stats.get("strengths", [])
        weak = lvl_stats.get("weaknesses", [])
        st.success(f"Level `{schreiben_level}`: {correct} / {attempted} correct")
        if strong:
            st.markdown(f"**Your strengths:** {', '.join(strong)}")
        if weak:
            st.markdown(f"**Areas to improve:** {', '.join(weak)}")
    else:
        st.markdown("_No previous writing activity for this level yet._")

    st.divider()

    # --- AI Schreiben Section ---
    st.subheader("Submit your letter or essay for feedback:")
    student_text = st.text_area(
        "Paste your German letter or essay here...",
        height=200,
        key="schreiben_input"
    )
    feedback = None
    if st.button("Get Feedback", key="get_feedback"):
        if not student_text.strip():
            st.error("Please paste your German text first!")
        else:
            with st.spinner("Herr Felix is marking your letter..."):
                ai_prompt = (
                    f"You are Herr Felix, a supportive but strict Goethe examiner. "
                    f"The student has submitted a {schreiben_level} German letter or essay. "
                    "Write a brief comment in English about what the student did well and what they should improve whiles highlighting their points so they understand. Check if the letter matces their level "
                    " Talk as Herr Felix talking to a student andhHighlight the phrases with errors so they see it. Dont just say errors and not letting them know where the exact mistake is. "
                    "1. Give a score out of 25 marks and confirm If score is above 17, say they have passed and can submit to tutor.Else If below, tell them to improve before submitting to tutor in a nice way and not discouraging."
                    "2. Always explain why you gave the student that score based on grammar,spellings, vocabulary,coherance and so on. Also check A.I usage or if students wrote with their effort . " 
                    "3. List and show them the phrases to improve on with tips,suggestions and what they should do. Let student use your suggestions to correct the letter but not the full corrected letter. "
                    " Give scores by analyzing grammar, structure, vocabulary and so on. Explain to the students why you gave them that score "                                
                )
                client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    temperature=0.6,
                    messages=[
                        {"role": "system", "content": ai_prompt},
                        {"role": "user", "content": student_text},
                    ],
                )
                feedback = response.choices[0].message.content
                st.session_state["schreiben_feedback"] = feedback
                st.success("Feedback ready! See below 👇")

    # --- Show Feedback, PDF Download, WhatsApp Sharing ---
    if "schreiben_feedback" in st.session_state and st.session_state["schreiben_feedback"]:
        feedback = st.session_state["schreiben_feedback"]
        st.markdown("### 📝 Feedback from Herr Felix")
        st.markdown(feedback)

        # PDF Download
        if st.button("Download Feedback as PDF", key="download_pdf"):
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            pdf.multi_cell(0, 10, f"Your Writing\n\n{student_text}\n\n---\n\nFeedback\n\n{feedback}")
            pdf_path = f"/tmp/{student_code}_schreiben_feedback.pdf"
            pdf.output(pdf_path)
            with open(pdf_path, "rb") as f:
                st.download_button(
                    label="Download PDF",
                    data=f,
                    file_name=f"{student_code}_Schreiben_Feedback.pdf",
                    mime="application/pdf"
                )

        # WhatsApp Share
        assignment_message = (
            f"Hi, please find my writing submission and feedback:\n\n"
            f"Writing:\n{student_text}\n\nFeedback:\n{feedback}"
        )
        whatsapp_url = (
            "https://api.whatsapp.com/send"
            "?phone=233205706589"
            f"&text={urllib.parse.quote(assignment_message)}"
        )
        st.markdown(
            f"[Share to WhatsApp]( {whatsapp_url} )",
            unsafe_allow_html=True
        )
