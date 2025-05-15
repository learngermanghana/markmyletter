import re
import pandas as pd
import streamlit as st

# ---------- Step 1: App Setup ----------
def setup_app():
    """
    Configure the Streamlit page and main title with provided branding.
    """
    st.set_page_config(page_title="📘 German Grammar Helper: A1–B2", layout="wide")
    st.title("📘 German Grammar Helper: A1–B2")
    st.markdown("#### Powered by Learn Language Education Academy")

# ---------- Load Student Codes (CSV) ----------
def load_student_codes():
    """
    Load valid student codes from 'student_codes.csv'.
    The CSV file must have a column named 'code'.
    """
    try:
        df = pd.read_csv('student_codes.csv')
        return df['code'].astype(str).tolist()
    except FileNotFoundError:
        st.error("Error: student_codes.csv not found. Please upload the file.")
        return []

# ---------- Student Login UI (Main Page) ----------
def show_student_login():
    """
    Prompt the student to enter their code on the main page and validate format + existence.
    Code format: letters (A–Z, a–z) followed by numbers (0–9).
    """
    codes = load_student_codes()
    student_code = st.text_input("🔐 Enter your student code (letters+numbers):")
    if student_code:
        if not re.fullmatch(r"[A-Za-z]+[0-9]+", student_code):
            st.error("Invalid code format. It should be letters followed by numbers.")
        elif student_code not in codes:
            st.error("Student code not recognized. Please check or contact your tutor.")
        else:
            st.success(f"Welcome, {student_code}!")
    return student_code

# ---------- Load Grammar Data Inline ----------
def load_grammar_data():
    """
    Returns full A1–B2 grammar topics hard-coded inline.
    Each entry: level, topic, keywords, explanation, example.
    """
    return [
              {"level":"A1","topic":"Word Classes (Wortarten)","keywords":["word classes","wortarten"],"explanation":"German Wortarten categorize words by function (e.g., nouns, verbs, adjectives, adverbs, pronouns, articles, prepositions, conjunctions, numerals, interjections).","example":"Das schnelle Auto fährt laut."},
        {"level":"A1","topic":"Personal Pronouns","keywords":["ich","du","er","sie","es","wir","ihr","Sie"],"explanation":"Pronouns replace nouns: ich (I), du (you). Must match case, number, and gender.","example":"Ich bin Felix."},
        {"level":"A1","topic":"Nouns & Genders","keywords":["nouns","genders","genus"],"explanation":"All German nouns are capitalized and have three genders: der (masc), die (fem), das (neut).","example":"Der Tisch, die Lampe, das Auto."},
        {"level":"A1","topic":"Verb Conjugation","keywords":["verb","conjugation","regular","irregular"],"explanation":"Regular verbs follow predictable endings (ich mache); irregular verbs change stems (ich gehe).","example":"Ich mache Hausaufgaben. Du gehst zur Schule."},
        {"level":"A1","topic":"'sein' and 'haben'","keywords":["sein","haben"],"explanation":"'sein' describes states and identity; 'haben' indicates possession and forms compound tenses.","example":"Ich bin müde. Ich habe ein Buch."},
        {"level":"A1","topic":"Present Tense (Präsens)","keywords":["present","präsens"],"explanation":"Used for current, habitual, or scheduled actions. Conjugate to match the subject.","example":"Ich lerne Deutsch. Er spielt Fußball."},
        {"level":"A1","topic":"Sentence Structure","keywords":["word order","satzstellung"],"explanation":"In main clauses, the finite verb is in the second position. Yes/no questions invert subject and verb.","example":"Kommst du morgen?"},
        {"level":"A1","topic":"Imperative (Imperativ)","keywords":["imperative","imperativ","du","ihr","Sie"],"explanation":"The imperative expresses commands: for informal singular (du) use the verb stem without ending (e.g., 'Komm!'); for informal plural (ihr) add '-t' to the stem (e.g., 'Kommt!'); for formal (Sie) use the infinitive + Sie (e.g., 'Kommen Sie!').","example":"Komm hier! Kommt hier! Kommen Sie hier!"},
        {"level":"A1","topic":"Definite & Indefinite Articles","keywords":["articles","der","die","das","ein","eine"],"explanation":"Definite (der, die, das) vs. indefinite (ein, eine) articles indicate gender and definiteness.","example":"Der Mann. Eine Frau."},
        {"level":"A1","topic":"Negation","keywords":["nicht","kein"],"explanation":"nicht negates verbs/adjectives; kein negates nouns.","example":"Ich komme nicht. Ich habe keinen Hund."},
        {"level":"A1","topic":"Modal Verbs","keywords":["können","müssen","dürfen","wollen","sollen"],"explanation":"Express ability, necessity, permission, or desire.","example":"Ich kann schwimmen."},
        {"level":"A1","topic":"Possessive Pronouns","keywords":["mein","dein","sein","ihr"],"explanation":"Indicate ownership: mein Buch, deine Tasche.","example":"Das ist mein Buch."},
        {"level":"A1","topic":"Adjective Endings (Basic)","keywords":["adjective endings","adjektivdeklination"],"explanation":"Basic adjective endings agree with the noun's gender, case, and number: der gute Mann, die schöne Blume.","example":"Die schöne Blume."},
        {"level":"A1","topic":"Adverbs (Basic)","keywords":["adverbs","adverbien"],"explanation":"Modify verbs, adjectives, or other adverbs: sehr (very), oft (often), hier (here), dort (there).","example":"Ich lerne sehr schnell."},
        {"level":"A1","topic":"Prepositions (2-way & Dative)","keywords":["prepositions","in","auf","mit"],"explanation":"Two-way prepositions use accusative for movement and dative for location; some prepositions (mit, zu) always take dative.","example":"Ich gehe in die Schule. Ich bin in der Schule. Ich fahre mit dem Bus."},
        {"level":"A1","topic":"Separable Verbs","keywords":["separable","verbs"],"explanation":"Prefixes separate in the present tense and move to the end of the clause: aufstehen, anrufen.","example":"Ich stehe um 7 Uhr auf."},
        {"level":"A1","topic":"Time & Date Expressions","keywords":["time","date","um","am","im"],"explanation":"Express times and dates: um 8 Uhr (time), am Montag (day), im Januar (month).","example":"Der Unterricht beginnt um 8 Uhr am Montag im Januar."},
        {"level":"A1","topic":"Common Connectors","keywords":["und","oder","aber","denn"],"explanation":"Basic coordinating conjunctions join clauses without changing word order: und (and), oder (or), aber (but), denn (because).","example":"Ich bin müde, aber glücklich."},
        {"level":"A1","topic":"Numbers & Dates","keywords":["numbers","dates"],"explanation":"Numbers and dates use cardinal and ordinal forms: eins, zwei; der 1. Januar.","example":"Heute ist der 1. Januar."},
{"level":"A1","topic":"Word Classes (Wortarten)","keywords":["wortarten","nouns","verbs","adjectives","adverbs","pronouns","articles","prepositions","conjunctions","numerals","interjections"],"explanation":"German Wortarten categorize words by function (e.g., nouns, verbs, adjectives, adverbs, pronouns, articles, prepositions, conjunctions, numerals, interjections).","example":"Das schnelle Auto fährt sehr laut."},
        {"level":"A1","topic":"Personal Pronouns","keywords":["ich","du","er","sie","es","wir","ihr","Sie"],"explanation":"Pronouns replace nouns: ich (I), du (you). Must match case, number, and gender.","example":"Ich bin Felix."},
        {"level":"A1","topic":"Nouns & Genders","keywords":["nouns","genders","genus"],"explanation":"All German nouns are capitalized and have three genders: der (masc), die (fem), das (neut).","example":"Der Tisch, die Lampe, das Auto."},
        {"level":"A1","topic":"Definite & Indefinite Articles Declension","keywords":["der","die","das","ein","eine"],"explanation":"Declines articles by case and number: Nom: der Mann/ein Mann; Acc: den Mann/einen Mann; Dat: dem Mann/einem Mann; Gen: des Mannes/eines Mannes.","example":"Nominativ: der Hund; Akkusativ: den Hund; Dativ: dem Hund; Genitiv: des Hundes."},
        {"level":"A1","topic":"Present Tense (Präsens)","keywords":["präsens","present"],"explanation":"Describes current or habitual actions; verb agrees with subject.","example":"Ich lerne Deutsch. Er spielt Fußball."},
        {"level":"A1","topic":"Modal Verbs Present Conjugation","keywords":["können","müssen","dürfen","wollen","sollen","mögen","möchten"],"explanation":"Present forms for modals: ich kann/muss/darf/will/soll/mag/möchte; du kannst/musst/darfst/willst/sollst/magst/möchtest.","example":"ich kann, du kannst; ich möchte, du möchtest."},
        {"level":"A1","topic":"Main Verbs Present Conjugation","keywords":["machen","gehen","haben","sein","sprechen"],"explanation":"Present forms for main verbs: ich mache/gehe/habe/bin/spreche; du machst/gehst/hast/bist/sprichst.","example":"ich mache, du machst; ich gehe, du gehst."},
        {"level":"A1","topic":"Modal Verbs Präteritum Conjugation","keywords":["dürfen","können","müssen","sollen","wollen","mögen","möchten"],"explanation":"Simple past for modals: ich durfte/konnte/musste/sollte/wollte/mochte/möchte;","example":"ich durfte, du durftest; ich mochte, du mochtest."},
        {"level":"A1","topic":"Statement Structure Rule","keywords":["statement rule","satzbau","svo"],"explanation":"In declarative sentences the finite verb is in the second position (SVO): Subject-Verb-Object.","example":"Ich kaufe einen Apfel."},
        {"level":"A1","topic":"Yes/No Questions","keywords":["yes or no questions","ja nein fragen","inversion"],"explanation":"Form yes/no questions by inverting subject and verb, without a question word.","example":"Kommst du morgen?"},
        {"level":"A1","topic":"W-Questions (W-Fragen)","keywords":["wer","was","wo","wann","warum","wie"],"explanation":"Use W-question words at the beginning; verb remains in second position.","example":"Wo wohnst du?"},
        {"level":"A1","topic":"Modal Verb Rule","keywords":["modal verb rule","modalverben"],"explanation":"Modal verbs occupy second position; the main infinitive goes to the end of the clause.","example":"Ich kann heute nicht kommen."},
        {"level":"A1","topic":"'Weil' Subordinate Clause Rule","keywords":["weil","subordinate clause","verb end"],"explanation":"In subordinate clauses with weil, the verb moves to the end of the clause.","example":"Ich bleibe zu Hause, weil ich krank bin."},
        {"level":"A1","topic":"Main Verbs Präteritum Conjugation","keywords":["machen","gehen","haben","sein","sprechen"],"explanation":"Simple past for main verbs: ich machte/ging/hatte/war/sprach;","example":"ich machte, du machtest; ich ging, du gingst."},
        # A2 Topics
        {"level":"A2","topic":"Accusative Prepositions","keywords":["bis","durch","für","gegen","ohne","um","entlang"],"explanation":"Always accusative: bis, durch, für, gegen, ohne, um, entlang.","example":"Ich gehe durch den Park."},
        {"level":"A2","topic":"Dative Prepositions","keywords":["aus","außer","bei","mit","nach","seit","von","zu","gegenüber"],"explanation":"Always dative: aus, außer, bei, mit, nach, seit, von, zu, gegenüber.","example":"Ich fahre mit dem Bus."},
        {"level":"A2","topic":"Two-way Prepositions (Full)","keywords":["an","auf","hinter","in","neben","über","unter","vor","zwischen"],"explanation":"Accusative for movement, dative for location for these preps.","example":"Ich lege das Buch auf den Tisch. Das Buch liegt auf dem Tisch."},
        # A2 Topics
        {"level":"A2","topic":"Dative Case Expanded","keywords":["dativ","wem"],"explanation":"The dative case marks indirect objects and answers 'Wem?'; verbs like helfen, danken, gehören require dative.","example":"Ich helfe meinem Freund."},
        {"level":"A2","topic":"Two-way Prepositions","keywords":["wechselpräpositionen","in","an","auf","über","unter","zwischen"],"explanation":"Use accusative for movement (Ich lege das Buch auf den Tisch) and dative for location (Das Buch liegt auf dem Tisch).","example":"Ich lege das Buch auf den Tisch."},
        {"level":"A2","topic":"Comparison of Adjectives","keywords":["komparativ","superlativ"],"explanation":"Form comparatives with -er + als and superlatives with am + adjective + -sten.","example":"Er ist schneller als ich. Er ist am schnellsten."},
        {"level":"A2","topic":"Perfect Tense (Perfekt)","keywords":["perfekt","haben","sein"],"explanation":"Formed with haben/sein + Partizip II to describe completed past actions; use sein for motion and change of state.","example":"Ich habe gegessen. Sie ist gekommen."},
        {"level":"A2","topic":"Future Tense (Futur I)","keywords":["futur","werden"],"explanation":"Use werden + infinitive to express future actions and predictions.","example":"Ich werde morgen lernen."},
        {"level":"A2","topic":"Reflexive Verbs","keywords":["reflexive","sich"],"explanation":"Use reflexive pronouns when subject and object refer to the same entity: Ich freue mich.","example":"Ich freue mich auf das Wochenende."},
        {"level":"A2","topic":"Subordinate Clauses","keywords":["weil","dass","wenn","ob"],"explanation":"In subordinate clauses introduced by conjunctions, the verb goes to the end of the clause.","example":"Ich komme nicht, weil ich krank bin."},
        {"level":"A2","topic":"Indirect Questions","keywords":["indirekte frage","wo","ob"],"explanation":"Use ob for yes/no indirect questions and question words for W-questions in reported speech.","example":"Ich weiß nicht, ob er kommt."},
        {"level":"A2","topic":"Relative Clauses","keywords":["relativsatz","der","die","das"],"explanation":"Provide additional information about a noun using relative pronouns and proper word order.","example":"Das ist der Mann, der Deutsch spricht."},
        {"level":"A2","topic":"Genitive Case","keywords":["genitiv","des","der"],"explanation":"Shows possession or relationships; used with genitive endings on articles or nouns.","example":"Das Buch des Bruders."},
        {"level":"A2","topic":"Adjective Endings After Articles","keywords":["adjective endings","adjektivdeklination"],"explanation":"Detailed adjective endings based on the gender, case, and type of article.","example":"eine rote Jacke, mit dem kleinen Kind."},
        {"level":"A2","topic":"Genitive Prepositions","keywords":["trotz","während","wegen","anstatt"],"explanation":"Prepositions that require the genitive case, expressing cause, time, or exception.","example":"Trotz des Regens gehen wir spazieren."},
        {"level":"A2","topic":"Separable & Inseparable Verbs","keywords":["trennbar","untrennbar"],"explanation":"Separable verbs detach their prefix; inseparable verbs keep it attached. Placement affects meaning.","example":"Ich stehe auf vs. Ich beschäftige mich."},
        {"level":"A2","topic":"Passive Voice (Present)","keywords":["passiv","werden","partizip"],"explanation":"Form passive sentence with werden + Partizip II to focus on the receiver of the action.","example":"Die Pizza wird geliefert."},
        {"level":"A2","topic":"Adverbs of Frequency & Degree","keywords":["oft","manchmal","sehr","kaum"],"explanation":"Use adverbs like oft, manchmal for frequency and sehr, kaum for degree to modify verbs.","example":"Ich bin meistens pünktlich."},
        {"level":"A2","topic":"TMP Rule","keywords":["time","manner","place"],"explanation":"Adverbs and adverbial phrases follow the order: Time - Manner - Place.","example":"Ich lerne heute gerne hier."},
        {"level":"A2","topic":"Common Connectors","keywords":["deshalb","außerdem","zwar aber"],"explanation":"Link ideas logically with connectors like deshalb, außerdem, zwar … aber.","example":"Ich lerne viel, deshalb verstehe ich besser."},
        # B1 Topics
        {"level":"B1","topic":"Simple Past (Präteritum)","keywords":["präteritum","past"],"explanation":"Primarily a written tense; regular verbs add -te, irregular verbs have stem changes.","example":"Ich ging gestern ins Kino."},
        {"level":"B1","topic":"Pluperfect (Plusquamperfekt)","keywords":["plusquamperfekt"],"explanation":"Describes an action completed before another past action: hatte/war + Partizip II.","example":"Ich hatte gegessen, bevor er kam."},
        {"level":"B1","topic":"Modal Verbs in Past","keywords":["modalverben","perfekt","müssen"],"explanation":"Combine modal verbs with haben + Partizip II for past necessity or ability.","example":"Ich habe arbeiten müssen."},
        {"level":"B1","topic":"Advanced Connectors","keywords":["zwar","aber","nicht nur","sondern"],"explanation":"Use advanced linking phrases like zwar … aber and nicht nur … sondern for nuance.","example":"Nicht nur lerne ich Deutsch, sondern ich spreche es täglich."},
        # B2 Topics
        {"level":"B2","topic":"Future Perfect (Futur II)","keywords":["futur II","future perfect"],"explanation":"Expresses that an action will have been completed by a future time: werde + Partizip II + sein/haben.","example":"Bis morgen werde ich den Brief geschrieben haben."},
        {"level":"B2","topic":"Passive Voice in All Tenses","keywords":["passiv","werden","partizip"],"explanation":"Form passive across tenses: Präsens (wird gemacht), Präteritum (wurde gemacht), Perfekt (ist gemacht worden).","example":"Das Buch wird gelesen. Das Buch ist gelesen worden."},
        {"level":"B2","topic":"Indirect Speech","keywords":["konjunktiv I","indirekte rede"],"explanation":"Report speech using Konjunktiv I for neutrality in reported statements.","example":"Er sagt, er habe Zeit."},
        {"level":"B2","topic":"Nominal Style","keywords":["nominalstil","nominalisierung"],"explanation":"Convert complex ideas into noun phrases for formal style (Nominalisierung).","example":"Sein Zuspätkommen war ein Problem."},
        {"level":"B2","topic":"Adverbial Participles","keywords":["partizipialkonstruktion","adverbial"],"explanation":"Use participle phrases to shorten subordinate clauses: Vom Regen überrascht, ging er nach Hause.","example":"Vom Regen überrascht, ging er nach Hause."}
    ]

# ---------- Step 3: Search Helper ----------
def search_grammar_topics(query, grammar_data, level_filter):
    query_keywords = [w.strip("?.!").lower() for w in query.split() if len(w) > 2]
    return [e for e in grammar_data if e['level'] in level_filter and any(qk in ak for qk in query_keywords for ak in e.get('keywords',[])+[e['topic'].lower()])]

# ---------- Step 4: Grammar Search UI ----------
def show_grammar_ui():
    grammar_data = load_grammar_data()
    level_filter = st.sidebar.multiselect("Select Level(s)", ["A1","A2","B1","B2"], default=["A1","A2","B1","B2"])
    query = st.text_input("🔍 Type a grammar question or keyword")
    if query:
        results = search_grammar_topics(query, grammar_data, level_filter)
        if results:
            for entry in results:
                st.subheader(f"{entry['topic']} ({entry['level']})")
                st.markdown(f"**Explanation:** {entry['explanation']}")
                st.markdown(f"**Example:** _{entry['example']}_")
                related = [t['topic'] for t in grammar_data if t['level']==entry['level'] and t['topic']!=entry['topic']]
                if related:
                    st.markdown(f"💡 **Related Topics:** {', '.join(related[:3])}")
                st.markdown("*Refer to your textbook or tutor for more detail.*")
        else:
            st.warning("No matching topics found.")

# ---------- Step 5: Letter & Essay Samples ----------
def show_letter_and_essay_samples():
    st.sidebar.markdown("---")
    samples = {
        "A1": {"intro":"Sehr geehrte Damen und Herren, ich hoffe, es geht Ihnen gut.","body":"Ich möchte einen Termin vereinbaren. Bitte teilen Sie mir mögliche Zeiten mit.","conclusion":"Ich freue mich im Voraus auf Ihre Rückmeldung. Mit freundlichen Grüßen, [Ihr Name]"},
        "A2": {"intro":"Hallo [Name], vielen Dank für deine Nachricht.","body":"Ich interessiere mich für Ihre Wohnung. Ist sie noch verfügbar?","conclusion":"Ich freue mich auf Ihre Antwort. Viele Grüße, [Ihr Name]"},
        "B1": {"intro":"Heutzutage ist das Thema Lernen ein wichtiges Thema in unserem Leben.","body":"Ich bin der Meinung, dass Lernen sehr wichtig ist, weil es uns hilft, unser Wissen zu erweitern. Einerseits gibt es viele Vorteile. Zum Beispiel hilft uns das Lernen mit Apps, flexibler und schneller zu lernen.","conclusion":"Abschließend lässt sich sagen, dass Lernen mit neuen Methoden sehr nützlich ist, auch wenn es manchmal herausfordernd sein kann."},
        "B2": {"intro":"In der heutigen digitalen Ära spielt Social Media eine zentrale Rolle in unserem Alltag.","body":"Während es die Kommunikation erleichtert, kann es auch zu Ablenkung und oberflächlichen Interaktionen führen.","conclusion":"Letztendlich hängt der Nutzen von Social Media von bewusster Nutzung ab."}
    }
    levels = st.sidebar.multiselect("Show Letters/Essays for:", ["A1","A2","B1","B2"], default=["A1","A2","B1","B2"])
    if st.sidebar.checkbox("📬 Show Letter Samples"):
        st.subheader("📬 Letter Samples")
        for lvl in levels:
            sample = samples.get(lvl)
            if sample:
                st.markdown(f"**{lvl} Letter:**")
                st.markdown(f"- **Introduction:** {sample['intro']}")
                st.markdown(f"- **Body:** {sample['body']}")
                st.markdown(f"- **Conclusion:** {sample['conclusion']}")
    if st.sidebar.checkbox("📝 Show Essay Samples"):
        st.subheader("📝 Essay Samples")
        for lvl in levels:
            sample = samples.get(lvl)
            if sample:
                st.markdown(f"**{lvl} Essay:**")
                st.markdown(f"- **Introduction:** {sample['intro']}")
                st.markdown(f"- **Body:** {sample['body']}")
                st.markdown(f"- **Conclusion:** {sample['conclusion']}")

# ---------- Step 6: Main ----------
def main():
    setup_app()
    student_code = show_student_login()
    if student_code and student_code in load_student_codes():
        show_letter_and_essay_samples()
        show_grammar_ui()
    else:
        st.warning("Enter a valid student code to proceed.")

if __name__ == "__main__":
    main()
