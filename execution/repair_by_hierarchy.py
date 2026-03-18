import json
import os
import requests
import re
from typing import Dict, List, Optional

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COUNTY_PROFILES_PATH = os.path.join(BASE_DIR, 'data', 'county_profiles.json')
ANOMALY_LIST_PATH = os.path.join(BASE_DIR, '.tmp', 'county_audit_results.json')

def get_json(url: str) -> Optional[Dict]:
    try:
        resp = requests.get(f"{url}?f=json", timeout=10, verify=False)
        return resp.json()
    except:
        return None

def heuristic_map(fields: List[Dict]) -> Dict:
    mapping = {}
    addr_patterns = ['address', 'siteaddress', 'prop_add', 'addr', 'locaddr', 'situsaddr', 'prop_addr', 'full_addr']
    owner_patterns = ['owner', 'ownername', 'fullowner', 'primaryowner', 'owner_1', 'prop_owner', 'name']
    pin_patterns = ['parcelid', 'pin', 'parcel_id', 'stpin', 'parcelnumber', 'prop_id', 'apn', 'parcel_no', 'parcelno']
    year_built_patterns = ['yearbuilt', 'year_built', 'yrblt', 'year_blt', 'built_year', 'const_year', 'act_year_blt']
    
    for p in addr_patterns:
        match = next((f for f in fields if p in f['name'].lower()), None)
        if match: mapping['address'] = match['name']; break
    for p in owner_patterns:
        match = next((f for f in fields if p in f['name'].lower()), None)
        if match: mapping['owner_name'] = match['name']; break
    for p in pin_patterns:
        match = next((f for f in fields if p in f['name'].lower()), None)
        if match: mapping['parcel_id'] = match['name']; break
    for p in year_built_patterns:
        match = next((f for f in fields if p in f['name'].lower()), None)
        if match: mapping['year_built'] = match['name']; break
    return mapping

def repair_all():
    if not os.path.exists(ANOMALY_LIST_PATH):
        print("Anomaly list not found. Run audit first.")
        return
        
    with open(ANOMALY_LIST_PATH, 'r') as f:
        missing = json.load(f).get('missing_all_fields', [])
        
    with open(COUNTY_PROFILES_PATH, 'r', encoding='utf-8') as f:
        profiles = json.load(f)

    repaired = 0
    for slug in missing:
        if slug not in profiles: continue
        url = profiles[slug]['layer_url']
        if not url: continue
        
        # Ascend to root
        root_url = re.sub(r'/\d+$', '', url)
        data = get_json(root_url)
        if not data or 'layers' not in data: continue
        
        # Look for Parcel layer
        candidate = None
        for layer in data['layers']:
            name = layer['name'].lower()
            if any(k in name for k in ['parcel', 'property', 'tax', 'real estate', 'ownership', 'cadastral']):
                if not any(noise in name for noise in ['anno', 'label', 'point', 'line', 'dimension', 'lot']):
                    candidate = layer
                    break
        
        # Final fallback if no parcel keyword, try id 0 or looking for any polygon with name "Parcels"
        if not candidate:
             for layer in data['layers']:
                if 'parcel' in layer['name'].lower(): 
                    candidate = layer
                    break

        if candidate:
            new_url = f"{root_url}/{candidate['id']}"
            layer_data = get_json(new_url)
            if layer_data and 'fields' in layer_data:
                mapping = heuristic_map(layer_data['fields'])
                if 'parcel_id' in mapping or 'address' in mapping:
                    print(f"[REPAIR] {slug}: {new_url} (Matches: {candidate['name']})")
                    profiles[slug]['layer_url'] = new_url
                    profiles[slug]['field_map'].update(mapping)
                    repaired += 1
    
    if repaired > 0:
        with open(COUNTY_PROFILES_PATH, 'w', encoding='utf-8') as f:
            json.dump(profiles, f, indent=2)
        print(f"\nRepaired {repaired} counties via hierarchy search.")
    else:
        print("\nNo repairs were found via hierarchy search.")

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    repair_all()
