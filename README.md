# Tax Regime Optimiser — Tax Year 2026-27

Old vs new regime income tax comparison for salaried employees under the
Income Tax Act 2025.  Computes both regimes, highlights the winner, shows
a breakeven chart, and exports a one-page branded PDF advisory.

Built by [Anuj Sureshkumar](https://anujsureshkumar.com) as part of the
*AI for Finance* portfolio.

---

## What it does

- Computes income tax under **both regimes** (Tax Year 2026-27, IT Act 2025):
  old-regime slabs (2.5/5/20/30%) and new-regime slabs (0/5/10/15/20/25/30%).
- Applies **surcharge with marginal relief** at all thresholds (Rs 50L, 1Cr, 2Cr, 5Cr).
- Applies **Sec 156 rebate** (formerly 87A): new regime up to Rs 60k when taxable
  income is Rs 12L or below; old regime up to Rs 12.5k when taxable is Rs 5L or below.
- Applies **new-regime rebate marginal relief** at the Rs 12L boundary so tax grows
  smoothly above it.
- Enforces **regime-gated deductions**: Sec 123, Sec 126, 80CCD(1B), Sec 129,
  Sec 24(b), HRA, professional tax are old-regime only.  New regime gets only
  Sec 19 standard deduction (Rs 75k) and Sec 124 employer NPS (cap 14% basic).
- Wires to 50 **synthetic demo employees** from `salary_master.csv` (non-real data).
- Exports a **one-page branded PDF advisory** with disclaimer.

---

## Prerequisites

Install Python 3.12 if you do not already have it:

```powershell
winget install --id Python.Python.3.12 -e
```

Restart your terminal after installation so `python` is on the PATH.

---

## Setup (PowerShell)

```powershell
# 1. Navigate to this project
cd "D:\Claude Projects\portfolio\tax-regime-optimizer"

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Run the app

```powershell
# Activate venv if not already active
.venv\Scripts\Activate.ps1

# Launch Streamlit
streamlit run app.py
```

The app opens at `http://localhost:8501`.

---

## Run unit tests

```powershell
# From the project root (tax-regime-optimizer\)
pytest tests/test_engine.py -v
```

Tests cover:
- New-regime deduction leakage (guardrail)
- All five DOD validation scenarios
- Surcharge marginal relief at the Rs 50L threshold
- New-regime rebate marginal relief at the Rs 12L boundary
- HRA exemption, slab computation

---

## Run engine self-checks

```powershell
python regime_engine.py
```

Prints the five validation scenarios to the console with PASS/FAIL status.

---

## Project structure

```
tax-regime-optimizer/
├── .streamlit/
│   └── config.toml          # Brand theme (Sea Green, Tahoma)
├── tests/
│   └── test_engine.py       # Pytest unit tests
├── app.py                   # Streamlit UI
├── regime_engine.py         # Tax engine (import this for custom use)
├── pdf_report.py            # ReportLab one-page PDF
├── requirements.txt
└── README.md
```

Salary data lives at `../synthetic-data/output/salary_master.csv`.

---

## Data note

All 50 demo employees are **synthetic** — invented names, PANs, and salary
figures.  No real employee data is used.  Re-generate the data at any time:

```powershell
cd "..\synthetic-data"
python gen_salary_slips.py
```

---

## Tax computation reference

| Item | IT Act 2025 section | Old regime | New regime |
|---|---|---|---|
| Standard deduction | Sec 19 | Rs 50,000 | Rs 75,000 |
| HRA exemption | Sec 14(10) | Yes | No |
| Employer NPS | Sec 124 | Cap 10% basic | Cap 14% basic |
| 80C / PF / ELSS | Sec 123 | Cap Rs 1.5L | No |
| Medical insurance | Sec 126 | Self Rs 25k, Parents Rs 50k | No |
| Employee NPS | 80CCD(1B) | Cap Rs 50k | No |
| Education loan | Sec 129 | No cap | No |
| Home loan interest | Sec 24(b) | Cap Rs 2L | No |
| Professional tax | — | Rs 2,400 | No (company policy) |
| Rebate | Sec 156 (old: 87A) | Up to Rs 12.5k if taxable <= 5L | Up to Rs 60k if taxable <= 12L |
| Surcharge cap | — | 10/15/25/37% | 10/15/25/25% (capped at 25%) |

---

*Part of the [AI for Finance](https://anujsureshkumar.com) portfolio by Anuj Sureshkumar.*
