import json
import os
from urllib.parse import quote

def test_map_links():
    # Mock profiles
    profiles = {
        "hamilton_county_in": {
            "county": "Hamilton County",
            "state_abbrev": "IN",
            "viewer_type": "experience",
            "viewer_id": "619d96a48c8241cbad905b9e640c157f",
            "layer_url": "https://gisdata.in.gov/..."
        },
        "boone_county_in": {
            "county": "Boone County",
            "state_abbrev": "IN",
            "viewer_type": "webapp",
            "viewer_id": "8a929e411e31457898b91586492644e2",
            "layer_url": "https://services3.arcgis.com/..."
        },
        "lake_county_in": {
            "county": "Lake County",
            "state_abbrev": "IN",
            "viewer_type": "experience",
            "viewer_id": "18676999665349e492506de765490541",
            "layer_url": "https://lcsogis.lakecountyin.org/..."
        }
    }

    test_cases = [
        ("Hamilton County", "IN", "123 Main St", "Noblesville", "46060"),
        ("Boone County", "IN", "456 Oak St", "Lebanon", "46052"),
        ("Lake County", "IN", "789 Pine St", "Gary", "46402"),
    ]

    for county_name, state, addr, city, zipc in test_cases:
        key = f"{county_name.lower().replace(' ', '_')}_in"
        profile = profiles.get(key)
        
        viewer_type = profile.get('viewer_type')
        viewer_id = profile.get('viewer_id')
        layer_url = profile.get('layer_url')

        print(f"\n--- Testing {county_name} ---")
        
        # Logic from fetch_arcgis_data.py
        if viewer_type == 'experience' and viewer_id:
            search_address = f"{addr}, {city}, {state} {zipc}".strip(', ')
            encoded_search = quote(search_address)
            map_link = f"https://experience.arcgis.com/experience/{viewer_id}#widget_2=text:{encoded_search}"
        elif viewer_type == 'webapp' and viewer_id:
            map_link = f"https://www.arcgis.com/apps/webappviewer/index.html?id={viewer_id}"
        elif 'Hamilton' in county_name and state == 'IN':
            search_address = f"{addr}, {city}, {state} {zipc}".strip(', ')
            encoded_search = quote(search_address)
            map_link = f"https://experience.arcgis.com/experience/619d96a48c8241cbad905b9e640c157f#widget_2=text:{encoded_search}"
        elif layer_url:
            map_link = f"https://www.arcgis.com/home/webmap/viewer.html?url={quote(layer_url)}&source=sd"
        else:
            map_link = "N/A"
            
        print(f"Generated Link: {map_link}")

if __name__ == "__main__":
    test_map_links()
