import json
import os
import requests
import re
import sys
from urllib.parse import quote

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COUNTY_PROFILES_PATH = os.path.join(BASE_DIR, 'data', 'county_profiles.json')
ANOMALY_LIST_PATH = os.path.join(BASE_DIR, '.tmp', 'county_audit_results.json')

def search_arcgis_online(query):
    """Searches ArcGIS Online for a specific query, prioritizing parcel layers."""
    search_url = f"https://www.arcgis.com/sharing/rest/search"
    # Loosened filters: removed -boundary as it might be in the parcel layer name itself
    params = {
        'q': f'"{query}" (type:"Feature Service" OR type:"Map Service") -fire -precinct',
        'f': 'json',
        'num': 5
    }
    try:
        resp = requests.get(search_url, params=params, timeout=10)
        results = resp.json().get('results', [])
        print(f"    - Search for '{query}' returned {len(results)} results")
        return results
    except Exception as e:
        print(f"    - Error searching for {query}: {e}")
        return []

def analyze_layer(url):
    """Fetches layer metadata to identify common field names."""
    try:
        resp = requests.get(f"{url}?f=json", timeout=10)
        data = resp.json()
        fields = data.get('fields', [])
        field_names = [f['name'].lower() for f in fields]
        
        mapping = {}
        # Enhanced heuristic mapping
        addr_patterns = ['address', 'siteaddress', 'prop_add', 'addr', 'locaddr', 'situsaddr', 'prop_addr', 'full_addr']
        owner_patterns = ['owner', 'ownername', 'fullowner', 'primaryowner', 'owner_1', 'prop_owner', 'name']
        pin_patterns = ['parcelid', 'pin', 'parcel_id', 'stpin', 'parcelnumber', 'prop_id', 'apn', 'parcel_no', 'parcelno']
        year_built_patterns = ['yearbuilt', 'year_built', 'yrblt', 'year_blt', 'built_year', 'const_year', 'act_year_blt']
        
        for p in addr_patterns:
            match = next((f for f in fields if p in f['name'].lower()), None)
            if match:
                mapping['address'] = match['name']
                break
                
        for p in owner_patterns:
            match = next((f for f in fields if p in f['name'].lower()), None)
            if match:
                mapping['owner_name'] = match['name']
                break
                
        for p in pin_patterns:
            match = next((f for f in fields if p in f['name'].lower()), None)
            if match:
                mapping['parcel_id'] = match['name']
                break

        for p in year_built_patterns:
            match = next((f for f in fields if p in f['name'].lower()), None)
            if match:
                mapping['year_built'] = match['name']
                break

        return mapping if mapping else None
    except:
        return None

def repair_counties(single_slug=None):
    if not os.path.exists(ANOMALY_LIST_PATH):
        print("Anomaly list not found. Run audit first.")
        return

    if single_slug:
        anomalies = [single_slug]
    else:
        with open(ANOMALY_LIST_PATH, 'r') as f:
            anomalies = json.load(f).get('missing_all_fields', [])

    with open(COUNTY_PROFILES_PATH, 'r', encoding='utf-8') as f:
        profiles = json.load(f)

    repaired_count = 0
    for slug in anomalies:
        if slug not in profiles: continue
        
        county = profiles[slug]['county']
        state = profiles[slug]['state']
        print(f"Repairing: {county}, {state} ({slug})")
        
        # Try a more targeted search
        results = search_arcgis_online(f"{county} {state} Parcel")
        if not results:
             results = search_arcgis_online(f"{county} {state} GIS")
             
        for res in results:
            url = res.get('url')
            if not url: continue
            
            # Ensure it ends in /0 or /1 for the actual layer
            if 'FeatureServer' in url or 'MapServer' in url:
                if not any(url.endswith(str(i)) for i in range(10)):
                    url += "/0"
                
                mapping = analyze_layer(url)
                if mapping and 'parcel_id' in mapping:
                    print(f"  - Found authoritative layer: {url}")
                    profiles[slug]['layer_url'] = url
                    profiles[slug]['field_map'].update(mapping)
                    repaired_count += 1
                    break

    if repaired_count > 0:
        with open(COUNTY_PROFILES_PATH, 'w', encoding='utf-8') as f:
            json.dump(profiles, f, indent=2)
        print(f"\nSuccessfully repaired {repaired_count} counties.")
    else:
        print("\nNo repairs were successful.")

if __name__ == "__main__":
    slug = sys.argv[1] if len(sys.argv) > 1 else None
    repair_counties(slug)
