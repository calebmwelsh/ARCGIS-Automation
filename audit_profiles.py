import json
import os

with open('data/county_profiles.json', 'r', encoding='utf-8') as f:
    profiles = json.load(f)

skeletons = []
high_quality = []
for key, p in profiles.items():
    field_count = sum(1 for v in p.get('field_map', {}).values() if v is not None)
    if field_count == 0:
        skeletons.append(key)
    elif field_count >= 10:
        high_quality.append(key)

print(f"Total Profiles: {len(profiles)}")
print(f"High Quality Counties (10+ fields): {len(high_quality)}")
print(f"Skeleton Counties (0 fields): {len(skeletons)}")
print("\nRemaining Skeletons:")
for s in sorted(skeletons)[:20]:
    print(f" - {s}")
if len(skeletons) > 20:
    print(f" ... and {len(skeletons)-20} more.")
