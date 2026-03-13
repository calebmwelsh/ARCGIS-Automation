"""
batch_onboard_counties.py
-------------------------
Reads `data/discovered_urls.json` and runs `onboard_county.py` for every
county that has a valid discovered URL.

Usage:
  python execution/batch_onboard_counties.py
"""

import json
import logging
import os
import subprocess
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DISCOVERED_URLS_PATH = os.path.join(DATA_DIR, "discovered_urls.json")
COUNTY_PROFILES_PATH = os.path.join(DATA_DIR, "county_profiles.json")
ONBOARD_SCRIPT = os.path.join(SCRIPT_DIR, "onboard_county.py")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def get_already_onboarded_keys():
    if not os.path.exists(COUNTY_PROFILES_PATH):
        return set()
    try:
        with open(COUNTY_PROFILES_PATH, "r", encoding="utf-8") as f:
            profiles = json.load(f)
            return set(profiles.keys())
    except Exception:
        return set()

def main():
    if not os.path.exists(DISCOVERED_URLS_PATH):
        logging.error(f"Cannot find {DISCOVERED_URLS_PATH}")
        return

    with open(DISCOVERED_URLS_PATH, "r", encoding="utf-8") as f:
        discovered = json.load(f)

    # Filter to only those with a valid URL
    valid_targets = {k: v for k, v in discovered.items() if v.get("url")}
    
    already_onboarded = get_already_onboarded_keys()
    
    pending_targets = []
    for k, v in valid_targets.items():
        if k not in already_onboarded:
            pending_targets.append(v)

    logging.info(f"Total discovered URLs: {len(valid_targets)}")
    logging.info(f"Already onboarded: {len(already_onboarded)}")
    logging.info(f"Pending to onboard: {len(pending_targets)}")

    if not pending_targets:
        logging.info("Nothing to do!")
        return

    logging.info("Starting batch onboarding process...")
    success_count = 0
    fail_count = 0

    for i, target in enumerate(pending_targets, 1):
        url = target["url"]
        county = target["county"]
        state = target["state_abbrev"]
        
        logging.info(f"[{i}/{len(pending_targets)}] Onboarding {county}, {state}...")
        
        # Build the command for onboard_county.py (NO --dry-run so it saves)
        cmd = [
            "python", ONBOARD_SCRIPT,
            "--url", url,
            "--county", county,
            "--state", state
        ]
        
        try:
            # We use an explicit timeout because we don't want the script hanging on a dead URL forever
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                logging.info(f"  -> Success: {county}, {state}")
                success_count += 1
            else:
                logging.error(f"  -> Failed: {county}, {state}")
                # Log the last few lines of the error for context
                err_lines = result.stderr.strip().split('\n')
                if err_lines:
                    logging.error(f"     Reason: {err_lines[-1]}")
                fail_count += 1
                
        except subprocess.TimeoutExpired:
            logging.error(f"  -> Failed (Timeout): {county}, {state}")
            fail_count += 1
        except Exception as e:
            logging.error(f"  -> Failed (Error): {e}")
            fail_count += 1
            
        # Give Vertex AI a short breather between calls
        time.sleep(2.0)

    logging.info(f"Batch complete. Success: {success_count}, Failed: {fail_count}")

if __name__ == "__main__":
    main()
