"""
regime_engine.py  --  Tax Year 2026-27 income tax engine.
Income Tax Act 2025 (New IT Act).

Both old and new regimes: slabs, surcharge with marginal relief,
4% cess, Sec 156 rebate (both regimes), new-regime rebate marginal
relief at the Rs 12 lakh boundary, regime-gated deductions.

Public API
----------
    from regime_engine import TaxParams, compute, params_from_csv_row

    params = TaxParams(gross_ctc=1_665_000, basic=749_200, ...)
    result = compute(params)
    print(result.winner, result.savings)

All monetary values in Indian Rupees (Rs).  Annual figures throughout.
Section codes are IT Act 2025 (e.g. Sec 123 = old 80C, Sec 124 = old
80CCD(2), Sec 126 = old 80D, Sec 129 = old 80E, Sec 156 = old 87A).
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Constants  (IT Act 2025 / verified against reference calculator)
# ---------------------------------------------------------------------------

STD_DED_OLD = 50_000          # Sec 19 -- old regime standard deduction
STD_DED_NEW = 75_000          # Sec 19 -- new regime (enhanced)
SEC_123_CAP = 1_50_000        # Sec 123 (old 80C) combined cap
SEC_126_SELF_CAP  = 25_000    # Sec 126 (old 80D) -- self + family
SEC_126_PARENTS_CAP = 50_000  # Sec 126 (old 80D) -- parents
SEC_CCD1B_CAP = 50_000        # 80CCD(1B) -- employee NPS
SEC_24B_CAP = 2_00_000        # Sec 24(b) -- home loan interest
PROFESSIONAL_TAX = 2_400      # Rs 2,400/year (company policy; OLD regime only)

# Sec 156 rebate (old: 87A)
NEW_REGIME_REBATE_MAX   = 60_000     # max rebate under new regime
NEW_REGIME_REBATE_LIMIT = 12_00_000  # taxable income threshold
OLD_REGIME_REBATE_MAX   = 12_500     # max rebate under old regime
OLD_REGIME_REBATE_LIMIT =  5_00_000  # taxable income threshold

# 8 metro cities per Sec 14(10) of IT Act 2025
METRO_CITIES = frozenset({
    "mumbai", "delhi", "kolkata", "chennai",
    "bengaluru", "hyderabad", "pune", "ahmedabad",
})


# ---------------------------------------------------------------------------
# Input / output data structures
# ---------------------------------------------------------------------------

@dataclass
class TaxParams:
    """
    Inputs for both-regime tax comparison.

    Salary structure:
        gross_ctc       Total annual CTC (employer cost)
        basic           Annual basic salary
        hra_component   HRA component in CTC (annual)
        employer_pf     Employer PF contribution (exempt; deducted from gross_ctc
                        to derive taxable gross)
        gratuity        Gratuity provision (exempt; deducted from gross_ctc)
        rent_paid       Annual rent paid (for Sec 14(10) HRA exemption)
        metro           True = metro city (50% basic); False = non-metro (40%)

    IT Act 2025 deductions (legacy column names in parentheses):
        employee_pf_80c     Employee PF (80C pool) -- Sec 123
        decl_80c_other      Other 80C: PPF, ELSS, LIC, etc. -- Sec 123
        decl_80d_self       Medical insurance self -- Sec 126, cap Rs 25k
        decl_80d_parents    Medical insurance parents -- Sec 126, cap Rs 50k
        decl_80ccd_1b_nps   Employee NPS Tier-I (80CCD(1B)) -- cap Rs 50k
        decl_80e_edu        Education loan interest (80E / Sec 129) -- no cap
        decl_24b_home       Home loan interest -- Sec 24(b), cap Rs 2L
        employer_nps        Employer NPS (80CCD(2) / Sec 124):
                            OLD cap = 10% of basic; NEW cap = 14% of basic
        professional_tax    Rs 2,400/year; OLD regime only (company policy)
    """
    gross_ctc: float = 0.0
    basic: float = 0.0
    hra_component: float = 0.0
    employer_pf: float = 0.0    # exempt component of CTC
    gratuity: float = 0.0       # exempt component of CTC
    rent_paid: float = 0.0      # annual
    metro: bool = False

    # Sec 123 (old 80C)
    employee_pf_80c: float = 0.0
    decl_80c_other: float = 0.0

    # Sec 126 (old 80D)
    decl_80d_self: float = 0.0
    decl_80d_parents: float = 0.0

    # Other old-regime deductions
    decl_80ccd_1b_nps: float = 0.0
    decl_80e_edu: float = 0.0
    decl_24b_home: float = 0.0

    # Sec 124 -- employer NPS (both regimes, different caps)
    employer_nps: float = 0.0

    # Professional tax
    professional_tax: float = float(PROFESSIONAL_TAX)


@dataclass
class RegimeBreakdown:
    """Itemised tax computation for one regime."""
    regime: str                  # 'old' or 'new'
    gross_income: float          # gross taxable salary (after removing exempt employer costs)
    deductions: dict             # {label: amount}
    total_deductions: float
    taxable_income: float
    base_tax: float
    rebate: float
    marginal_relief_rebate: float  # new-regime Rs 12L rebate marginal relief applied
    surcharge: float
    marginal_relief_surcharge: float  # surcharge marginal relief applied
    cess: float
    total_tax: float
    effective_rate_pct: float    # total_tax / gross_ctc * 100


@dataclass
class TaxResult:
    old: RegimeBreakdown
    new: RegimeBreakdown
    winner: str                  # 'old', 'new', or 'equal'
    savings: float               # absolute difference (Rs)


# ---------------------------------------------------------------------------
# Slab tax computation
# ---------------------------------------------------------------------------

def _calc_base_tax(taxable: float, regime: str) -> float:
    """Slab-wise income tax only. No surcharge, cess, or rebate."""
    if regime == "new":
        # IT Act 2025 new-regime slabs (Tax Year 2026-27)
        slabs = [
            (0,          4_00_000,  0.00),
            (4_00_000,   8_00_000,  0.05),
            (8_00_000,  12_00_000,  0.10),
            (12_00_000, 16_00_000,  0.15),
            (16_00_000, 20_00_000,  0.20),
            (20_00_000, 24_00_000,  0.25),
            (24_00_000,  1e12,      0.30),
        ]
    else:
        # IT Act 2025 old-regime slabs (below-60 age bracket)
        slabs = [
            (0,          2_50_000,  0.00),
            (2_50_000,   5_00_000,  0.05),
            (5_00_000,  10_00_000,  0.20),
            (10_00_000,  1e12,      0.30),
        ]
    tax = 0.0
    for lo, hi, rate in slabs:
        if taxable > lo:
            tax += min(taxable - lo, hi - lo) * rate
    return tax


# ---------------------------------------------------------------------------
# Surcharge with marginal relief
# ---------------------------------------------------------------------------

def _nominal_surcharge_rate(taxable: float, regime: str) -> float:
    """Nominal surcharge rate before marginal relief."""
    # NEW regime caps at 25% (IT Act 2025)
    if taxable > 5_00_00_000:    # > Rs 5 Cr
        return 0.25 if regime == "new" else 0.37
    if taxable > 2_00_00_000:    # > Rs 2 Cr
        return 0.25
    if taxable > 1_00_00_000:    # > Rs 1 Cr
        return 0.15
    if taxable > 50_00_000:      # > Rs 50 L
        return 0.10
    return 0.0


def _calc_surcharge_with_relief(
    base_tax: float, taxable: float, regime: str
) -> tuple[float, float]:
    """
    Returns (surcharge_applied, relief_amount).

    Marginal relief rule: (base_tax + surcharge) must not exceed
    (total_at_threshold + income_above_threshold), where total_at_threshold
    uses the rate applicable AT (not above) that threshold.

    Only the highest-crossed threshold is checked -- lower thresholds are
    never binding once the income is well into the next bracket.
    """
    if taxable <= 50_00_000:
        return 0.0, 0.0

    nominal_rate = _nominal_surcharge_rate(taxable, regime)
    nominal_surcharge = base_tax * nominal_rate

    # Map nominal rate -> (threshold that triggered it, rate just below threshold)
    # NEW regime: 25% applies both at 2Cr and 5Cr thresholds (same rate), so
    # at 5Cr+ we compare against the 5Cr threshold with rate=25% below it.
    if regime == "new" and nominal_rate == 0.25:
        if taxable > 5_00_00_000:
            active_threshold, rate_at_threshold = 5_00_00_000, 0.25
        else:
            active_threshold, rate_at_threshold = 2_00_00_000, 0.15
    else:
        rate_map = {
            0.10: (50_00_000,    0.00),
            0.15: (1_00_00_000,  0.10),
            0.25: (2_00_00_000,  0.15),
            0.37: (5_00_00_000,  0.25),
        }
        active_threshold, rate_at_threshold = rate_map.get(nominal_rate, (None, None))

    if active_threshold is None:
        return nominal_surcharge, 0.0

    # Total tax+surcharge at the threshold (no relief applied AT threshold itself)
    base_at_T = _calc_base_tax(active_threshold, regime)
    total_at_T = base_at_T * (1 + rate_at_threshold)
    # Cap: income_above_threshold flows through at 100% (no tax on the marginal rupee
    # beyond what the threshold tax creates)
    cap_total = total_at_T + (taxable - active_threshold)
    max_surcharge = max(0.0, cap_total - base_tax)
    applied = min(nominal_surcharge, max_surcharge)
    relief = nominal_surcharge - applied
    return applied, relief


# ---------------------------------------------------------------------------
# HRA exemption -- Sec 14(10)
# ---------------------------------------------------------------------------

def _hra_exemption(
    hra_component: float, basic: float, rent_paid: float, metro: bool
) -> float:
    """
    Annual HRA exemption under Sec 14(10) of IT Act 2025.
    Minimum of:
      (a) Actual HRA component
      (b) 50% of basic (metro) / 40% (non-metro)
      (c) Actual rent paid minus 10% of basic
    Zero if rent_paid is zero or hra_component is zero.
    """
    if rent_paid <= 0 or hra_component <= 0:
        return 0.0
    city_pct = 0.50 if metro else 0.40
    exemption = min(
        hra_component,
        basic * city_pct,
        max(0.0, rent_paid - basic * 0.10),
    )
    return max(0.0, exemption)


# ---------------------------------------------------------------------------
# Regime-gated deduction sets
# ---------------------------------------------------------------------------

def _old_regime_deductions(p: TaxParams) -> dict:
    """
    OLD regime deductions -- ALL eligible items.
    Returns {label: capped_amount}.

    GUARDRAIL: none of these items must appear in the new-regime dict.
    """
    hra_ex = _hra_exemption(p.hra_component, p.basic, p.rent_paid, p.metro)

    # Sec 123 (old 80C): employee PF + other 80C declarations, combined cap Rs 1.5L
    sec123 = min(p.employee_pf_80c + p.decl_80c_other, SEC_123_CAP)

    # Sec 126 (old 80D): separate caps for self and parents
    sec126_self    = min(p.decl_80d_self,    SEC_126_SELF_CAP)
    sec126_parents = min(p.decl_80d_parents, SEC_126_PARENTS_CAP)

    # 80CCD(1B) employee NPS: cap Rs 50k
    ccd1b = min(p.decl_80ccd_1b_nps, SEC_CCD1B_CAP)

    # Sec 129 (old 80E) education loan interest: no cap
    sec129 = max(0.0, p.decl_80e_edu)

    # Sec 24(b) home loan interest (self-occupied): cap Rs 2L
    sec24b = min(p.decl_24b_home, SEC_24B_CAP)

    # Sec 124 employer NPS: OLD cap = 10% of basic
    sec124_old = min(p.employer_nps, p.basic * 0.10)

    return {
        "Sec 19 — Standard deduction":              float(STD_DED_OLD),
        "Professional tax":                          float(p.professional_tax),
        "Sec 14(10) — HRA exemption":               hra_ex,
        "Sec 123 — PF + 80C / ELSS / LIC (cap Rs 1.5L)": sec123,
        "Sec 126 — 80D medical self (cap Rs 25k)":  sec126_self,
        "Sec 126 — 80D medical parents (cap Rs 50k)": sec126_parents,
        "80CCD(1B) — Employee NPS (cap Rs 50k)":    ccd1b,
        "Sec 129 — 80E education loan interest":    sec129,
        "Sec 24(b) — Home loan interest (cap Rs 2L)": sec24b,
        "Sec 124 — Employer NPS (cap 10% basic)":   sec124_old,
    }


def _new_regime_deductions(p: TaxParams) -> dict:
    """
    NEW regime deductions -- ONLY standard deduction + Sec 124 employer NPS.

    GUARDRAIL: professional tax, HRA, Sec 123, Sec 126, 80CCD(1B),
    Sec 129, Sec 24(b) are ALL excluded from this dict.
    """
    # Sec 124 employer NPS: NEW cap = 14% of basic
    sec124_new = min(p.employer_nps, p.basic * 0.14)

    return {
        "Sec 19 — Standard deduction":              float(STD_DED_NEW),
        "Sec 124 — Employer NPS (cap 14% basic)":  sec124_new,
    }


# ---------------------------------------------------------------------------
# Per-regime computation
# ---------------------------------------------------------------------------

def _compute_regime(
    gross: float,
    deductions: dict,
    regime: str,
    gross_ctc: float,
) -> RegimeBreakdown:
    total_ded = sum(deductions.values())
    taxable = max(0.0, round(gross - total_ded))

    base_tax = _calc_base_tax(taxable, regime)

    # Sec 156 rebate (old: 87A) -- apply before surcharge
    rebate = 0.0
    if regime == "new" and taxable <= NEW_REGIME_REBATE_LIMIT:
        rebate = min(base_tax, float(NEW_REGIME_REBATE_MAX))
    elif regime == "old" and taxable <= OLD_REGIME_REBATE_LIMIT:
        rebate = min(base_tax, float(OLD_REGIME_REBATE_MAX))

    tax_after_rebate = max(0.0, base_tax - rebate)

    # Surcharge with marginal relief
    surcharge, surcharge_relief = _calc_surcharge_with_relief(
        tax_after_rebate, taxable, regime
    )

    # New-regime rebate marginal relief at the Rs 12L boundary.
    # At exactly Rs 12L taxable, tax = 0 (rebate zeroes it).
    # For taxable > Rs 12L, ensure total tax (including cess) does not exceed
    # (taxable - Rs 12L).  Apply cap to (tax+surcharge) before cess.
    rebate_mr = 0.0
    if regime == "new" and taxable > NEW_REGIME_REBATE_LIMIT:
        pre_cess = tax_after_rebate + surcharge
        # Net tax at exactly Rs 12L = 0 (rebate fully covers Rs 60k tax there)
        # So cap on (tax+surcharge+cess) = taxable - 12L
        # => cap on (tax+surcharge) = (taxable - 12L) / 1.04
        cap_pre_cess = (taxable - NEW_REGIME_REBATE_LIMIT) / 1.04
        if pre_cess > cap_pre_cess:
            rebate_mr = pre_cess - cap_pre_cess
            # Reduce surcharge first; if surcharge is already 0, reduce tax
            surcharge_reduction = min(surcharge, rebate_mr)
            surcharge = surcharge - surcharge_reduction
            tax_reduction = rebate_mr - surcharge_reduction
            tax_after_rebate = max(0.0, tax_after_rebate - tax_reduction)

    cess = round((tax_after_rebate + surcharge) * 0.04)
    total_tax = round(tax_after_rebate + surcharge + cess)

    eff_rate = (total_tax / gross_ctc * 100) if gross_ctc > 0 else 0.0

    return RegimeBreakdown(
        regime=regime,
        gross_income=gross,
        deductions=deductions,
        total_deductions=total_ded,
        taxable_income=taxable,
        base_tax=round(base_tax),
        rebate=round(rebate),
        marginal_relief_rebate=round(rebate_mr),
        surcharge=round(surcharge),
        marginal_relief_surcharge=round(surcharge_relief),
        cess=cess,
        total_tax=total_tax,
        effective_rate_pct=round(eff_rate, 2),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute(p: TaxParams) -> TaxResult:
    """
    Compute old and new regime tax for a salaried person.
    Returns TaxResult with both regimes and the winner.

    Gross income for tax = gross_ctc - employer_pf - gratuity.
    (Employer PF and gratuity are employer costs included in CTC but
    exempt from employee's taxable salary.)
    """
    # Derive taxable gross: remove exempt employer-side costs
    gross = p.gross_ctc - p.employer_pf - p.gratuity

    old_ded = _old_regime_deductions(p)
    new_ded = _new_regime_deductions(p)

    old = _compute_regime(gross, old_ded, "old", p.gross_ctc)
    new = _compute_regime(gross, new_ded, "new", p.gross_ctc)

    if old.total_tax < new.total_tax:
        winner, savings = "old", new.total_tax - old.total_tax
    elif new.total_tax < old.total_tax:
        winner, savings = "new", old.total_tax - new.total_tax
    else:
        winner, savings = "equal", 0.0

    return TaxResult(old=old, new=new, winner=winner, savings=savings)


def params_from_csv_row(row) -> TaxParams:
    """
    Build TaxParams from a salary_master CSV row (pandas Series or dict).

    Maps legacy column names to IT Act 2025 sections:
        employee_pf_80c + decl_80c_other  -> Sec 123
        employer_nps_80ccd2               -> Sec 124
        decl_80d_self / decl_80d_parents  -> Sec 126
        decl_80ccd_1b_nps                 -> 80CCD(1B)
        decl_80e_edu_loan_int             -> Sec 129
        decl_24b_home_loan_int            -> Sec 24(b)
    """
    def _f(key: str, default: float = 0.0) -> float:
        try:
            v = row[key] if hasattr(row, '__getitem__') else getattr(row, key, default)
            return float(v) if v is not None else default
        except (KeyError, AttributeError, TypeError, ValueError):
            return default

    def _b(key: str) -> bool:
        try:
            v = row[key] if hasattr(row, '__getitem__') else getattr(row, key, False)
            if isinstance(v, (bool,)):
                return v
            if isinstance(v, str):
                return v.strip().lower() in ("true", "1", "yes")
            return bool(v)
        except (KeyError, AttributeError):
            return False

    return TaxParams(
        gross_ctc          = _f("gross_ctc"),
        basic              = _f("basic"),
        hra_component      = _f("hra_component"),
        employer_pf        = _f("employer_pf"),
        gratuity           = _f("gratuity"),
        rent_paid          = _f("rent_paid_annual"),
        metro              = _b("metro"),
        employee_pf_80c    = _f("employee_pf_80c"),
        decl_80c_other     = _f("decl_80c_other"),
        decl_80d_self      = _f("decl_80d_self"),
        decl_80d_parents   = _f("decl_80d_parents"),
        decl_80ccd_1b_nps  = _f("decl_80ccd_1b_nps"),
        decl_80e_edu       = _f("decl_80e_edu_loan_int"),
        decl_24b_home      = _f("decl_24b_home_loan_int"),
        employer_nps       = _f("employer_nps_80ccd2"),
        professional_tax   = _f("professional_tax", float(PROFESSIONAL_TAX)),
    )


# ---------------------------------------------------------------------------
# Self-test  (python regime_engine.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    def _inr(n: float) -> str:
        """Format as Indian Rs with lakh commas."""
        n = int(round(n))
        s = str(abs(n))
        if len(s) <= 3:
            result = s
        else:
            result = s[-3:]
            s = s[:-3]
            while len(s) > 2:
                result = s[-2:] + "," + result
                s = s[:-2]
            result = s + "," + result
        return ("Rs " if n >= 0 else "-Rs ") + result

    def _run(label: str, p: TaxParams, expect_winner: str = None) -> None:
        r = compute(p)
        status = ""
        if expect_winner:
            status = " PASS" if r.winner == expect_winner else f" FAIL (expected {expect_winner})"
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}")
        print(f"  Gross CTC       : {_inr(p.gross_ctc)}")
        print(f"  Taxable gross   : {_inr(p.gross_ctc - p.employer_pf - p.gratuity)}")
        print(f"  OLD regime tax  : {_inr(r.old.total_tax)}  "
              f"(taxable {_inr(r.old.taxable_income)}, eff {r.old.effective_rate_pct}%)")
        print(f"  NEW regime tax  : {_inr(r.new.total_tax)}  "
              f"(taxable {_inr(r.new.taxable_income)}, eff {r.new.effective_rate_pct}%)")
        print(f"  Winner          : {r.winner.upper()}  savings {_inr(r.savings)}{status}")

        # Guardrail: confirm no regime-bleed
        old_keys = set(r.old.deductions.keys())
        new_keys = set(r.new.deductions.keys())
        bleed = new_keys - {"Sec 19 — Standard deduction", "Sec 124 — Employer NPS (cap 14% basic)"}
        if bleed:
            print(f"  GUARDRAIL FAIL: new-regime deductions contain extra keys: {bleed}")
            sys.exit(1)

    # Scenario 1: INF1000 -- non-declarer, metro, rent. Expect NEW wins.
    _run("Scenario 1 -- INF1000 (non-declarer, CTC 16.65L, rent 4.33L, metro)",
         TaxParams(
             gross_ctc=16_65_000, basic=7_49_200,
             hra_component=3_74_600, employer_pf=21_600, gratuity=36_037,
             rent_paid=4_33_000, metro=True,
             employee_pf_80c=21_600, professional_tax=2_400,
         ),
         expect_winner="new")

    # Scenario 2: INF1002 -- declarer with home loan.
    # NEW wins at 15.31L CTC even with 3.37L in deductions because new-regime slabs
    # (15% in 12-16L band) dominate old-regime 30%. Key: deductions must be gated.
    _run("Scenario 2 -- INF1002 (declarer, CTC 15.31L, 80C+80D+80E+home loan, metro)",
         TaxParams(
             gross_ctc=15_31_000, basic=6_89_000,
             hra_component=3_44_500, employer_pf=21_600, gratuity=33_141,
             rent_paid=0, metro=True,
             employee_pf_80c=21_600, decl_80c_other=29_000,
             decl_80d_self=25_000, decl_80e_edu=19_000,
             decl_24b_home=1_90_000, professional_tax=2_400,
         ))

    # Scenario 3: taxable just above Rs 12L in new regime -- confirm rebate marginal relief
    _run("Scenario 3 -- taxable new ~Rs 12.05L (marginal relief boundary check)",
         TaxParams(
             gross_ctc=14_00_000, basic=6_30_000,
             hra_component=3_15_000, employer_pf=21_600, gratuity=30_303,
             rent_paid=0, metro=False,
         ))

    # Scenario 4: high earner > 50L -- confirm surcharge + marginal relief
    _run("Scenario 4 -- high earner CTC Rs 65L (surcharge + marginal relief)",
         TaxParams(
             gross_ctc=65_00_000, basic=29_25_000,
             hra_component=14_62_500, employer_pf=21_600, gratuity=1_40_693,
             rent_paid=0, metro=True,
         ))

    # Scenario 5: low earner ~6L, full 80C -- confirm OLD 87A rebate
    _run("Scenario 5 -- low earner CTC ~6L, full 80C Rs 1.5L (old rebate check)",
         TaxParams(
             gross_ctc=6_00_000, basic=2_70_000,
             hra_component=1_35_000, employer_pf=21_600, gratuity=12_987,
             rent_paid=0, metro=False,
             employee_pf_80c=21_600, decl_80c_other=1_28_400,
             professional_tax=2_400,
         ))

    print("\n\nAll engine self-tests completed.  Check PASS/FAIL lines above.")
