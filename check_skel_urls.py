import json
import os

with open('data/county_profiles.json', 'r', encoding='utf-8') as f:
    profiles = json.load(f)

skeletons = []
no_url = []
with_url = []

for key, p in profiles.items():
    field_count = sum(1 for v in p.get('field_map', {}).values() if v is not None)
    if field_count == 0:
        if not p.get('layer_url'):
            no_url.append(key)
        else:
            with_url.append(key)

print(f"Total Skeletons: {len(no_url) + len(with_url)}")
print(f"Skeletons WITHOUT URL: {len(no_url)}")
print(f"Skeletons WITH URL: {len(with_url)}")

print("\nWith URL (Needs hierarchy repair or mapping):")
for k in sorted(with_url):
    print(f" - {k}: {profiles[k]['layer_url']}")
