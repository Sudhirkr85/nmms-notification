import os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def generate_up_answer_key_pdf(output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'MainTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=15,
        alignment=1,
        textColor=colors.HexColor('#0d47a1'),
        spaceAfter=6
    )

    subtitle_style = ParagraphStyle(
        'SubTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        alignment=1,
        textColor=colors.HexColor('#1b5e20'),
        spaceAfter=12
    )

    badge_style = ParagraphStyle(
        'Badge',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        alignment=1,
        textColor=colors.HexColor('#b71c1c'),
        spaceAfter=15
    )

    heading2 = ParagraphStyle(
        'Heading2Custom',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        textColor=colors.HexColor('#0d47a1'),
        spaceBefore=10,
        spaceAfter=6
    )

    body_style = ParagraphStyle(
        'BodyCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#212121')
    )

    bold_body = ParagraphStyle(
        'BoldBody',
        parent=body_style,
        fontName='Helvetica-Bold'
    )

    footer_style = ParagraphStyle(
        'FooterCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        alignment=1,
        textColor=colors.HexColor('#555555'),
        spaceBefore=15
    )

    elements = []

    # Header
    elements.append(Paragraph("EXAMINATION REGULATORY AUTHORITY, UTTAR PRADESH, PRAYAGRAJ", title_style))
    elements.append(Paragraph("Office of the Secretary, Pariksha Niyamak Pradhikari (PNP), Allenganj, Prayagraj", subtitle_style))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#0d47a1'), spaceAfter=12))

    # Badge
    elements.append(Paragraph("NATIONAL MEANS-CUM-MERIT SCHOLARSHIP (NMMS) 2027-28", badge_style))
    elements.append(Paragraph("OFFICIAL NOTICE: PROVISIONAL ANSWER KEY &amp; OBJECTION PROCEDURE", ParagraphStyle('SubNotice', parent=subtitle_style, fontSize=11, textColor=colors.HexColor('#b71c1c'))))

    # Summary Table
    table_data = [
        [Paragraph("<b>Examination Name</b>", bold_body), Paragraph("National Means-cum-Merit Scholarship (NMMS) 2027-28", body_style)],
        [Paragraph("<b>Conducting State</b>", bold_body), Paragraph("Uttar Pradesh (All 75 Districts)", body_style)],
        [Paragraph("<b>Examination Date</b>", bold_body), Paragraph("01 November 2026 (Sunday)", body_style)],
        [Paragraph("<b>Target Candidates</b>", bold_body), Paragraph("Class 8 Students Studying in Govt / Aided Schools", body_style)],
        [Paragraph("<b>Test Structure</b>", bold_body), Paragraph("MAT (90 Marks) + SAT (90 Marks) = 180 Marks Total", body_style)],
        [Paragraph("<b>Provisional Key Status</b>", bold_body), Paragraph("RELEASED on Official Portal (entdata.co.in)", bold_body)],
        [Paragraph("<b>Objection Window</b>", bold_body), Paragraph("<b>Active Now &mdash; Closes 13 November 2026 (06:00 PM)</b>", bold_body)],
        [Paragraph("<b>Objection Mode</b>", bold_body), Paragraph("Online via Email to: <b>nmmsntsexam@gmail.com</b>", bold_body)]
    ]

    t = Table(table_data, colWidths=[160, 370])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f9f9f9')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 14))

    # Important Instructions
    elements.append(Paragraph("IMPORTANT GUIDELINES FOR CANDIDATES &amp; PARENTS", heading2))

    instructions = [
        "<b>1. Verification of Responses:</b> All students who appeared in the NMMS 2027-28 examination held on 01.11.2026 are advised to download the provisional answer key from the official website <b>entdata.co.in</b> and match their responses for both Mental Ability Test (MAT) and Scholastic Aptitude Test (SAT).",
        "<b>2. Submission of Objections:</b> If any candidate finds any discrepancy, ambiguity, or error in any question or answer key, they must send their representation/objection via email to the designated official email ID: <b>nmmsntsexam@gmail.com</b>.",
        "<b>3. Strict Deadline:</b> Objections will be accepted ONLY up to <b>13 November 2026 (06:00 PM)</b>. Representations received after this deadline will NOT be entertained under any circumstances.",
        "<b>4. Mandatory Documentary Evidence:</b> Clear proof/evidence supporting your objection (reference from NCERT/SCERT textbook or authorized educational material) MUST be attached with the email. Objections submitted without authentic documentary proof will be summarily rejected.",
        "<b>5. Permissible Mode:</b> Objections are accepted strictly through the official email. Representations submitted in person, by speed post/registered post, or over telephone/WhatsApp will NOT be considered.",
        "<b>6. Final Answer Key &amp; Evaluation:</b> All submitted objections will be examined by a panel of subject matter experts. Based on their recommendations, the Final Answer Key and Merit List (Result) will be compiled and published on entdata.co.in."
    ]

    for inst in instructions:
        elements.append(Paragraph(inst, body_style))
        elements.append(Spacer(1, 6))

    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#cccccc'), spaceAfter=8))

    # Coaching Footer
    elements.append(Paragraph("<b>Official Website:</b> https://entdata.co.in | <b>Official Email:</b> nmmsntsexam@gmail.com", footer_style))
    elements.append(Paragraph("<b>Notice Circulated by: Sagar Coaching Centre, Bhagwanpur</b> | YouTube: Sagar Coaching Centre Bhagwanpur", footer_style))
    elements.append(Paragraph("Helpline / WhatsApp: +91 91101 13671 | Dedicated to NMMS Excellence", footer_style))

    doc.build(elements)
    print(f"Successfully generated official PDF at: {output_path}")

if __name__ == "__main__":
    generate_up_answer_key_pdf("data/documents/UP_NMMS_2027_28_Answer_Key_Notice.pdf")
