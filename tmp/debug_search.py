import requests
import json

search_url = "https://www.arcgis.com/sharing/rest/search"
params = {
    'q': 'Wayne County Indiana Parcel (type:"Feature Service" OR type:"Map Service")',
    'f': 'json'
}
try:
    print("Searching...")
    resp = requests.get(search_url, params=params, timeout=10)
    results = resp.json().get('results', [])
    print(f"Found {len(results)} results")
    for r in results:
        print(f"- {r.get('title')}: {r.get('url')}")
except Exception as e:
    print(f"Error: {e}")
