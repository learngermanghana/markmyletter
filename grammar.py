# ====================================
# 1. IMPORTS, CONSTANTS, AND PAGE SETUP
# ====================================

import streamlit as st
from openai import OpenAI
import random
import pandas as pd
import os
from datetime import date

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

# --- File/database constants ---
CODES_FILE = "student_codes.csv"

# --- Daily usage limits (centralized for all modules) ---
FALOWEN_DAILY_LIMIT = 25
VOCAB_DAILY_LIMIT   = 20
SCHREIBEN_DAILY_LIMIT = 5

max_turns = 25
        
# --- Vocab lists for all levels ---
# --- Full vocab lists by level (define first, then reference) ---

a1_vocab = [
    ("Südseite","south side"), ("3. Stock","third floor"), ("Geschenk","present/gift"),
    ("Buslinie","bus line"), ("Ruhetag","rest day (closed)"), ("Heizung","heating"),
    ("Hälfte","half"), ("die Wohnung","apartment"), ("das Zimmer","room"), ("die Miete","rent"),
    ("der Balkon","balcony"), ("der Garten","garden"), ("das Schlafzimmer","bedroom"),
    ("das Wohnzimmer","living room"), ("das Badezimmer","bathroom"), ("die Garage","garage"),
    ("der Tisch","table"), ("der Stuhl","chair"), ("der Schrank","cupboard"), ("die Tür","door"),
    ("das Fenster","window"), ("der Boden","floor"), ("die Wand","wall"), ("die Lampe","lamp"),
    ("der Fernseher","television"), ("das Bett","bed"), ("die Küche","kitchen"), ("die Toilette","toilet"),
    ("die Dusche","shower"), ("das Waschbecken","sink"), ("der Ofen","oven"),
    ("der Kühlschrank","refrigerator"), ("die Mikrowelle","microwave"), ("die Waschmaschine","washing machine"),
    ("die Spülmaschine","dishwasher"), ("das Haus","house"), ("die Stadt","city"), ("das Land","country"),
    ("die Straße","street"), ("der Weg","way"), ("der Park","park"), ("die Ecke","corner"),
    ("die Bank","bank"), ("der Supermarkt","supermarket"), ("die Apotheke","pharmacy"),
    ("die Schule","school"), ("die Universität","university"), ("das Geschäft","store"),
    ("der Markt","market"), ("der Flughafen","airport"), ("der Bahnhof","train station"),
    ("die Haltestelle","bus stop"), ("die Fahrt","ride"), ("das Ticket","ticket"), ("der Zug","train"),
    ("der Bus","bus"), ("das Taxi","taxi"), ("das Auto","car"), ("die Ampel","traffic light"),
    ("die Kreuzung","intersection"), ("der Parkplatz","parking lot"), ("der Fahrplan","schedule"),
    ("zumachen","to close"), ("aufmachen","to open"), ("ausmachen","to turn off"),
    ("übernachten","to stay overnight"), ("anfangen","to begin"), ("vereinbaren","to arrange"),
    ("einsteigen","to get in / board"), ("umsteigen","to change (trains)"), ("aussteigen","to get out / exit"),
    ("anschalten","to switch on"), ("ausschalten","to switch off"), ("Anreisen","to arrive"), ("Ankommen","to arrive"),
    ("Abreisen","to depart"), ("Absagen","to cancel"), ("Zusagen","to agree"), ("günstig","cheap"),
    ("billig","inexpensive")
    "B2": ["Umwelt", "Entwicklung", "Auswirkung", ...],
    "C1": ["Ausdruck", "Beziehung", "Erkenntnis", ...]
]

a2_vocab = [
    ("die Verantwortung", "responsibility"), ("die Besprechung", "meeting"), ("die Überstunden", "overtime"),
    # ... (rest of your A2 vocab tuples, keep same format)
    ("die Bewerbung", "application")
]

# --- Vocab list dictionary ---
VOCAB_LISTS = {
    "A1": a1_vocab,
    "A2": a2_vocab,
    "B1": ["Fortschritt", "Eindruck", "Unterschied", "Vorschlag", "Erfahrung"],
    "B2": ["Umwelt", "Entwicklung", "Auswirkung", "Verhalten", "Verhältnis"],
    "C1": ["Ausdruck", "Beziehung", "Erkenntnis", "Verfügbarkeit", "Bereich"]
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
# 2. STUDENT LOGIN AND MAIN MENU (NO SIDEBAR)
# ====================================

def load_codes():
    if os.path.exists(CODES_FILE):
        df = pd.read_csv(CODES_FILE)
        if "code" not in df.columns:
            df = pd.DataFrame(columns=["code"])
        df["code"] = df["code"].astype(str).str.strip().str.lower()
    else:
        df = pd.DataFrame(columns=["code"])
    return df

# --- Step 1: Student Login (only shows login form) ---
if "student_code" not in st.session_state:
    st.session_state["student_code"] = ""
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.title("🔑 Student Login")
    code = st.text_input("Enter your student code to begin:")
    if st.button("Login"):
        code_clean = code.strip().lower()
        df_codes = load_codes()
        if code_clean in df_codes["code"].dropna().tolist():
            st.session_state["student_code"] = code_clean
            st.session_state["logged_in"] = True
            st.success("Welcome! Login successful.")
            st.rerun()    # Immediately stops and reruns script (no need for st.stop here)
        else:
            st.error("This code is not recognized. Please check with your tutor.")
            st.stop()                  # stops right after error
    st.stop()  # If they haven't logged in or pressed button, stop here!


# --- Step 2: Choose Practice Mode (CENTERED, NO SIDEBAR) ---
if st.session_state["logged_in"]:
    student_code = st.session_state.get("student_code", "")
    if student_code:
        st.markdown(
            f"<div style='font-size:1.08rem;margin-bottom:10px;color:#156276;'>"
            f"👋 <b>Welcome, <code>{student_code}</code>!</b></div>",
            unsafe_allow_html=True
        )
    st.header("Choose Practice Mode")
    tab = st.radio(
        "How do you want to practice?",
        ["Falowen Chat", "Vocab Trainer", "Schreiben Trainer"],
        key="main_tab_select"
    )
    st.markdown(
        f"<div style='background:#e0f2ff;border-radius:12px;padding:12px 18px;margin-bottom:12px;font-size:1.2rem;'>"
        f"🔹 <b>Active:</b> {tab}</div>",
        unsafe_allow_html=True
    )

    # -----------------------------------
    #        FALOWEN CHAT TAB
    # -----------------------------------
    if tab == "Falowen Chat":
        st.header("🗣️ Falowen – Speaking & Exam Trainer")

        # --- Session state variable setup ---
        for key, default in [
            ("falowen_stage", 1),
            ("falowen_mode", None),
            ("falowen_level", None),
            ("falowen_teil", None),
            ("falowen_messages", []),
            ("custom_topic_intro_done", False),
            ("custom_chat_level", None),
        ]:
            if key not in st.session_state:
                st.session_state[key] = default

        # ---- Step 1: Practice Mode ----
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

        # ---- Step 2: Level Selection ----
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

        # ---- Step 3: Exam Teil (for Exam Mode) ----
        if st.session_state["falowen_stage"] == 3:
            teil_options = {
                "A1": [
                    "Teil 1 – Basic Introduction",
                    "Teil 2 – Question and Answer",
                    "Teil 3 – Making A Request"
                ],
                "A2": [
                    "Teil 1 – Fragen zu Schlüsselwörtern",
                    "Teil 2 – Bildbeschreibung & Diskussion",
                    "Teil 3 – Gemeinsam planen"
                ],
                "B1": [
                    "Teil 1 – Gemeinsam planen (Dialogue)",
                    "Teil 2 – Präsentation (Monologue)",
                    "Teil 3 – Feedback & Fragen stellen"
                ],
                "B2": [
                    "Teil 1 – Diskussion",
                    "Teil 2 – Präsentation",
                    "Teil 3 – Argumentation"
                ],
                "C1": [
                    "Teil 1 – Vortrag",
                    "Teil 2 – Diskussion",
                    "Teil 3 – Bewertung"
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

        # ---- Step 4: Main Chat + User Input ----
        if st.session_state["falowen_stage"] == 4:
            falowen_usage_key = f"{st.session_state['student_code']}_falowen_{str(date.today())}"
            if "falowen_usage" not in st.session_state:
                st.session_state["falowen_usage"] = {}
            st.session_state["falowen_usage"].setdefault(falowen_usage_key, 0)

            # ---------- --AI ALWAYS STARTS THE CHAT IF EMPTY--- ---------------
            if not st.session_state["falowen_messages"]:
                mode  = st.session_state.get("falowen_mode", "")
                level = st.session_state.get("falowen_level", "A1")
                teil  = st.session_state.get("falowen_teil", "")

                # --------- EXAM MODE FIRST MESSAGE ---------
                if mode == "Geführte Prüfungssimulation (Exam Mode)":
                    if level == "A1" and teil.startswith("Teil 1"):
                        ai_first = (
                            "👋 For speaking part 1, you'll be asked to introduce yourself using these keywords: Name, Age, Place of Residence, Languages, Job, Hobby. "
                            "Afterwards, the examiner will pick your response and ask a few random questions. Let's practice: please type your introduction including all the keywords above."
                        )
                    elif level == "A1" and teil.startswith("Teil 2"):
                        ai_first = (
                            "Now we practice questions and answers! The topic is: 'Geschäft – schließen' (shop – to close). Please ask me a question about this in German."
                        )
                    elif level == "A1" and teil.startswith("Teil 3"):
                        ai_first = (
                            "Let's practice making polite requests! Please write a polite request, for example: 'Können Sie bitte das Fenster zumachen?'"
                        )
                    elif level == "A2" and teil.startswith("Teil 1"):
                        ai_first = (
                            "Let's start with your daily routine! Please tell me: What is the first thing you do in the morning?"
                        )
                    elif level == "A2" and teil.startswith("Teil 2"):
                        ai_first = (
                            "Describe the picture you see or answer my question about the topic 'Wetter' (weather)."
                        )
                    elif level == "A2" and teil.startswith("Teil 3"):
                        ai_first = (
                            "Let's make a plan together! What do you suggest?"
                        )
                    elif level == "B1" and teil.startswith("Teil 1"):
                        ai_first = (
                            "Welcome to the B1 exam – Planning together! Let's plan an activity together. What do you suggest?"
                        )
                    elif level == "B1" and teil.startswith("Teil 2"):
                        ai_first = (
                            "Now it's time for your presentation! Please introduce your topic. What would you like to talk about?"
                        )
                    elif level == "B1" and teil.startswith("Teil 3"):
                        ai_first = (
                            "You have just finished your presentation. Now I will ask you questions about it. Are you ready?"
                        )
                    elif level == "B2" and teil.startswith("Teil 1"):
                        topic = random.choice(b2_teil1_topics)
                        ai_first = f"Willkommen zur B2-Diskussion!\n\n**Thema:** {topic}\n\nWas denkst du dazu?"
                    elif level == "B2" and teil.startswith("Teil 2"):
                        presentation = random.choice(b2_teil2_presentations)
                        ai_first = f"Halte bitte deine Präsentation zum Thema:\n\n**{presentation}**\n\nTeile deine Meinung und Erfahrungen."
                    elif level == "B2" and teil.startswith("Teil 3"):
                        argument = random.choice(b2_teil3_arguments)
                        ai_first = f"Jetzt führen wir eine Argumentation.\n\n**Thema:** {argument}\n\nWas ist dein Standpunkt?"
                    elif level == "C1" and teil.startswith("Teil 1"):
                        lecture = random.choice(c1_teil1_lectures)
                        ai_first = f"Willkommen zur C1-Prüfung – Vortrag.\n\n**Vortragsthema:** {lecture}\n\nBitte halte einen kurzen Vortrag dazu."
                    elif level == "C1" and teil.startswith("Teil 2"):
                        discussion = random.choice(c1_teil2_discussions)
                        ai_first = f"Diskutiere bitte ausführlich mit mir über:\n\n**{discussion}**"
                    elif level == "C1" and teil.startswith("Teil 3"):
                        evaluation = random.choice(c1_teil3_evaluations)
                        ai_first = f"Jetzt kommt die Bewertung.\n\n**Thema:** {evaluation}\n\nWas ist deine abschließende Meinung?"
                    else:
                        ai_first = "Welcome to the exam! Let's begin. Please introduce yourself."
                # --------- CUSTOM CHAT FIRST MESSAGE ---------
                elif mode == "Eigenes Thema/Frage (Custom Chat)":
                    ai_first = (
                        "Hello! 👋 I'm Herr Felix, your AI examiner. Please give a topic or ask your first question, and I'll help you practice."
                    )
                else:
                    ai_first = "Hello! What would you like to practice today?"
                st.session_state["falowen_messages"].append({"role": "assistant", "content": ai_first})

            st.info(
                f"Today's practice: {st.session_state['falowen_usage'][falowen_usage_key]}/{FALOWEN_DAILY_LIMIT}"
            )

            # Show chat history
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

            # ------------- User input & daily limit enforcement -------------
            session_ended = st.session_state["falowen_usage"][falowen_usage_key] >= FALOWEN_DAILY_LIMIT

            if session_ended:
                st.warning("You have reached today's practice limit for Falowen Chat. Come back tomorrow!")
            else:
                user_input = st.chat_input("💬 Type your answer here...", key="falowen_input")
                if user_input:
                    st.session_state["falowen_messages"].append({"role": "user", "content": user_input})
                    if "falowen_turn_count" not in st.session_state:
                        st.session_state["falowen_turn_count"] = 0
                    st.session_state["falowen_turn_count"] += 1
                    st.session_state["falowen_usage"][falowen_usage_key] += 1
                    # <---- Insert your OpenAI reply logic here! ---->



                # ======== AI PROMPT/LOGIC FOR EXAM + CUSTOM CHAT ========
                level = st.session_state.get("falowen_level")
                teil = st.session_state.get("falowen_teil", "")
                mode = st.session_state.get("falowen_mode", "")
                is_exam_mode = mode == "Geführte Prüfungssimulation (Exam Mode)"
                is_custom_chat = mode == "Eigenes Thema/Frage (Custom Chat)"
                is_b1_teil3 = (
                    is_exam_mode and level == "B1" and teil.startswith("Teil 3") and "current_b1_teil3_topic" in st.session_state
                )

                # ---- A1 Exam Mode Prompts ----
                if is_exam_mode and level == "A1":
                    if teil.startswith("Teil 1"):
                        ai_system_prompt = (
                            "You are Herr Felix, an A1 German examiner. "
                            "Check the student's self-introduction (name, age, etc), correct errors, and give a grammar tip in English. "
                            "If the answer is perfect, praise them. Then, if ready, ask the next follow-up question from your internal list."
                        )
                    elif teil.startswith("Teil 2"):
                        ai_system_prompt = (
                            "You are Herr Felix, an A1 German examiner. "
                            "Check the student's question and answer for the topic and keyword, correct errors, and give a grammar tip in English. "
                            "If the answer is perfect, praise them. Then introduce the next Thema and keyword as the next prompt."
                        )
                    elif teil.startswith("Teil 3"):
                        ai_system_prompt = (
                            "You are Herr Felix, an A1 German examiner. "
                            "Check the student's polite request, correct errors, and give a grammar tip in English. "
                            "If the answer is perfect, praise them. Then give the next polite request prompt."
                        )
                # ---- CUSTOM CHAT AND ALL OTHER MODES ----
                else:
                    ai_system_prompt = (
                        "You are Herr Felix, a supportive and creative German examiner. "
                        "Continue the conversation, give simple corrections, and ask the next question."
                    )
                    if is_b1_teil3:
                        b1_topic = st.session_state['current_b1_teil3_topic']
                        ai_system_prompt = (
                            "You are Herr Felix, the examiner in a German B1 oral exam (Teil 3: Feedback & Questions). "
                            f"**IMPORTANT: Stay strictly on the topic:** {b1_topic}. "
                            "After student ask the question and you have given the student compliment, give another topic for the student ask the question. "
                            "The student is supposed to ask you one valid question about their presentation. "
                            "1. Read the student's message. "
                            "2. Praise if it's valid or politely indicate what's missing. "
                            "3. If valid, answer briefly in simple German. "
                            "4. End with clear exam tips in English. "
                            "Stay friendly, creative and exam-like."
                        )
                    elif is_custom_chat:
                        lvl = st.session_state.get('custom_chat_level', level)
                        if lvl == 'A2':
                            ai_system_prompt = (
                                "You are Herr Felix, a friendly but creative A2 German teacher and exam trainer. "
                                "Greet and give students ideas and examples about how to talk about the topic in English and ask only question. No correction or answer in the statement but only tip and possible phrases to use. This stage only when the student input their first question and not anyother input. "
                                "The first input from the student is their topic and not their reply or sentence or answer. It is always their presentation topic. Only the second and further repliers it their response to your question "
                                "Use simple English and German to correct the student's last answer. Tip and necessary suggestions should be explained in English with German supporting for student to understand. They are A2 beginners student. "
                                "You can also suggest keywords when needed. Ask one question only. Format your reply with answer, correction explanation in english, tip in english, and next question in German."
                            )
                        elif lvl == 'B1':
                            if not st.session_state.get('custom_topic_intro_done', False):
                                ai_system_prompt = (
                                    "You are Herr Felix, a supportive and creative B1 German teacher. "
                                    "The first input from the student is their topic and not their reply or sentence or answer. It is always their presentation topic. Only the second and further repliers it their response to your question "
                                    "Provide practical ideas/opinions/advantages/disadvantages/situation in their homeland for the topic in German and English, then ask one opinion question. No correction or answer in the statement but only tip and possible phrases to use. This stage only when the student input their first question and not anyother input. "
                                    "Support ideas and opinions explanation in English and German as these students are new B1 students. "
                                    "Ask creative question that helps student to learn how to answer opinions,advantages,disadvantages,situation in their country and so on. "
                                    "Always put the opinion question on a separate line so the student can notice the question from the ideas and examples"
                                )
                            else:
                                ai_system_prompt = (
                                    "You are Herr Felix, a supportive B1 German teacher. "
                                    "Reply in German and English, correct last answer, give a tip in English, and ask one question on the same topic."
                                )
                        elif lvl == 'A1':
                            ai_system_prompt = (
                                "You are Herr Felix, a supportive and creative A1 German teacher and exam trainer. "
                                "If the student's first input is an introduction, analyze it and give feedback in English with suggestions for improvement. "
                                "If the student asks a question with an answer, respond in the correct A1 exam format and ask a new question using the A1 keywords list. "
                                "For requests, reply as an examiner, give correction, and suggest other requests. "
                                "Offer to let the student decide how many practices/questions to do today. "
                                "Always be supportive and explain your feedback clearly in English."
                            )
                        elif lvl in ['B2', 'C1']:
                            ai_system_prompt = (
                                "You are Herr Felix, a supportive, creative, but strict B2/C1 German examiner. "
                                "Always correct the student's answer in both English and German. "
                                "Encourage deeper reasoning, advanced grammar, and real-world vocabulary in your feedback and questions."
                            )
                    # Mark intro done for B1/B2/C1 after first student reply
                    if is_custom_chat and lvl in ['B1', 'B2', 'C1'] and not st.session_state.get("custom_topic_intro_done", False):
                        st.session_state["custom_topic_intro_done"] = True

                conversation = [{"role": "system", "content": ai_system_prompt}] + st.session_state["falowen_messages"]
                with st.spinner("🧑‍🏫 Herr Felix is typing..."):
                    try:
                        client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
                        resp = client.chat.completions.create(model="gpt-4o", messages=conversation)
                        ai_reply = resp.choices[0].message.content
                    except Exception as e:
                        ai_reply = "Sorry, there was a problem generating a response."
                        st.error(str(e))
                st.session_state["falowen_messages"].append({"role": "assistant", "content": ai_reply})

            # --- Show if session ended ---
            if session_ended:
                st.warning("You have reached today's practice limit for Falowen Chat. Come back tomorrow!")
            else:
                # main chat logic
                ...
       
            # ------------- Navigation Buttons --------------
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("⬅️ Back", key="falowen_back"):
                    st.session_state.update({
                        "falowen_stage": 1,
                        "falowen_messages": [],
                        "falowen_turn_count": 0,
                        "custom_chat_level": None,
                        "custom_topic_intro_done": False
                    })
                    st.rerun()
                    st.stop
            with col2:
                if st.button("🔄 Restart Chat", key="falowen_restart"):
                    st.session_state.update({
                        "falowen_messages": [],
                        "falowen_turn_count": 0,
                        "custom_chat_level": None,
                        "custom_topic_intro_done": False
                    })
                    st.rerun()
            with col3:
                if st.button("Next ➡️ (Summary)", key="falowen_summary"):
                    st.success("Summary not implemented yet (placeholder).")


 # =========================================
# VOCAB TRAINER TAB (A1–C1, with Progress)
# =========================================

import datetime

elif tab == "Vocab Trainer":
    st.header("🧠 Vocab Trainer")

    # -------- Session state for vocab stats --------
    vocab_usage_key = f"{st.session_state['student_code']}_vocab_{str(date.today())}"

    if "vocab_usage" not in st.session_state:
        st.session_state["vocab_usage"] = {}
    if "vocab_correct_today" not in st.session_state:
        st.session_state["vocab_correct_today"] = 0
    if "vocab_streak" not in st.session_state:
        st.session_state["vocab_streak"] = 0
    if "vocab_mastered" not in st.session_state:
        st.session_state["vocab_mastered"] = {}  # word: count

    # ---- Streak logic ----
    if "last_vocab_practice_date" not in st.session_state:
        st.session_state["last_vocab_practice_date"] = ""
    today_str = str(date.today())
    if st.session_state["last_vocab_practice_date"] != today_str:
        yesterday = (date.today() - datetime.timedelta(days=1)).isoformat()
        if st.session_state["last_vocab_practice_date"] == yesterday:
            st.session_state["vocab_streak"] += 1
        else:
            st.session_state["vocab_streak"] = 1
        st.session_state["last_vocab_practice_date"] = today_str
        st.session_state["vocab_correct_today"] = 0  # Reset daily correct count

    st.session_state["vocab_usage"].setdefault(vocab_usage_key, 0)

    # ---- Display stats panel ----
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Today's attempts", f"{st.session_state['vocab_usage'][vocab_usage_key]}/{VOCAB_DAILY_LIMIT}")
    with col2:
        st.metric("Streak", f"{st.session_state['vocab_streak']} days")
    with col3:
        mastered_count = sum(1 for x in st.session_state["vocab_mastered"].values() if x >= 3)
        st.metric("Mastered words", mastered_count)

    st.progress(st.session_state["vocab_usage"][vocab_usage_key] / VOCAB_DAILY_LIMIT)

    # ---- Level select and word list ----
    vocab_level = st.selectbox(
        "Choose your level:",
        ["A1", "A2", "B1", "B2", "C1"],
        key="vocab_level_select"
    )
    vocab_list = VOCAB_LISTS.get(vocab_level, [])
    session_ended = st.session_state["vocab_usage"][vocab_usage_key] >= VOCAB_DAILY_LIMIT

    # ---- Show last few results ----
    if "vocab_history" not in st.session_state:
        st.session_state["vocab_history"] = []

    if st.session_state["vocab_history"]:
        st.markdown("#### Recent Results")
        for item in st.session_state["vocab_history"][-5:][::-1]:
            color = "#43a047" if item["correct"] else "#e53935"
            st.markdown(
                f"<span style='color:{color};font-weight:bold'>{item['word']}</span> → "
                f"<i>{item['answer']}</i>"
                f"{' ✅' if item['correct'] else ' ❌'}",
                unsafe_allow_html=True
            )

    # ---- Main practice block ----
    if not session_ended:
        # Pick or update word (randomly)
        if "current_vocab_word" not in st.session_state or st.button("Next Word"):
            st.session_state["current_vocab_word"], st.session_state["current_vocab_solution"] = random.choice(
                vocab_list if vocab_list and isinstance(vocab_list[0], tuple) else [(w, "") for w in vocab_list]
            )
            st.session_state["vocab_feedback"] = ""
            st.session_state["show_example"] = False

        word = st.session_state["current_vocab_word"]
        correct_answer = st.session_state.get("current_vocab_solution", "")

        st.subheader(f"🔤 What is the English meaning of: **{word}** ?")
        vocab_answer = st.text_input("Your English translation", key="vocab_answer")

        # --- Check answer and update stats ---
        if st.button("Check Answer"):
            # Flexible string check: lowercase, strip, and partial match allowed
            answer = vocab_answer.strip().lower()
            solutions = [x.strip().lower() for x in correct_answer.split("/")] if correct_answer else []
            correct = any(sol in answer or answer in sol for sol in solutions) if solutions else False

            # For B1/B2/C1, no solution provided, just let any answer pass as "practiced"
            if vocab_level in ["B1", "B2", "C1"] and not solutions:
                correct = True

            if correct:
                st.session_state["vocab_feedback"] = "✅ Correct! Great job!"
                st.session_state["vocab_correct_today"] += 1
                # Track mastered words
                st.session_state["vocab_mastered"][word] = st.session_state["vocab_mastered"].get(word, 0) + 1
            else:
                st.session_state["vocab_feedback"] = f"❌ Not quite! The correct answer is: **{correct_answer}**"
                st.session_state["vocab_mastered"][word] = 0  # Reset if got wrong

            # Save in history
            st.session_state["vocab_history"].append({
                "word": word,
                "answer": vocab_answer,
                "correct": correct
            })
            st.session_state["vocab_usage"][vocab_usage_key] += 1
            st.session_state["show_example"] = True

        # ---- Show feedback & example ----
        if st.session_state.get("vocab_feedback"):
            color = "#43a047" if "Correct" in st.session_state["vocab_feedback"] else "#e53935"
            st.markdown(
                f"<span style='color:{color};font-size:1.1em;'>{st.session_state['vocab_feedback']}</span>",
                unsafe_allow_html=True
            )
            # Suggest example phrase (AI or placeholder)
            if st.session_state.get("show_example"):
                # --- Suggest an example phrase for the word (placeholder or AI call) ---
                if vocab_level in ["A1", "A2"]:
                    example_phrase = f"Zum Beispiel: **Das ist mein {word}**."  # Simple placeholder
                else:
                    example_phrase = "Try to use this word in a sentence!"
                st.info(example_phrase)

    else:
        st.warning("You have reached today's practice limit for Vocab Trainer. Come back tomorrow!")



    # =========================================
    # SCHREIBEN TRAINER TAB (A1–C1, Free Input)
    # =========================================
    elif tab == "Schreiben Trainer":
        st.header("✍️ Schreiben Trainer")

        # ----- Usage key and limit -----
        schreiben_usage_key = f"{st.session_state['student_code']}_schreiben_{str(date.today())}"
        if "schreiben_usage" not in st.session_state:
            st.session_state["schreiben_usage"] = {}
        st.session_state["schreiben_usage"].setdefault(schreiben_usage_key, 0)

        st.info(
            f"Today's Schreiben submissions: {st.session_state['schreiben_usage'][schreiben_usage_key]}/{SCHREIBEN_DAILY_LIMIT}"
        )

        schreiben_level = st.selectbox(
            "Select your level:",
            ["A1", "A2", "B1", "B2", "C1"],
            key="schreiben_level_select"
        )

        if st.session_state["schreiben_usage"][schreiben_usage_key] >= SCHREIBEN_DAILY_LIMIT:
            st.warning("You've reached today's Schreiben submission limit. Please come back tomorrow!")
        else:
            st.write("**Paste your letter or essay below.** Herr Felix will mark it as a real Goethe examiner and give you feedback.")
            schreiben_text = st.text_area("Your letter/essay", height=250, key=f"schreiben_text_{schreiben_level}")

            if st.button("Check My Writing"):
                if not schreiben_text.strip():
                    st.warning("Please write something before submitting.")
                else:
                    ai_prompt = (
                        f"You are Herr Felix, a strict but supportive Goethe examiner. "
                        f"The student has submitted a {schreiben_level} German letter or essay. "
                        " Always talk as the tutor in english to explain mistake. Instead the student, use you so it would feel like Herr Felix communicating "
                        " Read the full text. Mark and correct grammar/spelling/structure mistakes, and provide a clear correction. "
                        " Write a brief comment in English about what the student did well and what they should improve. "
                        " Teach the student steps and tell the student to use your suggestion to correct the letter. Let student think a bit to be creative to correct the letter but dont completely show their corrected completed letter (in bold or highlight the changes if possible). "
                        " Mark the student work and give student a score out of 25 marks. Explain to the student why you gave that scores based on grammar,spelling, vocabulary and so on, explaining their strength,weakness and what they have to improve on"
                        "Show suggested phrases,vocabulary,conjunctions they could use next time based on the level. Also check if letter matches their level. No excesss use of A.I and translators "
                        " If scores is above 17 then student has passed and can submit to their tutor. If score is below 17,tell them to improve on "
                        
                    )
                    ai_message = (
                        f"{ai_prompt}\n\nStudent's letter/essay:\n{schreiben_text}"
                    )

                    with st.spinner("🧑‍🏫 Herr Felix is marking..."):
                        try:
                            client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
                            response = client.chat.completions.create(
                                model="gpt-4o",
                                messages=[{"role": "system", "content": ai_message}]
                            )
                            ai_feedback = response.choices[0].message.content.strip()
                        except Exception as e:
                            ai_feedback = f"Error: {str(e)}"

                    st.success("📝 **Feedback from Herr Felix:**")
                    st.markdown(ai_feedback)
                    st.session_state["schreiben_usage"][schreiben_usage_key] += 1

