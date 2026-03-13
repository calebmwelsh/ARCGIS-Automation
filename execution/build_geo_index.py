"""
build_geo_index.py
------------------
One-time (or periodic refresh) script that builds data/geo_index.json.

Data sources (all FREE, no API key required):
  1. Census ZCTA-to-County Relationship File (2020)
     -> Maps every ZIP code to its primary county FIPS + state FIPS
  2. Census County Gazetteer (2023)
     -> Maps county FIPS to county name + state abbreviation
  3. Zippopotam.us (free REST API, no key)
     -> Resolves city name(s) for each ZIP code

Usage:
  # Full US build (all ~42k ZIPs, takes a few minutes due to Zippopotam rate limiting)
  python execution/build_geo_index.py

  # Targeted build for specific states (fast — seconds)
  python execution/build_geo_index.py --states IN GA WA

  # Skip city enrichment (much faster, but no city names)
  python execution/build_geo_index.py --states IN --no-cities

Output:
  data/geo_index.json
"""

import argparse
import csv
import io
import json
import os
import time
import zipfile
from collections import defaultdict

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "geo_index.json")
COUNTY_PROFILES_PATH = os.path.join(DATA_DIR, "county_profiles.json")

# ---------------------------------------------------------------------------
# Census Data URLs
# ---------------------------------------------------------------------------
# ZCTA (ZIP Code Tabulation Area) -> County relationship file (2020 Census)
ZCTA_COUNTY_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
    "tab20_zcta520_county20_natl.txt"
)

# County Gazetteer (2023) - tab-separated, includes county name + state abbrev
COUNTY_GAZ_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/"
    "2023_Gaz_counties_national.zip"
)

# Zippopotam.us base URL for city lookup
ZIPPOPOTAM_URL = "https://api.zippopotam.us/us/{zip}"


# ---------------------------------------------------------------------------
# Step 1: Download & parse the county gazetteer
# ---------------------------------------------------------------------------
def fetch_county_gazetteer():
    """
    Returns a dict mapping county_fips (5-digit string, e.g. '18057')
    to {'county': 'Hamilton County', 'state_abbrev': 'IN', 'state': 'Indiana'}.
    """
    print("[1/4] Downloading county gazetteer...")
    resp = requests.get(COUNTY_GAZ_URL, timeout=60)
    resp.raise_for_status()

    # It's a zip file containing a .txt tab-separated file
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        # Find the .txt file inside the zip
        txt_files = [n for n in z.namelist() if n.endswith(".txt")]
        if not txt_files:
            raise RuntimeError("No .txt file found in county gazetteer zip")
        with z.open(txt_files[0]) as f:
            content = f.read().decode("utf-8")

    # State FIPS -> abbreviation mapping (hardcoded — Census standard)
    state_fips_to_abbrev = {
        "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
        "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
        "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
        "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
        "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
        "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
        "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
        "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
        "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
        "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
        "56": "WY", "60": "AS", "66": "GU", "69": "MP", "72": "PR",
        "78": "VI",
    }
    state_abbrev_to_name = {
        "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
        "CA": "California", "CO": "Colorado", "CT": "Connecticut",
        "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida",
        "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
        "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
        "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
        "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
        "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
        "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
        "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
        "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
        "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
        "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
        "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
        "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
        "WI": "Wisconsin", "WY": "Wyoming", "AS": "American Samoa",
        "GU": "Guam", "MP": "Northern Mariana Islands", "PR": "Puerto Rico",
        "VI": "U.S. Virgin Islands",
    }

    county_map = {}
    reader = csv.DictReader(io.StringIO(content), delimiter="\t")
    for row in reader:
        # Gazetteer columns: USPS, GEOID, ANSICODE, NAME, ALAND, AWATER, ALAND_SQMI, AWATER_SQMI, INTPTLAT, INTPTLONG
        usps = row.get("USPS", "").strip()         # State abbreviation
        geoid = row.get("GEOID", "").strip()       # 5-digit county FIPS
        name = row.get("NAME", "").strip()         # County name (e.g. "Hamilton County")

        if not geoid or not usps or not name:
            continue

        state_name = state_abbrev_to_name.get(usps, usps)
        county_map[geoid] = {
            "county": name,
            "state_abbrev": usps,
            "state": state_name,
        }

    print(f"   -> Loaded {len(county_map)} counties from gazetteer.")
    return county_map


# ---------------------------------------------------------------------------
# Step 2: Download & parse the ZCTA-to-County relationship file
# ---------------------------------------------------------------------------
def fetch_zcta_county_rel(state_filter=None):
    """
    Returns a dict mapping zip_code -> county_fips (5-digit string).
    
    The relationship file has one row per ZCTA-county overlap. We pick the
    county with the highest housing unit overlap (AREALAND_PART as proxy).
    
    state_filter: set of state FIPS codes to include, or None for all.
    """
    print("[2/4] Downloading ZCTA-to-County relationship file (this may take a moment)...")
    resp = requests.get(ZCTA_COUNTY_URL, timeout=120, stream=True)
    resp.raise_for_status()

    content = resp.content.decode("utf-8")
    print(f"   -> Downloaded {len(content):,} bytes.")

    # Parse: columns are pipe-delimited
    # ZCTA5_20, GEOID_ZCTA5_20, COUNTY_20, GEOID_COUNTY_20, ... , AREALAND_PART, AREAWATER_PART, ...
    overlap_map = defaultdict(list)  # zip -> [(area_land, county_fips)]

    reader = csv.DictReader(io.StringIO(content), delimiter="|")
    for row in reader:
        zip_code = row.get("GEOID_ZCTA5_20", "").strip().zfill(5)
        county_fips = row.get("GEOID_COUNTY_20", "").strip().zfill(5)

        if not zip_code or not county_fips or len(zip_code) != 5:
            continue

        # State filter: county FIPS starts with state FIPS (2 digits)
        if state_filter and county_fips[:2] not in state_filter:
            continue

        try:
            area = int(row.get("AREALAND_PART", "0") or "0")
        except ValueError:
            area = 0

        overlap_map[zip_code].append((area, county_fips))

    # Pick primary county (highest land area overlap)
    zip_to_county = {}
    for zip_code, overlaps in overlap_map.items():
        overlaps.sort(reverse=True)
        zip_to_county[zip_code] = overlaps[0][1]  # Primary county FIPS

    print(f"   -> Mapped {len(zip_to_county):,} ZIP codes to primary counties.")
    return zip_to_county


# ---------------------------------------------------------------------------
# Step 3: Enrich with city names via Zippopotam.us
# ---------------------------------------------------------------------------
def enrich_cities(zip_codes, delay=0.1):
    """
    For each ZIP code, fetches city name(s) from Zippopotam.us.
    Returns a dict: zip_code -> [list of place names].
    """
    city_map = {}
    total = len(zip_codes)
    print(f"[3/4] Enriching {total:,} ZIP codes with city names via Zippopotam.us...")
    print("      (Using 0.1s delay between requests to be respectful of the free API)")

    for i, zip_code in enumerate(sorted(zip_codes)):
        if (i + 1) % 100 == 0:
            print(f"      Progress: {i+1}/{total} ZIPs processed...")
        try:
            url = ZIPPOPOTAM_URL.format(zip=zip_code)
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                places = data.get("places", [])
                city_names = list({p.get("place name", "").strip() for p in places if p.get("place name")})
                city_map[zip_code] = city_names
            elif resp.status_code == 404:
                city_map[zip_code] = []  # ZIP not found in Zippopotam (PO Box, etc.)
            else:
                city_map[zip_code] = []
        except Exception:
            city_map[zip_code] = []
        time.sleep(delay)

    found = sum(1 for v in city_map.values() if v)
    print(f"   -> City names found for {found:,}/{total:,} ZIP codes.")
    return city_map


# ---------------------------------------------------------------------------
# Step 4: Load existing county_profiles.json for profile_key linking
# ---------------------------------------------------------------------------
def load_county_profiles():
    """
    Loads county_profiles.json if it exists.
    Builds a lookup: (county_name_lower, state_abbrev_lower) -> profile details.
    """
    if not os.path.exists(COUNTY_PROFILES_PATH):
        print("   [info] No county_profiles.json found — skipping profile linking.")
        return {}

    with open(COUNTY_PROFILES_PATH, "r", encoding="utf-8") as f:
        profiles = json.load(f)

    # Build a normalized lookup by county name + state
    lookup = {}
    # Profiles can be a dict of {profile_key: {...}} or a list
    if isinstance(profiles, dict):
        items = profiles.items()
    elif isinstance(profiles, list):
        items = [(p.get("key", str(i)), p) for i, p in enumerate(profiles)]
    else:
        return {}

    for profile_key, profile in items:
        county_raw = profile.get("county", "") or profile.get("name", "")
        state_raw = profile.get("state", "") or profile.get("state_abbrev", "")
        if county_raw and state_raw:
            norm_key = (county_raw.lower().strip(), state_raw.upper().strip())
            lookup[norm_key] = profile_key

    print(f"   -> Loaded {len(lookup)} county profiles for linking.")
    return lookup


# ---------------------------------------------------------------------------
# Step 5: Assemble the index
# ---------------------------------------------------------------------------
def build_index(zip_to_county, county_map, city_map, profile_lookup):
    """
    Builds the four-way geo_index structure.
    """
    print("[4/4] Assembling geo index...")

    by_zip = {}
    by_county = defaultdict(lambda: {"zips": [], "cities": set()})
    by_state = defaultdict(lambda: {"counties": {}})
    by_city = defaultdict(lambda: {"zips": []})

    for zip_code, county_fips in zip_to_county.items():
        county_info = county_map.get(county_fips)
        if not county_info:
            continue

        county_name = county_info["county"]
        state_abbrev = county_info["state_abbrev"]
        state_name = county_info["state"]
        cities = city_map.get(zip_code, [])

        # Try to find a matching ArcGIS profile_key
        norm_key = (county_name.lower(), state_abbrev.upper())
        profile_key = profile_lookup.get(norm_key)

        # by_zip
        by_zip[zip_code] = {
            "zip": zip_code,
            "cities": cities,
            "county": county_name,
            "county_fips": county_fips,
            "state": state_name,
            "state_abbrev": state_abbrev,
            **({"profile_key": profile_key} if profile_key else {}),
        }

        # by_county
        by_county[county_fips]["county"] = county_name
        by_county[county_fips]["county_fips"] = county_fips
        by_county[county_fips]["state"] = state_name
        by_county[county_fips]["state_abbrev"] = state_abbrev
        by_county[county_fips]["zips"].append(zip_code)
        by_county[county_fips]["cities"].update(cities)
        if profile_key:
            by_county[county_fips]["profile_key"] = profile_key

        # by_state
        by_state[state_abbrev]["state"] = state_name
        by_state[state_abbrev]["state_abbrev"] = state_abbrev
        if county_fips not in by_state[state_abbrev]["counties"]:
            by_state[state_abbrev]["counties"][county_fips] = county_name

        # by_city — keyed as "city_name_lower|state_abbrev"
        for city in cities:
            city_key = f"{city.lower()}|{state_abbrev.upper()}"
            if zip_code not in by_city[city_key]["zips"]:
                by_city[city_key]["city"] = city
                by_city[city_key]["state_abbrev"] = state_abbrev
                by_city[city_key]["state"] = state_name
                by_city[city_key]["zips"].append(zip_code)

    # Convert sets to sorted lists for JSON serialization
    for fips, data in by_county.items():
        data["cities"] = sorted(data["cities"])
        data["zips"] = sorted(data["zips"])

    # Finalize by_state: sort county keys
    for abbrev, data in by_state.items():
        data["counties"] = dict(
            sorted(data["counties"].items(), key=lambda x: x[1])
        )

    index = {
        "meta": {
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "zip_count": len(by_zip),
            "county_count": len(by_county),
            "state_count": len(by_state),
        },
        "by_zip": dict(sorted(by_zip.items())),
        "by_county": {k: dict(v) for k, v in sorted(by_county.items())},
        "by_state": dict(sorted(by_state.items())),
        "by_city": dict(sorted(by_city.items())),
    }

    print(f"   -> Index built: {len(by_zip):,} ZIPs | {len(by_county):,} counties | {len(by_state):,} states | {len(by_city):,} city entries")
    return index


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Build the geo_index.json from free Census Bureau data."
    )
    parser.add_argument(
        "--states",
        nargs="+",
        metavar="STATE",
        help="Filter to specific state abbreviations (e.g. IN GA WA). Omit for all US states.",
    )
    parser.add_argument(
        "--no-cities",
        action="store_true",
        help="Skip Zippopotam.us city enrichment (much faster, but no city names).",
    )
    args = parser.parse_args()

    # Resolve state abbreviation filter -> FIPS codes
    state_fips_filter = None
    if args.states:
        # State abbrev -> FIPS mapping (reverse of the one inside fetch_county_gazetteer)
        abbrev_to_fips = {
            "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06",
            "CO": "08", "CT": "09", "DE": "10", "DC": "11", "FL": "12",
            "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18",
            "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23",
            "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28",
            "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
            "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38",
            "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44",
            "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49",
            "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55",
            "WY": "56", "AS": "60", "GU": "66", "MP": "69", "PR": "72",
            "VI": "78",
        }
        state_fips_filter = set()
        for abbrev in args.states:
            fips = abbrev_to_fips.get(abbrev.upper())
            if fips:
                state_fips_filter.add(fips)
            else:
                print(f"   [warn] Unknown state abbreviation: {abbrev}")
        print(f"[Filter] Building for states: {', '.join(s.upper() for s in args.states)}")
    else:
        print("[Filter] Building for ALL US states (this may take several minutes for city enrichment).")

    os.makedirs(DATA_DIR, exist_ok=True)

    # Step 1: County names
    county_map = fetch_county_gazetteer()

    # Step 2: ZIP-to-county relationships
    zip_to_county = fetch_zcta_county_rel(state_filter=state_fips_filter)

    # Step 3: County profiles for linking
    profile_lookup = load_county_profiles()

    # Step 4: City enrichment (optional)
    if args.no_cities:
        print("[3/4] Skipping city enrichment (--no-cities flag set).")
        city_map = {z: [] for z in zip_to_county}
    else:
        city_map = enrich_cities(list(zip_to_county.keys()))

    # Step 5: Assemble and write
    index = build_index(zip_to_county, county_map, city_map, profile_lookup)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)

    print(f"\n[DONE] geo_index.json written to: {OUTPUT_PATH}")
    print(f"  File size: {os.path.getsize(OUTPUT_PATH):,} bytes")


if __name__ == "__main__":
    main()
