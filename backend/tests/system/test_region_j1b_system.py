"""
System End-to-End Tests for Task J1b (Multi-Province Java UI + Chat + Performance).
Runs against the staging backend (POSTGRES_DB=district_profiling_stage, REDIS_DB=1,
ACTIVE_PROVINCES=31,32,33,34,35,36) on a non-8000 port.
Marker: system.
"""

import json
import os
import time
import urllib.request
import uuid
import httpx
import pytest
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.system


def _select_district_ui(page, query: str):
    search_input = page.locator("#search-district-input")
    search_input.click()
    search_input.fill("")
    search_input.press_sequentially(query, delay=30)
    page.wait_for_selector(".search-autocomplete-item", timeout=5000)
    page.locator(".search-autocomplete-item").first.dispatch_event("click")
    page.wait_for_function(
        f"document.getElementById('info-district-name').textContent.toLowerCase().includes('{query.lower()}')",
        timeout=10000,
    )


@pytest.fixture(scope="function")
def j1b_browser_page(live_server_url):
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


def test_j1b_ui_switch_jabar_coblong_gated_and_jatim_perf(j1b_browser_page):
    """
    1. Switch to Jawa Barat (32) -> 627 features rendered on canvas, URL has ?prov=32.
    2. Measure province switch load time for 32 (627 polygons) and 35 (666 polygons).
    3. Select Coblong -> scorecard shows WorldPop label, memadai badge, province OSM note.
    4. Select gated Ciemas -> shows 'Data tidak memadai' and coverage reason.
    """
    page, errors, url, _ = j1b_browser_page
    geojson_counts = {}

    def on_response(resp):
        if "/data/boundaries/" in resp.url and resp.url.endswith(".geojson"):
            try:
                body = resp.json()
                geojson_counts[resp.url] = len(body.get("features", []))
            except Exception:
                pass

    page.on("response", on_response)
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector("#region-select option[value='32']:not([disabled])", state="attached", timeout=10000)

    # Verify legend entry for NULL composite
    assert "Data tidak memadai (cakupan OSM)" in page.inner_text(".info-legend-box")

    # 1. Switch to Jawa Barat (32) and measure load time
    t0_jabar = time.perf_counter()
    with page.expect_response(lambda r: "32_kecamatan.geojson" in r.url and r.status == 200):
        page.select_option("#region-select", "32")
        page.wait_for_function(
            "document.getElementById('nav-district-count').textContent.includes('627')",
            timeout=15000,
        )
    jabar_ms = (time.perf_counter() - t0_jabar) * 1000.0
    print(f"[PERF] Province switch to Jawa Barat (32, 627 polygons): {jabar_ms:.1f} ms")

    assert "prov=32" in page.url
    assert page.inner_text(".brand-badge") == "Jawa Barat"
    jabar_gj_count = next((v for k, v in geojson_counts.items() if "32_kecamatan.geojson" in k), 0)
    assert jabar_gj_count == 627, f"Expected 627 GeoJSON features for 32, got {jabar_gj_count}"
    canvas_box = page.locator("#gis-map-canvas .leaflet-overlay-pane canvas").first.bounding_box()
    assert canvas_box is not None and canvas_box["width"] > 0 and canvas_box["height"] > 0

    # 2. Select Coblong (32.73.230) -> scorecard with population source label & coverage badge
    _select_district_ui(page, "Coblong")
    page.wait_for_function("document.getElementById('score-dial-val').textContent !== '--'", timeout=10000)
    assert "WorldPop" in page.inner_text("#info-district-pop-note")
    assert "memadai" in page.inner_text("#district-coverage-badge").lower()
    assert "belum lengkap" in page.inner_text("#province-osm-note").lower()
    assert float(page.inner_text("#score-dial-val")) > 0.0

    # 3. Select gated kecamatan (Ciemas 32.02.010) -> Data tidak memadai
    _select_district_ui(page, "Ciemas")
    page.wait_for_function("document.getElementById('score-dial-val').textContent === 'N/A'", timeout=10000)
    assert "Data tidak memadai" in page.inner_text("#score-meta-title")
    assert "Data tidak memadai" in page.inner_text("#gated-coverage-box")
    assert "tidak memadai" in page.inner_text("#district-coverage-badge").lower()

    # 4. Switch to Jawa Timur (35, 666 polygons) and measure load time
    t0_jatim = time.perf_counter()
    with page.expect_response(lambda r: "35_kecamatan.geojson" in r.url and r.status == 200):
        page.select_option("#region-select", "35")
        page.wait_for_function(
            "document.getElementById('nav-district-count').textContent.includes('666')",
            timeout=15000,
        )
    jatim_ms = (time.perf_counter() - t0_jatim) * 1000.0
    print(f"[PERF] Province switch to Jawa Timur (35, 666 polygons): {jatim_ms:.1f} ms")
    assert "prov=35" in page.url
    jatim_gj_count = next((v for k, v in geojson_counts.items() if "35_kecamatan.geojson" in k), 0)
    assert jatim_gj_count == 666

    assert len(errors) == 0, f"Expected 0 console errors, got: {errors}"


def test_j1b_reload_with_prov_34_opens_diy(j1b_browser_page):
    """Reloading /?prov=34 opens DI Yogyakarta with 78 kecamatan and WorldPop source."""
    page, errors, url, _ = j1b_browser_page
    page.goto(f"{url}/?prov=34", wait_until="networkidle")
    page.wait_for_function(
        "document.getElementById('nav-district-count').textContent.includes('78')",
        timeout=15000,
    )
    assert page.inner_text(".brand-badge") == "DI Yogyakarta"
    assert page.locator("#region-select").input_value() == "34"
    assert "78 Kecamatan DI Yogyakarta" in page.inner_text("#info-district-area")
    assert "WorldPop" in page.inner_text("#info-district-pop-note")
    assert len(errors) == 0, f"Expected 0 console errors, got: {errors}"


def test_j1b_chat_gondokusuman_province_34(live_server_url):
    """Chat question 'Bagaimana skor Gondokusuman?' with province_code='34' answers with Gondokusuman (34.71.060)."""
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    try:
        req = urllib.request.Request(f"{ollama_url}/api/tags")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status != 200:
                pytest.skip("Ollama not reachable")
    except Exception:
        pytest.skip("Ollama not reachable for live chat test")

    uid = uuid.uuid4().hex[:8]
    email = f"j1b_chat_{uid}@drp.local"
    password = "SecurePassword123!"
    user_id = None

    try:
        with httpx.Client(base_url=live_server_url, timeout=90.0) as client:
            reg = client.post(
                "/api/v1/auth/register",
                json={"email": email, "password": password, "display_name": "J1b Chat Tester"},
            )
            assert reg.status_code in (200, 201)
            user_id = reg.json().get("id")
            login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
            assert login.status_code == 200
            token = login.json()["access_token"]

            res = client.post(
                "/api/v1/chat",
                json={
                    "messages": [{"role": "user", "content": "Bagaimana skor Gondokusuman?"}],
                    "province_code": "34",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res.status_code == 200
            data = res.json()
            assert "Gondokusuman" in data["reply"]
            assert data["guardrail"] in ("passed", "retried", "numeric_fallback")
            tools = [t["name"] for t in data.get("tool_calls_executed", [])]
            assert "get_district_scorecard" in tools
            fly_actions = [a for a in data.get("map_actions", []) if a["action_type"] == "fly_to"]
            assert any(a["payload"]["district_code"] == "34.71.060" for a in fly_actions)
    finally:
        if user_id:
            try:
                from backend.app.core.db import get_db_cursor, get_redis_client
                with get_db_cursor() as cur:
                    cur.execute("DELETE FROM chat_audit WHERE user_id = %s;", (user_id,))
                    cur.execute("DELETE FROM app_users WHERE id = %s;", (user_id,))
                r = get_redis_client()
                if r:
                    r.delete(f"rate:chat:user:{user_id}")
            except Exception:
                pass
