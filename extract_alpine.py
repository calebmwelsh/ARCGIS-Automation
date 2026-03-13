import json
try:
    with open('data/county_profiles.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    profile = data.get('alpine_county_ca')
    if profile:
        print(json.dumps(profile, indent=2))
    else:
        print("Profile 'alpine_county_ca' not found.")
except Exception as e:
    print(f"Error: {e}")
