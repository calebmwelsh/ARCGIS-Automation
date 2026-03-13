import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DISCOVERED_PATH = os.path.join(DATA_DIR, 'discovered_urls.json')
PROFILES_PATH = os.path.join(DATA_DIR, 'county_profiles.json')

def clean_data():
    with open(PROFILES_PATH, 'r', encoding='utf-8') as f:
        profiles = json.load(f)
        
    with open(DISCOVERED_PATH, 'r', encoding='utf-8') as f:
        discovered = json.load(f)

    bad_keys = []
    
    # Find contaminated IN counties
    for key, data in profiles.items():
        if key.endswith('_in') and 'Florida_Statewide_Cadastral' in data.get('layer_url', ''):
            bad_keys.append(key)
            
    print(f"Removing {len(bad_keys)} bad cross-state mappings...")
    for key in bad_keys:
        print(f" - {key}")
        if key in profiles:
            del profiles[key]
        if key in discovered:
            del discovered[key]
            
    # Also delete hamilton county entirely to force a clean re-run for our test case
    test_key = 'hamilton_county_in'
    if test_key in profiles: del profiles[test_key]
    if test_key in discovered: del discovered[test_key]
            
    with open(PROFILES_PATH, 'w', encoding='utf-8') as f:
        json.dump(profiles, f, indent=2)
        
    with open(DISCOVERED_PATH, 'w', encoding='utf-8') as f:
        json.dump(discovered, f, indent=2)

if __name__ == '__main__':
    clean_data()
