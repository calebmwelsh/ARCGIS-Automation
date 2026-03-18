import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COUNTY_PROFILES_PATH = os.path.join(BASE_DIR, 'data', 'county_profiles.json')

def audit_profiles():
    if not os.path.exists(COUNTY_PROFILES_PATH):
        print(f"Error: {COUNTY_PROFILES_PATH} not found.")
        return

    with open(COUNTY_PROFILES_PATH, 'r', encoding='utf-8') as f:
        profiles = json.load(f)

    stats = {
        "total_counties": len(profiles),
        "by_state": {},
        "missing_url": [],
        "missing_all_fields": [],
        "missing_year_built": [],
        "high_quality": [] # Has URL, parcel_id, address, and year_built
    }

    for key, p in profiles.items():
        state = p.get('state', 'Unknown')
        stats["by_state"][state] = stats["by_state"].get(state, 0) + 1
        
        url = p.get('layer_url')
        field_map = p.get('field_map', {})
        
        has_url = url and "arcgis" in url.lower()
        has_address = field_map.get('address') is not None
        has_parcel = field_map.get('parcel_id') is not None
        has_year = field_map.get('year_built') is not None
        
        if not url:
            stats["missing_url"].append(key)
        
        if not field_map or all(v is None for v in field_map.values()):
            stats["missing_all_fields"].append(key)
            
        if not has_year:
            stats["missing_year_built"].append(key)
            
        if has_url and has_address and has_parcel and has_year:
            stats["high_quality"].append(key)

    print(f"Total Counties Analyzed: {stats['total_counties']}")
    print(f"Counties Missing URL: {len(stats['missing_url'])}")
    print(f"Counties with No Fields Mapped: {len(stats['missing_all_fields'])}")
    print(f"Counties Missing Year Built: {len(stats['missing_year_built'])}")
    print(f"Counties categorized as 'High Quality': {len(stats['high_quality'])}")
    
    # Analyze Indiana specifically
    in_total = stats["by_state"].get("Indiana", 0)
    in_high_quality = [k for k in stats["high_quality"] if k.endswith("_in")]
    print(f"\nIndiana Specific Stats:")
    print(f"  Total IN Counties: {in_total}")
    print(f"  High Quality IN Counties: {len(in_high_quality)}")
    print(f"  Sample HQ IN: {in_high_quality[:5]}")

    # Log anomalies to a file for review
    anomalies = {
        "missing_url": stats["missing_url"][:50], # Limit to 50 for summary
        "missing_all_fields": stats["missing_all_fields"][:50],
        "high_quality_indiana": in_high_quality
    }
    
    anomaly_path = os.path.join(BASE_DIR, '.tmp', 'county_audit_results.json')
    with open(anomaly_path, 'w', encoding='utf-8') as f:
        json.dump(anomalies, f, indent=2)
    print(f"\nAudit results saved to: {anomaly_path}")

if __name__ == "__main__":
    audit_profiles()
