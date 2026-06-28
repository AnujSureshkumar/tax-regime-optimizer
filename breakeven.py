"""
breakeven.py  --  Deduction sweep for the old-vs-new breakeven chart.

Small, import-safe helper (no Streamlit) so the sweep can be unit-tested.
Used by app.py to draw the breakeven line chart and annotate the crossover.

WHY THE X-AXIS IS THE ABSOLUTE TOTAL OLD-REGIME DEDUCTION
---------------------------------------------------------
The earlier version swept only the *discretionary* declarations on top of a
fixed structural base (standard deduction + professional tax + HRA + employer
NPS). That made the x-axis the incremental slice, so the marker and crossover
sat in the wrong place: a person with a large fixed HRA looked like they were
claiming almost nothing, and reducing deductions never flipped the regime the
way it should.

Locked redesign: the x-axis is the person's TOTAL old-regime deductions in
absolute rupees. The key fact that makes this clean is that old-regime total
tax depends ONLY on taxable income = gross - total old deductions. So we can
draw the old line by forcing the total old deduction to each x (regardless of
how it is composed), and the new line is flat because the new regime ignores
these deductions entirely.

APPROACH (documented for the build report)
------------------------------------------
For each target total deduction x on the x-axis we build TaxParams from the
person's base but force the OLD-regime total deduction to exactly x:
  - rent_paid = 0            (removes HRA)
  - professional_tax = 0
  - every discretionary declaration field = 0
  - employer_nps = 0         (folded into x; we only read the .old side here)
  - decl_80e_edu = max(0, x - STD_DED_OLD)
The old regime always keeps its standard deduction (STD_DED_OLD), and Sec 129
(80E) is uncapped, so the reported old total_deductions equals x exactly for
x >= STD_DED_OLD. For x < STD_DED_OLD the total floors at STD_DED_OLD (the
standard deduction is always granted); that is fine because the crossover is
well above Rs 50,000. The salary structure (gross_ctc, basic, employer_pf,
gratuity) is left intact, so gross income is unchanged. All tax is computed by
the real engine (regime_engine.compute) -- no tax maths is reimplemented here.

The new line is flat: the new regime only ever gets the standard deduction plus
Sec 124 employer NPS, neither of which moves with x. The old line falls as x
rises. Where they cross is the total deduction at which the old regime becomes
cheaper. Below the crossover the new regime wins; above it the old regime wins.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from regime_engine import TaxParams, compute, STD_DED_OLD

# Default ceiling for the deduction sweep (rupees). The crossover for a typical
# salaried person sits well within this, and the ceiling is extended below when
# the person's actual total deductions run higher.
DED_MAX_DEFAULT = 10_00_000


@dataclass
class SweepResult:
    """Result of a deduction sweep, ready to plot."""
    ded_levels: list[int]        # swept TOTAL old-regime deduction values (rupees)
    old_taxes: list[float]       # old-regime total tax at each deduction level
    new_taxes: list[float]       # new-regime total tax at each deduction level (flat)
    breakeven_ded: float | None  # interpolated total deduction where old first beats new, or None
    breakeven_tax: float | None  # total tax at the breakeven (rupees), or None
    current_ded: float           # the person's ACTUAL absolute old-regime total deductions (rupees)


def forced_total_params(base: TaxParams, total_ded: float) -> TaxParams:
    """
    Build TaxParams whose OLD-regime total deduction equals ``total_ded``.

    Zeros rent (removes HRA), professional tax, employer NPS and every
    discretionary declaration, then injects the remainder above the always-on
    standard deduction into the uncapped Sec 129 (80E) field. The salary
    structure (gross_ctc, basic, employer_pf, gratuity) is left untouched, so
    gross income is unchanged. See the module docstring for the rationale.

    For ``total_ded >= STD_DED_OLD`` the engine's reported old total_deductions
    equals ``total_ded`` exactly; below that it floors at STD_DED_OLD.
    """
    return replace(
        base,
        rent_paid=0.0,
        professional_tax=0.0,
        employer_nps=0.0,
        employee_pf_80c=0.0,
        decl_80c_other=0.0,
        decl_80d_self=0.0,
        decl_80d_parents=0.0,
        decl_80ccd_1b_nps=0.0,
        decl_24b_home=0.0,
        decl_80e_edu=max(0.0, float(total_ded) - STD_DED_OLD),
    )


def old_tax_at_total(base: TaxParams, x: float) -> float:
    """Old-regime total tax when the total old deduction is forced to ``x``."""
    return compute(forced_total_params(base, x)).old.total_tax


def new_tax_flat(base: TaxParams) -> float:
    """
    New-regime total tax for the person. A single constant: the new regime
    ignores the swept deductions, so its line is flat across x.
    """
    return compute(base).new.total_tax


def current_total_deductions(base: TaxParams) -> float:
    """
    The person's ACTUAL absolute old-regime total deductions, in rupees
    (includes HRA, standard deduction, professional tax, every declaration).
    This is the marker position on the chart.
    """
    return compute(base).old.total_deductions


def _find_crossover(
    levels: list[int], old_taxes: list[float], new_taxes: list[float]
) -> tuple[float | None, float | None]:
    """
    Find the first total-deduction level where the old line drops to/below the
    new line, within range.

    Returns (breakeven_ded, breakeven_tax) by linear interpolation on the sign
    change of (old - new), or (None, None) if the old line never reaches the
    new line. Because the old line falls as the total deduction rises, below the
    crossover the new regime wins and above it the old regime wins.
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
    Sweep the TOTAL old-regime deduction from ``ded_min`` to ``ded_max``
    (inclusive of the top step), holding the salary structure fixed, and compute
    old- and new-regime total tax at each point with the real engine.

    The ceiling is extended so the current-total marker stays on-chart, then
    hard-capped at the gross taxable income (CTC - employer PF - gratuity):
    deductions beyond taxable salary are meaningless. Returns a SweepResult
    including any crossover within the range and the person's actual absolute
    old-regime total deductions.
    """
    gross_taxable = base.gross_ctc - base.employer_pf - base.gratuity

    current_ded = current_total_deductions(base)
    # Keep the current-total marker on the chart even if it sits above the
    # default ceiling, but never sweep beyond the gross taxable income.
    ceiling = max(ded_max, current_ded * 1.1)
    ceiling = min(ceiling, gross_taxable)
    ded_max = int(max(ded_min, ceiling))

    if step is None:
        step = max(10_000, (ded_max - ded_min) // 50)

    levels = list(range(ded_min, ded_max + step, step))
    new_flat = new_tax_flat(base)
    old_taxes = [old_tax_at_total(base, x) for x in levels]
    new_taxes = [new_flat for _ in levels]

    breakeven_ded, breakeven_tax = _find_crossover(levels, old_taxes, new_taxes)
    return SweepResult(
        ded_levels=levels,
        old_taxes=old_taxes,
        new_taxes=new_taxes,
        breakeven_ded=breakeven_ded,
        breakeven_tax=breakeven_tax,
        current_ded=current_ded,
    )
