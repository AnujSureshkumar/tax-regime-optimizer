"""
tests/test_breakeven.py  --  Unit tests for breakeven.py (the deduction sweep).

Covers the locked "sweep deductions, hold salary fixed" decision:
    1. deduction_params zeros every discretionary declaration and injects the
       swept value into the uncapped Sec 129 (80E) field, leaving the salary
       structure untouched.
    2. The new-regime line is flat (it ignores discretionary deductions) and the
       old-regime line falls as deductions rise.
    3. Crossover detection finds the deduction level where old first beats new,
       or reports None when it never does within range.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from regime_engine import TaxParams, compute
from breakeven import (
    deduction_params,
    current_deductions,
    build_sweep,
    _find_crossover,
    _DISCRETIONARY_FIELDS,
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


class TestDeductionParams:
    def test_discretionary_fields_zeroed_except_injection(self):
        base = _renter_params()
        p = deduction_params(base, 3_00_000)
        # The swept value lands in the uncapped 80E field...
        assert p.decl_80e_edu == 3_00_000
        # ...and every other discretionary field is zeroed.
        for f in _DISCRETIONARY_FIELDS:
            if f == "decl_80e_edu":
                continue
            assert getattr(p, f) == 0.0, f"{f} should be zeroed"

    def test_salary_structure_held_fixed(self):
        base = _renter_params()
        p = deduction_params(base, 5_00_000)
        assert p.gross_ctc == base.gross_ctc
        assert p.basic == base.basic
        assert p.hra_component == base.hra_component
        assert p.employer_pf == base.employer_pf
        assert p.gratuity == base.gratuity
        assert p.rent_paid == base.rent_paid
        assert p.metro == base.metro
        assert p.employer_nps == base.employer_nps
        assert p.professional_tax == base.professional_tax

    def test_injected_value_flows_through_uncapped(self):
        """80E has no cap, so the injected rupee value reaches the old-regime
        total deductions on top of the structural baseline."""
        base = _nondeclarer_renter()
        structural = compute(deduction_params(base, 0.0)).old.total_deductions
        with_3l = compute(deduction_params(base, 3_00_000)).old.total_deductions
        assert with_3l - structural == 3_00_000

    def test_current_deductions_is_claimed_slice(self):
        """current_deductions returns the discretionary slice of the person's
        actual old-regime deductions (actual total minus structural baseline)."""
        base = _renter_params()
        cur = current_deductions(base)
        assert cur > 0
        # The renter claims 80C (PF 21,600 + other 50,000, capped at 1.5L),
        # 80D self 25,000 and 24(b) 2,00,000 -> 71,600 + 25,000 + 2,00,000.
        assert cur == 71_600 + 25_000 + 2_00_000


class TestSweepShape:
    def test_new_line_is_flat(self):
        base = _nondeclarer_renter()
        sweep = build_sweep(base, 0, 8_00_000, 50_000)
        assert len(set(sweep.new_taxes)) == 1, "new-regime line must be flat"

    def test_old_line_falls(self):
        base = _nondeclarer_renter()
        sweep = build_sweep(base, 0, 8_00_000, 50_000)
        for a, b in zip(sweep.old_taxes, sweep.old_taxes[1:]):
            assert b <= a, "old-regime line must be non-increasing as deductions rise"

    def test_old_falls_strictly_below_new_with_enough_deductions(self):
        base = _nondeclarer_renter()
        sweep = build_sweep(base, 0, 8_00_000, 50_000)
        assert sweep.old_taxes[0] > sweep.new_taxes[0], "old should start above new"
        assert sweep.old_taxes[-1] < sweep.new_taxes[-1], "old should end below new"


class TestCrossover:
    def test_crossover_found_within_range(self):
        base = _nondeclarer_renter()
        sweep = build_sweep(base, 0, 8_00_000, 50_000)
        assert sweep.breakeven_ded is not None
        assert 0 < sweep.breakeven_ded < 8_00_000

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
