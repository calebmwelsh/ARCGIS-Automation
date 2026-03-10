import json
import os

import requests
from dotenv import load_dotenv

# Load environment variables from the .env directory
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env', '.env')
load_dotenv(dotenv_path)

def fetch_arcgis_data():
    """
    Fetches data from an ArcGIS REST API Feature Service using configuration
    from the .env file.
    """
    # 1. Pull configuration from semantic UI environment variables
    base_url = os.environ.get('ARCGIS_FEATURE_SERVICE_URL')
    if not base_url:
        print("Error: ARCGIS_FEATURE_SERVICE_URL is not set.")
        return
        
    zip_code_str = os.environ.get('ZIP_CODE', '').strip()
    zip_codes = [z.strip() for z in zip_code_str.split(',')] if zip_code_str else []
    year_condition = os.environ.get('YEAR_BUILT_CONDITION', 'any')
    year1 = os.environ.get('YEAR_BUILD_1', '').strip()
    year2 = os.environ.get('YEAR_BUILD_2', '').strip()
    
    out_fields = os.environ.get('DATA_OUTPUT_OPTIONS', '*')
    record_count = os.environ.get('RESULT_RECORD_COUNT', '50')
    
    # Reconstruct the WHERE clause from semantic inputs
    clauses = []
    if zip_codes:
        if len(zip_codes) == 1:
            clauses.append(f"LOCZIP = '{zip_codes[0]}'")
        else:
            zip_list_str = ", ".join([f"'{z}'" for z in zip_codes])
            clauses.append(f"LOCZIP IN ({zip_list_str})")
        
    if year_condition != 'any' and year1:
        if year_condition == 'exactly':
            clauses.append(f"year_built = {year1}")
        elif year_condition == 'after':
            clauses.append(f"year_built > {year1}")
        elif year_condition == 'before':
            clauses.append(f"year_built < {year1}")
        elif year_condition == 'between' and year2:
            low = min(int(year1), int(year2))
            high = max(int(year1), int(year2))
            clauses.append(f"year_built BETWEEN {low} AND {high}")
            
    where_clause = " AND ".join(clauses) if clauses else "1=1"
    
    # Technical Parameters (Hardcoded defaults)
    result_offset = '0'
    order_by = ''
    return_geometry = 'false'
    
    # Spatial parameters (Hardcoded defaults)
    geometry = ''
    geometry_type = 'esriGeometryEnvelope'
    spatial_rel = 'esriSpatialRelIntersects'

    # Construct the query URL
    # The endpoint is always <layer_url>/query
    query_url = f"{base_url.rstrip('/')}/query"

    # Define query parameters
    params = {
        'where': where_clause,
        'outFields': out_fields,
        'resultRecordCount': record_count,
        'resultOffset': result_offset,
        'f': 'json',          # Always request JSON format
        'returnGeometry': return_geometry
    }

    # Add optional parameters if they are provided
    if order_by:
        params['orderByFields'] = order_by
    if geometry:
        params['geometry'] = geometry
        params['geometryType'] = geometry_type
        params['spatialRel'] = spatial_rel

    print(f"Fetching data from: {query_url}")
    print(f"Parameters: {params}\n")

    try:
        # 2. Make the HTTP GET request
        response = requests.get(query_url, params=params)
        
        # Check if the request was successful
        response.raise_for_status()

        # Parse the JSON response
        data = response.json()

        # Check for API-level errors within a 200 OK response
        if 'error' in data:
            print(f"API Error: {data['error'].get('message', 'Unknown Error')}")
            print(f"Details: {data['error'].get('details', [])}")
            return

        # 3. Handle the results
        features = data.get('features', [])
        print(f"Successfully retrieved {len(features)} records.\n")
        
        # Save to a temporary file for easy inspection later
        tmp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.tmp')
        os.makedirs(tmp_dir, exist_ok=True)
        out_file = os.path.join(tmp_dir, 'arcgis_raw_results.json')
        
        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            
        print(f"Saved raw output to {out_file}\n")
        
        print("--- PARCEL SUMMARIES ---")
        for feature in features:
            attrs = feature.get('attributes', {})
            obj_id = attrs.get('OBJECTID')
            address = attrs.get('LOCADDRESS', 'No Address')
            year = attrs.get('year_built', 'Unknown Year')
            
            # Construct the Experience Builder URL using the search widget and address
            search_address = f"{address}, {attrs.get('LOCCITY', '')}, IN {attrs.get('LOCZIP', '')}"
            from urllib.parse import quote
            encoded_search = quote(search_address)
            exp_url = f"https://experience.arcgis.com/experience/619d96a48c8241cbad905b9e640c157f#widget_2=text:{encoded_search}"
            
            print(f"ID: {obj_id} | Built: {year} | Address: {address}")
            print(f"Map Link: {exp_url}")
            print("-" * 50)

    except requests.exceptions.RequestException as e:
        print(f"HTTP Request failed: {e}")
    except json.JSONDecodeError:
        print("Failed to decode JSON response.")
        print("Raw response text:", response.text)

if __name__ == "__main__":
    fetch_arcgis_data()
