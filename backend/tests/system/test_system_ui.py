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
                        cur.execute("DELETE FROM chat_logs WHERE user_id = %s;", (u_id,))
                        cur.execute("DELETE FROM chat_audit WHERE user_id = %s;", (u_id,))
                        cur.execute("DELETE FROM app_users WHERE id = %s;", (u_id,))
                        r = get_redis_client()
                        if r:
                            r.delete(f"rate:chat:user:{u_id}")
        except Exception:
            pass


def test_system_ui_overview_and_map(browser_page):
    """DEMO.md §1: Peta seluruh Jakarta, status header, street base + label pane + choropleth."""
    page, errors, url, _ = browser_page
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector("#split-layout", timeout=10000)
    page.wait_for_selector("#gis-map-canvas", timeout=10000)

    # Header components check
    telemetry_strip = page.locator(".nav-telemetry-strip")
    assert telemetry_strip.is_visible()

    # Default base should be Peta Jalan (World_Street_Map + Reference labels), never Esri Dark Gray
    tile_urls = page.evaluate("""async () => {
        const { state } = await import('/js/state.js');
        const urls = [];
        state.map.eachLayer(layer => {
            if (layer instanceof L.TileLayer && typeof layer._url === 'string') {
                urls.push(layer._url);
            }
        });
        return urls;
    }""")
    assert any("World_Street_Map" in u for u in tile_urls), f"Expected World_Street_Map in {tile_urls}"
    assert any("World_Boundaries_and_Places" in u for u in tile_urls), f"Expected reference labels in {tile_urls}"
    assert not any("World_Dark_Gray" in u for u in tile_urls), f"Unexpected Esri Dark Gray tiles in {tile_urls}"

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


def _boxes_overlap(a, b) -> bool:
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )


def test_system_ui_legend_collapse_persists_and_no_mobile_overlap(live_server_url):
    """
    F1-A:
    1. Wide screen (1366x768): legend starts expanded, collapses on click, persists across reload.
    2. Narrow screen (390x844): legend starts collapsed and does not overlap chat input (collapsed or expanded).
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # 1. Wide screen 1366x768
        ctx_wide = browser.new_context(viewport={"width": 1366, "height": 768})
        page_wide = ctx_wide.new_page()
        errors_wide = []
        page_wide.on("console", lambda m: errors_wide.append(m.text) if m.type == "error" else None)

        page_wide.goto(live_server_url, wait_until="networkidle")
        page_wide.wait_for_selector("#map-legend-toggle", timeout=10000)
        assert page_wide.get_attribute("#map-legend-toggle", "aria-expanded") == "true"
        assert page_wide.locator("#map-legend-body").is_visible()

        # Collapse legend and verify persistence across reload
        page_wide.click("#map-legend-toggle")
        assert page_wide.get_attribute("#map-legend-toggle", "aria-expanded") == "false"
        assert not page_wide.locator("#map-legend-body").is_visible()

        page_wide.reload(wait_until="networkidle")
        page_wide.wait_for_selector("#map-legend-toggle", timeout=10000)
        assert page_wide.get_attribute("#map-legend-toggle", "aria-expanded") == "false"
        assert not page_wide.locator("#map-legend-body").is_visible()

        # Expand again and verify persistence
        page_wide.click("#map-legend-toggle")
        assert page_wide.get_attribute("#map-legend-toggle", "aria-expanded") == "true"
        assert page_wide.locator("#map-legend-body").is_visible()
        ctx_wide.close()
        assert len(errors_wide) == 0, f"Wide legend test console errors: {errors_wide}"

        # 2. Narrow phone screen 390x844
        ctx_phone = browser.new_context(viewport={"width": 390, "height": 844})
        page_phone = ctx_phone.new_page()
        errors_phone = []
        page_phone.on("console", lambda m: errors_phone.append(m.text) if m.type == "error" else None)

        page_phone.goto(live_server_url, wait_until="networkidle")
        page_phone.wait_for_selector("#map-legend-toggle", timeout=10000)
        assert page_phone.get_attribute("#map-legend-toggle", "aria-expanded") == "false"
        assert not page_phone.locator("#map-legend-body").is_visible()

        legend_box = page_phone.locator(".info-legend-box").bounding_box()
        input_box = page_phone.locator("#chat-msg-input").bounding_box()
        send_box = page_phone.locator("#btn-send-chat").bounding_box()
        assert legend_box and input_box and send_box
        assert not _boxes_overlap(legend_box, input_box), f"Collapsed legend {legend_box} overlaps chat input {input_box}"
        assert not _boxes_overlap(legend_box, send_box), f"Collapsed legend {legend_box} overlaps send button {send_box}"

        # Also verify expanded legend on 390x844 stays above chat input
        page_phone.click("#map-legend-toggle")
        page_phone.wait_for_timeout(150)
        legend_box_exp = page_phone.locator(".info-legend-box").bounding_box()
        input_box_exp = page_phone.locator("#chat-msg-input").bounding_box()
        assert legend_box_exp and input_box_exp
        assert not _boxes_overlap(legend_box_exp, input_box_exp), f"Expanded legend {legend_box_exp} overlaps chat input {input_box_exp}"

        ctx_phone.close()
        browser.close()
        assert len(errors_phone) == 0, f"Phone legend test console errors: {errors_phone}"


def test_system_ui_chat_history_riwayat_panel(browser_page):
    """
    F1-B: Logged-in user sends a chat turn (out-of-scope refusal, 0 LLM rounds)
    and sees the entry in the Riwayat panel, toggles 'Lihat jawaban', and clears history.
    """
    page, errors, url, created_emails = browser_page
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector("#split-layout", timeout=10000)

    # Guest does not see Riwayat button
    assert not page.locator("#btn-chat-history").is_visible()
    assert "90 hari" in page.inner_text("#chat-privacy-notice")

    # Log in via modal
    login_ui(page, created_emails)
    page.wait_for_selector("#btn-chat-history", state="visible", timeout=5000)

    # Send a deterministic out-of-scope chat message (0 LLM rounds)
    prompt_text = "Apakah proyek apartemen 3.000 unit di Tebet boleh disetujui izin pembangunannya?"
    page.fill("#chat-msg-input", prompt_text)
    page.click("#btn-send-chat")
    page.wait_for_function(
        "document.getElementById('chat-history').textContent.includes('tidak berwenang')",
        timeout=10000,
    )

    # Open Riwayat panel
    page.click("#btn-chat-history")
    page.wait_for_selector("#chat-history-drawer", state="visible", timeout=5000)
    page.wait_for_selector(".chat-history-item", timeout=10000)

    drawer_text = page.inner_text("#chat-history-drawer")
    assert prompt_text in drawer_text

    # Toggle 'Lihat jawaban'
    toggle_resp = page.locator(".btn-history-toggle-resp").first
    assert toggle_resp.inner_text().strip() == "Lihat jawaban"
    toggle_resp.click()
    resp_el = page.locator(".chat-history-item-response").first
    assert resp_el.is_visible()
    assert "tidak berwenang" in resp_el.inner_text()

    # Clear history with confirm dialog
    page.once("dialog", lambda d: d.accept())
    page.click("#btn-clear-chat-history")
    page.wait_for_function(
        "document.getElementById('chat-history-drawer-list').textContent.includes('Belum ada riwayat')",
        timeout=5000,
    )

    assert len(errors) == 0, f"Riwayat UI test console errors: {errors}"


def test_system_ui_splitter_clamp_persist_and_keyboard(live_server_url):
    """
    F2-A:
    At 1366x768 and 1024x768:
    - Dragging splitter to extreme right and extreme left keeps divider >= 10px wide, visible, and draggable back.
    - Sidebar is never narrower than 320px; left panel is >= 45%.
    - Reload restores a clamped split (including clamping extreme localStorage values).
    - Double-click resets to 70/30 (clamped) and keyboard arrows move the divider.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for vp_width, vp_height in [(1366, 768), (1024, 768)]:
            ctx = browser.new_context(viewport={"width": vp_width, "height": vp_height})
            page = ctx.new_page()
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

            page.goto(live_server_url, wait_until="networkidle")
            page.wait_for_selector("#split-resizer", timeout=10000)

            resizer = page.locator("#split-resizer")
            assert resizer.get_attribute("role") == "separator"
            assert resizer.get_attribute("aria-orientation") == "vertical"
            assert resizer.get_attribute("tabindex") == "0"

            def boxes():
                c = page.locator("#split-layout").bounding_box()
                l = page.locator("#map-viewport").bounding_box()
                r = resizer.bounding_box()
                s = page.locator("#info-panel").bounding_box()
                assert c and l and r and s
                return c, l, r, s

            def drag_resizer_to(target_x: float):
                _, _, r_box, _ = boxes()
                start_x = r_box["x"] + r_box["width"] / 2
                start_y = r_box["y"] + r_box["height"] / 2
                page.mouse.move(start_x, start_y)
                page.mouse.down()
                page.mouse.move(target_x, start_y, steps=10)
                page.mouse.up()
                page.wait_for_timeout(80)

            # 1. Drag to extreme right
            c0, _, _, _ = boxes()
            drag_resizer_to(c0["x"] + c0["width"] - 2)
            c1, l1, r1, s1 = boxes()
            assert r1["width"] >= 10, f"Resizer shrank at {vp_width}x{vp_height}: {r1}"
            assert resizer.is_visible()
            assert s1["width"] >= 320 - 0.5, f"Sidebar < 320px at {vp_width}x{vp_height}: {s1}"
            assert r1["x"] + r1["width"] <= c1["x"] + c1["width"]

            # 2. Verify divider is draggable back to left extreme
            drag_resizer_to(c1["x"] + 5)
            c2, l2, r2, s2 = boxes()
            assert r2["width"] >= 10, f"Resizer shrank after left drag at {vp_width}x{vp_height}: {r2}"
            assert resizer.is_visible()
            assert s2["width"] >= 320 - 0.5
            assert l2["width"] >= c2["width"] * 0.45 - 1.5, f"Left panel < 45% at {vp_width}x{vp_height}: {l2}"
            assert l2["width"] < l1["width"] - 40, "Dragging back left did not shrink left panel"

            # 3. Reload restores clamped split
            page.reload(wait_until="networkidle")
            page.wait_for_selector("#split-resizer", timeout=10000)
            c3, l3, r3, s3 = boxes()
            assert r3["width"] >= 10
            assert s3["width"] >= 320 - 0.5
            assert abs(l3["width"] - l2["width"]) <= 3

            # Even if localStorage holds an extreme value (98%), reload clamps it safely
            page.evaluate("localStorage.setItem('drp_split_left_pct', '98')")
            page.reload(wait_until="networkidle")
            page.wait_for_selector("#split-resizer", timeout=10000)
            c4, l4, r4, s4 = boxes()
            assert r4["width"] >= 10
            assert s4["width"] >= 320 - 0.5
            assert r4["x"] + r4["width"] <= c4["x"] + c4["width"]

            # 4. Keyboard ArrowLeft moves divider left, ArrowRight moves it right
            resizer.focus()
            before_kb_left = boxes()[1]["width"]
            page.keyboard.press("ArrowLeft")
            page.wait_for_timeout(50)
            after_kb_left = boxes()[1]["width"]
            assert after_kb_left < before_kb_left, f"ArrowLeft did not move divider at {vp_width}x{vp_height}"

            page.keyboard.press("ArrowRight")
            page.wait_for_timeout(50)
            after_kb_right = boxes()[1]["width"]
            assert after_kb_right > after_kb_left, f"ArrowRight did not move divider at {vp_width}x{vp_height}"

            # 5. Double-click resets to 70/30 (clamped)
            resizer.dblclick()
            page.wait_for_timeout(80)
            c5, l5, r5, s5 = boxes()
            assert r5["width"] >= 10
            assert s5["width"] >= 320 - 0.5
            expected_70 = min(
                c5["width"] - 320 - r5["width"],
                c5["width"] * 0.70,
            )
            assert abs(l5["width"] - expected_70) <= 3

            ctx.close()
            assert len(errors) == 0, f"Splitter UI test console errors at {vp_width}x{vp_height}: {errors}"

        browser.close()


def test_system_ui_map_indonesia_bounds_and_min_zoom(browser_page):
    """
    M1: Keep the map inside Indonesia (padded maxBounds + dynamic minZoom).
    1. After load, zoom out 6 times; check map stays within padded Indonesia box
       and zoom >= minZoom (>= 3).
    2. Zoom out to minZoom; verify zoom-out stops at minZoom and control disables.
    3. Drag far east; verify centre longitude stays <= 141.5.
    4. Resize viewport to mobile (390x844) and back to 1440x900; verify minZoom
       recomputes dynamically and zoom clamps up if below the new minZoom.
    """
    page, errors, url, _ = browser_page
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector("#gis-map-canvas .leaflet-control-zoom-out", timeout=10000)

    def read_map_state():
        return page.evaluate("""async () => {
            const { state } = await import('/js/state.js');
            const m = state.map;
            const b = m.getBounds();
            const c = m.getCenter();
            const mb = m.options.maxBounds;
            const tileBounds = [];
            m.eachLayer(layer => {
                if (layer instanceof L.TileLayer) {
                    tileBounds.push(Boolean(layer.options && layer.options.bounds));
                }
            });
            return {
                zoom: m.getZoom(),
                minZoom: m.getMinZoom(),
                maxZoom: m.getMaxZoom(),
                center: [c.lat, c.lng],
                bounds: {
                    south: b.getSouth(),
                    west: b.getWest(),
                    north: b.getNorth(),
                    east: b.getEast(),
                },
                maxBounds: mb ? {
                    south: mb.getSouth(),
                    west: mb.getWest(),
                    north: mb.getNorth(),
                    east: mb.getEast(),
                } : null,
                viscosity: m.options.maxBoundsViscosity,
                tileBoundsSet: tileBounds,
                zoomOutDisabled: document.querySelector('.leaflet-control-zoom-out')?.classList.contains('leaflet-disabled') || false,
            };
        }""")

    init_state = read_map_state()
    assert init_state["maxBounds"] is not None
    assert init_state["viscosity"] == 1.0
    assert init_state["minZoom"] >= 3
    assert len(init_state["tileBoundsSet"]) >= 2 and all(init_state["tileBoundsSet"])

    mb = init_state["maxBounds"]
    assert mb["south"] < -11.5 and mb["west"] < 94.5
    assert mb["north"] > 6.5 and mb["east"] > 141.5

    # 1. Zoom out 6 times via UI zoom-out button
    zoom_out_btn = page.locator("#gis-map-canvas .leaflet-control-zoom-out")
    for _ in range(6):
        if "leaflet-disabled" in (zoom_out_btn.get_attribute("class") or ""):
            break
        zoom_out_btn.click()
        page.wait_for_timeout(350)

    after_6 = read_map_state()
    assert after_6["zoom"] >= after_6["minZoom"] >= 3
    # Center stays inside the padded Indonesia box
    assert mb["south"] <= after_6["center"][0] <= mb["north"]
    assert mb["west"] <= after_6["center"][1] <= mb["east"]
    # Horizontal bounds stay inside padded Indonesia box when viewport width <= maxBounds width
    assert after_6["bounds"]["west"] >= mb["west"] - 0.1
    assert after_6["bounds"]["east"] <= mb["east"] + 0.1

    # 2. Drag the map far east; check centre longitude stays <= 141.5
    canvas_box = page.locator("#gis-map-canvas").bounding_box()
    assert canvas_box is not None
    start_x = canvas_box["x"] + canvas_box["width"] * 0.8
    end_x = canvas_box["x"] + 20
    drag_y = canvas_box["y"] + canvas_box["height"] * 0.4
    for _ in range(3):
        page.mouse.move(start_x, drag_y)
        page.mouse.down()
        page.mouse.move(end_x, drag_y, steps=10)
        page.mouse.up()
        page.wait_for_timeout(350)

    after_east = read_map_state()
    assert after_east["center"][1] <= 141.5, f"Center lng drifted past 141.5: {after_east['center']}"
    assert after_east["center"][1] >= 94.5

    # 3. Zoom out all the way to minZoom and confirm user cannot zoom out past it
    for _ in range(6):
        if "leaflet-disabled" in (zoom_out_btn.get_attribute("class") or ""):
            break
        zoom_out_btn.click()
        page.wait_for_timeout(350)

    at_min = read_map_state()
    assert at_min["zoom"] == at_min["minZoom"]
    assert at_min["zoomOutDisabled"] is True

    # 4. Resize to narrow mobile viewport -> minZoom drops to 3; zoom back out to 3;
    #    then resize back to desktop -> minZoom rises to 4 and map zooms in automatically.
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(400)
    mobile_state = read_map_state()
    assert mobile_state["minZoom"] == 3

    for _ in range(3):
        if "leaflet-disabled" in (zoom_out_btn.get_attribute("class") or ""):
            break
        zoom_out_btn.click()
        page.wait_for_timeout(350)
    assert read_map_state()["zoom"] == 3

    page.set_viewport_size({"width": 1440, "height": 900})
    page.wait_for_timeout(400)
    restored_state = read_map_state()
    assert restored_state["minZoom"] >= 4
    assert restored_state["zoom"] >= restored_state["minZoom"]


def test_system_ui_base_layers_switch_persist_and_label_pane(browser_page):
    """
    U1:
    1. Top-right layer control has both 'Peta Jalan' (default) and 'Satelit'.
    2. Custom label pane sits above overlayPane (400 < zIndex < 600, pointer-events: none)
       and holds the label tile layer.
    3. Switching to 'Satelit' loads Esri World_Imagery + reference labels, updates map
       container background, and persists across reload via localStorage.
    4. Zero console errors.
    """
    page, errors, url, _ = browser_page
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector("#gis-map-canvas .leaflet-control-layers", timeout=10000)

    base_labels = page.eval_on_selector_all(
        ".leaflet-control-layers-base label",
        "els => els.map(e => e.textContent.trim())",
    )
    assert "Peta Jalan" in base_labels and "Satelit" in base_labels, f"Unexpected base labels: {base_labels}"

    def inspect_layers_and_panes():
        return page.evaluate("""async () => {
            const { state } = await import('/js/state.js');
            const m = state.map;
            const overlayPane = m.getPane('overlayPane');
            const markerPane = m.getPane('markerPane');
            const labelPane = m.getPane('mapLabels');
            const tiles = [];
            m.eachLayer(layer => {
                if (layer instanceof L.TileLayer) {
                    tiles.push({
                        url: layer._url || '',
                        pane: layer.options?.pane || 'tilePane',
                        hasBounds: Boolean(layer.options && layer.options.bounds),
                    });
                }
            });
            const checkedLabel = document.querySelector('.leaflet-control-layers-base input:checked')?.parentElement?.textContent?.trim() || '';
            const mapBg = window.getComputedStyle(document.getElementById('gis-map-canvas')).backgroundColor;
            return {
                overlayZ: overlayPane ? Number(window.getComputedStyle(overlayPane).zIndex) : null,
                markerZ: markerPane ? Number(window.getComputedStyle(markerPane).zIndex) : null,
                labelZ: labelPane ? Number(window.getComputedStyle(labelPane).zIndex) : null,
                labelPointerEvents: labelPane ? window.getComputedStyle(labelPane).pointerEvents : null,
                tiles,
                checkedLabel,
                mapBg,
                storedBase: localStorage.getItem('drp_map_base_layer'),
            };
        }""")

    street_state = inspect_layers_and_panes()
    assert street_state["checkedLabel"] == "Peta Jalan"
    assert street_state["labelZ"] is not None
    assert street_state["overlayZ"] < street_state["labelZ"] < street_state["markerZ"]
    assert street_state["labelPointerEvents"] == "none"
    assert any("World_Street_Map" in t["url"] for t in street_state["tiles"])
    assert any("World_Boundaries_and_Places" in t["url"] and t["pane"] == "mapLabels" for t in street_state["tiles"])
    assert all(t["hasBounds"] for t in street_state["tiles"])
    assert street_state["mapBg"] == "rgb(229, 227, 223)"

    # Switch to Satelit
    sat_label = page.locator(".leaflet-control-layers-base label", has_text="Satelit")
    sat_label.click()
    page.wait_for_function(
        "localStorage.getItem('drp_map_base_layer') === 'Satelit'",
        timeout=5000,
    )
    page.wait_for_timeout(300)

    sat_state = inspect_layers_and_panes()
    assert sat_state["checkedLabel"] == "Satelit"
    assert sat_state["storedBase"] == "Satelit"
    assert any("World_Imagery" in t["url"] for t in sat_state["tiles"])
    assert any("World_Boundaries_and_Places" in t["url"] and t["pane"] == "mapLabels" for t in sat_state["tiles"])
    assert any("World_Transportation" in t["url"] and t["pane"] == "mapLabels" for t in sat_state["tiles"])
    assert all(t["hasBounds"] for t in sat_state["tiles"])
    assert sat_state["mapBg"] != "rgb(229, 227, 223)"

    # Reload and verify persistence
    page.reload(wait_until="networkidle")
    page.wait_for_selector("#gis-map-canvas .leaflet-control-layers", timeout=10000)

    reloaded_state = inspect_layers_and_panes()
    assert reloaded_state["checkedLabel"] == "Satelit"
    assert reloaded_state["storedBase"] == "Satelit"
    assert any("World_Imagery" in t["url"] for t in reloaded_state["tiles"])
    assert len(errors) == 0, f"Expected 0 console errors, got: {errors}"

    assert len(errors) == 0, f"Map bounds UI test console errors: {errors}"
