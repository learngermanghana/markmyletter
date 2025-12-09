import pathlib
import textwrap

from fpdf import FPDF
import streamlit as st

st.set_page_config(page_title="Xenom IT Systems Proposal", page_icon="🖋️", layout="centered")

base_path = pathlib.Path(__file__).resolve().parents[1]
logo_path = base_path / "ChatGPT Image Dec 9, 2025, 10_21_14 AM.png"
font_path = base_path / "font" / "DejaVuSans.ttf"


class ProposalPDF(FPDF):
    def __init__(self, font_family: str):
        super().__init__()
        self.font_family = font_family

    def footer(self):
        self.set_y(-15)
        self.set_font(self.font_family, size=9)
        self.set_text_color(90, 90, 90)
        self.cell(0, 10, f"Prepared for: Xenom IT Systems · Page {self.page_no()} of {{nb}}", align="C")


@st.cache_data
def build_proposal_pdf() -> bytes:
    if font_path.exists():
        ProposalPDF.add_font("DejaVu", fname=str(font_path), uni=True)
        font_family = "DejaVu"
    else:
        font_family = "Arial"

    pdf = ProposalPDF(font_family=font_family)
    pdf.alias_nb_pages()
    pdf.set_title("Xenom IT Systems Proposal")
    pdf.set_author("Xenom IT Solutions")
    pdf.add_page()

    pdf.set_font(font_family, size=16)
    pdf.cell(0, 10, "Proposal Letter for Xenom IT Systems", ln=True)
    pdf.set_font(font_family, size=12)
    pdf.cell(0, 8, "A concise overview of our software solutions and contact details.", ln=True)
    pdf.ln(5)

    if logo_path.exists():
        pdf.image(str(logo_path), w=60)
        pdf.ln(5)

    pdf.set_font(font_family, size=14)
    pdf.cell(0, 10, "Who We Are", ln=True)
    pdf.set_font(font_family, size=12)
    pdf.multi_cell(
        0,
        8,
        textwrap.dedent(
            """
            Xenom IT Solutions is a Ghana-based software company building practical digital tools that solve real problems in
            church administration, business inventory & sales, and German language learning. We are the creators of Apzla,
            Sedifex, and Falowen.
            """
        ).replace("\n", " "),
    )
    pdf.ln(2)

    pdf.set_font(font_family, size=14)
    pdf.cell(0, 10, "Our Solutions", ln=True)
    pdf.set_font(font_family, size=12)
    pdf.multi_cell(
        0,
        8,
        textwrap.dedent(
            """
            Quick feature highlights:
            • Apzla: member records, attendance tracking
            • Sedifex: POS + CRM
            • Falowen: exam prep support
            """
        ).strip(),
    )
    pdf.ln(2)

    pdf.set_font(font_family, size=12)
    pdf.cell(0, 8, "1. Apzla - For Churches", ln=True)
    pdf.set_font(font_family, size=12)
    pdf.multi_cell(
        0,
        8,
        textwrap.dedent(
            """
            A simple digital system to help churches stay organised and connected. Apzla helps you:
            - Keep proper member and visitor records
            - Track attendance for services and events
            - Support departments and ministries with accurate data
            - Share announcements and reminders more efficiently
            For churches and ministries that want to move from paper & scattered WhatsApp chats to one organised system.
            """
        ).strip(),
    )
    pdf.ln(1)

    pdf.set_font(font_family, size=12)
    pdf.cell(0, 8, "2. Sedifex - For Businesses", ln=True)
    pdf.set_font(font_family, size=12)
    pdf.multi_cell(
        0,
        8,
        textwrap.dedent(
            """
            An inventory and sales system for all kinds of businesses and consultancies running a point of sale with customer
            relationship management. Sedifex helps you:
            - Track stock and inventory in real time
            - Record sales and transactions
            - Manage customers and contacts (basic CRM)
            - See simple reports to guide decisions
            For shops, pharmacies, small supermarkets, service businesses, and any organisation that needs clear stock and customer records.
            """
        ).strip(),
    )
    pdf.ln(1)

    pdf.set_font(font_family, size=12)
    pdf.cell(0, 8, "3. Falowen - For German Learning", ln=True)
    pdf.set_font(font_family, size=12)
    pdf.multi_cell(
        0,
        8,
        textwrap.dedent(
            """
            A digital platform for German learning and exam preparation, designed to work with schools, training centres, and private tutors.
            Falowen helps you:
            - Support students preparing for Goethe and other exams
            - Provide structured practice for vocabulary, grammar, and speaking
            - Offer a digital extension of your classroom teaching
            For schools and language centres that want a modern tool to support their German programmes.
            """
        ).strip(),
    )
    pdf.ln(2)

    pdf.set_font(font_family, size=14)
    pdf.cell(0, 10, "Demo & Contact", ln=True)
    pdf.set_font(font_family, size=12)
    pdf.cell(0, 8, "Apzla (churches) & Sedifex (businesses)", ln=True)
    pdf.set_font(font_family, size=12)
    pdf.multi_cell(
        0,
        8,
        "Email: sedifexbiz@gmail.com\n"
        "Phone / WhatsApp: +233 59 505 4266\n"
        "Website: www.sedifex.com",
    )
    pdf.ln(1)
    pdf.set_font(font_family, size=12)
    pdf.cell(0, 8, "Falowen (German learning & schools)", ln=True)
    pdf.set_font(font_family, size=12)
    pdf.multi_cell(
        0,
        8,
        "Email: learngermanghana@gmail.com\n"
        "Phone / WhatsApp: +233 20 570 6589\n"
        "Websites: www.falowen.app | www.learngermanghana.com",
    )

    # fpdf may return either ``str`` (pyfpdf) or ``bytearray`` (fpdf2) when
    # ``dest="S"`` is used. Streamlit's ``download_button`` expects a ``bytes``
    # payload, so normalise the output to bytes and only encode if the library
    # returned text.
    pdf_bytes = pdf.output(dest="S")
    if isinstance(pdf_bytes, str):
        return pdf_bytes.encode("latin1")
    return bytes(pdf_bytes)


st.title("🖋️ Proposal Letter for Xenom IT Systems")
st.caption("A concise overview of our software solutions and contact details.")

st.download_button(
    "⬇️ Download proposal as PDF",
    data=build_proposal_pdf(),
    file_name="xenom_it_systems_proposal.pdf",
    mime="application/pdf",
)

if logo_path.exists():
    st.image(str(logo_path), caption="Xenom IT Systems", use_column_width=True)

st.markdown("""
**Xenom IT Solutions**
Smart, simple software for churches, businesses, and schools.
""")

st.divider()

st.header("Who We Are")
st.write(
    "Xenom IT Solutions is a Ghana-based software company building practical digital tools "
    "that solve real problems in church administration, business inventory & sales, and German language learning. "
    "We are the creators of Apzla, Sedifex, and Falowen."
)

st.divider()

st.header("Our Solutions")
st.markdown(
    """
    **Quick feature highlights**
    - **Apzla:** Member records, attendance tracking
    - **Sedifex:** POS + CRM
    - **Falowen:** Exam prep support
    """
)

col1, col2 = st.columns(2, gap="large")
with col1:
    st.subheader("1. Apzla – For Churches")
    st.write(
        textwrap.dedent(
            """
            A simple digital system to help churches stay organised and connected.
            Apzla helps you:
            • Keep proper member and visitor records
            • Track attendance for services and events
            • Support departments and ministries with accurate data
            • Share announcements and reminders more efficiently

            For churches and ministries that want to move from paper & scattered WhatsApp chats to one organised system.
            """
        ).strip()
    )

with col2:
    st.subheader("2. Sedifex – For Businesses")
    st.write(
        textwrap.dedent(
            """
            An inventory and sales system for all kinds of businesses and consultancies running a point of sale with customer relationship management.
            Sedifex helps you:
            • Track stock and inventory in real time
            • Record sales and transactions
            • Manage customers and contacts (basic CRM)
            • See simple reports to guide decisions

            For shops, pharmacies, small supermarkets, service businesses, and any organisation that needs clear stock and customer records.
            """
        ).strip()
    )

st.subheader("3. Falowen – For German Learning")
st.write(
    textwrap.dedent(
        """
        A digital platform for German learning and exam preparation, designed to work with schools, training centres, and private tutors.
        Falowen helps you:
        • Support students preparing for Goethe and other exams
        • Provide structured practice for vocabulary, grammar, and speaking
        • Offer a digital extension of your classroom teaching

        For schools and language centres that want a modern tool to support their German programmes.
        """
    ).strip()
)

st.divider()

st.header("Demo & Contact")

contact_col1, contact_col2 = st.columns(2, gap="large")
with contact_col1:
    st.subheader("Apzla (churches) & Sedifex (businesses)")
    st.write(
        """
        Email: sedifexbiz@gmail.com
        Phone / WhatsApp: +233 59 505 4266
        Website: [www.sedifex.com](https://www.sedifex.com)
        """
    )

with contact_col2:
    st.subheader("Falowen (German learning & schools)")
    st.write(
        """
        Email: learngermanghana@gmail.com
        Phone / WhatsApp: +233 20 570 6589
        Websites: [www.falowen.app](https://www.falowen.app)
        [www.learngermanghana.com](https://www.learngermanghana.com)
        """
    )

st.info(
    "Choose the solution that fits you and contact us for a demo or meeting."
)
