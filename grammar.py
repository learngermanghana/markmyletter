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
STUDENTS_CSV          = "students.csv.csv"
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
# 3. UTILITY FUNCTIONS
# ====================================

@st.cache_data
def load_student_data(path: str = STUDENTS_CSV) -> pd.DataFrame:
    if not os.path.exists(path):
        st.error(f"Students file not found at `{path}`.")
        st.stop()
    df = pd.read_csv(path)
    for col in ["StudentCode", "Email"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.lower().str.strip()
    return df

def init_vocab_db(path: str = VOCAB_DB):
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

def get_vocab_streak(c, student_code: str) -> int:
    c.execute("SELECT DISTINCT date FROM vocab_progress WHERE student_code=? ORDER BY date DESC", (student_code,))
    dates = [row[0] for row in c.fetchall()]
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

def get_exam_prompt(level, teil):
    if level not in FALOWEN_EXAM_PROMPTS:
        return "You are Herr Felix, a Goethe examiner. Conduct the exam as per level and part."
    for t in FALOWEN_EXAM_PROMPTS[level]:
        if teil.startswith(t):
            return FALOWEN_EXAM_PROMPTS[level][t]
    return list(FALOWEN_EXAM_PROMPTS[level].values())[0]

def get_custom_prompt(level):
    return FALOWEN_CUSTOM_PROMPTS.get(level, FALOWEN_CUSTOM_PROMPTS["A1"])

# ====================================
# 4. TAB FUNCTION DEFINITIONS
# ====================================

def falowen_chat_tab():
    st.header("🗣️ Falowen – Speaking & Exam Trainer")
    # --- YOUR FULL CHAT LOGIC GOES HERE ---
    st.write("Falowen chat logic placeholder.")

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
    st.header("✍️ Schreiben Trainer")
    st.write("Full schreiben logic here.")

# ====================================
# 5. DASHBOARD/LOGIN/OTHER UI FUNCTIONS
# ====================================

def login_screen():
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
    # Add more stats if needed

# ====================================
# 6. MAIN FUNCTION
# ====================================

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

    # --- Initialize session state keys for this tab ---
    if "vocab_usage" not in st.session_state:
        st.session_state.vocab_usage = {}
    if "vocab_level" not in st.session_state:
        st.session_state.vocab_level = "A1"
    if "vocab_idx" not in st.session_state:
        st.session_state.vocab_idx = 0
    if "vocab_feedback" not in st.session_state:
        st.session_state.vocab_feedback = ""
    if "show_next_button" not in st.session_state:
        st.session_state.show_next_button = False

    # --- Main logic ---
    student_code = st.session_state.student_code
    today_str = str(date.today())
    vocab_usage_key = f"{student_code}_vocab_{today_str}"
    st.session_state.vocab_usage.setdefault(vocab_usage_key, 0)

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
                    # Example sentence (optional)
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
    st.header("✍️ Schreiben Trainer")

    student_code = st.session_state.student_code
    student_name = st.session_state.student_name
    today_str = str(date.today())
    usage_key = f"{student_code}_schreiben_{today_str}"

    # Usage tracking
    if "schreiben_usage" not in st.session_state:
        st.session_state.schreiben_usage = {}
    st.session_state.schreiben_usage.setdefault(usage_key, 0)

    # Connect/init DB for writing feedback
    conn = sqlite3.connect(VOCAB_DB, check_same_thread=False)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS schreiben_feedback (
            student_code TEXT,
            date TEXT,
            level TEXT,
            score INTEGER,
            strengths TEXT,
            weaknesses TEXT
        )
    """)
    conn.commit()

    # --- Latest feedback summary ---
    with st.expander("📈 Your Writing Progress (Latest)", expanded=True):
        c.execute(
            "SELECT date, level, score, strengths, weaknesses FROM schreiben_feedback WHERE student_code=? ORDER BY date DESC LIMIT 1",
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
            st.write("_No submissions yet. Your progress will appear here!_")

    # --- Writing history table + chart ---
    with st.expander("🗂️ Your Writing Progress (History)", expanded=False):
        c.execute(
            "SELECT date, level, score, strengths, weaknesses FROM schreiben_feedback WHERE student_code=? ORDER BY date DESC LIMIT 10",
            (student_code,),
        )
        rows = c.fetchall()
        if rows:
            df_history = pd.DataFrame(rows, columns=["Date", "Level", "Score", "Strengths", "Needs Improvement"])
            st.dataframe(df_history, use_container_width=True)
            if len(df_history) > 1:
                # Sort chronologically for chart
                df_sorted = df_history.sort_values("Date")
                st.line_chart(df_sorted["Score"], use_container_width=True)
            st.caption("Last 10 attempts. Use this table to reflect on your strengths and weaknesses over time.")
        else:
            st.write("_No writing history yet. Your progress will appear here!_")

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

    schreiben_text = st.text_area(
        "**Paste your letter or essay below.** Herr Felix will mark it as a real Goethe examiner and give you feedback.",
        height=250,
        key=f"schreiben_text_{schreiben_level}"
    )

    if st.button("Check My Writing"):
        if not schreiben_text.strip():
            st.warning("Please write something before submitting.")
            return

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

        # WhatsApp link (fix line breaks for URL)
        import urllib.parse
        assignment_msg = (
            f"Hallo Herr Felix! Hier ist mein Schreiben für die Korrektur ({schreiben_level}):\n\n"
            f"{schreiben_text}\n\n---\nFeedback: {ai_feedback[:600]}..."
        )
        whatsapp_url = (
            "https://api.whatsapp.com/send"
            f"?phone=233205706589&text={urllib.parse.quote(assignment_msg)}"
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

