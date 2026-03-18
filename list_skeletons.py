import json
import os

with open('data/county_profiles.json', 'r', encoding='utf-8') as f:
    profiles = json.load(f)

skeletons = []
for key, p in profiles.items():
    field_count = sum(1 for v in p.get('field_map', {}).values() if v is not None)
    if field_count == 0:
        skeletons.append(f"{p['county']}, {p['state_abbrev']} ({key})")

print(f"Found {len(skeletons)} skeleton counties:")
for s in sorted(skeletons):
    print(f" - {s}")
