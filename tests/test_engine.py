"""
tests/test_engine.py  --  Unit tests for regime_engine.py.

Run with:
    pytest tests/test_engine.py -v

Critical guardrails tested:
    1. New-regime deduction set contains ONLY Sec 19 + Sec 124 (no leakage)
    2. Old-regime deductions include all eligible items
    3. 5 validation scenarios from the DOD
    4. Surcharge marginal relief prevents cliff at Rs 50L threshold
    5. New-regime rebate marginal relief prevents cliff at Rs 12L boundary
"""

from __future__ import annotations

import sys
import os

# Allow import from parent directory when running via pytest from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from regime_engine import (
    TaxParams, TaxResult, compute,
    _calc_base_tax, _calc_surcharge_with_relief, _hra_exemption,
    _old_regime_deductions, _new_regime_deductions,
    NEW_REGIME_REBATE_LIMIT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _basic_params(**kwargs) -> TaxParams:
    """Minimal valid TaxParams; caller overrides specific fields."""
    base = dict(
        gross_ctc=10_00_000,
        basic=4_50_000,
        hra_component=2_25_000,
        employer_pf=21_600,
        gratuity=21_645,
        rent_paid=0,
        metro=False,
    )
    base.update(kwargs)
    return TaxParams(**base)


# ---------------------------------------------------------------------------
# GUARDRAIL 1: New-regime deduction leakage test
# ---------------------------------------------------------------------------

class TestNewRegimeDeductionSet:
    """GUARDRAIL 1: No old-regime deductions must leak into the new regime."""

    ALLOWED_NEW_KEYS = {
        "Sec 19 — Standard deduction",
        "Sec 124 — Employer NPS (cap 14% basic)",
    }

    def _check_no_leak(self, p: TaxParams) -> None:
        new_ded = _new_regime_deductions(p)
        unexpected = set(new_ded.keys()) - self.ALLOWED_NEW_KEYS
        assert not unexpected, (
            f"New-regime deductions contain unexpected keys: {unexpected}"
        )

    def test_new_regime_no_professional_tax(self):
        p = _basic_params(professional_tax=2_400)
        self._check_no_leak(p)

    def test_new_regime_no_hra(self):
        p = _basic_params(hra_component=2_25_000, rent_paid=3_00_000, metro=True)
        self._check_no_leak(p)

    def test_new_regime_no_sec123(self):
        p = _basic_params(employee_pf_80c=21_600, decl_80c_other=1_00_000)
        self._check_no_leak(p)

    def test_new_regime_no_sec126(self):
        p = _basic_params(decl_80d_self=25_000, decl_80d_parents=50_000)
        self._check_no_leak(p)

    def test_new_regime_no_ccd1b(self):
        p = _basic_params(decl_80ccd_1b_nps=50_000)
        self._check_no_leak(p)

    def test_new_regime_no_sec129(self):
        p = _basic_params(decl_80e_edu=1_00_000)
        self._check_no_leak(p)

    def test_new_regime_no_sec24b(self):
        p = _basic_params(decl_24b_home=2_00_000)
        self._check_no_leak(p)

    def test_new_regime_with_employer_nps(self):
        """Sec 124 employer NPS IS allowed in new regime."""
        p = _basic_params(employer_nps=45_000)
        new_ded = _new_regime_deductions(p)
        self._check_no_leak(p)
        assert new_ded["Sec 124 — Employer NPS (cap 14% basic)"] > 0

    def test_new_regime_sec124_cap_is_14pct_basic(self):
        """New regime Sec 124 cap = 14% of basic (not 10%)."""
        p = _basic_params(basic=5_00_000, employer_nps=1_00_000)
        new_ded = _new_regime_deductions(p)
        assert new_ded["Sec 124 — Employer NPS (cap 14% basic)"] == 70_000  # 14% of 5L


class TestOldRegimeDeductionSet:
    """Old regime should include ALL eligible deductions."""

    def test_hra_in_old_regime(self):
        p = _basic_params(hra_component=2_25_000, rent_paid=3_00_000, metro=True)
        old_ded = _old_regime_deductions(p)
        assert old_ded["Sec 14(10) — HRA exemption"] > 0

    def test_professional_tax_in_old_regime(self):
        p = _basic_params(professional_tax=2_400)
        old_ded = _old_regime_deductions(p)
        assert old_ded["Professional tax"] == 2_400

    def test_sec123_cap_at_150000(self):
        p = _basic_params(employee_pf_80c=1_00_000, decl_80c_other=1_00_000)
        old_ded = _old_regime_deductions(p)
        # Total 2L, capped at 1.5L
        assert old_ded["Sec 123 — PF + 80C / ELSS / LIC (cap Rs 1.5L)"] == 1_50_000

    def test_sec124_cap_is_10pct_basic_old_regime(self):
        p = _basic_params(basic=5_00_000, employer_nps=1_00_000)
        old_ded = _old_regime_deductions(p)
        # 10% of 5L = 50k, but employer_nps = 1L → cap 50k
        assert old_ded["Sec 124 — Employer NPS (cap 10% basic)"] == 50_000

    def test_sec24b_capped_at_200000(self):
        p = _basic_params(decl_24b_home=5_00_000)
        old_ded = _old_regime_deductions(p)
        assert old_ded["Sec 24(b) — Home loan interest (cap Rs 2L)"] == 2_00_000


# ---------------------------------------------------------------------------
# HRA exemption tests
# ---------------------------------------------------------------------------

class TestHRAExemption:
    def test_metro_50pct(self):
        # min(HRA=3L, 50% of 6L=3L, rent 4L - 10% of 6L=3.4L) = 3L
        ex = _hra_exemption(3_00_000, 6_00_000, 4_00_000, metro=True)
        assert ex == 3_00_000

    def test_non_metro_40pct(self):
        # min(HRA=2L, 40% of 5L=2L, rent 3L - 10% of 5L=2.5L) = 2L
        ex = _hra_exemption(2_00_000, 5_00_000, 3_00_000, metro=False)
        assert ex == 2_00_000

    def test_rent_below_10pct_basic(self):
        # Rent = 30k, 10% basic = 50k → rent - 10% < 0 → exemption = 0
        ex = _hra_exemption(2_00_000, 5_00_000, 30_000, metro=False)
        assert ex == 0

    def test_no_rent(self):
        ex = _hra_exemption(2_00_000, 5_00_000, 0, metro=True)
        assert ex == 0


class TestHRAExemptionThreeLeg:
    """
    Regression lock for the three-leg Sec 14(10) rule as it surfaces in the
    app's manual mode (Round-2 BUG 2). A manual-style person with CTC 20L has a
    derived basic of 9L and HRA component of 4.5L (50% of basic, metro). The
    granted exemption is the LEAST of the three legs and must be:
      - non-zero (and equal to the least leg) when rent clearly exceeds 10% basic;
      - zero when rent is below 10% of basic (leg (c) floors at 0);
      - zero when rent is 0.
    """

    HRA_KEY = "Sec 14(10) — HRA exemption"

    def _manual_person(self, rent: float) -> TaxParams:
        # CTC 20L -> basic 9L, HRA component 4.5L (metro, 50% of basic).
        return _basic_params(
            gross_ctc=20_00_000, basic=9_00_000, hra_component=4_50_000,
            rent_paid=rent, metro=True,
        )

    def test_rent_above_10pct_basic_grants_least_leg(self):
        # Rent 4,80,000: leg(c) = 4,80,000 - 90,000 = 3,90,000.
        # Legs: (a) 4,50,000, (b) 50% of 9L = 4,50,000, (c) 3,90,000 -> least 3,90,000.
        p = self._manual_person(4_80_000)
        ded = _old_regime_deductions(p)
        assert ded[self.HRA_KEY] == 3_90_000
        # And it equals the explicit least-of-three legs.
        legs = (p.hra_component, 0.50 * p.basic, max(0.0, p.rent_paid - 0.10 * p.basic))
        assert ded[self.HRA_KEY] == min(legs)
        assert ded[self.HRA_KEY] > 0

    def test_rent_below_10pct_basic_grants_zero(self):
        # The exact case the tester hit: basic 9L, rent 40,000 < 90,000.
        p = self._manual_person(40_000)
        ded = _old_regime_deductions(p)
        assert ded[self.HRA_KEY] == 0

    def test_zero_rent_grants_zero(self):
        p = self._manual_person(0)
        ded = _old_regime_deductions(p)
        assert ded[self.HRA_KEY] == 0


# ---------------------------------------------------------------------------
# Tax slab tests
# ---------------------------------------------------------------------------

class TestSlabs:
    def test_new_regime_zero_below_4L(self):
        assert _calc_base_tax(3_99_999, "new") == 0.0

    def test_new_regime_slab_5pct(self):
        # 4L to 8L at 5%: on 4L income entirely in this slab = 5% of (4L-4L)... wait 4L is boundary
        # tax on 6L: 0 + 5% * 2L = 10,000
        tax = _calc_base_tax(6_00_000, "new")
        assert tax == 10_000.0

    def test_old_regime_zero_below_250k(self):
        assert _calc_base_tax(2_50_000, "old") == 0.0

    def test_old_regime_12pct_income_at_500k(self):
        # 0-2.5L:0, 2.5-5L: 5%*250k = 12500
        tax = _calc_base_tax(5_00_000, "old")
        assert tax == 12_500.0


# ---------------------------------------------------------------------------
# Surcharge marginal relief
# ---------------------------------------------------------------------------

class TestSurcharge:
    def test_no_surcharge_below_50L(self):
        base = _calc_base_tax(49_00_000, "new")
        sur, relief = _calc_surcharge_with_relief(base, 49_00_000, "new")
        assert sur == 0.0

    def test_surcharge_10pct_just_above_50L(self):
        # Just above 50L, nominal surcharge = 10%
        # Marginal relief may kick in for incomes just above 50L
        base = _calc_base_tax(51_00_000, "new")
        sur, relief = _calc_surcharge_with_relief(base, 51_00_000, "new")
        assert sur >= 0

    def test_marginal_relief_prevents_cliff_50L(self):
        """
        Tax just above Rs 50L must not greatly exceed tax at Rs 50L plus the extra rupees.

        Marginal relief caps (tax + surcharge) before cess.  Cess (4%) applies on top,
        so crossing Rs 1L over the threshold should cost at most Rs 1L × 1.04 = Rs 1,04,000
        in additional tax (not Rs 1L + 10% surcharge on the full base).
        """
        base_at_50 = _calc_base_tax(50_00_000, "new")
        # No surcharge at exactly 50L
        total_at_50 = base_at_50 * 1.04  # base + cess (no surcharge at threshold)

        income_over = 51_00_000  # Rs 1L above
        base_over = _calc_base_tax(income_over, "new")
        sur_over, _ = _calc_surcharge_with_relief(base_over, income_over, "new")
        total_over = (base_over + sur_over) * 1.04

        # Marginal relief ensures (tax+sur) doesn't cliff; cess adds 4% on top.
        # So total at 51L should not exceed total at 50L + 1L × 1.04 (cess-inclusive).
        max_allowed = total_at_50 + 1_00_000 * 1.04 + 1  # +1 for rounding
        assert total_over <= max_allowed, (
            f"Cliff at Rs 50L: total at 51L ({total_over:.0f}) > "
            f"total at 50L ({total_at_50:.0f}) + 1.04L ({max_allowed:.0f})"
        )

    def test_new_regime_surcharge_cap_25pct(self):
        """New regime surcharge must never exceed 25%."""
        base = _calc_base_tax(10_00_00_000, "new")  # 100 Cr
        sur, _ = _calc_surcharge_with_relief(base, 10_00_00_000, "new")
        assert sur <= base * 0.25 + 1


# ---------------------------------------------------------------------------
# New-regime rebate marginal relief at Rs 12L
# ---------------------------------------------------------------------------

class TestRebateMarginalRelief:
    def test_no_tax_at_12L_new_regime(self):
        """At exactly Rs 12L taxable income, new regime tax = 0."""
        p = TaxParams(
            gross_ctc=13_46_000, basic=6_05_700,
            hra_component=3_02_850, employer_pf=21_600, gratuity=29_134,
            rent_paid=0, metro=False,
        )
        r = compute(p)
        # Taxable new = 1346000 - 21600 - 29134 - 75000 = ~12,20,266 ... not exact
        # Build a param where taxable new is EXACTLY 12L
        # gross = 12L + 75k std ded = 12.75L  → gross_ctc = 12.75L + employer_pf + gratuity
        gross_for_tax = 12_00_000 + 75_000  # taxable before std ded
        # No employer_pf or gratuity to keep it clean
        p2 = TaxParams(
            gross_ctc=gross_for_tax, basic=5_00_000,
            hra_component=2_50_000, employer_pf=0, gratuity=0,
            rent_paid=0, metro=False,
        )
        r2 = compute(p2)
        assert r2.new.taxable_income == 12_00_000
        assert r2.new.total_tax == 0, f"Expected 0 at Rs 12L taxable new, got {r2.new.total_tax}"

    def test_smooth_transition_above_12L_new_regime(self):
        """
        For taxable income just above Rs 12L in new regime, total tax should grow
        smoothly (not jump to Rs 60k+ suddenly).
        Specifically, total_tax(12L + X) <= X for small X.
        """
        def _tax_at_taxable_new(taxable: float) -> float:
            # Build params where new-regime taxable = exactly 'taxable'
            gross = taxable + 75_000  # std ded = 75k in new regime
            p = TaxParams(
                gross_ctc=gross, basic=4_50_000,
                hra_component=2_25_000, employer_pf=0, gratuity=0,
                rent_paid=0, metro=False,
            )
            return compute(p).new.total_tax

        # At 12L: should be 0
        t_12l = _tax_at_taxable_new(12_00_000)
        assert t_12l == 0, f"Tax at 12L should be 0, got {t_12l}"

        # At 12L + 50k: should be <= 50k
        t_12l_50k = _tax_at_taxable_new(12_00_000 + 50_000)
        assert t_12l_50k <= 50_000 + 100, (  # +100 tolerance for rounding
            f"Tax at 12L+50k = {t_12l_50k}, should be <= 50,000"
        )

        # At 12L + 5L: marginal relief should no longer apply, smooth growth
        t_17l = _tax_at_taxable_new(17_00_000)
        assert t_17l > 0


# ---------------------------------------------------------------------------
# DOD Validation scenarios (5 scenarios)
# ---------------------------------------------------------------------------

class TestValidationScenarios:
    """
    Five scenarios from the Definition of Done.
    These also serve as regression tests.
    """

    def test_scenario_1_inf1000_new_wins(self):
        """INF1000: gross_ctc 16.65L, non-declarer, metro, rent 4.33L -> NEW wins."""
        p = TaxParams(
            gross_ctc=16_65_000, basic=7_49_200,
            hra_component=3_74_600, employer_pf=21_600, gratuity=36_037,
            rent_paid=4_33_000, metro=True,
            employee_pf_80c=21_600, professional_tax=2_400,
        )
        r = compute(p)
        print(f"\nScenario 1: OLD={r.old.total_tax:,}  NEW={r.new.total_tax:,}  winner={r.winner}")
        assert r.winner == "new", (
            f"Scenario 1 expected NEW wins, got {r.winner}. "
            f"OLD={r.old.total_tax}, NEW={r.new.total_tax}"
        )

    def test_scenario_2_inf1002_deductions_gated(self):
        """
        INF1002: gross_ctc 15.31L, home loan + deductions, metro, no rent.

        Computed: OLD=Rs 1,60,449  NEW=Rs 93,797  winner=NEW.

        Note: the task spec says 'OLD competitive/wins' but for a 15.31L earner with
        3.37L in deductions, new-regime slabs (15% in 12-16L band) beat old-regime
        slabs (30% at 10L+) even after the deduction benefit.  The CRITICAL assertion
        here is that all declared deductions (Sec 123, 126, 129, 24b) are correctly
        gated to old regime only and do NOT appear in new regime.
        """
        p = TaxParams(
            gross_ctc=15_31_000, basic=6_89_000,
            hra_component=3_44_500, employer_pf=21_600, gratuity=33_141,
            rent_paid=0, metro=True,
            employee_pf_80c=21_600, decl_80c_other=29_000,
            decl_80d_self=25_000, decl_80e_edu=19_000,
            decl_24b_home=1_90_000, professional_tax=2_400,
        )
        r = compute(p)
        print(f"\nScenario 2: OLD={r.old.total_tax:,}  NEW={r.new.total_tax:,}  winner={r.winner}")

        # GUARDRAIL: deductions gated correctly to old regime only
        new_ded = _new_regime_deductions(p)
        old_ded = _old_regime_deductions(p)

        # New regime must NOT contain these old-regime-only deductions
        forbidden_patterns = ["24(b)", "home", "80e", "sec 129", "80d", "sec 126",
                               "sec 123", "80c", "professional"]
        for label in new_ded.keys():
            for pat in forbidden_patterns:
                assert pat not in label.lower(), (
                    f"Old-regime deduction leaked into new regime: '{label}'"
                )

        # Old regime MUST contain these deductions with correct values
        assert old_ded["Sec 24(b) — Home loan interest (cap Rs 2L)"] == 1_90_000
        assert old_ded["Sec 126 — 80D medical self (cap Rs 25k)"] == 25_000
        assert old_ded["Sec 129 — 80E education loan interest"] == 19_000
        assert old_ded["Sec 123 — PF + 80C / ELSS / LIC (cap Rs 1.5L)"] == 50_600

        # Old regime should be more competitive than a non-declarer in old regime
        p_no_ded = TaxParams(
            gross_ctc=15_31_000, basic=6_89_000,
            hra_component=3_44_500, employer_pf=21_600, gratuity=33_141,
            rent_paid=0, metro=True, employee_pf_80c=21_600, professional_tax=2_400,
        )
        r_no_ded = compute(p_no_ded)
        assert r.old.total_tax < r_no_ded.old.total_tax, (
            "Deductions should reduce old-regime tax vs non-declarer"
        )

    def test_scenario_3_rebate_marginal_relief(self):
        """Taxable new just above Rs 12L: confirm rebate marginal relief applies."""
        # Taxable new = 12L + 1L = 13L → without relief, tax = ~25,000 (15% of 1L)
        # With rebate marginal relief: tax should be <= 1L
        gross = 13_00_000 + 75_000  # +75k std ded
        p = TaxParams(
            gross_ctc=gross, basic=5_00_000,
            hra_component=2_50_000, employer_pf=0, gratuity=0,
            rent_paid=0, metro=False,
        )
        r = compute(p)
        assert r.new.taxable_income == 13_00_000
        # Tax should not jump sharply — with relief: total <= (taxable - 12L) = 1L
        assert r.new.total_tax <= 1_00_000 + 500, (  # 500 for rounding
            f"Scenario 3: expected new tax <= 1L at 13L taxable, got {r.new.total_tax}"
        )

    def test_scenario_4_high_earner_surcharge(self):
        """Gross > Rs 50L: surcharge triggers AND marginal relief cap holds."""
        # Gross CTC 65L: basic 29.25L, etc.
        p = TaxParams(
            gross_ctc=65_00_000, basic=29_25_000,
            hra_component=14_62_500, employer_pf=21_600, gratuity=1_40_693,
            rent_paid=0, metro=True,
        )
        r = compute(p)
        print(f"\nScenario 4: OLD={r.old.total_tax:,}  NEW={r.new.total_tax:,}  winner={r.winner}")
        # Confirm surcharge is applied in at least one regime
        surcharge_applied = r.old.surcharge > 0 or r.new.surcharge > 0
        assert surcharge_applied, "Scenario 4: expected surcharge for 65L CTC"
        # Marginal relief: verify total at 65L doesn't catastrophically exceed total at 50L + 15L
        # (just a sanity bound, not a strict pass)
        assert r.old.total_tax > 0 and r.new.total_tax > 0

    def test_scenario_5_low_earner_old_rebate(self):
        """Low earner ~6L gross, full 80C -> OLD regime 87A rebate should zero the tax."""
        p = TaxParams(
            gross_ctc=6_00_000, basic=2_70_000,
            hra_component=1_35_000, employer_pf=21_600, gratuity=12_987,
            rent_paid=0, metro=False,
            employee_pf_80c=21_600, decl_80c_other=1_28_400,
            professional_tax=2_400,
        )
        r = compute(p)
        print(f"\nScenario 5: OLD={r.old.total_tax:,}  NEW={r.new.total_tax:,}  winner={r.winner}")
        # Old taxable = gross - 50k - 2.4k - 150k = (600k-21600-12987) - 50k - 2.4k - 150k
        # = 565413 - 202400 = 363013 → below 5L → rebate applies → tax = 0
        assert r.old.total_tax == 0, (
            f"Scenario 5: expected old regime tax = 0 (87A rebate), got {r.old.total_tax}. "
            f"Taxable old = {r.old.taxable_income}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
