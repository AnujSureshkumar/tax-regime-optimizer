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

from breakeven import build_sweep
from pdf_report import generate_pdf, render_sweep_chart_png
from regime_engine import TaxParams, TaxResult, compute, params_from_csv_row


def _round_to(value: float, base: int = 100) -> int:
    """Round to the nearest `base`. Mirrors the synthetic-data generator's
    round_to (gen_salary_slips.py / common.py) so manually entered CTCs derive
    the same salary structure as the demo data."""
    return int(round(value / base) * base)


def _derive_components(ctc: float) -> dict:
    """Derive the salary structure from Gross CTC using the demo company's
    standard structure (same deterministic formulas as the generator's
    build_employee). Returns basic, hra_component, employer_pf, gratuity and
    employee_pf (the mirrored employer PF that feeds the 80C / Sec 123 pool)."""
    basic = _round_to(0.45 * ctc, 100)
    hra_component = _round_to(0.50 * basic, 100)
    employer_pf = min(_round_to(0.12 * basic, 12), 21_600)
    gratuity = _round_to(0.0481 * basic, 1)
    employee_pf = employer_pf  # mirror the employer cap; feeds the 80C pool
    return {
        "basic": basic,
        "hra_component": hra_component,
        "employer_pf": employer_pf,
        "gratuity": gratuity,
        "employee_pf": employee_pf,
    }

# ---------------------------------------------------------------------------
# Page config and brand CSS injection
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Tax Regime Optimiser — Tax Year 2026-27",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
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
    /* Tabbed form — active tab text + underline on the ramp (Deep Sea Green) */
    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] { color: #2A8676; }
    .stTabs [data-baseweb="tab-highlight"] { background-color: #2A8676; }
    /* Primary "Compute comparison" submit button — Deep Sea Green per design */
    .stFormSubmitButton>button {
        background-color: #2A8676; color: white; border: none; font-weight: bold;
    }
    .stFormSubmitButton>button:hover { background-color: #4DBBAE; color: white; }
    /* "About this prototype" expander header — bold and slightly larger on the
       ramp (Deep Sea Green). Streamlit-internal selector; verify in the running
       app and adjust if the DOM differs. */
    [data-testid="stExpander"] summary p {
        font-weight: 700; font-size: 1.05rem; color: #2A8676;
    }
    /* Persistent disclaimer line — hairline top+bottom border on Wash. */
    .persistent-disclaimer {
        border-top: 1px solid #B5E2D9; border-bottom: 1px solid #B5E2D9;
        background: #E1EFEC; padding: 6px 10px; margin: 6px 0 10px 0;
        font-size: 0.78rem; color: #2A8676;
    }
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


# A quiet sidebar note (the inputs now live on the main page).
st.sidebar.caption(
    "Tax Regime Optimiser · Tax Year 2026-27 · synthetic demo data · "
    "built by Anuj Sureshkumar."
)

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
st.title("Tax Regime Optimiser")
st.caption("Tax Year 2026-27  ·  Income Tax Act 2025  ·  Old vs New regime comparison")

# Persistent disclaimer line — always visible, directly under the caption.
st.markdown(
    '<div class="persistent-disclaimer">Not tax advice  ·  synthetic demo data  ·  '
    'verify with a CA before submitting Form 124</div>',
    unsafe_allow_html=True,
)

# About this prototype — open by default, collapsible.
with st.expander("About this prototype", expanded=True):
    st.markdown(
        "A working prototype, built by a Finance Controller to show what a strong "
        "internal finance tool can look like."
    )
    st.markdown(
        "The tax engine is real. For Tax Year 2026-27 under the Income Tax Act, 2025, "
        "it computes the slabs, the surcharge with marginal relief, and the Section 156 "
        "rebate (formerly Section 87A) correctly."
    )
    st.markdown(
        "The salary structure is synthetic. It models the pay structure of a fictional "
        "IT company. A real CTC usually has components this demo does not cover, such as "
        "reimbursable allowances and meal allowance. So entering your gross "
        "CTC will not reproduce your actual break-up, and the tax will not match either."
    )
    st.markdown(
        "This is not tax advice. Verify your regime choice with a Chartered Accountant "
        "before submitting Form 124, which replaces Form 12BB from 1 April 2026."
    )

df = load_salary_master()

params: TaxParams | None = None
employee_name = "Employee"

# ---------------------------------------------------------------------------
# Input-mode toggle (top of the main page, above the form)
# ---------------------------------------------------------------------------
MODE_DEMO = "Demo employee"
MODE_MANUAL = "Enter my own details"

st.markdown("**Input mode**")
if hasattr(st, "segmented_control"):
    mode = st.segmented_control(
        "Input mode",
        [MODE_DEMO, MODE_MANUAL],
        default=MODE_DEMO,
        label_visibility="collapsed",
        key="input_mode",
    )
else:  # fallback for older Streamlit
    mode = st.radio(
        "Input mode", [MODE_DEMO, MODE_MANUAL],
        horizontal=True, label_visibility="collapsed",
        key="input_mode",
    )
# segmented_control returns None if the user clicks the active chip to clear it
if mode is None:
    mode = MODE_DEMO
st.caption("Demo loads a sample employee. Enter your own to compute on your figures.")

# ---------------------------------------------------------------------------
# Mode A: Demo employee picker (main page)
# ---------------------------------------------------------------------------
if mode == MODE_DEMO:
    st.markdown(
        """
        <div style="background:#E1EFEC;border-radius:4px;padding:8px 10px;
        font-size:0.8rem;color:#6B7570;margin:6px 0;">
        <strong>Synthetic demo data</strong> — 50 non-real employees of a
        fictional ITeS company. Names, PANs and figures are invented.
        </div>
        """,
        unsafe_allow_html=True,
    )

    if df.empty:
        st.error("salary_master.csv not found.  Expected at data/salary_master.csv")
    else:
        options = [
            f"{row['emp_id']} — {row['name']} ({row['designation']}, CTC {_inr(row['gross_ctc'])})"
            for _, row in df.iterrows()
        ]
        pick_col, _ = st.columns([2, 1])
        with pick_col:
            selected_idx = st.selectbox(
                "Select employee", range(len(options)), format_func=lambda i: options[i]
            )
        row = df.iloc[selected_idx]
        employee_name = row["name"]
        params = params_from_csv_row(row)

        with st.expander("Raw declaration data (from salary_master)"):
            display_cols = [
                "emp_id", "gross_ctc", "basic", "hra_component", "metro",
                "rent_paid_annual", "employee_pf_80c", "decl_80c_other",
                "decl_80d_self", "decl_80d_parents", "decl_80ccd_1b_nps",
                "decl_80e_edu_loan_int", "decl_24b_home_loan_int",
                "employer_nps_80ccd2",
            ]
            st.dataframe(row[display_cols].to_frame().T, use_container_width=True)

# ---------------------------------------------------------------------------
# Mode B: Manual entry — single scrolling form on the main page
# ---------------------------------------------------------------------------
# One st.form, three labelled sections stacked vertically, submit at the very
# bottom so the user scrolls past every section. The salary structure is
# DERIVED from Gross CTC using the demo company's standard structure (so an
# impossible basic/HRA cannot be entered); only metro and rent stay user inputs.
else:
    with st.form("manual_entry"):
        # --- Section 1: Salary structure ---
        st.subheader("Salary structure")
        left, right = st.columns(2)
        with left:
            gross_ctc = st.number_input(
                "Gross CTC", value=15_00_000, step=10_000, min_value=1_00_000,
                help="Total cost to company for the year, before any deductions.")
            metro = st.checkbox(
                "Metro city?", value=True,
                help="Tick if you live in a metro. 50% of basic is used for the "
                     "HRA exemption, otherwise 40%.")
        with right:
            rent_paid = st.number_input(
                "Rent paid (annual)", value=0, step=5_000,
                help="Total rent paid for the year. Enter 0 if you are not claiming HRA.")

        # Derive the salary structure from CTC (same formulas as the generator).
        comp = _derive_components(gross_ctc)
        basic        = comp["basic"]
        hra_comp     = comp["hra_component"]
        employer_pf  = comp["employer_pf"]
        gratuity     = comp["gratuity"]
        emp_pf       = comp["employee_pf"]
        gross_taxable = gross_ctc - employer_pf - gratuity

        st.caption(
            "Components are derived from CTC using the demo company's standard "
            "salary structure."
        )
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Basic", _inr(basic))
        m2.metric("HRA component", _inr(hra_comp))
        m3.metric("Employer PF", _inr(employer_pf))
        m4.metric("Gratuity", _inr(gratuity))
        m5.metric("Gross taxable", _inr(gross_taxable))

        # --- Section 2: Old-regime deductions ---
        st.subheader("Old-regime deductions")
        st.caption(
            "Optional. Leave blank if you are not claiming deductions, for example "
            "if you expect the new regime."
        )
        left, right = st.columns(2)
        with left:
            other_80c = st.number_input(
                "Other 80C (PPF / ELSS / LIC)", value=0, step=5_000,
                help="Other 80C investments such as PPF, ELSS or LIC (Section 123).")
            d_ccd1b = st.number_input(
                "80CCD(1B) NPS", value=0, step=5_000,
                help="Additional NPS contribution. Capped at 50,000.")
            emp_nps = st.number_input(
                "Employer NPS / 80CCD(2)", value=0, step=5_000,
                help="Employer's NPS contribution (Section 124). Allowed under both regimes.")
            pt = st.number_input(
                "Professional tax", value=2_400, step=100,
                help="Professional tax deducted by your employer during the year.")
        with right:
            d_80d_self = st.number_input(
                "80D self & family", value=0, step=1_000,
                help="Health insurance premium for self and family. Capped at 25,000.")
            d_80d_par = st.number_input(
                "80D parents", value=0, step=1_000,
                help="Health insurance premium for parents. Capped at 50,000.")
            d_24b = st.number_input(
                "Sec 24(b) home-loan interest", value=0, step=10_000,
                help="Interest on a self-occupied home loan. Capped at 2,00,000.")
            d_80e = st.number_input(
                "80E education-loan interest", value=0, step=5_000,
                help="Interest paid on an education loan. No upper limit.")

        # --- Section 3: Your details ---
        st.subheader("Your details")
        name_input = st.text_input(
            "Name", value="", placeholder="Your name",
            help="Used to label the downloadable PDF report.")
        st.info(
            "These details are used only to compute and label your comparison. "
            "Old-regime deductions apply only when you choose the old regime; "
            "the new regime ignores them. Nothing is saved after you close the app."
        )

        # Single submit button at the very bottom.
        submitted = st.form_submit_button(
            "Compute comparison", type="primary", use_container_width=True
        )

    if submitted:
        st.session_state["manual_submitted"] = True

    # Render results once the form has been submitted at least once. The form
    # widgets keep their committed values across reruns (e.g. a PDF download),
    # so we can rebuild params from them each run.
    if st.session_state.get("manual_submitted"):
        employee_name = name_input.strip() or "Employee"
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
if params is None:
    if mode == MODE_MANUAL:
        st.info("Fill in the sections above and press **Compute comparison** to see your result.")
    else:
        st.info("Select an input mode and fill in the details to see your comparison.")
    st.stop()

result: TaxResult = compute(params)

# Informational check (manual mode): declared old-regime deductions cannot
# exceed taxable salary. The engine floors taxable income at zero, so this is
# a heads-up, not a hard block.
if mode == MODE_MANUAL and result.old.total_deductions > result.old.gross_income:
    st.warning(
        f"Your declared deductions ({_inr(result.old.total_deductions)}) exceed "
        f"your taxable salary ({_inr(result.old.gross_income)}). Taxable income "
        f"is floored at zero."
    )

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
# Deduction-sweep chart
# ---------------------------------------------------------------------------
st.subheader("How much deduction do you need?")
st.caption(
    "This holds your salary structure fixed and varies the deductions you "
    "claim. The new regime ignores most deductions, so its line is flat. The "
    "old regime falls as you claim more. Where they cross is the deduction "
    "level at which the old regime becomes cheaper for you."
)

# Sweep the claimed old-regime deductions (salary structure held fixed).
sweep = build_sweep(params)
ded_range = sweep.ded_levels

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=[d / 1_00_000 for d in ded_range], y=[t / 1_00_000 for t in sweep.old_taxes],
    name="Old Regime", mode="lines",
    line=dict(color="#F4C9B6", width=2),
))
fig.add_trace(go.Scatter(
    x=[d / 1_00_000 for d in ded_range], y=[t / 1_00_000 for t in sweep.new_taxes],
    name="New Regime", mode="lines",
    line=dict(color="#4DBBAE", width=2),
))
# Mark the person's current claimed deductions.
fig.add_vline(
    x=sweep.current_ded / 1_00_000,
    line_dash="dot", line_color="#2A8676", line_width=1.5,
    annotation_text=f"Current deductions ({_inr(sweep.current_ded)})",
    annotation_position="top right",
    annotation_font_size=10,
)
# Annotate the crossover, if the old regime overtakes the new within range.
if sweep.breakeven_ded is not None:
    fig.add_trace(go.Scatter(
        x=[sweep.breakeven_ded / 1_00_000], y=[sweep.breakeven_tax / 1_00_000],
        name="Breakeven", mode="markers",
        marker=dict(color="#2A8676", size=10, symbol="circle-open", line=dict(width=2)),
        hovertemplate=f"Breakeven ~{_inr(sweep.breakeven_ded)}<extra></extra>",
        showlegend=False,
    ))
    fig.add_annotation(
        x=sweep.breakeven_ded / 1_00_000, y=sweep.breakeven_tax / 1_00_000,
        text=f"Breakeven ~{_inr(sweep.breakeven_ded)}",
        showarrow=True, arrowhead=2, arrowcolor="#2A8676",
        ax=0, ay=-34, font=dict(size=10, color="#2A8676"),
    )

fig.update_layout(
    font=dict(family="Tahoma, Verdana, sans-serif", color="#2E3A36", size=12),
    plot_bgcolor="#F8F6EF",
    paper_bgcolor="#F8F6EF",
    xaxis=dict(title="Deductions claimed (Rs Lakhs)", gridcolor="#D6DBD7", linecolor="#6B7570"),
    yaxis=dict(title="Total Tax (Rs Lakhs)", gridcolor="#D6DBD7", linecolor="#6B7570"),
    legend=dict(bgcolor="#F8F6EF", bordercolor="#D6DBD7"),
    margin=dict(l=60, r=30, t=40, b=50),
    height=380,
)
st.plotly_chart(fig, use_container_width=True)

if sweep.breakeven_ded is not None:
    st.caption(
        f"At your salary structure, the old regime becomes cheaper once you "
        f"claim about **{_inr(sweep.breakeven_ded)}** in deductions."
    )
else:
    st.caption(
        "Across this deduction range the new regime stays cheaper throughout — "
        "the lines do not cross."
    )

# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------
st.subheader("Export PDF advisory")

# Render a static matplotlib copy of the deduction-sweep chart for the PDF.
chart_png = render_sweep_chart_png(sweep)

pdf_bytes = generate_pdf(
    result=result,
    employee_name=employee_name,
    gross_ctc=params.gross_ctc,
    chart_png=chart_png,
)

st.download_button(
    label="Download one-page PDF advisory",
    data=pdf_bytes,
    file_name=f"tax-advisory-{employee_name.replace(' ', '-').lower()}-2026-27.pdf",
    mime="application/pdf",
)
