"""Interactive flyer builder for proposal PDF downloads."""
import pathlib
import textwrap
from typing import List

from fpdf import FPDF
import streamlit as st

st.set_page_config(page_title="Proposal Flyer Builder", page_icon="📰", layout="centered")

base_path = pathlib.Path(__file__).resolve().parents[1]
logo_path = base_path / "ChatGPT Image Dec 9, 2025, 10_21_14 AM.png"
font_path = base_path / "font" / "DejaVuSans.ttf"


def _load_font_family(pdf: FPDF) -> str:
    """Return the preferred font family available to the PDF."""
    if font_path.exists():
        pdf.add_font("DejaVu", fname=str(font_path), uni=True)
        return "DejaVu"
    return "Arial"


def _normalise_lines(raw: str) -> List[str]:
    """Split a textarea payload into non-empty, trimmed lines."""
    return [line.strip() for line in raw.splitlines() if line.strip()]


def build_flyer_pdf(
    *,
    company: str,
    tagline: str,
    description: str,
    highlights: List[str],
    services: List[str],
    contact_email: str,
    contact_phone: str,
    website: str,
    call_to_action: str,
) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    font_family = _load_font_family(pdf)

    pdf.set_text_color(32, 32, 32)
    pdf.set_font(font_family, "B", 20)
    pdf.cell(0, 12, company, ln=True)

    if tagline:
        pdf.set_font(font_family, "I", 13)
        pdf.set_text_color(80, 80, 80)
        pdf.multi_cell(0, 8, tagline)
        pdf.ln(2)

    if logo_path.exists():
        pdf.image(str(logo_path), w=45)
        pdf.ln(4)

    pdf.set_text_color(32, 32, 32)
    pdf.set_font(font_family, size=12)
    pdf.multi_cell(0, 8, description.strip())
    pdf.ln(3)

    if highlights:
        pdf.set_font(font_family, "B", 14)
        pdf.cell(0, 10, "Highlights", ln=True)
        pdf.set_font(font_family, size=12)
        for item in highlights:
            pdf.cell(5)
            pdf.cell(0, 8, f"• {item}", ln=True)
        pdf.ln(2)

    if services:
        pdf.set_font(font_family, "B", 14)
        pdf.cell(0, 10, "Key Services", ln=True)
        pdf.set_font(font_family, size=12)
        for service in services:
            pdf.cell(5)
            pdf.cell(0, 8, f"• {service}", ln=True)
        pdf.ln(2)

    pdf.set_font(font_family, "B", 14)
    pdf.cell(0, 10, "Contact & Demo", ln=True)
    pdf.set_font(font_family, size=12)
    pdf.multi_cell(
        0,
        8,
        textwrap.dedent(
            f"""
            Email: {contact_email}
            Phone / WhatsApp: {contact_phone}
            Website: {website}
            """
        ).strip(),
    )
    pdf.ln(2)

    if call_to_action:
        pdf.set_font(font_family, "B", 13)
        pdf.set_text_color(0, 86, 179)
        pdf.multi_cell(0, 8, call_to_action.strip())

    pdf_bytes = pdf.output(dest="S")
    if isinstance(pdf_bytes, str):
        return pdf_bytes.encode("latin1")
    return bytes(pdf_bytes)


st.title("📰 Proposal Flyer Builder")
st.caption("Create a concise flyer and download it as a PDF for sharing.")

with st.form("flyer_form"):
    company = st.text_input("Company / brand name", value="Xenom IT Systems")
    tagline = st.text_input("Tagline", value="Smart, simple software for churches, businesses, and schools.")
    description = st.text_area(
        "Short description",
        value=(
            "We build practical digital tools that solve real problems in church administration, "
            "business inventory & sales, and German language learning."
        ),
    )
    highlights_raw = st.text_area(
        "Highlights (one per line)",
        value="Reliable cloud hosting\nFriendly support team\nLocal expertise for Ghana",
    )
    services_raw = st.text_area(
        "Key services (one per line)",
        value="Apzla – Church administration\nSedifex – Inventory & POS\nFalowen – German learning platform",
    )
    contact_email = st.text_input("Contact email", value="sedifexbiz@gmail.com")
    contact_phone = st.text_input("Phone / WhatsApp", value="+233 59 505 4266")
    website = st.text_input("Website", value="www.sedifex.com")
    call_to_action = st.text_area("Call to action", value="Book a free 20-minute demo today.")

    submitted = st.form_submit_button("Generate flyer")

if submitted:
    highlights = _normalise_lines(highlights_raw)
    services = _normalise_lines(services_raw)
    flyer_pdf = build_flyer_pdf(
        company=company,
        tagline=tagline,
        description=description,
        highlights=highlights,
        services=services,
        contact_email=contact_email,
        contact_phone=contact_phone,
        website=website,
        call_to_action=call_to_action,
    )

    st.success("Flyer generated! Download the PDF below.")
    st.download_button(
        "⬇️ Download flyer as PDF",
        data=flyer_pdf,
        file_name="proposal_flyer.pdf",
        mime="application/pdf",
    )
    st.write("Preview of your details:")
    st.json(
        {
            "company": company,
            "tagline": tagline,
            "highlights": highlights,
            "services": services,
            "contact_email": contact_email,
            "contact_phone": contact_phone,
            "website": website,
            "call_to_action": call_to_action,
        }
    )
else:
    st.info("Fill in the form and click **Generate flyer** to download your PDF.")
