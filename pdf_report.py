"""
pdf_report.py  --  One-page branded PDF advisory.

Generates a single-page PDF showing old vs new regime comparison,
winner highlight, key figures, the deduction-sweep chart, and a mandatory
tax disclaimer.

The body is built with ReportLab Platypus (Frame + flowables) so content
flows and can never overlap, regardless of how many deduction rows each
regime carries.  Fixed page chrome (header band, synthetic-data strip,
footer, corner waves) is drawn on the canvas via the page template.

Uses the brand constants from instructions.md ss5.5.
Font: Tahoma if embeddable; else Helvetica (built-in fallback).
"""

from __future__ import annotations

import io
from datetime import date
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
    Image,
)

from regime_engine import TaxResult, RegimeBreakdown

# ---------------------------------------------------------------------------
# Brand colours (instructions.md ss5.5)
# ---------------------------------------------------------------------------
SEA_GREEN       = colors.HexColor("#4DBBAE")
SEA_GREEN_LIGHT = colors.HexColor("#B5E2D9")
SEA_GREEN_WASH  = colors.HexColor("#E1EFEC")
SEA_GREEN_DEEP  = colors.HexColor("#2A8676")
CREAM           = colors.HexColor("#F8F6EF")
SLATE_INK       = colors.HexColor("#2E3A36")
MUTED_SAGE      = colors.HexColor("#6B7570")
HAIRLINE        = colors.HexColor("#D6DBD7")
STATUS_FAV      = colors.HexColor("#B8DAB8")
STATUS_UNFAV    = colors.HexColor("#F4C9C9")
OLD_LINE        = colors.HexColor("#F4C9B6")  # old-regime line colour (chart)

# ---------------------------------------------------------------------------
# Font registration (try Tahoma; fall back to built-in Helvetica)
# ---------------------------------------------------------------------------
_FONT_REGULAR = "Helvetica"
_FONT_BOLD    = "Helvetica-Bold"

def _try_register_tahoma() -> bool:
    """Attempt to register Tahoma from the Windows font directory."""
    import os
    win_fonts = r"C:\Windows\Fonts"
    try:
        pdfmetrics.registerFont(TTFont("Tahoma", os.path.join(win_fonts, "tahoma.ttf")))
        pdfmetrics.registerFont(TTFont("Tahoma-Bold", os.path.join(win_fonts, "tahomabd.ttf")))
        global _FONT_REGULAR, _FONT_BOLD
        _FONT_REGULAR = "Tahoma"
        _FONT_BOLD    = "Tahoma-Bold"
        return True
    except Exception:
        return False

_try_register_tahoma()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inr(n: float) -> str:
    """Format as Indian Rs with lakh-crore grouping, e.g. Rs 1,23,456."""
    n = int(round(n))
    negative = n < 0
    s = str(abs(n))
    if len(s) <= 3:
        grouped = s
    else:
        grouped = s[-3:]
        s = s[:-3]
        while len(s) > 2:
            grouped = s[-2:] + "," + grouped
            s = s[:-2]
        grouped = s + "," + grouped
    return ("-Rs " if negative else "Rs ") + grouped


# ---------------------------------------------------------------------------
# Paragraph styles
# ---------------------------------------------------------------------------

def _styles() -> dict:
    return {
        "section": ParagraphStyle(
            "section", fontName=_FONT_BOLD, fontSize=7, leading=9,
            textColor=SEA_GREEN_DEEP, alignment=TA_LEFT, spaceBefore=1, spaceAfter=1),
        "label": ParagraphStyle(
            "label", fontName=_FONT_REGULAR, fontSize=7, leading=8.5,
            textColor=MUTED_SAGE, alignment=TA_LEFT),
        "label_bold": ParagraphStyle(
            "label_bold", fontName=_FONT_BOLD, fontSize=7.5, leading=9,
            textColor=SLATE_INK, alignment=TA_LEFT),
        "value": ParagraphStyle(
            "value", fontName=_FONT_REGULAR, fontSize=7, leading=8.5,
            textColor=SLATE_INK, alignment=TA_RIGHT),
        "value_bold": ParagraphStyle(
            "value_bold", fontName=_FONT_BOLD, fontSize=7.5, leading=9,
            textColor=SLATE_INK, alignment=TA_RIGHT),
        "value_credit": ParagraphStyle(
            "value_credit", fontName=_FONT_REGULAR, fontSize=7, leading=8.5,
            textColor=SEA_GREEN_DEEP, alignment=TA_RIGHT),
        "header_win": ParagraphStyle(
            "header_win", fontName=_FONT_BOLD, fontSize=8.5, leading=10,
            textColor=colors.white, alignment=TA_CENTER),
        "header_lose": ParagraphStyle(
            "header_lose", fontName=_FONT_BOLD, fontSize=8.5, leading=10,
            textColor=SLATE_INK, alignment=TA_CENTER),
        "total_label": ParagraphStyle(
            "total_label", fontName=_FONT_BOLD, fontSize=8.5, leading=10,
            textColor=SLATE_INK, alignment=TA_LEFT),
        "total_value": ParagraphStyle(
            "total_value", fontName=_FONT_BOLD, fontSize=8.5, leading=10,
            textColor=SLATE_INK, alignment=TA_RIGHT),
        "winner": ParagraphStyle(
            "winner", fontName=_FONT_BOLD, fontSize=10, leading=12,
            textColor=colors.white, alignment=TA_CENTER),
        "howto": ParagraphStyle(
            "howto", fontName=_FONT_REGULAR, fontSize=7.5, leading=9.5,
            textColor=SLATE_INK, alignment=TA_LEFT),
        "chart_cap": ParagraphStyle(
            "chart_cap", fontName=_FONT_BOLD, fontSize=7.5, leading=9.5,
            textColor=SEA_GREEN_DEEP, alignment=TA_LEFT),
        "disc_head": ParagraphStyle(
            "disc_head", fontName=_FONT_BOLD, fontSize=7, leading=9,
            textColor=SEA_GREEN_DEEP, alignment=TA_LEFT),
        "disc_body": ParagraphStyle(
            "disc_body", fontName=_FONT_REGULAR, fontSize=6.5, leading=8.5,
            textColor=MUTED_SAGE, alignment=TA_LEFT),
    }


# ---------------------------------------------------------------------------
# One regime breakdown as a flowing Table
# ---------------------------------------------------------------------------

def _regime_table(r: RegimeBreakdown, is_winner: bool, col_w: float, S: dict) -> Table:
    """Build one regime's tax breakdown as a Table whose rows auto-size."""
    val_w = 64
    label_w = col_w - val_w

    rows: list[list] = []
    styles: list[tuple] = []

    def add(cells, height=None):
        rows.append(cells)

    # --- Header row (spans both columns) ---
    regime_label = "NEW REGIME" if r.regime == "new" else "OLD REGIME"
    if is_winner:
        regime_label += "  — RECOMMENDED"
    head_style = S["header_win"] if is_winner else S["header_lose"]
    hi = len(rows)
    add([Paragraph(regime_label, head_style), ""])
    styles.append(("SPAN", (0, hi), (1, hi)))
    styles.append(("BACKGROUND", (0, hi), (1, hi),
                   SEA_GREEN if is_winner else SEA_GREEN_WASH))
    styles.append(("TOPPADDING", (0, hi), (1, hi), 4))
    styles.append(("BOTTOMPADDING", (0, hi), (1, hi), 4))

    # --- Gross taxable salary ---
    gi = len(rows)
    add([Paragraph("Gross taxable salary", S["section"]), ""])
    styles.append(("SPAN", (0, gi), (1, gi)))
    add([Paragraph("Gross salary (CTC less PF and gratuity)", S["label"]),
         Paragraph(_inr(r.gross_income), S["value"])])

    # --- Deductions ---
    di = len(rows)
    add([Paragraph("Deductions", S["section"]), ""])
    styles.append(("SPAN", (0, di), (1, di)))
    for label, amt in r.deductions.items():
        if amt > 0:
            add([Paragraph(label, S["label"]),
                 Paragraph(_inr(amt), S["value"])])

    ti = len(rows)
    add([Paragraph("Total deductions", S["section"]),
         Paragraph("(" + _inr(r.total_deductions) + ")", S["value_credit"])])
    styles.append(("LINEBELOW", (0, ti), (1, ti), 0.4, HAIRLINE))

    # --- Taxable income ---
    xi = len(rows)
    add([Paragraph("Taxable income", S["label_bold"]),
         Paragraph(_inr(r.taxable_income), S["value_bold"])])
    styles.append(("LINEBELOW", (0, xi), (1, xi), 0.4, HAIRLINE))

    # --- Tax computation ---
    ci = len(rows)
    add([Paragraph("Tax computation", S["section"]), ""])
    styles.append(("SPAN", (0, ci), (1, ci)))
    add([Paragraph("Slab tax", S["label"]),
         Paragraph(_inr(r.base_tax), S["value"])])
    if r.rebate > 0:
        add([Paragraph("Sec 156 rebate", S["label"]),
             Paragraph("(" + _inr(r.rebate) + ")", S["value_credit"])])
    if r.marginal_relief_rebate > 0:
        add([Paragraph("Rebate marginal relief", S["label"]),
             Paragraph("(" + _inr(r.marginal_relief_rebate) + ")", S["value_credit"])])
    if r.surcharge > 0:
        add([Paragraph("Surcharge", S["label"]),
             Paragraph(_inr(r.surcharge), S["value"])])
    if r.marginal_relief_surcharge > 0:
        add([Paragraph("Surcharge marginal relief", S["label"]),
             Paragraph("(" + _inr(r.marginal_relief_surcharge) + ")", S["value_credit"])])
    add([Paragraph("Health and Education Cess (4%)", S["label"]),
         Paragraph(_inr(r.cess), S["value"])])

    # --- Total tax liability (highlighted) ---
    li = len(rows)
    add([Paragraph("Total tax liability", S["total_label"]),
         Paragraph(_inr(r.total_tax), S["total_value"])])
    styles.append(("BACKGROUND", (0, li), (1, li),
                   STATUS_FAV if is_winner else STATUS_UNFAV))
    styles.append(("TOPPADDING", (0, li), (1, li), 4))
    styles.append(("BOTTOMPADDING", (0, li), (1, li), 4))

    # --- Effective rate ---
    add([Paragraph(f"Effective rate on CTC: {r.effective_rate_pct}%", S["label"]), ""])
    styles.append(("SPAN", (0, len(rows) - 1), (1, len(rows) - 1)))

    base_style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]
    t = Table(rows, colWidths=[label_w, val_w])
    t.setStyle(TableStyle(base_style + styles))
    return t


# ---------------------------------------------------------------------------
# Matplotlib deduction-sweep chart -> PNG bytes  (FIX 6)
# ---------------------------------------------------------------------------

def render_sweep_chart_png(sweep, dpi: int = 150) -> bytes:
    """
    Render a static copy of the deduction-sweep chart with matplotlib and
    return PNG bytes.  Same series and colours as the Plotly chart in app.py:
    old line falling, new line flat, vertical marker at current deductions, a
    marked crossover.  Kept matplotlib-only (no kaleido/headless Chrome) so it
    is reliable on Streamlit Cloud.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = [d / 1_00_000 for d in sweep.ded_levels]
    old = [t / 1_00_000 for t in sweep.old_taxes]
    new = [t / 1_00_000 for t in sweep.new_taxes]

    fig, ax = plt.subplots(figsize=(7.0, 2.25), dpi=dpi)
    fig.patch.set_facecolor("#F8F6EF")
    ax.set_facecolor("#F8F6EF")

    ax.plot(x, old, color="#F4C9B6", lw=2.0, label="Old regime")
    ax.plot(x, new, color="#4DBBAE", lw=2.0, label="New regime")

    # Current-deduction marker
    cur_x = sweep.current_ded / 1_00_000
    ax.axvline(cur_x, color="#2A8676", ls=":", lw=1.3)
    ax.annotate(
        f"Current  {_inr(sweep.current_ded)}",
        xy=(cur_x, max(new)), xytext=(3, 2), textcoords="offset points",
        fontsize=7, color="#2A8676", ha="left", va="bottom",
    )

    # Crossover marker
    if sweep.breakeven_ded is not None:
        bx = sweep.breakeven_ded / 1_00_000
        by = sweep.breakeven_tax / 1_00_000
        ax.plot([bx], [by], marker="o", mfc="none", mec="#2A8676", ms=8, mew=2)
        ax.annotate(
            f"Breakeven  {_inr(sweep.breakeven_ded)}",
            xy=(bx, by), xytext=(4, 10), textcoords="offset points",
            fontsize=7, color="#2A8676",
            arrowprops=dict(arrowstyle="->", color="#2A8676", lw=1),
        )

    ax.set_xlabel("Deductions claimed (Rs Lakhs)", fontsize=8, color="#2E3A36")
    ax.set_ylabel("Total tax (Rs Lakhs)", fontsize=8, color="#2E3A36")
    ax.tick_params(labelsize=7, colors="#6B7570")
    ax.grid(True, color="#D6DBD7", lw=0.6)
    for spine in ax.spines.values():
        spine.set_color("#6B7570")
        spine.set_linewidth(0.6)
    ax.legend(fontsize=7, facecolor="#F8F6EF", edgecolor="#D6DBD7", loc="upper right")

    fig.tight_layout(pad=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Page chrome (drawn on the canvas, fixed position)
# ---------------------------------------------------------------------------

DISCLAIMER = (
    "DISCLAIMER: This document is prepared for illustrative purposes only using synthetic data. "
    "It does not constitute tax advice. Tax liability depends on individual circumstances, "
    "age, other income sources, and final declarations. Consult a Chartered Accountant "
    "or tax professional before making a regime choice."
)

_MARGIN = 18 * mm


def _draw_chrome(c: canvas.Canvas, doc) -> None:
    """Draw fixed page chrome: background, header band, synthetic strip, footer,
    corner waves.  Content (winner banner, tables, chart, disclaimer) flows in
    the frame above the footer."""
    W, H = A4
    employee_name = getattr(doc, "_employee_name", "Employee")

    # Background
    c.setFillColor(CREAM)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # Header band
    c.setFillColor(SEA_GREEN_DEEP)
    c.rect(0, H - 30 * mm, W, 30 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont(_FONT_BOLD, 14)
    c.drawString(_MARGIN, H - 12 * mm, "Tax Regime Optimiser")
    c.setFont(_FONT_REGULAR, 9)
    c.drawString(_MARGIN, H - 18 * mm, "Tax Year 2026-27  |  Income Tax Act 2025")
    c.setFont(_FONT_BOLD, 10)
    c.drawRightString(W - _MARGIN, H - 12 * mm, employee_name)
    c.setFont(_FONT_REGULAR, 8)
    c.drawRightString(W - _MARGIN, H - 18 * mm,
                      f"Generated {date.today().strftime('%d %b %Y')}")

    # Accent rule under header
    c.setStrokeColor(SEA_GREEN)
    c.setLineWidth(2)
    c.line(_MARGIN, H - 31 * mm, W - _MARGIN, H - 31 * mm)

    # Synthetic-data strip
    strip_y = H - 36 * mm
    c.setFillColor(SEA_GREEN_WASH)
    c.rect(_MARGIN, strip_y - 7, W - 2 * _MARGIN, 14, fill=1, stroke=0)
    c.setFont(_FONT_BOLD, 7.5)
    c.setFillColor(SEA_GREEN_DEEP)
    c.drawCentredString(
        W / 2, strip_y - 2,
        "SYNTHETIC DEMO DATA — Figures shown are illustrative for a non-real employee.")

    # Footer
    c.setFont(_FONT_REGULAR, 6.5)
    c.setFillColor(MUTED_SAGE)
    c.drawString(_MARGIN, 4 * mm, "contact@anujsureshkumar.com  |  anujsureshkumar.com")
    c.drawRightString(W - _MARGIN, 4 * mm, "Page 1 of 1")

    # Decorative corner wave hairlines (bottom-right)
    c.setStrokeColor(SEA_GREEN_LIGHT)
    c.setLineWidth(0.8)
    for offset in range(3):
        r_val = 10 + offset * 6
        c.arc(W - _MARGIN - r_val, 1 * mm, W - _MARGIN + r_val, 1 * mm + 2 * r_val,
              startAng=90, extent=90)


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def generate_pdf(
    result: TaxResult,
    employee_name: str = "Employee",
    gross_ctc: float = 0.0,
    chart_png: Optional[bytes] = None,
    output_path: Optional[str] = None,
) -> bytes:
    """
    Generate a one-page branded PDF advisory.

    Parameters
    ----------
    result       : TaxResult from regime_engine.compute()
    employee_name: Display name on the PDF
    gross_ctc    : Total CTC for reference (already in result)
    chart_png    : Optional PNG bytes of the deduction-sweep chart (FIX 6).
                   When provided, embedded between the regime tables and the
                   disclaimer.  Defaults to None so the PDF works without it.
    output_path  : Optional file path to save.  Always returns bytes.
    """
    buf = io.BytesIO()
    W, H = A4
    S = _styles()

    # Content frame sits between the synthetic strip and the footer.
    frame_top = H - 40 * mm
    frame_bottom = 7 * mm
    frame_x = _MARGIN
    frame_w = W - 2 * _MARGIN
    frame_h = frame_top - frame_bottom

    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=_MARGIN, rightMargin=_MARGIN,
        topMargin=40 * mm, bottomMargin=frame_bottom,
        title=f"Tax Regime Advisory — Tax Year 2026-27 — {employee_name}",
    )
    doc._employee_name = employee_name
    frame = Frame(frame_x, frame_bottom, frame_w, frame_h,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
                  id="body")
    doc.addPageTemplates([
        PageTemplate(id="main", frames=[frame], onPage=_draw_chrome)
    ])

    story: list = []

    # --- Winner banner ---
    winner_label = {
        "new": "NEW REGIME RECOMMENDED — saves " + _inr(result.savings),
        "old": "OLD REGIME RECOMMENDED — saves " + _inr(result.savings),
        "equal": "BOTH REGIMES EQUAL — no saving either way",
    }[result.winner]
    banner = Table([[Paragraph(winner_label, S["winner"])]], colWidths=[frame_w])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SEA_GREEN),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(banner)
    story.append(Spacer(1, 6))

    # --- Two regime tables side by side ---
    gap = 6
    col_w = (frame_w - gap) / 2
    old_table = _regime_table(result.old, result.winner == "old", col_w, S)
    new_table = _regime_table(result.new, result.winner == "new", col_w, S)
    parent = Table([[old_table, new_table]], colWidths=[col_w, col_w])
    parent.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), gap),
        ("LEFTPADDING", (1, 0), (1, 0), 0),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(parent)
    story.append(Spacer(1, 6))

    # --- How to read this ---
    story.append(Paragraph(
        '<b>How to read this:</b> The recommended regime has the lower total tax. '
        'Verify with a CA before submitting Form 124.', S["howto"]))
    story.append(Spacer(1, 6))

    # --- Deduction-sweep chart (FIX 6) ---
    if chart_png is not None:
        story.append(Paragraph(
            "Deductions vs tax — old regime falls as you claim more; new regime is flat.",
            S["chart_cap"]))
        story.append(Spacer(1, 2))
        img_w = frame_w
        img_h = img_w * (2.25 / 7.0)  # preserve the figure aspect ratio
        max_h = 52 * mm
        if img_h > max_h:
            img_h = max_h
        story.append(Image(io.BytesIO(chart_png), width=img_w, height=img_h))
        story.append(Spacer(1, 6))

    # --- Disclaimer box ---
    disc = Table(
        [[Paragraph("DISCLAIMER", S["disc_head"])],
         [Paragraph(DISCLAIMER.replace("DISCLAIMER: ", ""), S["disc_body"])]],
        colWidths=[frame_w])
    disc.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SEA_GREEN_WASH),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (0, 0), 4),
        ("BOTTOMPADDING", (0, 0), (0, 0), 0),
        ("TOPPADDING", (0, 1), (0, 1), 1),
        ("BOTTOMPADDING", (0, 1), (0, 1), 4),
    ]))
    story.append(disc)

    doc.build(story)
    pdf_bytes = buf.getvalue()

    if output_path:
        with open(output_path, "wb") as f:
            f.write(pdf_bytes)

    return pdf_bytes
