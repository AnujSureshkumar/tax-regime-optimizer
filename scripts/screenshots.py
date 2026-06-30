"""
screenshots.py — headless Playwright capture of the LIVE Tax Regime Optimiser.

Captures three clean, retina-sharp PNGs of the deployed Streamlit app and saves
them into D:\\Claude Projects\\ for the Post 6 / launch-pack visuals:

  1. optimizer-form-<date>.png        hero/form (title -> disclaimer -> mode
                                      toggle -> employee dropdown), About collapsed.
  2. optimizer-result-INF1000-<date>.png  demo default (INF1000 Farhan Mukherjee)
                                      old-vs-new comparison, result container.
  3. optimizer-myth893-<date>.png     Post 6 hero: "new wins by Rs 893" near-miss
                                      reproduced in manual mode, inputs + result.

Capture-only. Does NOT touch app logic. Asserts the exact regime_engine.py rupee
figures are on screen BEFORE each capture and fails loudly if they are not.

Run (from the repo root):
    .venv\\Scripts\\python.exe scripts\\screenshots.py

Stack: Python, Playwright, headless Chromium. viewport 1200x900, 2x device scale.
"""

from __future__ import annotations

import io
import sys
import time
from datetime import date
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# --- Configuration ----------------------------------------------------------
APP_URL = "https://tax-regime-optimizer-cifcwrfbvz3psf374q32fv.streamlit.app/"
OUT_DIR = Path(r"D:\Claude Projects")
# Date stamp for the output filenames. Defaults to today; override with a single
# CLI arg (YYYY-MM-DD) to pin the deliverable date, e.g. `screenshots.py 2026-06-30`.
TODAY = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
SCALE = 2  # device_scale_factor — retina-sharp text

# The Streamlit Community-Cloud app renders inside an iframe (.../~/+/) that
# scrolls internally — the outer page never grows past the viewport. So we use a
# TALL viewport: the app iframe fills it (height:100%), every section paints at
# once with no internal scroll, and a full-page screenshot can be cropped to any
# region (including the result block, which is well below the normal fold).
VIEWPORT = {"width": 1200, "height": 3200}
COLD_START_MS = 120_000  # the Community-Cloud app sleeps; wait this long for the h1

# Hide the Streamlit top toolbar for a clean frame (headless + not-logged-in
# means there is no "Manage app" pill anyway, but the header still renders).
# Injected INTO the app frame.
HIDE_TOOLBAR_CSS = """
    header[data-testid="stHeader"] { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }
    #MainMenu { display: none !important; }
"""
# Hide the Streamlit Cloud status badge iframe on the host page.
HIDE_HOST_CSS = 'iframe[title="Streamlit Cloud Status"]{display:none!important;}'

# --- Expected figures (exact regime_engine.py output — verified locally) ----
# Shot 3: manual, CTC 16L metro, rent 4.2L + 80C 1.5L + NPS 50k -> deductions ~6.0L
SHOT3 = {
    "ctc": "1600000",
    "rent": "420000",
    "other_80c": "150000",
    "nps_1b": "50000",
    "old": "Rs 1,05,221",
    "new": "Rs 1,04,328",
    "savings": "Rs 893",
}
# Shot 2: demo default INF1000 Farhan Mukherjee
SHOT2 = {
    "old": "Rs 1,71,688",
    "new": "Rs 1,14,248",
}


# --- Frame acquisition ------------------------------------------------------
def get_app_frame(page):
    """The Streamlit app renders inside an iframe whose URL contains '/~/+/'.
    Return that Frame object (poll briefly, it appears a moment after load)."""
    deadline = time.time() + 30
    while time.time() < deadline:
        for f in page.frames:
            if "~/+" in f.url:
                return f
        page.wait_for_timeout(250)
    raise RuntimeError("Streamlit app frame (/~/+/) never appeared")


def wake_and_wait(page):
    """Click the Community-Cloud wake button if the app is asleep, then wait for
    the h1 'Tax Regime Optimiser' inside the app frame (long cold-start timeout).
    Returns the app Frame."""
    # The wake button lives on the host page, not the app frame.
    try:
        wake = page.get_by_role("button", name="Yes, get this app back up!")
        if wake.is_visible(timeout=8_000):
            print("  app was asleep — clicking wake button…")
            wake.click()
    except PWTimeout:
        pass  # app was already awake; no wake button

    app = get_app_frame(page)
    title = app.get_by_role("heading", name="Tax Regime Optimiser")
    title.wait_for(state="visible", timeout=COLD_START_MS)
    print("  h1 'Tax Regime Optimiser' is visible (in app frame).")
    return app


def inject_clean_frame(app) -> None:
    app.add_style_tag(content=HIDE_TOOLBAR_CSS)


def collapse_about(app) -> None:
    """The 'About this prototype' expander renders open (expanded=True). Collapse
    it so the form/result sits higher in the frame."""
    summary = (
        app.locator('[data-testid="stExpander"] summary')
        .filter(has_text="About this prototype")
        .first
    )
    details = (
        app.locator('[data-testid="stExpander"]')
        .filter(has_text="About this prototype")
        .locator("details")
        .first
    )
    try:
        if details.get_attribute("open") is not None:
            summary.click()
            app.wait_for_timeout(400)
    except PWTimeout:
        pass


def num_input(app, label_substr: str):
    """A Streamlit number_input's <input>, located by its visible label text."""
    return app.locator(
        f'div[data-testid="stNumberInput"]:has(label:has-text("{label_substr}")) input'
    )


def set_number(app, label_substr: str, value: str) -> None:
    inp = num_input(app, label_substr)
    inp.wait_for(state="visible", timeout=15_000)
    inp.click()
    inp.fill(value)
    inp.press("Tab")  # commit / blur


def bbox(app, locator) -> dict:
    locator.scroll_into_view_if_needed()
    app.wait_for_timeout(150)
    b = locator.bounding_box()
    if b is None:
        raise RuntimeError("could not measure bounding box for a capture marker")
    return b


def crop_full_page(page, x0: float, y0: float, x1: float, y1: float, out_path: Path) -> None:
    """Take a full-page screenshot at 2x and crop to the CSS-pixel rectangle
    (x0,y0)-(x1,y1). Element bounding boxes from the app frame are page-relative,
    so a tall-viewport full-page capture crops correctly."""
    png = page.screenshot(full_page=True)
    img = Image.open(io.BytesIO(png))
    box = (int(x0 * SCALE), int(y0 * SCALE), int(x1 * SCALE), int(y1 * SCALE))
    box = (
        max(0, box[0]),
        max(0, box[1]),
        min(img.width, box[2]),
        min(img.height, box[3]),
    )
    img.crop(box).save(out_path)
    w, h = box[2] - box[0], box[3] - box[1]
    print(f"  saved {out_path.name}  ({w}x{h}px @ {SCALE}x)")


def assert_on_page(app, *needles: str) -> None:
    """Fail loudly unless every figure is present in the app frame's rendered
    DOM."""
    body = app.locator("body").inner_text()
    missing = [n for n in needles if n not in body]
    if missing:
        raise AssertionError(
            f"Expected figure(s) not found on page: {missing}.\n"
            f"Engine output may have changed — do NOT ship this capture."
        )
    print(f"  asserted on page: {', '.join(needles)}")


# --- The three shots --------------------------------------------------------
def shot_1_form(page, app) -> None:
    """Hero/form: title -> disclaimer -> mode toggle -> employee dropdown, About
    collapsed. Demo mode (default). Bottom boundary = the result winner banner."""
    print("Shot 1 — hero/form…")
    collapse_about(app)
    app.wait_for_timeout(400)

    title = app.get_by_role("heading", name="Tax Regime Optimiser")
    app.get_by_text("synthetic demo data").first.wait_for(timeout=15_000)
    winner = app.locator(".winner-box")
    winner.wait_for(state="visible", timeout=30_000)

    top = bbox(app, title)["y"] - 12
    bot = bbox(app, winner)["y"] - 10  # stop just above the result banner
    out = OUT_DIR / f"optimizer-form-{TODAY}.png"
    crop_full_page(page, 0, max(0, top), VIEWPORT["width"], bot, out)


def shot_2_demo(page, app) -> None:
    """Demo default INF1000 result container. Synthetic-data box -> result cards."""
    print("Shot 2 — demo INF1000 result…")
    collapse_about(app)
    # Ensure demo mode + INF1000 (first option, the default).
    app.get_by_role("button", name="Demo employee").click()
    app.wait_for_timeout(600)

    winner = app.locator(".winner-box")
    winner.wait_for(state="visible", timeout=30_000)
    assert_on_page(app, SHOT2["old"], SHOT2["new"], "Farhan Mukherjee")

    top_marker = app.get_by_text("50 non-real employees").first
    bottom_marker = app.get_by_role("heading", name="How much deduction do you need?")
    top = bbox(app, top_marker)["y"] - 10
    bot = bbox(app, bottom_marker)["y"] - 8
    out = OUT_DIR / f"optimizer-result-INF1000-{TODAY}.png"
    crop_full_page(page, 0, max(0, top), VIEWPORT["width"], bot, out)


def shot_3_myth893(page, app) -> None:
    """Manual mode 'new wins by Rs 893' near-miss. Disclaimer line -> result
    cards (so the inputs and the figures are both in frame)."""
    print("Shot 3 — manual 'new wins by Rs 893'…")
    collapse_about(app)
    app.get_by_role("button", name="Enter my own details").click()
    app.wait_for_timeout(800)

    # Metro stays ticked (default True). Fill CTC, rent, 80C, NPS.
    set_number(app, "Gross CTC", SHOT3["ctc"])
    set_number(app, "Rent paid (per year)", SHOT3["rent"])
    set_number(app, "Other 80C (PPF / ELSS / LIC)", SHOT3["other_80c"])
    set_number(app, "80CCD(1B) NPS", SHOT3["nps_1b"])

    app.get_by_role("button", name="Compute comparison").click()

    winner = app.locator(".winner-box")
    winner.wait_for(state="visible", timeout=30_000)
    # Recompute wait: assert the exact figures before capturing.
    assert_on_page(app, SHOT3["old"], SHOT3["new"], SHOT3["savings"])

    disclaimer = app.locator(".persistent-disclaimer")
    bottom_marker = app.get_by_role("heading", name="How much deduction do you need?")
    top = bbox(app, disclaimer)["y"] - 10
    bot = bbox(app, bottom_marker)["y"] - 8
    out = OUT_DIR / f"optimizer-myth893-{TODAY}.png"
    crop_full_page(page, 0, max(0, top), VIEWPORT["width"], bot, out)


# --- Main -------------------------------------------------------------------
def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport=VIEWPORT, device_scale_factor=SCALE
        )
        page = context.new_page()

        print(f"Opening {APP_URL}")
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=COLD_START_MS)
        page.add_style_tag(content=HIDE_HOST_CSS)  # hide the status-badge iframe
        app = wake_and_wait(page)
        inject_clean_frame(app)
        app.wait_for_timeout(1_500)  # let the first script run settle

        # Order: form (demo) -> demo result -> manual result. Re-inject the
        # clean-frame CSS before each shot (a rerun can drop the injected tag).
        inject_clean_frame(app)
        shot_1_form(page, app)
        inject_clean_frame(app)
        shot_2_demo(page, app)
        inject_clean_frame(app)
        shot_3_myth893(page, app)

        browser.close()
    print("\nDone. All three PNGs written to", OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
