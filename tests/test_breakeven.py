"""
tests/test_breakeven.py  --  Unit tests for breakeven.py (the CTC sweep).

Covers the locked "hold deductions fixed" decision:
    1. scaled_params scales ONLY the salary structure and holds rent +
       every declared deduction fixed at the base person's rupee values.
    2. With deductions held fixed, the old-regime line no longer spuriously
       overtakes the new-regime line at high CTC (the deployed bug).
    3. Crossover detection finds a crossing within range, or reports None.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from regime_engine import TaxParams
from breakeven import scaled_params, build_sweep, _find_crossover


def _renter_params() -> TaxParams:
    """A renter (metro, rent 4.33L) carrying several declared deductions —
    used to confirm the fixed fields really are held fixed while salary scales."""
    return TaxParams(
        gross_ctc=16_65_000, basic=7_49_200, hra_component=3_74_600,
        employer_pf=21_600, gratuity=36_037, rent_paid=4_33_000, metro=True,
        employee_pf_80c=21_600, decl_80c_other=50_000, decl_80d_self=25_000,
        decl_24b_home=2_00_000, professional_tax=2_400,
    )


def _nondeclarer_renter() -> TaxParams:
    """INF1000: the documented bug case — a non-declarer who claims HRA
    (metro, rent 4.33L). Under the OLD proportional sweep its HRA exemption
    ran away as CTC scaled, making the old line spuriously beat the new one
    at high CTC. With rent held fixed that runaway is gone."""
    return TaxParams(
        gross_ctc=16_65_000, basic=7_49_200, hra_component=3_74_600,
        employer_pf=21_600, gratuity=36_037, rent_paid=4_33_000, metro=True,
        employee_pf_80c=21_600, professional_tax=2_400,
    )


class TestScaledParams:
    def test_salary_structure_scales(self):
        base = _renter_params()
        p = scaled_params(base, base.gross_ctc * 2)  # double CTC
        assert p.gross_ctc == base.gross_ctc * 2
        assert p.basic == round(base.basic * 2)
        assert p.hra_component == round(base.hra_component * 2)
        assert p.employer_pf == round(base.employer_pf * 2)
        assert p.gratuity == round(base.gratuity * 2)

    def test_deductions_and_rent_held_fixed(self):
        base = _renter_params()
        p = scaled_params(base, base.gross_ctc * 3)  # triple CTC
        # Rent and every declared deduction stay at the base rupee values.
        assert p.rent_paid == base.rent_paid
        assert p.employee_pf_80c == base.employee_pf_80c
        assert p.decl_80c_other == base.decl_80c_other
        assert p.decl_80d_self == base.decl_80d_self
        assert p.decl_80d_parents == base.decl_80d_parents
        assert p.decl_80ccd_1b_nps == base.decl_80ccd_1b_nps
        assert p.decl_80e_edu == base.decl_80e_edu
        assert p.decl_24b_home == base.decl_24b_home
        assert p.employer_nps == base.employer_nps
        assert p.professional_tax == base.professional_tax
        assert p.metro == base.metro

    def test_identity_at_base_ctc(self):
        base = _renter_params()
        p = scaled_params(base, base.gross_ctc)
        assert p.basic == base.basic
        assert p.gross_ctc == base.gross_ctc


class TestOldDoesNotOvertakeNew:
    def test_old_stays_above_new_at_high_ctc_for_renter(self):
        """
        Regression for the deployed bug: with rent + deductions held fixed,
        the old-regime line must NOT drop below the new-regime line as CTC
        scales up (which it did under the old proportional-scaling sweep,
        because the HRA exemption ran away with rising basic).
        """
        base = _nondeclarer_renter()
        sweep = build_sweep(base, 8_00_000, 66_00_000, 1_00_000)
        offenders = [
            c for c, o, n in zip(sweep.ctcs, sweep.old_taxes, sweep.new_taxes)
            if o < n  # old cheaper than new == old line dipped below
        ]
        assert not offenders, (
            f"Old regime spuriously beats new at high CTC: {offenders[:5]}"
        )

    def test_top_of_range_hra_exemption_is_capped(self):
        """At the top of the range, the fixed rent caps the HRA exemption via
        the (rent - 10% basic) leg — it must not equal the scaled HRA component."""
        from regime_engine import _hra_exemption
        base = _renter_params()
        top = scaled_params(base, 66_00_000)
        hra = _hra_exemption(top.hra_component, top.basic, top.rent_paid, top.metro)
        # rent (fixed 4.33L) - 10% of the scaled basic is the binding leg
        assert hra < top.hra_component
        assert hra == max(0.0, top.rent_paid - top.basic * 0.10)


class TestCrossoverDetection:
    def test_crossover_found_on_sign_change(self):
        ctcs = [10, 20, 30]
        old = [100.0, 90.0, 80.0]
        new = [80.0, 90.0, 100.0]  # crosses exactly at the middle point
        ctc, tax = _find_crossover(ctcs, old, new)
        assert ctc == 20.0
        assert tax == 90.0

    def test_crossover_interpolated(self):
        ctcs = [10, 20]
        old = [100.0, 80.0]
        new = [90.0, 100.0]  # diff: +10 -> -20, crosses 1/3 of the way
        ctc, tax = _find_crossover(ctcs, old, new)
        assert 13.0 < ctc < 14.0  # 10 + (10/30)*10 = 13.33

    def test_no_crossover_returns_none(self):
        ctcs = [10, 20, 30]
        old = [100.0, 90.0, 80.0]
        new = [50.0, 40.0, 30.0]  # new always cheaper, never crosses
        ctc, tax = _find_crossover(ctcs, old, new)
        assert ctc is None and tax is None
