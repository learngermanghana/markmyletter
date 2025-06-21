# ====================================
# 1. IMPORTS, CONSTANTS, UTILITIES, DATA LISTS
# ====================================
import os
import random
import difflib
import sqlite3
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st
from openai import OpenAI
from fpdf import FPDF

# --- App and file constants ---
STUDENTS_CSV          = "students.csv"
VOCAB_DB              = "vocab_progress.db"
CODES_FILE            = "student_codes.csv"
FALOWEN_DAILY_LIMIT   = 25
VOCAB_DAILY_LIMIT     = 20
SCHREIBEN_DAILY_LIMIT = 5
MAX_TURNS             = 25

# ====================================
# DATA LISTS: VOCAB & EXAM TOPICS
# ====================================

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
b1_vocab = [
    "Fortschritt", "Eindruck", "Unterschied", "Vorschlag", "Erfahrung", "Ansicht", "Abschluss", "Entscheidung"
]
b2_vocab = [
    "Umwelt", "Entwicklung", "Auswirkung", "Verhalten", "Verhältnis", "Struktur", "Einfluss", "Kritik"
]
c1_vocab = [
    "Ausdruck", "Beziehung", "Erkenntnis", "Verfügbarkeit", "Bereich", "Perspektive", "Relevanz", "Effizienz"
]
VOCAB_LISTS = {
    "A1": a1_vocab,
    "A2": a2_vocab,
    "B1": b1_vocab,
    "B2": b2_vocab,
    "C1": c1_vocab
}

# Exam topic lists (A1–C1, Teil 1–3)
A1_TEIL1 = [
    "Name", "Alter", "Wohnort", "Land", "Sprache", "Familie", "Beruf", "Hobby"
]
A1_TEIL2 = [
    ("Geschäft", "schließen"), ("Uhr", "Uhrzeit"), ("Arbeit", "Kollege"),
    ("Hausaufgabe", "machen"), ("Küche", "kochen"), ("Freizeit", "lesen"),
    ("Telefon", "anrufen"), ("Reise", "Hotel"), ("Auto", "fahren"),
    ("Einkaufen", "Obst"), ("Schule", "Lehrer"), ("Geburtstag", "Geschenk"),
    ("Essen", "Frühstück"), ("Arzt", "Termin"), ("Zug", "Abfahrt"),
    ("Wetter", "Regen"), ("Buch", "lesen"), ("Computer", "E-Mail"),
    ("Kind", "spielen"), ("Wochenende", "Plan"), ("Bank", "Geld"),
    ("Sport", "laufen"), ("Abend", "Fernsehen"), ("Freunde", "Besuch"),
    ("Bahn", "Fahrkarte"), ("Straße", "Stau"), ("Essen gehen", "Restaurant"),
    ("Hund", "Futter"), ("Familie", "Kinder"), ("Post", "Brief"),
    ("Nachbarn", "laut"), ("Kleid", "kaufen"), ("Büro", "Chef"),
    ("Urlaub", "Strand"), ("Kino", "Film"), ("Internet", "Seite"),
    ("Bus", "Abfahrt"), ("Arztpraxis", "Wartezeit"), ("Kuchen", "backen"),
    ("Park", "spazieren"), ("Bäckerei", "Brötchen"), ("Geldautomat", "Karte"),
    ("Buchladen", "Roman"), ("Fernseher", "Programm"), ("Tasche", "vergessen"),
    ("Stadtplan", "finden"), ("Ticket", "bezahlen"), ("Zahnarzt", "Schmerzen"),
    ("Museum", "Öffnungszeiten"), ("Handy", "Akku leer")
]
A1_TEIL3 = [
    "Radio anmachen", "Fenster zumachen", "Licht anschalten", "Tür aufmachen", "Tisch sauber machen",
    "Hausaufgaben schicken", "Buch bringen", "Handy ausmachen", "Stuhl nehmen", "Wasser holen",
    "Fenster öffnen", "Musik leiser machen", "Tafel sauber wischen", "Kaffee kochen", "Deutsch üben",
    "Auto waschen", "Kind abholen", "Tisch decken", "Termin machen", "Nachricht schreiben"
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
# 2. DATA LOADERS, DB HELPERS, UTILITIES
# ====================================

@st.cache_data
def load_student_data(path: str = STUDENTS_CSV) -> pd.DataFrame:
    """Load student CSV or show error and stop if missing."""
    if not os.path.exists(path):
        st.error(f"Students file not found at `{path}`.")
        st.stop()
    df = pd.read_csv(path)
    for col in ["StudentCode", "Email"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.lower().str.strip()
    return df

def init_vocab_db(path: str = VOCAB_DB):
    """Initialize vocab progress DB or show error."""
    try:
        conn = sqlite3.connect(path, check_same_thread=False)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS vocab_progress (
                student_code TEXT,
                date TEXT,
                level TEXT,
                word TEXT,
                correct INTEGER,
                PRIMARY KEY (student_code, date, level, word)
            )""")
        conn.commit()
        return conn, c
    except sqlite3.Error as e:
        st.error(f"Database error: {e}")
        st.stop()

def get_vocab_streak(c, student_code: str) -> int:
    """Get consecutive day streak for vocab practice."""
    try:
        c.execute("SELECT DISTINCT date FROM vocab_progress WHERE student_code=? ORDER BY date DESC", (student_code,))
        dates = [row[0] for row in c.fetchall()]
    except sqlite3.Error:
        return 0
    if not dates:
        return 0
    streak = 1
    prev = datetime.strptime(dates[0], "%Y-%m-%d")
    for d in dates[1:]:
        if datetime.strptime(d, "%Y-%m-%d") == prev - timedelta(days=1):
            streak += 1
            prev -= timedelta(days=1)
        else:
            break
    return streak

def is_close_answer(student: str, correct: str) -> bool:
    student, correct = student.strip().lower(), correct.strip().lower()
    if correct.startswith("to "): correct = correct[3:]
    if len(student) < 3 or len(student) < 0.6 * len(correct): return False
    return difflib.SequenceMatcher(None, student, correct).ratio() > 0.8

def is_almost(student: str, correct: str) -> bool:
    student, correct = student.strip().lower(), correct.strip().lower()
    if correct.startswith("to "): correct = correct[3:]
    r = difflib.SequenceMatcher(None, student, correct).ratio()
    return 0.6 < r <= 0.8

def generate_pdf(student: str, level: str, original: str, feedback: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=13)
    pdf.cell(0, 12, f"Schreiben Correction – {level}", ln=1)
    pdf.ln(2)
    pdf.multi_cell(0, 10, f"Dear {student},\n\nYour original text:\n{original}\n\nFeedback:\n{feedback}")
    return pdf.output(dest='S').encode('latin-1')

# ====================================
# 3. LOGIN SCREEN & DASHBOARD
# ====================================

def login_screen() -> bool:
    """Displays login; halts app on failure, returns True if logged in."""
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if not st.session_state.logged_in:
        st.title("🔑 Student Login")
        inp = st.text_input("Student Code or Email:").strip().lower()
        if st.button("Login"):
            df = load_student_data()
            match = df[(df.StudentCode == inp) | (df.Email == inp)]
            if not match.empty:
                info = match.iloc[0].to_dict()
                st.session_state.logged_in = True
                st.session_state.student_info = info
                st.session_state.student_name = info.get('Name', 'Student')
                st.session_state.student_code = info.get('StudentCode', '').lower()
                st.experimental_rerun()
            else:
                st.error("Login failed — code or email not recognized.")
        st.stop()
    return True

def show_dashboard(c):
    info = st.session_state.student_info
    code = st.session_state.student_code
    st.header(f"🎓 Welcome, {info.get('Name','')}!")
    streak = get_vocab_streak(c, code)
    st.markdown(f"🔥 **Vocab Streak:** {streak} days")
    # You can add more stats here!

# Usage in main() to follow in next stage

# ====================================
# 4. MAIN TABS & APP LOGIC
# ====================================

def falowen_chat_tab():
    st.header("🗣️ Falowen – Speaking & Exam Trainer")
    st.write("(Falowen chat interface will appear here)")

def vocab_trainer_tab():
    st.header("🧠 Vocab Trainer")
    st.write("(Vocabulary trainer interface will appear here)")

def schreiben_trainer_tab():
    st.header("✍️ Schreiben Trainer")
    st.write("(Writing trainer interface will appear here)")

def main():
    if not login_screen():
        return
    conn, c = init_vocab_db()

    tab = st.sidebar.radio(
        "Choose Mode",
        ["Dashboard", "Falowen Chat", "Vocab Trainer", "Schreiben Trainer"]
    )

    if tab == "Dashboard":
        show_dashboard(c)
    elif tab == "Falowen Chat":
        falowen_chat_tab()
    elif tab == "Vocab Trainer":
        vocab_trainer_tab()
    elif tab == "Schreiben Trainer":
        schreiben_trainer_tab()

if __name__ == "__main__":
    main()

def vocab_trainer_tab():
    st.header("🧠 Vocab Trainer")

    student_code = st.session_state.student_code
    today_str = str(date.today())
    vocab_usage_key = f"{student_code}_vocab_{today_str}"
    if "vocab_usage" not in st.session_state:
        st.session_state.vocab_usage = {}
    st.session_state.vocab_usage.setdefault(vocab_usage_key, 0)
    if "vocab_level" not in st.session_state:
        st.session_state.vocab_level = "A1"
    if "vocab_idx" not in st.session_state:
        st.session_state.vocab_idx = 0
    if "vocab_feedback" not in st.session_state:
        st.session_state.vocab_feedback = ""
    if "show_next_button" not in st.session_state:
        st.session_state.show_next_button = False

    # --- Level select ---
    vocab_level = st.selectbox("Choose level", ["A1", "A2", "B1", "B2", "C1"], key="vocab_level_select")
    if vocab_level != st.session_state.vocab_level:
        st.session_state.vocab_level = vocab_level
        st.session_state.vocab_idx = 0
        st.session_state.vocab_feedback = ""
        st.session_state.show_next_button = False

    vocab_list = VOCAB_LISTS.get(st.session_state.vocab_level, [])
    is_tuple = isinstance(vocab_list[0], tuple) if vocab_list else False

    st.info(
        f"Today's vocab attempts: {st.session_state.vocab_usage[vocab_usage_key]}/{VOCAB_DAILY_LIMIT}"
    )

    if st.session_state.vocab_usage[vocab_usage_key] >= VOCAB_DAILY_LIMIT:
        st.warning("You've reached your daily vocab limit. Come back tomorrow!")
    elif vocab_list:
        idx = st.session_state.vocab_idx % len(vocab_list)
        word = vocab_list[idx][0] if is_tuple else vocab_list[idx]
        correct_answer = vocab_list[idx][1] if is_tuple else None

        st.markdown(f"🔤 **Translate this German word to English:** <b>{word}</b>", unsafe_allow_html=True)

        if not st.session_state.show_next_button:
            user_answer = st.text_input("Your English translation", key=f"vocab_answer_{idx}")
            if st.button("Check", key=f"vocab_check_{idx}"):
                if is_tuple:
                    if is_close_answer(user_answer, correct_answer):
                        st.session_state.vocab_feedback = f"✅ Correct!"
                    elif is_almost(user_answer, correct_answer):
                        st.session_state.vocab_feedback = f"🟡 Almost! The correct answer is: <b>{correct_answer}</b>"
                    else:
                        st.session_state.vocab_feedback = f"❌ Not quite. The correct answer is: <b>{correct_answer}</b>"
                    # Optional: show example
                    example = ""
                    if word == "der Fahrplan":
                        example = "Example: Der Fahrplan zeigt die Abfahrtszeiten."
                    if example:
                        st.session_state.vocab_feedback += "<br><i>" + example + "</i>"
                else:
                    if user_answer.strip():
                        st.session_state.vocab_feedback = "✅ Good, next!"
                    else:
                        st.session_state.vocab_feedback = "❌ Try to type something."

                st.session_state.vocab_usage[vocab_usage_key] += 1
                st.session_state.show_next_button = True

        if st.session_state.vocab_feedback:
            st.markdown(st.session_state.vocab_feedback, unsafe_allow_html=True)

        if st.session_state.show_next_button:
            if st.button("Next ➡️"):
                st.session_state.vocab_idx += 1
                st.session_state.vocab_feedback = ""
                st.session_state.show_next_button = False
def schreiben_trainer_tab():
    """Schreiben Trainer interface with feedback, PDF export, WhatsApp link, and stats."""
    st.header("✍️ Schreiben Trainer")
    # Initialize usage counter
    student_code = st.session_state.student_code
    student_name = st.session_state.student_name
    today_str = str(date.today())
    usage_key = f"{student_code}_schreiben_{today_str}"
    if "schreiben_usage" not in st.session_state:
        st.session_state.schreiben_usage = {}
    st.session_state.schreiben_usage.setdefault(usage_key, 0)

    # Initialize or connect to writing feedback DB
    conn = sqlite3.connect(VOCAB_DB, check_same_thread=False)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS schreiben_feedback (
            student_code TEXT,
            date TEXT,
            level TEXT,
            score INTEGER,
            strengths TEXT,
            weaknesses TEXT
        )"""
    )
    conn.commit()

    # Show latest feedback stats
    with st.expander("📈 Your Writing Progress", expanded=True):
        c.execute(
            "SELECT date, level, score, strengths, weaknesses"
            " FROM schreiben_feedback WHERE student_code=?"
            " ORDER BY date DESC LIMIT 1",
            (student_code,),
        )
        row = c.fetchone()
        if row:
            st.markdown(
                f"**Last Attempt:** {row[0]}  \n"
                f"**Level:** {row[1]}  \n"
                f"**Score:** {row[2]} / 25  \n"
                f"**Strengths:** {row[3] or '–'}  \n"
                f"**Needs Improvement:** {row[4] or '–'}"
            )
        else:
            st.write("_No submissions yet. Your progress will appear here!_\n")

    st.info(
        f"Today's Schreiben submissions: {st.session_state.schreiben_usage[usage_key]}/{SCHREIBEN_DAILY_LIMIT}"
    )

    # Level selection
    schreiben_level = st.selectbox(
        "Select your level:",
        ["A1", "A2", "B1", "B2", "C1"],
        key="schreiben_level_select"
    )

    # Check usage limit
    if st.session_state.schreiben_usage[usage_key] >= SCHREIBEN_DAILY_LIMIT:
        st.warning("You've reached today's Schreiben submission limit. Please come back tomorrow!")
        return

    # Text input
    schreiben_text = st.text_area(
        "**Paste your letter or essay below.** Herr Felix will mark it as a real Goethe examiner and give you feedback.",
        height=250,
        key=f"schreiben_text_{schreiben_level}"
    )

    if st.button("Check My Writing"):
        if not schreiben_text.strip():
            st.warning("Please write something before submitting.")
        else:
            # Build the AI prompt
            ai_prompt = (
                f"You are Herr Felix, a strict but supportive Goethe examiner. "
                f"The student has submitted a {schreiben_level} German letter or essay. "
                "Talk as the tutor in English to explain mistakes. Use 'you' for the student to sound direct. "
                "Read the full text. Mark and correct grammar/spelling/structure mistakes, and provide a clear correction. "
                "Write a brief comment in English about what the student did well and what they should improve. "
                "Give a score out of 25 marks, with reasoning (grammar, spelling, vocab, structure). "
                "Show strengths, weaknesses, suggested phrases, vocabulary, conjunctions for next time. Also check if letter matches their level. "
                "If score is above 17, say they have passed and can submit to tutor. If below, tell them to improve."
            )
            ai_message = f"{ai_prompt}\n\nStudent's letter/essay:\n{schreiben_text}"

            with st.spinner("🧑‍🏫 Herr Felix is marking..."):
                try:
                    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
                    response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role": "system", "content": ai_message}]
                    )
                    ai_feedback = response.choices[0].message.content.strip()
                except Exception as e:
                    st.error(f"Error: {e}")
                    return

            # Display feedback
            st.success("📝 **Feedback from Herr Felix:**")
            st.markdown(ai_feedback)

            # PDF download
            pdf_bytes = generate_pdf(
                student=student_name,
                level=schreiben_level,
                original=schreiben_text,
                feedback=ai_feedback
            )
            st.download_button(
                label="⬇️ Download Feedback as PDF", 
                data=pdf_bytes,
                file_name=f"Schreiben_Feedback_{schreiben_level}_{date.today()}.pdf",
                mime="application/pdf"
            )

            # WhatsApp link
            assignment_msg = (
                f"Hallo Herr Felix! Hier ist mein Schreiben für die Korrektur ({schreiben_level}):\n\n"
                f"{schreiben_text}\n\n---\nFeedback: {ai_feedback[:600]}..."
            )
            whatsapp_url = (
                "https://api.whatsapp.com/send"
                f"?phone=233205706589&text={assignment_msg.replace(' ', '%20').replace('\\n', '%0A')}"
            )
            st.markdown(
                f'<a href="{whatsapp_url}" target="_blank" '
                'style="font-size:1.15rem;background:#1ad03f;padding:9px 18px;'
                'border-radius:10px;text-decoration:none;color:white;">'
                '📲 Send Assignment via WhatsApp</a>',
                unsafe_allow_html=True
            )

            # Save feedback to DB
            import re
            score = None
            m = re.search(r"Score[: ]*([0-9]+)", ai_feedback)
            if m:
                score = int(m.group(1))
            strengths = weaknesses = ""
            if "Strengths:" in ai_feedback:
                strengths = ai_feedback.split("Strengths:")[1].split("\n")[0].strip()
            if "Weaknesses:" in ai_feedback:
                weaknesses = ai_feedback.split("Weaknesses:")[1].split("\n")[0].strip()
            if score is not None:
                c.execute(
                    "INSERT INTO schreiben_feedback (student_code, date, level, score, strengths, weaknesses) VALUES (?,?,?,?,?,?)",
                    (student_code, today_str, schreiben_level, score, strengths, weaknesses)
                )
                conn.commit()

            # Increment usage
            st.session_state.schreiben_usage[usage_key] += 1
def falowen_chat_tab():
    st.header("🗣️ Falowen – Speaking & Exam Trainer")

    # --- Set up session state (first run only) ---
    for key, default in [
        ("falowen_stage", 1), ("falowen_mode", None), ("falowen_level", None),
        ("falowen_teil", None), ("falowen_messages", []), ("custom_topic_intro_done", False),
        ("custom_chat_level", None), ("falowen_turn_count", 0)
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # Step 1: Practice Mode
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

    # Step 2: Level
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

    # Step 3: Exam Part
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
    # Step 4: Main Chat (history, input, usage tracking)
    # -------------------------
    if st.session_state["falowen_stage"] == 4:
        falowen_usage_key = f"{st.session_state['student_code']}_falowen_{str(date.today())}"
        if "falowen_usage" not in st.session_state:
            st.session_state["falowen_usage"] = {}
        st.session_state["falowen_usage"].setdefault(falowen_usage_key, 0)

        # --- Display chat history ---
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

        # --- Input and usage logic ---
        session_ended = st.session_state["falowen_usage"][falowen_usage_key] >= FALOWEN_DAILY_LIMIT
        if session_ended:
            st.warning("You have reached today's practice limit for Falowen Chat. Come back tomorrow!")
        else:
            user_input = st.chat_input("💬 Type your answer here...", key="falowen_input")
            if user_input:
                st.session_state["falowen_messages"].append({"role": "user", "content": user_input})
                st.session_state["falowen_turn_count"] += 1
                st.session_state["falowen_usage"][falowen_usage_key] += 1
                st.rerun()  # Next half (AI logic, prompts, OpenAI call) in Stage 6B
# ========= Falowen Chat AI PROMPT LOGIC & RESPONSE HANDLER =========

# ---- EXAM MODE SYSTEM PROMPT TEMPLATES ----
FALOWEN_EXAM_PROMPTS = {
    "A1": {
        "Teil 1": (
            "You are Herr Felix, a Goethe A1 examiner. "
            "After the student introduction, ask three random personal questions based on their introduction (about name, age, job, etc.). "
            "Mark their response, give gentle correction (in English), and provide tips for improvement. "
            "After three questions, summarize strengths and suggest how to improve further."
        ),
        "Teil 2": (
            "You are Herr Felix, an A1 examiner. For each round, pick the next topic and keyword from the exam list. "
            "The student should ask a question using the keyword (e.g., 'Geschäft – schließen'). "
            "Check if it's a proper question. If yes, answer briefly, then recommend the next keyword and ask the next question."
        ),
        "Teil 3": (
            "You are Herr Felix, an A1 examiner. The student should write a polite request (using modal verbs or imperative). "
            "Check if the sentence is correct and polite, then recommend the next prompt from the official list (e.g., 'Radio anmachen')."
        ),
    },
    "A2": {
        "Teil 1": (
            "You are Herr Felix, a Goethe A2 examiner. "
            "Student gives a topic and asks a question. Check if the question is correct and relates to the topic. "
            "Reply with a short answer, correction in English, and suggest another topic/question from the exam list."
        ),
        "Teil 2": (
            "You are Herr Felix, an A2 examiner. Student talks about a topic (e.g., Reisen, Essen). "
            "Give correction and English explanation, then ask a new question on the same topic."
        ),
        "Teil 3": (
            "You are Herr Felix, an A2 examiner. Plan something together (e.g., ins Kino gehen). "
            "Respond to student suggestion, ask what, when, where, and why, and check their ability to suggest and plan."
        ),
    },
    "B1": {
        "Teil 1": (
            "You are Herr Felix, a B1 examiner. Student suggests an activity to plan. "
            "Ask about details, advantages, and possible problems. Give gentle correction, tips, and always suggest the next step to plan."
        ),
        "Teil 2": (
            "You are Herr Felix, a B1 examiner. Student is giving a presentation. "
            "After their message, ask for 1-2 details, correct errors, and give exam feedback."
        ),
        "Teil 3": (
            "You are Herr Felix, a B1 examiner. Student has finished a presentation. "
            "Ask questions about their talk, give positive and constructive feedback (in English), and suggest one exam tip."
        ),
    },
    "B2": {
        "Teil 1": (
            "You are Herr Felix, a B2 examiner. Student gives their opinion on a topic. "
            "Challenge their opinion, ask for reasons/examples, and give advanced corrections."
        ),
        "Teil 2": (
            "You are Herr Felix, a B2 examiner. Student presents a topic. "
            "After each answer, give C1-style questions, correct errors, and encourage deeper arguments."
        ),
        "Teil 3": (
            "You are Herr Felix, a B2 examiner. Argue with the student about the topic, ask for evidence, and provide feedback on advanced language use."
        ),
    },
    "C1": {
        "Teil 1": (
            "You are Herr Felix, a C1 examiner. Listen to student's lecture. "
            "Ask probing questions, correct advanced grammar, and comment on structure and vocabulary."
        ),
        "Teil 2": (
            "You are Herr Felix, a C1 examiner. Lead a formal discussion. "
            "Challenge student's argument, give critical feedback, and suggest native-like phrases."
        ),
        "Teil 3": (
            "You are Herr Felix, a C1 examiner. Summarize the topic, ask the student to reflect, and give advice for future improvement."
        ),
    }
}

# ---- CUSTOM CHAT SYSTEM PROMPT TEMPLATES ----
FALOWEN_CUSTOM_PROMPTS = {
    "A1": (
        "You are Herr Felix, a friendly A1 tutor. "
        "If student's first input, greet and suggest a few A1-level phrases, then ask a simple question about the topic (no correction yet). "
        "For all other answers: correct grammar and vocabulary mistakes in English, give a short tip, and ask another simple question about the same topic."
    ),
    "A2": (
        "You are Herr Felix, a creative A2 German teacher and exam trainer. "
        "If first input: greet, give ideas in English/German, suggest keywords, and ask one question. No correction. "
        "For later answers: correct in English and German, give a tip, and ask a follow-up related to their topic or previous answer."
    ),
    "B1": (
        "You are Herr Felix, a supportive B1 teacher. "
        "If first input: practical ideas/opinions/advantages/disadvantages, question on new line, no correction. "
        "For others: feedback in German & English, highlight strengths/weaknesses, new opinion/experience question."
    ),
    "B2": (
        "You are Herr Felix, a creative and demanding B2 trainer. "
        "If first input: suggest main points, arguments, connectors in English/German, then a question. No correction. "
        "Later: advanced corrections, English/German explanations, more exam-like question, academic vocabulary."
    ),
    "C1": (
        "You are Herr Felix, a C1 examiner. "
        "First input: academic phrases/argument structures, deeper analysis, then a question (no correction). "
        "Other answers: correct academic style, add complexity/depth, always finish with an open-ended, reflective question."
    ),
}

def get_exam_prompt(level, teil):
    if level not in FALOWEN_EXAM_PROMPTS:
        return "You are Herr Felix, a Goethe examiner. Conduct the exam as per level and part."
    # Find teil, allow slight flexibility ("Teil 1 – ..." etc)
    for t in FALOWEN_EXAM_PROMPTS[level]:
        if teil.startswith(t):
            return FALOWEN_EXAM_PROMPTS[level][t]
    return list(FALOWEN_EXAM_PROMPTS[level].values())[0]

def get_custom_prompt(level, first_input=False):
    # Returns main custom prompt; in real use you can distinguish first_input
    return FALOWEN_CUSTOM_PROMPTS.get(level, FALOWEN_CUSTOM_PROMPTS["A1"])

# ------- MESSAGE & AI LOGIC FOR FALOWEN CHAT TAB (to insert in stage 4 logic after user_input) -------
if (
    "falowen_stage" in st.session_state and
    st.session_state["falowen_stage"] == 4 and
    st.session_state.get("falowen_messages")
    and st.session_state["falowen_messages"][-1]["role"] == "user"
):
    mode  = st.session_state.get("falowen_mode", "")
    level = st.session_state.get("falowen_level", "A1")
    teil  = st.session_state.get("falowen_teil", "")
    is_exam = (mode == "Geführte Prüfungssimulation (Exam Mode)")
    is_custom = (mode == "Eigenes Thema/Frage (Custom Chat)")

    # Choose system prompt
    if is_exam:
        ai_system_prompt = get_exam_prompt(level, teil or "")
    else:
        # Optionally, handle first input specially:
        is_first = not st.session_state.get("custom_topic_intro_done", False)
        ai_system_prompt = get_custom_prompt(level, first_input=is_first)
        st.session_state["custom_topic_intro_done"] = True

    # Assemble full conversation history for OpenAI
    conversation = [{"role": "system", "content": ai_system_prompt}]
    for m in st.session_state["falowen_messages"]:
        conversation.append({"role": m["role"], "content": m["content"]})

    # ---- Call OpenAI ----
    with st.spinner("🧑‍🏫 Herr Felix is typing..."):
        try:
            client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
            resp = client.chat.completions.create(model="gpt-4o", messages=conversation)
            ai_reply = resp.choices[0].message.content
        except Exception as e:
            ai_reply = f"Sorry, there was a problem: {str(e)}"
            st.error(str(e))

    st.session_state["falowen_messages"].append({"role": "assistant", "content": ai_reply})
    st.rerun()


