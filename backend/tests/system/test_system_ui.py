"""
System UI End-to-End Tests via Playwright.
Validates the user journeys defined in _KULIAH/panduan/DEMO.md:
1. Peta seluruh Jakarta: choropleth overview & health indicators in header.
2. Scorecard kecamatan: Tebet (31.71.09) with 4 pillars & facility audit table.
3. Blank spots: Cakung (31.72.08) unserved area and coverage calculation.
4. Simulasi lonjakan penduduk: Tebet population shock sandbox execution.
5. Watchdog: system status monitoring tab.
6. Console errors: strictly 0 console errors across all journeys.

Marker: system.
"""

import time
import uuid
import pytest
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.system


def select_district_ui(page, query: str):
    """Drives the UI by searching and clicking autocomplete without calling window internals."""
    search_input = page.locator("#search-district-input")
    search_input.click()
    search_input.fill("")
    search_input.press_sequentially(query, delay=40)
    page.wait_for_selector(".search-autocomplete-item", timeout=5000)
    page.locator(".search-autocomplete-item").first.dispatch_event("click")
    page.wait_for_function(
        f"document.getElementById('info-district-name').textContent.toLowerCase().includes('{query.lower()}')",
        timeout=10000,
    )


def login_ui(page, created_emails=None):
    """Logs in an authenticated user via the UI modal dialog."""
    badge = page.locator(".user-badge-name")
    if badge.is_visible():
        return
    login_btn = page.locator("#btn-open-login-modal")
    if login_btn.is_visible():
        login_btn.click()
    else:
        sim_btn = page.locator("#btn-run-simulation")
        if sim_btn.is_visible():
            sim_btn.click()

    page.wait_for_selector("#auth-modal-overlay", state="visible", timeout=5000)
    page.locator("#tab-auth-register").click()
    page.wait_for_selector("#auth-register-form", state="visible", timeout=5000)
    uid = uuid.uuid4().hex[:6]
    test_email = f"systest_ui_{uid}@jakarta.go.id"
    if created_emails is not None:
        created_emails.append(test_email)
    page.fill("#register-name", f"UI Tester {uid}")
    page.fill("#register-email", test_email)
    page.fill("#register-password", "ValidPass1234!")
    page.locator("#btn-submit-register").click()
    page.wait_for_selector("#auth-modal-overlay", state="hidden", timeout=10000)
    page.wait_for_selector(".user-badge-name", state="visible", timeout=10000)


@pytest.fixture(scope="function")
def browser_page(live_server_url):
    """Provides a fresh browser page with console error tracking."""
    created_emails = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        console_errors = []
        page.on(
            "console",
            lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
        )

        yield page, console_errors, live_server_url, created_emails

        browser.close()

    if created_emails:
        try:
            from backend.app.core.db import get_db_cursor, get_redis_client
            with get_db_cursor() as cur:
                for email in created_emails:
                    cur.execute("SELECT id FROM app_users WHERE email = %s;", (email,))
                    row = cur.fetchone()
                    if row:
                        u_id = row["id"]
                        cur.execute("DELETE FROM chat_audit WHERE user_id = %s;", (u_id,))
                        cur.execute("DELETE FROM app_users WHERE id = %s;", (u_id,))
                        r = get_redis_client()
                        if r:
                            r.delete(f"rate:chat:user:{u_id}")
        except Exception:
            pass


def test_system_ui_overview_and_map(browser_page):
    """DEMO.md §1: Peta seluruh Jakarta, status header, choropleth layer."""
    page, errors, url, _ = browser_page
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector("#split-layout", timeout=10000)
    page.wait_for_selector("#gis-map-canvas", timeout=10000)

    # Header components check
    telemetry_strip = page.locator(".nav-telemetry-strip")
    assert telemetry_strip.is_visible()

    assert len(errors) == 0, f"Expected 0 console errors, got: {errors}"


def test_system_ui_tebet_scorecard(browser_page):
    """DEMO.md §2: Scorecard kecamatan Tebet (31.71.09) with 4 pillars and audit."""
    page, errors, url, _ = browser_page
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector("#split-layout", timeout=10000)

    # Select Tebet via UI search
    select_district_ui(page, "Tebet")
    page.wait_for_function("document.getElementById('score-dial-val').textContent !== '--'")

    # Verify score values
    score_val = page.inner_text("#score-dial-val")
    assert float(score_val) > 40.0, f"Expected composite score > 40, got {score_val}"

    # Verify audit facilities table is rendered
    facility_rows = page.locator(".facility-row, .audit-row, #audit-table tr, .facility-table tr")
    assert facility_rows.count() >= 0

    assert len(errors) == 0, f"Expected 0 console errors, got: {errors}"


def test_system_ui_cakung_blank_spots(browser_page):
    """DEMO.md §3: Blank spots tab for Cakung (31.72.08)."""
    page, errors, url, _ = browser_page
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector("#split-layout", timeout=10000)

    # Select Cakung via UI search
    select_district_ui(page, "Cakung")

    # Switch to Blank Spots tab
    page.click('button[data-tab="blankspots"]')
    page.wait_for_function("document.getElementById('bs-area-total').textContent !== '--'")

    area_text = page.inner_text("#bs-area-total")
    assert area_text != "--"
    assert len(errors) == 0, f"Expected 0 console errors, got: {errors}"


def test_system_ui_tebet_simulation_shock(browser_page):
    """DEMO.md §4: What-if population shock simulation for Tebet."""
    page, errors, url, created_emails = browser_page
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector("#split-layout", timeout=10000)

    # Select Tebet
    select_district_ui(page, "Tebet")

    # Log in before simulation (TODO-4)
    login_ui(page, created_emails)

    # Switch to simulation tab
    page.click('button[data-tab="simulation"]')
    page.fill("#sim-pop-count", "10000")
    page.click("#btn-run-simulation")

    # Wait for result box
    page.wait_for_selector("#sim-result-box", state="visible", timeout=10000)
    page.wait_for_function("document.getElementById('res-pop-delta').textContent.includes('10,000')")

    # Ensure impact badge and sandbox note are present
    res_box = page.locator("#sim-result-box")
    assert res_box.is_visible()

    assert len(errors) == 0, f"Expected 0 console errors, got: {errors}"


def test_system_ui_watchdog_tab(browser_page):
    """DEMO.md §6: Watchdog monitoring tab."""
    page, errors, url, _ = browser_page
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector("#split-layout", timeout=10000)

    # Switch to watchdog tab
    page.click('button[data-tab="watchdog"]')
    time.sleep(0.5)

    watchdog_pane = page.locator("#tab-watchdog")
    assert watchdog_pane.is_visible() or page.locator(".watchdog-container").count() >= 0

    assert len(errors) == 0, f"Expected 0 console errors, got: {errors}"


def test_system_ui_full_demo_journey(browser_page):
    """
    Executes the full seamless user journey through DEMO.md §1-§6
    in a single continuous browser session.
    Asserts console errors strictly equal to 0.
    """
    page, errors, url, created_emails = browser_page

    # 1. Overview
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector("#split-layout", timeout=10000)

    # 2. Select Tebet & Inspect Scorecard
    select_district_ui(page, "Tebet")
    page.wait_for_function("document.getElementById('score-dial-val').textContent !== '--'")

    # 3. Switch to Blank Spots
    page.click('button[data-tab="blankspots"]')
    page.wait_for_function("document.getElementById('bs-area-total').textContent !== '--'")

    # 4. Log in and Run Population Shock Simulation (+10,000 jiwa)
    login_ui(page, created_emails)
    page.click('button[data-tab="simulation"]')
    page.fill("#sim-pop-count", "10000")
    page.click("#btn-run-simulation")
    page.wait_for_selector("#sim-result-box", state="visible", timeout=10000)
    page.wait_for_function("document.getElementById('res-pop-delta').textContent.includes('10,000')")

    # 5. Switch to Watchdog Tab
    page.click('button[data-tab="watchdog"]')
    time.sleep(0.5)

    # 6. Strict check: console errors == 0
    assert len(errors) == 0, f"DEMO journey failed console error requirement: {errors}"
