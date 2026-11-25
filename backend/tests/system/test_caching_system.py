"""
System End-to-End Tests for Task U3 (Caching & Session Reuse):
1. API Cache-Control headers on public GETs vs non-public routes.
2. Playwright UI: switching province back does not refetch GeoJSON or district list,
   and re-clicking a kecamatan does not refetch its detail.
Marker: system.
"""

import httpx
import pytest
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.system


def test_system_api_cache_control_headers(live_server_url, requires_seed):
    """Public GET endpoints return Cache-Control: public, max-age=300; private/live routes do not."""
    with httpx.Client(base_url=live_server_url, timeout=10.0) as client:
        for path in (
            "/api/v1/regions",
            "/api/v1/meta/standards",
            "/api/v1/districts?province_code=31",
            "/api/v1/districts/31.71.09",
            "/api/v1/facilities?district_code=31.71.09",
            "/api/v1/spatial/blank-spots?district_code=31.71.09&facility_type=puskesmas_kelurahan",
        ):
            r = client.get(path)
            assert r.status_code == 200, f"Unexpected status {r.status_code} for {path}"
            assert r.headers.get("Cache-Control") == "public, max-age=300", f"Missing Cache-Control on {path}"

        for path in ("/health", "/api/v1/watchdog/telemetry", "/api/v1/auth/me"):
            r = client.get(path)
            assert "max-age=300" not in (r.headers.get("Cache-Control") or ""), (
                f"Public max-age leaked on {path}: {r.headers.get('Cache-Control')}"
            )


def test_system_ui_province_switch_back_does_not_refetch_geojson(live_server_url, requires_seed):
    """
    Switching province 31 -> 32 -> 31 reuses in-memory GeoJSON and districts cache
    with 0 GeoJSON/districts refetches on switch back, and 0 console errors.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1366, "height": 768})
        page = context.new_page()

        console_errors = []
        requested_urls = []
        page.on(
            "console",
            lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
        )
        page.on("request", lambda req: requested_urls.append(req.url))

        page.goto(live_server_url, wait_until="networkidle")
        page.wait_for_function(
            "document.getElementById('nav-district-count').textContent.includes('44')",
            timeout=15000,
        )

        # Ensure initial load had no duplicate parallel fetches of the same GeoJSON/districts URL
        geojson_reqs = [u for u in requested_urls if "/data/boundaries/" in u]
        districts_reqs = [u for u in requested_urls if "/api/v1/districts" in u and "31.71" not in u]
        assert len(geojson_reqs) == 1, f"Duplicate initial GeoJSON fetches: {geojson_reqs}"
        assert len(districts_reqs) == 1, f"Duplicate initial districts fetches: {districts_reqs}"

        # Click Tebet twice via search/UI -> detail fetched only once
        requested_urls.clear()
        search_input = page.locator("#search-district-input")
        search_input.click()
        search_input.fill("Tebet")
        page.wait_for_selector(".search-autocomplete-item", timeout=5000)
        page.locator(".search-autocomplete-item").first.dispatch_event("click")
        page.wait_for_function(
            "document.getElementById('info-district-name').textContent.includes('Tebet')",
            timeout=10000,
        )
        detail_reqs_1 = [u for u in requested_urls if "/api/v1/districts/31.71.09" in u]
        assert len(detail_reqs_1) == 1

        requested_urls.clear()
        search_input.click()
        search_input.fill("Cilandak")
        page.wait_for_selector(".search-autocomplete-item", timeout=5000)
        page.locator(".search-autocomplete-item").first.dispatch_event("click")
        page.wait_for_function(
            "document.getElementById('info-district-name').textContent.includes('Cilandak')",
            timeout=10000,
        )
        requested_urls.clear()
        search_input.click()
        search_input.fill("Tebet")
        page.wait_for_selector(".search-autocomplete-item", timeout=5000)
        page.locator(".search-autocomplete-item").first.dispatch_event("click")
        page.wait_for_function(
            "document.getElementById('info-district-name').textContent.includes('Tebet')",
            timeout=10000,
        )
        detail_reqs_2 = [u for u in requested_urls if "/api/v1/districts/31.71.09" in u]
        assert len(detail_reqs_2) == 0, f"Expected cached district detail, got refetches: {detail_reqs_2}"

        # If province 32 is active, test 31 -> 32 -> 31 switch back without GeoJSON refetch
        is_32_active = page.eval_on_selector(
            "#region-select option[value='32']",
            "el => Boolean(el && !el.disabled)",
        )
        if is_32_active:
            page.select_option("#region-select", "32")
            page.wait_for_function(
                "document.getElementById('nav-district-count').textContent.includes('627')",
                timeout=15000,
            )

            requested_urls.clear()
            page.select_option("#region-select", "31")
            page.wait_for_function(
                "document.getElementById('nav-district-count').textContent.includes('44')",
                timeout=10000,
            )
            switch_back_geojson = [u for u in requested_urls if "/data/boundaries/" in u]
            switch_back_districts = [u for u in requested_urls if "/api/v1/districts" in u]
            assert switch_back_geojson == [], f"Unexpected GeoJSON refetch on switch back: {switch_back_geojson}"
            assert switch_back_districts == [], f"Unexpected districts refetch on switch back: {switch_back_districts}"

        browser.close()
        assert len(console_errors) == 0, f"Expected 0 console errors, got: {console_errors}"
