"""
app.py  --  Tax Regime Optimiser (Tax Year 2026-27, IT Act 2025).

Streamlit app: pick a demo employee OR enter your own salary details,
compare old vs new regime tax, see the winner, and export a branded
one-page PDF advisory.

Run:
    streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from pdf_report import generate_pdf
from regime_engine import TaxParams, TaxResult, compute, params_from_csv_row

# ---------------------------------------------------------------------------
# Page config and brand CSS injection
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Tax Regime Optimiser — Tax Year 2026-27",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    html, body, [class*="css"] {
        font-family: Tahoma, Verdana, "Trebuchet MS", "DejaVu Sans", sans-serif !important;
    }
    h1, h2, h3 { color: #2E3A36; }
    h2 { color: #2A8676; }
    .stButton>button { background-color: #4DBBAE; color: white; border: none; }
    .stButton>button:hover { background-color: #2A8676; color: white; }
    .winner-box {
        background: #4DBBAE; color: white; border-radius: 6px;
        padding: 14px 20px; text-align: center; font-size: 1.1rem; font-weight: bold;
    }
    .old-box {
        background: #E1EFEC; border-radius: 6px; padding: 12px 16px;
    }
    .new-box {
        background: #E1EFEC; border-radius: 6px; padding: 12px 16px;
    }
    .winner-regime {
        background: #B5E2D9; border-left: 4px solid #4DBBAE;
        border-radius: 4px; padding: 12px 16px;
    }
    .disclaimer-box {
        background: #E1EFEC; border-left: 4px solid #2A8676;
        border-radius: 4px; padding: 10px 14px; font-size: 0.8rem; color: #6B7570;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
from pathlib import Path

# Bundled inside the repo so the demo picker works on Streamlit Cloud
# (single-repo deploy). __file__-relative so it resolves regardless of CWD.
DATA_PATH = Path(__file__).parent / "data" / "salary_master.csv"

@st.cache_data
def load_salary_master() -> pd.DataFrame:
    try:
        df = pd.read_csv(DATA_PATH)
        return df
    except FileNotFoundError:
        return pd.DataFrame()


def _inr(n: float) -> str:
    """Format as Indian Rs with lakh-crore grouping."""
    n = int(round(n))
    s = str(abs(n))
    if len(s) <= 3:
        g = s
    else:
        g = s[-3:]
        s = s[:-3]
        while len(s) > 2:
            g = s[-2:] + "," + g
            s = s[:-2]
        g = s + "," + g
    return ("Rs " if n >= 0 else "-Rs ") + g


# ---------------------------------------------------------------------------
# Sidebar: input mode
# ---------------------------------------------------------------------------
st.sidebar.title("Tax Regime Optimiser")
st.sidebar.caption("Tax Year 2026-27  ·  Income Tax Act 2025")

mode = st.sidebar.radio(
    "Input mode",
    ["Pick a demo employee", "Enter my own details"],
    help="Demo employees are synthetic / non-real."
)

df = load_salary_master()

params: TaxParams | None = None
employee_name = "Employee"

# ---------------------------------------------------------------------------
# Mode A: Demo employee picker
# ---------------------------------------------------------------------------
if mode == "Pick a demo employee":
    st.sidebar.markdown(
        """
        <div style="background:#E1EFEC;border-radius:4px;padding:8px 10px;
        font-size:0.8rem;color:#6B7570;margin-top:6px;">
        <strong>Synthetic demo data</strong> — 50 non-real employees of a
        fictional ITeS company. Names, PANs and figures are invented.
        </div>
        """,
        unsafe_allow_html=True,
    )

    if df.empty:
        st.sidebar.error("salary_master.csv not found.  Expected at data/salary_master.csv")
    else:
        options = [
            f"{row['emp_id']} — {row['name']} ({row['designation']}, CTC {_inr(row['gross_ctc'])})"
            for _, row in df.iterrows()
        ]
        selected_idx = st.sidebar.selectbox(
            "Select employee", range(len(options)), format_func=lambda i: options[i]
        )
        row = df.iloc[selected_idx]
        employee_name = row["name"]
        params = params_from_csv_row(row)

        with st.sidebar.expander("Raw declaration data (from salary_master)"):
            display_cols = [
                "emp_id", "gross_ctc", "basic", "hra_component", "metro",
                "rent_paid_annual", "employee_pf_80c", "decl_80c_other",
                "decl_80d_self", "decl_80d_parents", "decl_80ccd_1b_nps",
                "decl_80e_edu_loan_int", "decl_24b_home_loan_int",
                "employer_nps_80ccd2",
            ]
            st.dataframe(row[display_cols].to_frame().T, use_container_width=True)

# ---------------------------------------------------------------------------
# Mode B: Manual entry
# ---------------------------------------------------------------------------
else:
    st.sidebar.subheader("Salary components (annual, Rs)")
    gross_ctc    = st.sidebar.number_input("Gross CTC", value=15_00_000, step=10_000, min_value=1_00_000)
    basic        = st.sidebar.number_input("Basic salary", value=int(gross_ctc * 0.45), step=5_000)
    hra_comp     = st.sidebar.number_input("HRA component", value=int(basic * 0.50), step=5_000)
    employer_pf  = st.sidebar.number_input("Employer PF (annual)", value=21_600, step=1_000)
    gratuity     = st.sidebar.number_input("Gratuity provision (annual)", value=int(basic * 0.0481), step=1_000)
    metro        = st.sidebar.checkbox("Metro city (50% basic for HRA)", value=True)
    rent_paid    = st.sidebar.number_input("Rent paid (annual, 0 if not claiming HRA)", value=0, step=5_000)

    st.sidebar.subheader("Old-regime deductions")
    emp_pf       = st.sidebar.number_input("Employee PF (80C pool)", value=21_600, step=1_000,
                                           help="Sec 123 — contributes to Rs 1.5L cap")
    other_80c    = st.sidebar.number_input("Other 80C (PPF, ELSS, LIC, etc.)", value=0, step=5_000,
                                           help="Sec 123 — combined cap Rs 1.5L with employee PF")
    d_80d_self   = st.sidebar.number_input("80D medical — self & family (cap Rs 25k)", value=0, step=1_000)
    d_80d_par    = st.sidebar.number_input("80D medical — parents (cap Rs 50k)", value=0, step=1_000)
    d_ccd1b      = st.sidebar.number_input("80CCD(1B) employee NPS (cap Rs 50k)", value=0, step=5_000)
    d_80e        = st.sidebar.number_input("80E education loan interest (no cap)", value=0, step=5_000)
    d_24b        = st.sidebar.number_input("Sec 24(b) home loan interest (cap Rs 2L)", value=0, step=10_000)
    emp_nps      = st.sidebar.number_input("Employer NPS / 80CCD(2) (Sec 124)", value=0, step=5_000,
                                           help="Cap: 10% basic (old regime) / 14% basic (new regime)")
    pt           = st.sidebar.number_input("Professional tax (old regime only)", value=2_400, step=100)

    employee_name = st.sidebar.text_input("Your name (for PDF)", value="Employee")

    params = TaxParams(
        gross_ctc       = float(gross_ctc),
        basic           = float(basic),
        hra_component   = float(hra_comp),
        employer_pf     = float(employer_pf),
        gratuity        = float(gratuity),
        rent_paid       = float(rent_paid),
        metro           = metro,
        employee_pf_80c = float(emp_pf),
        decl_80c_other  = float(other_80c),
        decl_80d_self   = float(d_80d_self),
        decl_80d_parents= float(d_80d_par),
        decl_80ccd_1b_nps= float(d_ccd1b),
        decl_80e_edu    = float(d_80e),
        decl_24b_home   = float(d_24b),
        employer_nps    = float(emp_nps),
        professional_tax= float(pt),
    )

# ---------------------------------------------------------------------------
# Compute and display results
# ---------------------------------------------------------------------------
st.title("Tax Regime Optimiser")
st.caption("Tax Year 2026-27  ·  Income Tax Act 2025  ·  Old vs New regime comparison")

if params is None:
    st.info("Select an input mode and fill in the details to see your comparison.")
    st.stop()

result: TaxResult = compute(params)

# --- Winner banner ---
winner_labels = {
    "new": f"NEW REGIME RECOMMENDED — saves {_inr(result.savings)} per year",
    "old": f"OLD REGIME RECOMMENDED — saves {_inr(result.savings)} per year",
    "equal": "BOTH REGIMES EQUAL — no saving either way",
}
st.markdown(
    f'<div class="winner-box">{winner_labels[result.winner]}</div>',
    unsafe_allow_html=True,
)
st.markdown("")

# --- Side-by-side regime cards ---
col_old, col_new = st.columns(2)

def _regime_card(col, r, is_winner: bool) -> None:
    label = "Old Regime" if r.regime == "old" else "New Regime"
    header = f"{'✅ ' if is_winner else ''}**{label}**"
    box_class = "winner-regime" if is_winner else ("old-box" if r.regime == "old" else "new-box")
    with col:
        st.subheader(label)
        st.markdown(
            f"""
            <div class="{box_class}">
            <strong>Total tax: {_inr(r.total_tax)}</strong>
            &nbsp;&nbsp;|&nbsp;&nbsp;Effective rate: {r.effective_rate_pct}%
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.expander("Deductions breakdown", expanded=is_winner):
            for label_d, amt in r.deductions.items():
                if amt > 0:
                    st.markdown(
                        f"<span style='color:#6B7570'>{label_d}</span>: **{_inr(amt)}**",
                        unsafe_allow_html=True,
                    )
            st.markdown(f"**Total deductions: {_inr(r.total_deductions)}**")

        with st.expander("Tax computation", expanded=is_winner):
            st.markdown(f"Taxable income: **{_inr(r.taxable_income)}**")
            st.markdown(f"Slab tax: **{_inr(r.base_tax)}**")
            if r.rebate > 0:
                st.markdown(f"Sec 156 rebate: **({_inr(r.rebate)})**")
            if r.marginal_relief_rebate > 0:
                st.markdown(f"Rebate marginal relief: **({_inr(r.marginal_relief_rebate)})**")
            if r.surcharge > 0:
                st.markdown(f"Surcharge: **{_inr(r.surcharge)}**")
            if r.marginal_relief_surcharge > 0:
                st.markdown(f"Surcharge marginal relief: **({_inr(r.marginal_relief_surcharge)})**")
            st.markdown(f"Cess (4%): **{_inr(r.cess)}**")
            st.markdown(f"**Total tax: {_inr(r.total_tax)}**")

_regime_card(col_old, result.old, result.winner == "old")
_regime_card(col_new, result.new, result.winner == "new")

# ---------------------------------------------------------------------------
# Breakeven chart
# ---------------------------------------------------------------------------
st.subheader("Breakeven analysis")
st.caption(
    "How total tax changes with gross CTC — shows the crossover point where regimes switch."
)

# Build CTC range around the current value
base_ctc = params.gross_ctc
ctc_min  = max(3_00_000, int(base_ctc * 0.5))
ctc_max  = int(base_ctc * 2.0)
step_size = max(50_000, int((ctc_max - ctc_min) / 50))
ctc_range = list(range(ctc_min, ctc_max + step_size, step_size))

old_taxes, new_taxes = [], []

for ctc_val in ctc_range:
    # Scale components proportionally
    scale = ctc_val / base_ctc
    p_scaled = TaxParams(
        gross_ctc       = float(ctc_val),
        basic           = round(params.basic * scale),
        hra_component   = round(params.hra_component * scale),
        employer_pf     = round(params.employer_pf * scale),
        gratuity        = round(params.gratuity * scale),
        rent_paid       = round(params.rent_paid * scale),
        metro           = params.metro,
        employee_pf_80c = round(params.employee_pf_80c * scale),
        decl_80c_other  = round(params.decl_80c_other * scale),
        decl_80d_self   = params.decl_80d_self,
        decl_80d_parents= params.decl_80d_parents,
        decl_80ccd_1b_nps= round(params.decl_80ccd_1b_nps * scale),
        decl_80e_edu    = round(params.decl_80e_edu * scale),
        decl_24b_home   = params.decl_24b_home,
        employer_nps    = round(params.employer_nps * scale),
        professional_tax= params.professional_tax,
    )
    r_scaled = compute(p_scaled)
    old_taxes.append(r_scaled.old.total_tax)
    new_taxes.append(r_scaled.new.total_tax)

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=[c / 1_00_000 for c in ctc_range], y=[t / 1_00_000 for t in old_taxes],
    name="Old Regime", mode="lines",
    line=dict(color="#F4C9B6", width=2),
))
fig.add_trace(go.Scatter(
    x=[c / 1_00_000 for c in ctc_range], y=[t / 1_00_000 for t in new_taxes],
    name="New Regime", mode="lines",
    line=dict(color="#4DBBAE", width=2),
))
# Mark current employee position
fig.add_vline(
    x=base_ctc / 1_00_000,
    line_dash="dot", line_color="#2A8676", line_width=1.5,
    annotation_text=f"Current CTC ({_inr(base_ctc)})",
    annotation_position="top right",
    annotation_font_size=10,
)

fig.update_layout(
    font=dict(family="Tahoma, Verdana, sans-serif", color="#2E3A36", size=12),
    plot_bgcolor="#F8F6EF",
    paper_bgcolor="#F8F6EF",
    xaxis=dict(title="Gross CTC (Rs Lakhs)", gridcolor="#D6DBD7", linecolor="#6B7570"),
    yaxis=dict(title="Total Tax (Rs Lakhs)", gridcolor="#D6DBD7", linecolor="#6B7570"),
    legend=dict(bgcolor="#F8F6EF", bordercolor="#D6DBD7"),
    margin=dict(l=60, r=30, t=40, b=50),
    height=380,
)
st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------
st.subheader("Export PDF advisory")

pdf_bytes = generate_pdf(
    result=result,
    employee_name=employee_name,
    gross_ctc=params.gross_ctc,
)

st.download_button(
    label="Download one-page PDF advisory",
    data=pdf_bytes,
    file_name=f"tax-advisory-{employee_name.replace(' ', '-').lower()}-2026-27.pdf",
    mime="application/pdf",
)

# ---------------------------------------------------------------------------
# Disclaimer
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div class="disclaimer-box">
    <strong>Disclaimer</strong> — This tool uses synthetic, non-real employee data for
    demonstration purposes only. It does not constitute tax advice. Tax liability depends
    on individual circumstances, age, other income sources, and final declarations. Verify
    your regime choice with a Chartered Accountant or tax professional before submitting
    Form 12BB. Built by <a href="https://anujsureshkumar.com">Anuj Sureshkumar</a>.
    </div>
    """,
    unsafe_allow_html=True,
)
