"""
breakeven.py  --  CTC sweep for the old-vs-new breakeven chart.

Small, import-safe helper (no Streamlit) so the sweep can be unit-tested.
Used by app.py to draw the breakeven line chart and annotate the crossover.

WHY THIS EXISTS / THE DEDUCTION DECISION
----------------------------------------
The first deployed version scaled the *entire* salary — including rent and
every declared deduction — proportionally with CTC.  That made the old
regime's HRA exemption grow without bound (rent rose in lockstep with basic),
so above ~Rs 33L the old-regime line spuriously dipped below the new-regime
line.  A CA audience reads that as a glitch.

Locked decision: HOLD DEDUCTIONS FIXED.  We sweep gross CTC and scale ONLY
the CTC-linked salary structure (basic, HRA component, employer PF, gratuity).
Every rupee deduction — rent paid, 80C/PF, 80D, 80CCD(1B), 80E, 24(b),
employer NPS, professional tax — is held CONSTANT at the selected person's
actual declared value.

Holding rent fixed while basic grows caps the HRA exemption through the
`rent - 10% of basic` leg of Sec 14(10): as basic climbs, that leg shrinks
and the exemption stops running away.  The result is a clean, conventional,
slab-driven breakeven where the old line stays above the new line at high CTC.
"""

from __future__ import annotations

from dataclasses import dataclass

from regime_engine import TaxParams, compute

# Fields that scale proportionally with gross CTC (the salary structure).
_SCALING_FIELDS = ("basic", "hra_component", "employer_pf", "gratuity")

# Fields held fixed at the selected person's actual rupee values.
# (metro is a flag, carried through unchanged; everything else here is a
#  rupee deduction that must NOT grow with the swept CTC.)
_FIXED_FIELDS = (
    "rent_paid",
    "employee_pf_80c",
    "decl_80c_other",
    "decl_80d_self",
    "decl_80d_parents",
    "decl_80ccd_1b_nps",
    "decl_80e_edu",
    "decl_24b_home",
    "employer_nps",
    "professional_tax",
)


@dataclass
class SweepResult:
    """Result of a CTC sweep, ready to plot."""
    ctcs: list[int]            # swept gross-CTC values (rupees)
    old_taxes: list[float]     # old-regime total tax at each CTC
    new_taxes: list[float]     # new-regime total tax at each CTC
    crossover_ctc: float | None    # interpolated CTC where the lines cross (rupees), or None
    crossover_tax: float | None    # total tax at the crossover (rupees), or None


def scaled_params(base: TaxParams, ctc_val: float) -> TaxParams:
    """
    Build TaxParams for one point of the sweep.

    Scales the salary structure (basic / HRA / employer PF / gratuity) with
    CTC; holds rent and every declared deduction fixed at the base person's
    actual rupee values.  See module docstring for the rationale.
    """
    scale = ctc_val / base.gross_ctc if base.gross_ctc else 0.0
    kwargs = dict(gross_ctc=float(ctc_val), metro=base.metro)
    for f in _SCALING_FIELDS:
        kwargs[f] = round(getattr(base, f) * scale)
    for f in _FIXED_FIELDS:
        kwargs[f] = getattr(base, f)
    return TaxParams(**kwargs)


def _find_crossover(
    ctcs: list[int], old_taxes: list[float], new_taxes: list[float]
) -> tuple[float | None, float | None]:
    """
    Find the first CTC where the old and new lines cross, within range.

    Returns (crossover_ctc, crossover_tax) by linear interpolation on the
    sign change of (old - new), or (None, None) if the lines never cross.
    """
    diffs = [o - n for o, n in zip(old_taxes, new_taxes)]
    for i in range(len(diffs) - 1):
        d0, d1 = diffs[i], diffs[i + 1]
        if d0 == 0.0:
            return float(ctcs[i]), float(old_taxes[i])
        if d0 * d1 < 0:  # sign change between consecutive points -> a crossing
            frac = d0 / (d0 - d1)  # in (0, 1)
            ctc = ctcs[i] + frac * (ctcs[i + 1] - ctcs[i])
            tax = old_taxes[i] + frac * (old_taxes[i + 1] - old_taxes[i])
            return float(ctc), float(tax)
    # Check the final point landing exactly on zero
    if diffs and diffs[-1] == 0.0:
        return float(ctcs[-1]), float(old_taxes[-1])
    return None, None


def build_sweep(
    base: TaxParams, ctc_min: int, ctc_max: int, step: int
) -> SweepResult:
    """
    Sweep gross CTC from ctc_min to ctc_max (inclusive of the top step) and
    compute old- and new-regime total tax at each point with deductions held
    fixed.  Returns a SweepResult including any crossover within the range.
    """
    ctcs = list(range(ctc_min, ctc_max + step, step))
    old_taxes, new_taxes = [], []
    for ctc_val in ctcs:
        r = compute(scaled_params(base, ctc_val))
        old_taxes.append(r.old.total_tax)
        new_taxes.append(r.new.total_tax)
    crossover_ctc, crossover_tax = _find_crossover(ctcs, old_taxes, new_taxes)
    return SweepResult(
        ctcs=ctcs,
        old_taxes=old_taxes,
        new_taxes=new_taxes,
        crossover_ctc=crossover_ctc,
        crossover_tax=crossover_tax,
    )
