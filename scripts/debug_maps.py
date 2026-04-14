#!/usr/bin/env python3
"""Debug: see what Google Maps returns for a venue."""
import re
import time
from camoufox.sync_api import Camoufox

def accept_consent(page):
    try:
        selectors = [
            "button:has-text('Accept all')",
            "button:has-text('Alle akzeptieren')",
            "button:has-text('Tout accepter')",
            "button:has-text('Aceptar todo')",
            "button:has-text('Accept')",
            "button:has-text('I agree')",
            "form[action*='consent'] button",
        ]
        for sel in selectors:
            try:
                btn = page.locator(sel)
                if btn.count() > 0:
                    print(f"  Found consent button: {sel}")
                    btn.first.click(timeout=3000)
                    time.sleep(1.5)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False

with Camoufox(headless=True) as browser:
    page = browser.new_page()
    
    # Go to Google Maps
    print("Loading Google Maps...")
    page.goto("https://www.google.com/maps/@22.27,114.17,13z",
              wait_until="domcontentloaded", timeout=20000)
    time.sleep(4)
    
    print(f"URL: {page.url}")
    print(f"Title: {page.title()}")
    
    # Check for consent
    if "consent" in page.url:
        print("Consent page detected!")
        accepted = accept_consent(page)
        print(f"Consent accepted: {accepted}")
        time.sleep(2)
    
    # Try searching for a venue
    query = "Foxglove 2/F, 6 Duddell St, Central, Hong Kong Hong Kong"
    from urllib.parse import quote_plus
    url = f"https://www.google.com/maps/search/{quote_plus(query)}"
    print(f"\nSearching: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=12000)
    time.sleep(3)
    
    print(f"URL: {page.url}")
    text = page.inner_text("body")
    print(f"\n--- Page text (first 2000 chars) ---")
    print(text[:2000])
    print(f"\n--- End ---")
    
    # Check for rating pattern
    m = re.search(r"(\d[.,]\d)\s*\((\d[\d.,]*)\)", text)
    if m:
        print(f"\nRating found: {m.group(1)} ({m.group(2)} reviews)")
    else:
        print("\nNo rating pattern found")
        # Show all numbers in parentheses
        parens = re.findall(r"\(([^)]+)\)", text)
        print(f"Text in parentheses: {parens[:10]}")
