"""
pdf_report.py  --  One-page branded PDF advisory.

Generates a single-page PDF showing old vs new regime comparison,
winner highlight, key figures, and a mandatory tax disclaimer.

Uses ReportLab with the brand constants from instructions.md ss5.5.
Font: Tahoma if embeddable; else DejaVu Sans (closest open-licence substitute).
"""

from __future__ import annotations

import io
from datetime import date
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

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

# ---------------------------------------------------------------------------
# Font registration (try Tahoma; fall back to built-in Helvetica)
# ---------------------------------------------------------------------------
_FONT_REGULAR = "Helvetica"
_FONT_BOLD    = "Helvetica-Bold"

def _try_register_tahoma() -> bool:
    """Attempt to register Tahoma from Windows font directory."""
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


def _draw_hairline(c: canvas.Canvas, x1: float, y: float, x2: float) -> None:
    c.setStrokeColor(HAIRLINE)
    c.setLineWidth(0.5)
    c.line(x1, y, x2, y)


def _section_header(c: canvas.Canvas, text: str, x: float, y: float, width: float) -> float:
    """Draw a section header (ALL CAPS, Sea Green Deep) with hairline below. Returns new y."""
    c.setFont(_FONT_BOLD, 9)
    c.setFillColor(SEA_GREEN_DEEP)
    c.drawString(x, y, text.upper())
    y -= 4
    _draw_hairline(c, x, y, x + width)
    return y - 6


def _regime_column(
    c: canvas.Canvas,
    r: RegimeBreakdown,
    x: float, y_start: float,
    col_w: float,
    is_winner: bool,
    gross_ctc: float,
) -> None:
    """Draw one regime's tax breakdown column."""
    row_h = 13
    label_x = x + 4
    val_x   = x + col_w - 4

    # Column header background
    header_fill = SEA_GREEN if is_winner else SEA_GREEN_WASH
    header_text = colors.white if is_winner else SLATE_INK
    c.setFillColor(header_fill)
    c.rect(x, y_start, col_w, 18, fill=1, stroke=0)
    regime_label = ("NEW REGIME" if r.regime == "new" else "OLD REGIME")
    if is_winner:
        regime_label += "  — RECOMMENDED"
    c.setFillColor(header_text)
    c.setFont(_FONT_BOLD, 9)
    c.drawCentredString(x + col_w / 2, y_start + 5, regime_label)

    y = y_start - row_h

    def _row(label: str, val: float, bold: bool = False, indent: int = 8,
             color: object = SLATE_INK) -> None:
        nonlocal y
        font = _FONT_BOLD if bold else _FONT_REGULAR
        c.setFont(font, 8)
        c.setFillColor(MUTED_SAGE)
        c.drawString(label_x + indent, y, label)
        c.setFillColor(color)
        c.drawRightString(val_x, y, _inr(val))
        y -= row_h

    def _section(title: str) -> None:
        nonlocal y
        c.setFont(_FONT_BOLD, 7)
        c.setFillColor(SEA_GREEN_DEEP)
        c.drawString(label_x, y, title)
        y -= 10

    _section("Gross taxable salary")
    _row("Gross salary (CTC - PF - Gratuity)", r.gross_income, indent=4)

    _section("Deductions")
    for label, amt in r.deductions.items():
        if amt > 0:
            _row(label[:42], amt, indent=4)

    total_ded_color = SEA_GREEN_DEEP
    c.setFont(_FONT_BOLD, 8)
    c.setFillColor(total_ded_color)
    c.drawString(label_x + 4, y, "Total deductions")
    c.drawRightString(val_x, y, f"({_inr(r.total_deductions)})")
    y -= row_h

    # Taxable income
    _draw_hairline(c, x + 4, y + 8, x + col_w - 4)
    c.setFont(_FONT_BOLD, 9)
    c.setFillColor(SLATE_INK)
    c.drawString(label_x, y, "Taxable income")
    c.drawRightString(val_x, y, _inr(r.taxable_income))
    y -= row_h

    _section("Tax computation")
    _row("Slab tax", r.base_tax)
    if r.rebate > 0:
        _row("Sec 156 rebate", -r.rebate, color=SEA_GREEN_DEEP)
    if r.marginal_relief_rebate > 0:
        _row("Rebate marginal relief", -r.marginal_relief_rebate, color=SEA_GREEN_DEEP)
    if r.surcharge > 0:
        _row("Surcharge", r.surcharge)
    if r.marginal_relief_surcharge > 0:
        _row("Surcharge marginal relief", -r.marginal_relief_surcharge, color=SEA_GREEN_DEEP)
    _row("Health & Education Cess (4%)", r.cess)

    # Total tax box
    y -= 2
    fill = STATUS_FAV if is_winner else STATUS_UNFAV
    c.setFillColor(fill)
    c.rect(x, y, col_w, 18, fill=1, stroke=0)
    c.setFont(_FONT_BOLD, 10)
    c.setFillColor(SLATE_INK)
    c.drawString(label_x, y + 4, "Total tax liability")
    c.drawRightString(val_x, y + 4, _inr(r.total_tax))
    y -= 22

    # Effective rate
    c.setFont(_FONT_REGULAR, 7.5)
    c.setFillColor(MUTED_SAGE)
    c.drawString(label_x, y, f"Effective rate on CTC: {r.effective_rate_pct}%")


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

DISCLAIMER = (
    "DISCLAIMER: This document is prepared for illustrative purposes only using synthetic data. "
    "It does not constitute tax advice. Tax liability depends on individual circumstances, "
    "age, other income sources, and final declarations. Consult a Chartered Accountant "
    "or tax professional before making a regime choice."
)


def generate_pdf(
    result: TaxResult,
    employee_name: str = "Employee",
    gross_ctc: float = 0.0,
    output_path: Optional[str] = None,
) -> bytes:
    """
    Generate a one-page branded PDF advisory.

    Parameters
    ----------
    result       : TaxResult from regime_engine.compute()
    employee_name: Display name on the PDF
    gross_ctc    : Total CTC for reference (already in result)
    output_path  : Optional file path to save.  Always returns bytes.
    """
    buf = io.BytesIO()
    W, H = A4
    margin = 18 * mm

    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Tax Regime Advisory — Tax Year 2026-27 — {employee_name}")

    # --- Background ---
    c.setFillColor(CREAM)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # --- Header bar ---
    c.setFillColor(SEA_GREEN_DEEP)
    c.rect(0, H - 30 * mm, W, 30 * mm, fill=1, stroke=0)

    c.setFillColor(colors.white)
    c.setFont(_FONT_BOLD, 14)
    c.drawString(margin, H - 12 * mm, "Tax Regime Optimiser")
    c.setFont(_FONT_REGULAR, 9)
    c.drawString(margin, H - 18 * mm, "Tax Year 2026-27  |  Income Tax Act 2025")

    # Right side of header
    c.setFont(_FONT_BOLD, 10)
    c.drawRightString(W - margin, H - 12 * mm, employee_name)
    c.setFont(_FONT_REGULAR, 8)
    c.drawRightString(W - margin, H - 18 * mm, f"Generated {date.today().strftime('%d %b %Y')}")

    # Accent rule under header
    c.setStrokeColor(SEA_GREEN)
    c.setLineWidth(2)
    c.line(margin, H - 31 * mm, W - margin, H - 31 * mm)

    # --- Synthetic data label ---
    y_top = H - 36 * mm
    c.setFillColor(SEA_GREEN_WASH)
    c.rect(margin, y_top - 7, W - 2 * margin, 14, fill=1, stroke=0)
    c.setFont(_FONT_BOLD, 7.5)
    c.setFillColor(SEA_GREEN_DEEP)
    c.drawCentredString(
        W / 2, y_top - 2,
        "SYNTHETIC DEMO DATA — Figures shown are illustrative for a non-real employee."
    )

    y = y_top - 18

    # --- Winner banner ---
    winner_label = {
        "new": "NEW REGIME RECOMMENDED — saves " + _inr(result.savings),
        "old": "OLD REGIME RECOMMENDED — saves " + _inr(result.savings),
        "equal": "BOTH REGIMES EQUAL — no saving either way",
    }[result.winner]

    c.setFillColor(SEA_GREEN)
    c.rect(margin, y - 12, W - 2 * margin, 18, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont(_FONT_BOLD, 10)
    c.drawCentredString(W / 2, y - 6, winner_label)
    y -= 22

    # --- Two-column breakdown ---
    col_gap = 6
    col_w = (W - 2 * margin - col_gap) / 2
    col_left  = margin
    col_right = margin + col_w + col_gap

    old_is_winner = result.winner == "old"
    new_is_winner = result.winner == "new"

    _regime_column(c, result.old, col_left,  y, col_w, old_is_winner, result.old.gross_income)
    _regime_column(c, result.new, col_right, y, col_w, new_is_winner, result.new.gross_income)

    # --- Breakeven note ---
    y_break = 52 * mm
    _draw_hairline(c, margin, y_break, W - margin)
    c.setFont(_FONT_BOLD, 8)
    c.setFillColor(SEA_GREEN_DEEP)
    c.drawString(margin, y_break - 8, "How to read this:")
    c.setFont(_FONT_REGULAR, 7.5)
    c.setFillColor(SLATE_INK)
    c.drawString(margin + 70, y_break - 8,
                 "The recommended regime has lower total tax.  Verify with a CA before submitting Form 12BB.")

    # --- Disclaimer box (must be visible without scrolling) ---
    disc_y = 8 * mm
    c.setFillColor(SEA_GREEN_WASH)
    c.rect(margin, disc_y, W - 2 * margin, 30, fill=1, stroke=0)
    c.setFont(_FONT_BOLD, 7)
    c.setFillColor(SEA_GREEN_DEEP)
    c.drawString(margin + 4, disc_y + 20, "DISCLAIMER")
    c.setFont(_FONT_REGULAR, 6.5)
    c.setFillColor(MUTED_SAGE)
    # Wrap disclaimer text
    words = DISCLAIMER.split()
    line, lines_out = [], []
    for w in words:
        test = " ".join(line + [w])
        if c.stringWidth(test, _FONT_REGULAR, 6.5) > (W - 2 * margin - 8):
            lines_out.append(" ".join(line))
            line = [w]
        else:
            line.append(w)
    lines_out.append(" ".join(line))
    for i, ln in enumerate(lines_out[:3]):
        c.drawString(margin + 4, disc_y + 12 - i * 8, ln)

    # --- Footer ---
    c.setFont(_FONT_REGULAR, 6.5)
    c.setFillColor(MUTED_SAGE)
    c.drawString(margin, 4 * mm, "contact@anujsureshkumar.com  |  anujsureshkumar.com")
    c.drawRightString(W - margin, 4 * mm, "Page 1 of 1")

    # Decorative wave hairlines (bottom-right corner, CV-style)
    c.setStrokeColor(SEA_GREEN_LIGHT)
    c.setLineWidth(0.8)
    for offset in range(3):
        r_val = 10 + offset * 6
        c.arc(W - margin - r_val, 1 * mm, W - margin + r_val, 1 * mm + 2 * r_val,
              startAng=90, extent=90)

    c.save()
    pdf_bytes = buf.getvalue()

    if output_path:
        with open(output_path, "wb") as f:
            f.write(pdf_bytes)

    return pdf_bytes
