"""
tests/test_breakeven.py  --  Unit tests for breakeven.py (the deduction sweep).

Covers the locked "absolute total old-regime deduction" redesign:
    1. forced_total_params forces the OLD-regime total deduction to exactly the
       target x (for x >= STD_DED_OLD), by zeroing rent / professional tax /
       employer NPS / every discretionary declaration and injecting the
       remainder into the uncapped Sec 129 (80E) field, while leaving the salary
       structure untouched.
    2. The new-regime line is flat (it ignores these deductions) and the
       old-regime line is non-increasing as the total deduction rises.
    3. current_total_deductions is the person's ACTUAL absolute old-regime total.
    4. Crossover detection finds the total deduction where old first beats new,
       or reports None when it never does within range.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from regime_engine import TaxParams, compute, STD_DED_OLD
from breakeven import (
    forced_total_params,
    old_tax_at_total,
    new_tax_flat,
    current_total_deductions,
    build_sweep,
    _find_crossover,
)


def _renter_params() -> TaxParams:
    """A renter (metro, rent 4.33L) carrying several declared deductions."""
    return TaxParams(
        gross_ctc=16_65_000, basic=7_49_200, hra_component=3_74_600,
        employer_pf=21_600, gratuity=36_037, rent_paid=4_33_000, metro=True,
        employee_pf_80c=21_600, decl_80c_other=50_000, decl_80d_self=25_000,
        decl_24b_home=2_00_000, professional_tax=2_400,
    )


def _nondeclarer_renter() -> TaxParams:
    """A non-declarer who claims HRA (metro, rent 4.33L)."""
    return TaxParams(
        gross_ctc=16_65_000, basic=7_49_200, hra_component=3_74_600,
        employer_pf=21_600, gratuity=36_037, rent_paid=4_33_000, metro=True,
        employee_pf_80c=21_600, professional_tax=2_400,
    )


class TestForcedTotalParams:
    def test_total_deduction_forced_to_x(self):
        """For x >= STD_DED_OLD the engine's reported old total_deductions == x,
        regardless of the person's actual deduction composition."""
        base = _renter_params()
        for x in (50_000, 1_50_000, 3_00_000, 6_00_000, 9_21_800):
            forced = forced_total_params(base, x)
            assert compute(forced).old.total_deductions == x, f"total != x at x={x}"

    def test_below_std_ded_floors_at_std_ded(self):
        """Below the standard deduction the total floors at STD_DED_OLD (the
        standard deduction is always granted)."""
        base = _renter_params()
        forced = forced_total_params(base, 20_000)
        assert compute(forced).old.total_deductions == STD_DED_OLD

    def test_salary_structure_held_fixed(self):
        base = _renter_params()
        p = forced_total_params(base, 5_00_000)
        assert p.gross_ctc == base.gross_ctc
        assert p.basic == base.basic
        assert p.hra_component == base.hra_component
        assert p.employer_pf == base.employer_pf
        assert p.gratuity == base.gratuity
        # Optional fields are zeroed to make the total controllable.
        assert p.rent_paid == 0.0
        assert p.professional_tax == 0.0
        assert p.employer_nps == 0.0

    def test_gross_income_unchanged(self):
        """Forcing the deduction must not change gross taxable income."""
        base = _renter_params()
        base_gross = compute(base).old.gross_income
        forced_gross = compute(forced_total_params(base, 7_00_000)).old.gross_income
        assert forced_gross == base_gross


class TestCurrentTotalDeductions:
    def test_equals_engine_old_total(self):
        base = _renter_params()
        assert current_total_deductions(base) == compute(base).old.total_deductions

    def test_includes_hra_and_structural(self):
        """The absolute total is far larger than the discretionary slice: it
        includes HRA, standard deduction, professional tax and every cap."""
        base = _renter_params()
        cur = current_total_deductions(base)
        # Standard 50k + prof tax 2.4k + HRA + 80C cap 1.5L + 80D 25k + 24b 2L.
        assert cur > 4_00_000


class TestSweepShape:
    def test_new_line_is_flat(self):
        base = _nondeclarer_renter()
        sweep = build_sweep(base, 0, 10_00_000, 50_000)
        assert len(set(sweep.new_taxes)) == 1, "new-regime line must be flat"
        assert sweep.new_taxes[0] == new_tax_flat(base)

    def test_old_line_non_increasing(self):
        base = _nondeclarer_renter()
        sweep = build_sweep(base, 0, 10_00_000, 50_000)
        for a, b in zip(sweep.old_taxes, sweep.old_taxes[1:]):
            assert b <= a, "old-regime line must be non-increasing as deductions rise"

    def test_old_starts_above_ends_below_new(self):
        base = _nondeclarer_renter()
        sweep = build_sweep(base, 0, 10_00_000, 50_000)
        assert sweep.old_taxes[0] > sweep.new_taxes[0], "old should start above new"
        assert sweep.old_taxes[-1] < sweep.new_taxes[-1], "old should end below new"

    def test_current_marker_is_absolute_total(self):
        base = _renter_params()
        sweep = build_sweep(base)
        assert sweep.current_ded == compute(base).old.total_deductions


class TestCrossover:
    def test_crossover_found_within_range(self):
        base = _nondeclarer_renter()
        sweep = build_sweep(base, 0, 10_00_000, 50_000)
        assert sweep.breakeven_ded is not None
        assert 0 < sweep.breakeven_ded < 10_00_000

    def test_no_crossover_in_a_small_range(self):
        """Over a tiny deduction range the old line never catches the new line,
        so no breakeven is reported."""
        base = _nondeclarer_renter()
        sweep = build_sweep(base, 0, 20_000, 10_000)
        assert sweep.breakeven_ded is None
        assert sweep.breakeven_tax is None

    def test_find_crossover_on_sign_change(self):
        levels = [10, 20, 30]
        old = [100.0, 90.0, 80.0]
        new = [90.0, 90.0, 90.0]  # old crosses below at the middle point
        level, tax = _find_crossover(levels, old, new)
        assert level == 20.0
        assert tax == 90.0

    def test_find_crossover_interpolated(self):
        levels = [10, 20]
        old = [100.0, 80.0]
        new = [90.0, 90.0]  # diff: +10 -> -10, crosses halfway
        level, tax = _find_crossover(levels, old, new)
        assert level == 15.0

    def test_find_crossover_returns_none(self):
        levels = [10, 20, 30]
        old = [100.0, 95.0, 92.0]
        new = [50.0, 50.0, 50.0]  # old never reaches new
        level, tax = _find_crossover(levels, old, new)
        assert level is None and tax is None


class TestOldTaxAtTotal:
    def test_old_tax_falls_as_total_rises(self):
        base = _nondeclarer_renter()
        assert old_tax_at_total(base, 8_00_000) < old_tax_at_total(base, 1_00_000)
