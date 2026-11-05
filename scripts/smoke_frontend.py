#!/usr/bin/env python3
"""
Playwright End-to-End Frontend Smoke Test Script.
Captures verified screenshots:
- 01_overview.png: Initial interface & choropleth overview
- 02_tebet_scorecard.png: Tebet scorecard with 4 pillars, verbatim composite note & excluded types
- 03_blank_spot.png: Blank-spot spatial layer & cross-border coverage metadata
- 04_simulation.png: What-if sandbox (+10,000 jiwa) with impact level, disclaimer box & assumptions
- 05_chat.png: Cognitive spatial AI assistant with guardrail badge & validated citations
"""

import os
import sys
import time
import subprocess
import urllib.request
import urllib.error
from playwright.sync_api import sync_playwright

SCREENSHOTS_DIR = os.path.abspath("scripts/output/screenshots")
BACKEND_URL = "http://127.0.0.1:8000"

def is_backend_healthy() -> bool:
    try:
        req = urllib.request.urlopen(f"{BACKEND_URL}/health", timeout=2)
        return req.getcode() == 200
    except Exception:
        return False

def ensure_backend_running():
    if is_backend_healthy():
        print(">> Backend is already running on port 8000.")
        return None

    print(">> Starting FastAPI backend uvicorn server...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    for _ in range(30):
        if is_backend_healthy():
            print(">> Backend successfully started and healthy.")
            return proc
        time.sleep(0.5)

    raise RuntimeError("Backend server failed to start within 15 seconds.")

def main():
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    server_proc = ensure_backend_running()

    extracted_texts = {}
    try:
        print(">> Launching Playwright Chromium...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            # 1. Overview Page
            print("\n[Step 1] Loading frontend overview page...")
            page.goto(BACKEND_URL, wait_until="networkidle")
            page.wait_for_selector("#split-layout")
            time.sleep(2)  # Wait for GeoJSON rendering
            path_01 = os.path.join(SCREENSHOTS_DIR, "01_overview.png")
            page.screenshot(path=path_01)
            print(f" -> Saved: {path_01}")
            extracted_texts["01_overview"] = {
                "right_panel": page.inner_text("#info-panel"),
                "chat_panel": page.inner_text("#chatbot-dock")
            }

            # 2. Select Tebet & Inspect Scorecard
            print("\n[Step 2] Selecting Tebet (31.71.09) and verifying Scorecard panel...")
            page.evaluate("selectDistrict('31.71.09')")
            page.wait_for_function("document.getElementById('info-district-name').textContent.includes('Tebet')")
            page.wait_for_function("document.getElementById('score-dial-val').textContent !== '--'")
            time.sleep(1.5)
            path_02 = os.path.join(SCREENSHOTS_DIR, "02_tebet_scorecard.png")
            page.screenshot(path=path_02)
            print(f" -> Saved: {path_02}")
            extracted_texts["02_tebet_scorecard"] = {
                "right_panel": page.inner_text("#info-panel"),
                "chat_panel": page.inner_text("#chatbot-dock")
            }

            # 3. Open Blank Spots Layer
            print("\n[Step 3] Opening Blank Spot layer for puskesmas_kelurahan...")
            page.click('button[data-tab="blankspots"]')
            page.wait_for_function("document.getElementById('bs-area-total').textContent !== '--'")
            time.sleep(1.5)
            path_03 = os.path.join(SCREENSHOTS_DIR, "03_blank_spot.png")
            page.screenshot(path=path_03)
            print(f" -> Saved: {path_03}")
            extracted_texts["03_blank_spot"] = {
                "right_panel": page.inner_text("#info-panel"),
                "chat_panel": page.inner_text("#chatbot-dock")
            }

            # 4. What-If Population Shock Simulation (+10,000 jiwa)
            print("\n[Step 4] Running What-If Simulation (+10,000 jiwa)...")
            page.click('button[data-tab="simulation"]')
            time.sleep(0.5)
            page.fill("#sim-pop-count", "10000")
            page.click("#btn-run-simulation")
            page.wait_for_selector("#sim-result-box", state="visible", timeout=10000)
            page.wait_for_function("document.getElementById('res-pop-delta').textContent.includes('10,000')")
            time.sleep(1.0)
            path_04 = os.path.join(SCREENSHOTS_DIR, "04_simulation.png")
            page.screenshot(path=path_04)
            print(f" -> Saved: {path_04}")
            extracted_texts["04_simulation"] = {
                "right_panel": page.inner_text("#info-panel"),
                "chat_panel": page.inner_text("#chatbot-dock")
            }

            # 5. Asisten Tata Ruang AI Chat
            print("\n[Step 5] Sending Chat message to Asisten Tata Ruang...")
            # Ensure chat dock is expanded
            chat_dock = page.locator("#chatbot-dock")
            if "collapsed" in (chat_dock.get_attribute("class") or ""):
                page.click("#btn-toggle-chat")
                time.sleep(0.5)

            chat_input = page.locator("#chat-msg-input")
            chat_input.fill("Berapa skor kelayakan hidup Tebet?")
            page.click("#btn-send-chat")

            # Wait for assistant response and guardrail badge
            print(" -> Waiting for AI agent response (Ollama Qwen 2.5 14B)...")
            page.wait_for_selector(".guardrail-badge", timeout=45000)
            time.sleep(2.0)
            path_05 = os.path.join(SCREENSHOTS_DIR, "05_chat.png")
            page.screenshot(path=path_05)
            print(f" -> Saved: {path_05}")
            extracted_texts["05_chat"] = {
                "right_panel": page.inner_text("#info-panel"),
                "chat_panel": page.inner_text("#chatbot-dock")
            }

            # 6. Overview Choropleth Map with Legend
            print("\n[Step 6] Capturing Overview Choropleth Map with Legend...")
            page.evaluate("unselectDistrict()")
            time.sleep(1.5)
            path_06 = os.path.join(SCREENSHOTS_DIR, "06_overview_choropleth.png")
            page.screenshot(path=path_06)
            print(f" -> Saved: {path_06}")
            extracted_texts["06_overview_choropleth"] = {
                "right_panel": page.inner_text("#info-panel"),
                "chat_panel": page.inner_text("#chatbot-dock"),
                "legend": page.inner_text(".info-legend-box") if page.locator(".info-legend-box").count() > 0 else ""
            }

            import json
            scratch_path = os.path.abspath("scripts/output/smoke_extracted_texts.json")
            os.makedirs(os.path.dirname(scratch_path), exist_ok=True)
            with open(scratch_path, "w", encoding="utf-8") as f:
                json.dump(extracted_texts, f, indent=2, ensure_ascii=False)
            print(f">> Verbatim extracted texts saved to {scratch_path}")

            browser.close()
            print("\n>> ALL 6 SMOKE TEST SCREENSHOTS CAPTURED SUCCESSFULLY!")

    except Exception as e:
        print(f"\n[ERROR/BLOCKED] Smoke test failed: {e}", file=sys.stderr)
        raise e
    finally:
        if server_proc:
            print(">> Stopping temporary backend server...")
            server_proc.terminate()
            server_proc.wait()

if __name__ == "__main__":
    main()
