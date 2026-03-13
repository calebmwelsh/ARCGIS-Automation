"""
discover_county_urls.py
------------------------
Automated discovery of ArcGIS FeatureServer URLs for counties.

Usage:
  # Discover URLs for specific states (recommended)
  python execution/discover_county_urls.py --states IN GA
  
  # Discover URLs for all counties (starts a long background process)
  python execution/discover_county_urls.py --all

This script:
  1. Reads `data/geo_index.json` to get a list of counties.
  2. Queries the public ArcGIS Online REST catalog for each county:
     "County Name" "State Name" parcel type:"Feature Service"
  3. Sorts and filters the results to find the most likely official county parcel FeatureServer.
  4. Saves the results to `data/discovered_urls.json`.

Note: This approach discovers ~60-80% of counties. Some counties do not host data on ArcGIS Online.
"""

import argparse
import json
import logging
import os
import time

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
GEO_INDEX_PATH = os.path.join(DATA_DIR, "geo_index.json")
DISCOVERED_URLS_PATH = os.path.join(DATA_DIR, "discovered_urls.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def search_arcgis_online(county_name: str, state_name: str, state_abbrev: str) -> list[dict]:
    """
    Search ArcGIS online for parcel feature services matching the county and state.
    """
    base_url = "https://www.arcgis.com/sharing/rest/search"
    
    # Keyword search for the county, state, and 'parcel'
    # We restrict to Feature Service (for querying)
    query = f'"{county_name}" ("{state_name}" OR "{state_abbrev}") parcel type:"Feature Service"'
    
    params = {
        "q": query,
        "f": "json",
        "num": 5, # top 5 results
        "sortField": "numViews", # prioritize heavily used official layers
        "sortOrder": "desc"
    }
    
    try:
        r = requests.get(base_url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get("results", [])
    except Exception as e:
        logging.error(f"Error searching for {county_name}, {state_abbrev}: {e}")
        return []

def filter_best_result(results: list[dict], county_name: str, state_name: str, state_abbrev: str) -> dict | None:
    """
    Attempts to pick the best FeatureServer from the raw results.
    """
    if not results:
        return None
        
    c_name_lower = county_name.lower().replace(" county", "")
    s_name_lower = state_name.lower()
        
    for res in results:
        url = res.get("url", "")
        title = res.get("title", "").lower()
        snippet = (res.get("snippet") or "").lower()
        tags = [t.lower() for t in res.get("tags", [])]
        
        # We specifically want FeatureServers
        if "FeatureServer" not in url:
            continue
            
        # STRICT STATE FILTER: The result must reference the state to prevent cross-state contamination.
        state_match = (
            s_name_lower in title or 
            s_name_lower in snippet or 
            s_name_lower in tags or
            state_abbrev.lower() in tags
        )
        
        if not state_match:
            continue
            
        # Avoid "statewide" aggregations if we're looking for a specific county,
        # unless it explicitly matches the county.
        if c_name_lower in title or "parcel" in title or c_name_lower in snippet or c_name_lower in tags:
            # Pick the first one that matches our heuristics (already sorted by views)
            return {
                "title": res.get("title"),
                "url": url,
                "owner": res.get("owner"),
                "snippet": res.get("snippet")
            }
            
    return None

def main():
    parser = argparse.ArgumentParser(description="Discover ArcGIS parcel URLs for counties.")
    parser.add_argument("--states", nargs="+", help="State abbreviations to process (e.g. IN GA)")
    parser.add_argument("--all", action="store_true", help="Process all states in geo_index")
    args = parser.parse_args()

    if not args.states and not args.all:
        parser.error("Must specify either --states [list] or --all")

    if not os.path.exists(GEO_INDEX_PATH):
        logging.error(f"Geo index not found at {GEO_INDEX_PATH}. Please build it first.")
        return

    with open(GEO_INDEX_PATH, "r", encoding="utf-8") as f:
        geo_index = json.load(f)

    by_county = geo_index.get("by_county", {})
    
    # Filter counties based on requested states
    target_counties = []
    for fips, data in by_county.items():
        state_abbr = data.get("state_abbrev", "").upper()
        if args.all or (args.states and state_abbr in [s.upper() for s in args.states]):
            target_counties.append(data)

    logging.info(f"Loaded {len(target_counties)} counties for discovery.")

    # Load existing discoveries if any
    discovered = {}
    if os.path.exists(DISCOVERED_URLS_PATH):
        with open(DISCOVERED_URLS_PATH, "r", encoding="utf-8") as f:
            discovered = json.load(f)

    success_count = 0
    
    for i, county in enumerate(target_counties, 1):
        c_name = county["county"]
        s_name = county["state"]
        s_abbr = county["state_abbrev"]
        key = f"{c_name}_{s_abbr}".lower().replace(" ", "_")
        
        # Skip if already discovered (unless forcing rebuild, but we keep it simple here)
        if key in discovered and discovered[key].get("url"):
            continue

        logging.info(f"[{i}/{len(target_counties)}] Searching for {c_name}, {s_abbr}...")
        
        results = search_arcgis_online(c_name, s_name, s_abbr)
        best = filter_best_result(results, c_name, s_name, s_abbr)
        
        if best:
            logging.info(f"  -> Found: {best['title']} ({best['url']})")
            discovered[key] = {
                "county": c_name,
                "state_abbrev": s_abbr,
                "url": best["url"],
                "title": best["title"],
                "owner": best["owner"]
            }
            success_count += 1
        else:
            logging.info("  -> No suitable URL found.")
            discovered[key] = {
                "county": c_name,
                "state_abbrev": s_abbr,
                "url": None,
                "error": "Not found in ArcGIS Online catalog"
            }
            
        # Save incrementally
        with open(DISCOVERED_URLS_PATH, "w", encoding="utf-8") as f:
            json.dump(discovered, f, indent=2)
            
        # Be polite to the public API
        time.sleep(1.0)

    logging.info(f"\nDone. Successfully found URLs for {success_count} new counties.")
    logging.info(f"Results saved to {DISCOVERED_URLS_PATH}")

if __name__ == "__main__":
    main()
