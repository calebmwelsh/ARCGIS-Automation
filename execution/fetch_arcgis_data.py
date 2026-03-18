import json
import os
import re
import requests
from dotenv import load_dotenv

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, '.env', '.env')
DATA_DIR = os.path.join(BASE_DIR, 'data')
GEO_INDEX_PATH = os.path.join(DATA_DIR, 'geo_index.json')
COUNTY_PROFILES_PATH = os.path.join(DATA_DIR, 'county_profiles.json')

load_dotenv(ENV_PATH)

def build_profile_key(county_name: str, state_abbrev: str) -> str:
    """Matches the key generation from onboard_county.py"""
    slug = re.sub(r"[^a-z0-9]+", "_", county_name.lower().strip()) 
    slug = slug.strip("_")
    return f"{slug}_{state_abbrev.lower()}"

def get_profile_by_scope(scope_type: str, scope_value: str, geo=None):
    """Looks up the county profile based on scope type and value."""
    if not os.path.exists(COUNTY_PROFILES_PATH):
        return None
        
    try:
        with open(COUNTY_PROFILES_PATH, 'r', encoding='utf-8') as f:
            profiles = json.load(f)
            
        county_name = None
        state_abbrev = None

        if not geo and os.path.exists(GEO_INDEX_PATH):
            with open(GEO_INDEX_PATH, 'r', encoding='utf-8') as f:
                geo = json.load(f)
                
        if not geo: return None

        if scope_type == 'zip':
            zip_info = geo.get('by_zip', {}).get(scope_value)
            if zip_info:
                county_name = zip_info['county']
                state_abbrev = zip_info['state_abbrev']
                
        elif scope_type == 'county':
            county_info = geo.get('by_county', {}).get(scope_value)
            if county_info:
                county_name = county_info['county']
                state_abbrev = county_info['state_abbrev']
                
        elif scope_type == 'city':
            city_info = geo.get('by_city', {}).get(scope_value.lower())
            if city_info and city_info.get('zips'):
                first_zip = city_info['zips'][0]
                zip_info = geo.get('by_zip', {}).get(first_zip)
                if zip_info:
                    county_name = zip_info['county']
                    state_abbrev = zip_info['state_abbrev']

        if county_name and state_abbrev:
            profile_key = build_profile_key(county_name, state_abbrev)
            print(f"Mapped {scope_type} '{scope_value}' to profile: {profile_key}")
            return profiles.get(profile_key)
            
    except Exception as e:
        print(f"Error loading profile data: {e}")
        
    return None

def fetch_arcgis_data():
    """
    Fetches data from an ArcGIS REST API Feature Service using semantic configuration.
    Dynamically routes to the correct county URL based on LOCATION SCOPE.
    """
    scope_type = os.environ.get('SEARCH_SCOPE_TYPE', 'zip').strip().lower()
    scope_value = os.environ.get('SEARCH_SCOPE_VALUE', '').strip()
    
    # Legacy fallback
    legacy_zip = os.environ.get('ZIP_CODE', '').strip()
    if not scope_value and legacy_zip:
        scope_type = 'zip'
        scope_value = legacy_zip

    year_condition = os.environ.get('YEAR_BUILT_CONDITION', 'any')
    year1 = os.environ.get('YEAR_BUILD_1', '').strip()
    year2 = os.environ.get('YEAR_BUILD_2', '').strip()
    out_fields = os.environ.get('DATA_OUTPUT_OPTIONS', '*')
    record_count = os.environ.get('RESULT_RECORD_COUNT', '50')
    
    geo = None
    if os.path.exists(GEO_INDEX_PATH):
        with open(GEO_INDEX_PATH, 'r', encoding='utf-8') as f:
            geo = json.load(f)

    profile = get_profile_by_scope(scope_type, scope_value, geo) if scope_value else None
    
    if profile:
        base_url = profile['layer_url']
        field_map = profile.get('field_map', {})
        print(f"Dynamic Profiling Active: '{profile['county']}, {profile['state_abbrev']}' (Scope: {scope_type}={scope_value})")
    else:
        # Fallback to hardcoded .env URL
        base_url = os.environ.get('ARCGIS_FEATURE_SERVICE_URL')
        if not base_url:
            print("Error: No valid County Profile found, and no ARCGIS_FEATURE_SERVICE_URL fallback provided.")
            return
        field_map = {} 

    # Field Mappings
    f_zip = field_map.get('zip') or 'LOCZIP'
    f_year = field_map.get('year_built') or 'year_built'
    f_address = field_map.get('address') or 'LOCADDRESS'
    f_city = field_map.get('city') or 'LOCCITY'
    f_owner = field_map.get('owner_name') or 'DEEDEDOWNR'
    f_val = field_map.get('total_value') or 'ASSTOT'
    f_report_url = field_map.get('property_report_url')

    # Ensure all mapped fields ARE in the outFields query if they are non-null
    if out_fields != '*':
        requested_fields = [f.strip() for f in out_fields.split(',')]
        # Only include fields that were explicitly found in the profile (not fallbacks)
        explicit_mapped_fields = [
            field_map.get('zip'), field_map.get('year_built'), field_map.get('address'),
            field_map.get('city'), field_map.get('owner_name'), field_map.get('total_value'),
            field_map.get('property_report_url')
        ]
        for f in explicit_mapped_fields:
            if f and f not in requested_fields:
                requested_fields.append(f)
        out_fields = ",".join(requested_fields)

    # Reconstruct the WHERE clause using mapped fields
    clauses = []
    
    if scope_type == 'zip' and scope_value and f_zip:
        clauses.append(f"{f_zip} = '{scope_value}'")
    elif scope_type == 'city' and scope_value and f_city:
        city_name = scope_value.split('|')[0] if '|' in scope_value else scope_value
        city_name = city_name.strip().upper()
        clauses.append(f"UPPER({f_city}) = '{city_name}'")
    elif scope_type == 'county' and scope_value and f_zip and geo:
        # Use the geo_index to get all ZIPs in that county and filter the statewide/county layer by them
        county_info = geo.get('by_county', {}).get(scope_value)
        if county_info and county_info.get('zips'):
            zips = county_info['zips']
            in_list = ", ".join(f"'{z}'" for z in zips)
            clauses.append(f"{f_zip} IN ({in_list})")
        else:
            print(f"Warning: Could not resolve ZIP codes for county {scope_value}. Querying entire layer.")
        
    if year_condition != 'any' and year1 and f_year:
        if year_condition == 'exactly':
            clauses.append(f"{f_year} = {year1}")
        elif year_condition == 'after':
            clauses.append(f"{f_year} > {year1}")
        elif year_condition == 'before':
            clauses.append(f"{f_year} < {year1}")
        elif year_condition == 'between' and year2:
            low = min(int(year1), int(year2))
            high = max(int(year1), int(year2))
            clauses.append(f"{f_year} BETWEEN {low} AND {high}")
            
    where_clause = " AND ".join(clauses) if clauses else "1=1"
    
    # Query Construct
    query_url = f"{base_url.rstrip('/')}/query"
    params = {
        'where': where_clause,
        'outFields': out_fields,
        'resultRecordCount': record_count,
        'f': 'json',
        'returnGeometry': 'false'
    }

    print(f"Fetching data from: {query_url}")
    print(f"Parameters: {params}\n")

    try:
        response = requests.get(query_url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if 'error' in data:
            print(f"API Error: {data['error'].get('message', 'Unknown Error')}")
            print(f"Details: {data['error'].get('details', [])}")
            return

        features = data.get('features', [])
        print(f"Successfully retrieved {len(features)} records.\n")
        
        tmp_dir = os.path.join(BASE_DIR, '.tmp')
        os.makedirs(tmp_dir, exist_ok=True)
        out_file = os.path.join(tmp_dir, 'arcgis_raw_results.json')
        
        # Standardize features for UI consumption
        state_abbrev = profile['state_abbrev'] if profile else ''
        county_name = profile['county'] if profile else ''
        layer_url = profile['layer_url'] if profile else ''
        
        for feature in features:
            attrs = feature.get('attributes', {})
            # Inject standard keys
            attrs['std_address'] = str(attrs.get(f_address) or '').strip()
            attrs['std_city'] = str(attrs.get(f_city) or '').strip()
            attrs['std_zip'] = str(attrs.get(f_zip) or '').strip()
            attrs['std_year_built'] = attrs.get(f_year)
            attrs['std_property_report_url'] = attrs.get(f_report_url) if f_report_url else None
            # Fallback to profile template if attribute-based URL is missing
            if not attrs['std_property_report_url'] and profile:
                attrs['std_property_report_url'] = profile.get('property_report_url_template')
                
            attrs['std_state'] = state_abbrev
            attrs['std_county'] = county_name
            attrs['std_layer_url'] = layer_url
            attrs['std_viewer_type'] = profile.get('viewer_type') if profile else None
            attrs['std_viewer_id'] = profile.get('viewer_id') if profile else None

        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            
        print(f"Saved raw output to {out_file} (with standardized fields)\n")
        print(f"{'--- PARCEL SUMMARIES ---':^50}")
        
        for feature in features:
            attrs = feature.get('attributes', {})
            obj_id = attrs.get('OBJECTID') or attrs.get('FID') or 'N/A'
            address = attrs.get(f_address) or 'No Address'
            year = attrs.get(f_year) or 'Unknown Year'
            owner = attrs.get(f_owner) or 'Unknown Owner'
            val = attrs.get(f_val)
            val_str = f"${val:,.0f}" if isinstance(val, (int, float)) else str(val)
            
            # Map search fallback
            city = attrs.get(f_city, '')
            zipc = attrs.get(f_zip, '')
            state = profile['state_abbrev'] if profile else ''
            county = profile['county'] if profile else ''
            report_url = attrs.get('std_property_report_url')

            # Generalized Map Link Generation
            viewer_type = attrs.get('std_viewer_type')
            viewer_id = attrs.get('std_viewer_id')
            
            if report_url:
                map_link = report_url
            elif viewer_type == 'experience' and viewer_id:
                search_address = f"{address}, {city}, {state} {zipc}".strip(', ')
                from urllib.parse import quote
                encoded_search = quote(search_address)
                map_link = f"https://experience.arcgis.com/experience/{viewer_id}#widget_2=text:{encoded_search}"
            elif viewer_type == 'webapp' and viewer_id:
                # Construct Web AppBuilder link (id parameter)
                # Note: Exact search params for Web AppBuilder vary, but id is consistent
                map_link = f"https://www.arcgis.com/apps/webappviewer/index.html?id={viewer_id}"
            elif 'Hamilton' in county and state == 'IN':
                # Legacy hardcode fallback
                search_address = f"{address}, {city}, {state} {zipc}".strip(', ')
                from urllib.parse import quote
                encoded_search = quote(search_address)
                map_link = f"https://experience.arcgis.com/experience/619d96a48c8241cbad905b9e640c157f#widget_2=text:{encoded_search}"
            elif layer_url:
                from urllib.parse import quote
                map_link = f"https://www.arcgis.com/home/webmap/viewer.html?url={quote(layer_url)}&source=sd"
            else:
                map_link = "N/A"
            
            print(f"ID: {obj_id} | Built: {year} | Value: {val_str}")
            print(f"Owner: {owner}")
            print(f"Address: {address}")
            print(f"Map Link: {map_link}")
            print("-" * 50)

    except requests.exceptions.RequestException as e:
        print(f"HTTP Request failed: {e}")
    except json.JSONDecodeError:
        print("Failed to decode JSON response.")

if __name__ == "__main__":
    fetch_arcgis_data()


