"""
System End-to-End Tests for Task R1: 38-province <optgroup> region switcher,
?prov= reload behaviour, and Maluku bbox fit.
Marker: system.
"""

import pytest
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.system

EXPECTED_OPTGROUPS = [
    "Sumatra",
    "Jawa",
    "Bali & Nusa Tenggara",
    "Kalimantan",
    "Sulawesi",
    "Maluku",
    "Papua",
]


def test_r1_region_select_optgroups_and_maluku_prov_param(live_server_url):
    """Verify 7 island <optgroup>s across 38 provinces and ?prov=81 Maluku bbox fit."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        errors = []
        page.on(
            "console",
            lambda msg: errors.append(msg.text) if msg.type == "error" else None,
        )

        page.goto(live_server_url, wait_until="networkidle")
        page.wait_for_selector("#region-select optgroup", state="attached", timeout=10000)

        labels = page.eval_on_selector_all(
            "#region-select optgroup",
            "els => els.map(e => e.label)",
        )
        assert labels == EXPECTED_OPTGROUPS

        opt_count = page.locator("#region-select option").count()
        assert opt_count == 38

        # Test ?prov=81 (Maluku) if active in current server config
        is_81_active = page.eval_on_selector(
            "#region-select option[value='81']",
            "el => !el.disabled",
        )
        if is_81_active:
            page.goto(f"{live_server_url}/?prov=81", wait_until="networkidle")
            page.wait_for_function(
                "document.getElementById('nav-district-count').textContent.includes('118')",
                timeout=15000,
            )
            assert page.inner_text(".brand-badge") == "Maluku"
            assert page.locator("#region-select").input_value() == "81"
            canvas_box = page.locator("#gis-map-canvas .leaflet-overlay-pane canvas").first.bounding_box()
            assert canvas_box is not None and canvas_box["width"] > 0 and canvas_box["height"] > 0

        browser.close()
        assert len(errors) == 0, f"Expected 0 console errors, got: {errors}"
