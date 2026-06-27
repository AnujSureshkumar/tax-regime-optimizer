"""
breakeven.py  --  Deduction sweep for the old-vs-new breakeven chart.

Small, import-safe helper (no Streamlit) so the sweep can be unit-tested.
Used by app.py to draw the breakeven line chart and annotate the crossover.

WHY THIS SWEEPS DEDUCTIONS, NOT CTC
-----------------------------------
The first version swept gross CTC.  But CTC is not in the employee's control:
they might switch jobs once a year at most.  The deductions they claim ARE in
their control, every year.  So the useful question is "how much deduction do I
need before the old regime beats the new one for me", at my fixed salary.

Locked decision: HOLD THE SALARY STRUCTURE FIXED, SWEEP THE CLAIMED DEDUCTIONS.
We keep gross_ctc, basic, hra_component, employer_pf, gratuity, rent_paid,
metro, employer_nps and professional_tax at the selected person's actual
values, and vary only the discretionary old-regime declarations (80C, 80D,
80CCD(1B), 80E, 24(b)).

APPROACH (documented for the build report)
------------------------------------------
We use the "single synthetic deduction" approach.  For each target deduction
level x on the x-axis we:
  1. Zero every discretionary declaration field (employee_pf_80c, decl_80c_other,
     decl_80d_self, decl_80d_parents, decl_80ccd_1b_nps, decl_80e_edu,
     decl_24b_home), leaving the structural fields untouched.
  2. Inject x into decl_80e_edu (Sec 129, education-loan interest), which the
     engine caps at no upper limit, so the rupee value flows through 1:1.
This makes the *claimed* old-regime deduction equal exactly x at every point,
while the new regime, which ignores these declarations, stays flat.  All tax is
computed by the real engine (regime_engine.compute) -- no tax maths is
reimplemented here.

The x-axis therefore reads "total discretionary deductions claimed under the
old regime".  The new line is flat (the new regime only ever gets the standard
deduction plus Sec 124 employer NPS, neither of which moves with x).  The old
line falls as x rises.  Where they cross is the deduction level at which the
old regime becomes cheaper.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from regime_engine import TaxParams, compute

# Discretionary old-regime declarations -- these are what the user chooses to
# claim, and what we sweep.  Everything else on TaxParams is held fixed.
_DISCRETIONARY_FIELDS = (
    "employee_pf_80c",
    "decl_80c_other",
    "decl_80d_self",
    "decl_80d_parents",
    "decl_80ccd_1b_nps",
    "decl_80e_edu",
    "decl_24b_home",
)

# Default ceiling for the deduction sweep (rupees).  Anuj's estimate puts the
# breakeven near Rs 8-8.5L, so 10L should show the crossing for most people.
DED_MAX_DEFAULT = 10_00_000


@dataclass
class SweepResult:
    """Result of a deduction sweep, ready to plot."""
    ded_levels: list[int]        # swept discretionary-deduction values (rupees)
    old_taxes: list[float]       # old-regime total tax at each deduction level
    new_taxes: list[float]       # new-regime total tax at each deduction level (flat)
    breakeven_ded: float | None  # interpolated deduction level where old first beats new, or None
    breakeven_tax: float | None  # total tax at the breakeven (rupees), or None
    current_ded: float           # the person's current claimed old-regime deductions (rupees)


def deduction_params(base: TaxParams, ded_val: float) -> TaxParams:
    """
    Build TaxParams for one point of the sweep.

    Zeros every discretionary declaration, then injects ``ded_val`` into the
    uncapped Sec 129 (80E) field so the claimed old-regime deduction equals
    ``ded_val`` exactly.  The salary structure and the always-on structural
    items (standard deduction, professional tax, HRA, employer NPS) are left
    untouched.  See the module docstring for the rationale.
    """
    zeroed = {f: 0.0 for f in _DISCRETIONARY_FIELDS}
    zeroed["decl_80e_edu"] = float(ded_val)
    return replace(base, **zeroed)


def current_deductions(base: TaxParams) -> float:
    """
    The person's CURRENT claimed (discretionary) old-regime deductions, in
    rupees, expressed on the same axis the sweep uses.

    Computed as the difference between their actual old-regime total deductions
    and the structural baseline (the deductions that remain when every
    discretionary declaration is zeroed).  This is the slice of their old-regime
    deductions that the user actually controls.
    """
    actual_total = compute(base).old.total_deductions
    structural = compute(deduction_params(base, 0.0)).old.total_deductions
    return max(0.0, actual_total - structural)


def _find_crossover(
    levels: list[int], old_taxes: list[float], new_taxes: list[float]
) -> tuple[float | None, float | None]:
    """
    Find the first deduction level where the old line drops to/below the new
    line, within range.

    Returns (breakeven_ded, breakeven_tax) by linear interpolation on the sign
    change of (old - new), or (None, None) if the old line never reaches the
    new line.
    """
    diffs = [o - n for o, n in zip(old_taxes, new_taxes)]
    for i in range(len(diffs) - 1):
        d0, d1 = diffs[i], diffs[i + 1]
        if d0 == 0.0:
            return float(levels[i]), float(old_taxes[i])
        if d0 * d1 < 0:  # sign change between consecutive points -> a crossing
            frac = d0 / (d0 - d1)  # in (0, 1)
            level = levels[i] + frac * (levels[i + 1] - levels[i])
            tax = old_taxes[i] + frac * (old_taxes[i + 1] - old_taxes[i])
            return float(level), float(tax)
    # Check the final point landing exactly on zero
    if diffs and diffs[-1] == 0.0:
        return float(levels[-1]), float(old_taxes[-1])
    return None, None


def build_sweep(
    base: TaxParams,
    ded_min: int = 0,
    ded_max: int = DED_MAX_DEFAULT,
    step: int | None = None,
) -> SweepResult:
    """
    Sweep the claimed old-regime deduction from ``ded_min`` to ``ded_max``
    (inclusive of the top step), holding the salary structure fixed, and compute
    old- and new-regime total tax at each point with the real engine.

    The ceiling is clamped to the gross taxable income (CTC - employer PF -
    gratuity): deductions above taxable salary are meaningless.  Returns a
    SweepResult including any crossover within the range and the person's
    current claimed deductions.
    """
    gross_taxable = base.gross_ctc - base.employer_pf - base.gratuity

    current_ded = current_deductions(base)
    # Keep the current-deduction marker on the chart even if it sits above the
    # default ceiling, but never sweep beyond the gross taxable income.
    ceiling = max(ded_max, current_ded * 1.05)
    ceiling = min(ceiling, gross_taxable)
    ded_max = int(max(ded_min, ceiling))

    if step is None:
        step = max(10_000, (ded_max - ded_min) // 50)

    levels = list(range(ded_min, ded_max + step, step))
    old_taxes, new_taxes = [], []
    for ded_val in levels:
        r = compute(deduction_params(base, ded_val))
        old_taxes.append(r.old.total_tax)
        new_taxes.append(r.new.total_tax)

    breakeven_ded, breakeven_tax = _find_crossover(levels, old_taxes, new_taxes)
    return SweepResult(
        ded_levels=levels,
        old_taxes=old_taxes,
        new_taxes=new_taxes,
        breakeven_ded=breakeven_ded,
        breakeven_tax=breakeven_tax,
        current_ded=current_ded,
    )
