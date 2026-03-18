"""
onboard_county.py
------------------
AI-assisted county onboarding script.

Given an ArcGIS FeatureServer URL + county/state, this script:
  1. Fetches sample parcel records from the FeatureServer
  2. Looks up the county in geo_index.json to get the canonical Census name + FIPS
  3. Sends the sample record to Vertex AI to infer a field_map
  4. Validates the field_map against actual field names in the response
  5. Writes the county profile to data/county_profiles.json

Usage:
  python execution/onboard_county.py \\
      --url "https://services5.arcgis.com/.../FeatureServer/0" \\
      --county "Hamilton" \\
      --state IN

  # Dry-run (prints profile but does not write):
  python execution/onboard_county.py --url "..." --county "Hamilton" --state IN --dry-run

Requirements:
  - VERTEX_PROJECT_ID and VERTEX_LOCATION in .env/.env
  - data/geo_index.json must exist (run build_geo_index.py first)
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time

import requests
from dotenv import load_dotenv

# Load env from centralized .env directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT, ".env", ".env"))

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
GEO_INDEX_PATH = os.path.join(DATA_DIR, "geo_index.json")
COUNTY_PROFILES_PATH = os.path.join(DATA_DIR, "county_profiles.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# Standard field set we want to map to for every county
# ---------------------------------------------------------------------------
STANDARD_FIELDS = {
    "address":           "Street address of the parcel (physical/situs location)",
    "zip":               "ZIP code of the parcel (physical/situs location)",
    "city":              "City of the parcel (physical/situs location)",
    "owner_name":        "Name of the property owner (deeded owner or primary owner)",
    "owner_address":     "Mailing street address of the owner",
    "owner_city":        "Mailing city of the owner",
    "owner_state":       "Mailing state of the owner",
    "owner_zip":         "Mailing ZIP of the owner",
    "year_built":        "Year the structure was built",
    "parcel_id":         "Unique parcel identifier or parcel number",
    "land_value":        "Assessed value of the land only",
    "improvement_value": "Assessed value of the improvements (structures) only",
    "total_value":       "Total assessed value (land + improvements)",
    "property_class":    "Property use or class code description",
    "legal_description": "Legal description of the parcel",
    "acres":             "Parcel size in acres",
    "sq_ft_building":    "Total building square footage",
    "property_report_url": "Link to the official property report page",
}


# ---------------------------------------------------------------------------
# Step 1: Fetch sample records from the FeatureServer
# ---------------------------------------------------------------------------
def fetch_sample_records(url: str, sample_count: int = 5) -> list[dict]:
    # 1. Clean and Normalize URL
    url = url.strip().split("?")[0].rstrip("/")
    
    # Normalize hostname to lowercase, keep path case
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(url)
    hostname = parsed.netloc.lower()
    path = parsed.path
    url = urlunparse(parsed._replace(netloc=hostname))

    # Detect base layer URL
    path_segments = url.rstrip("/").split("/")
    if path_segments[-1].isdigit():
        base_layer_url = url
    else:
        if url.lower().endswith("featureserver") or url.lower().endswith("mapserver"):
            base_layer_url = url + "/0"
        else:
            base_layer_url = url

    # 2. Setup Headers and Params
    verify_ssl = True
    if 'current_args' in globals() and current_args.no_verify:
        verify_ssl = False
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json"
    }

    # 3. Multi-Stage Discovery
    # Stage A: Standard Query
    query_url = base_layer_url + "/query"
    params = {"f": "json", "where": "1=1", "outFields": "*", "resultRecordCount": str(sample_count), "returnGeometry": "false"}
    
    logging.info(f"Discovery A (Query): {query_url}")
    try:
        resp = requests.get(query_url, params=params, headers=headers, timeout=30, verify=verify_ssl)
        if resp.ok:
            data = resp.json()
            if "features" in data and data["features"]:
                logging.info("Schema found via A.")
                return [f["attributes"] for f in data["features"]]
    except: pass

    # Stage B: Metadata Fallback
    logging.info(f"Discovery B (Metadata): {base_layer_url}")
    try:
        resp = requests.get(base_layer_url, params={"f": "json"}, headers=headers, timeout=30, verify=verify_ssl)
        if resp.ok:
            data = resp.json()
            if "fields" in data:
                logging.info("Schema found via B.")
                return [{field["name"]: None for field in data["fields"]}]
    except: pass

    # Stage C: Alternate Capitalization
    alt_url = url
    if "/arcgis/" in alt_url: alt_url = alt_url.replace("/arcgis/", "/ArcGIS/")
    elif "/ArcGIS/" in alt_url: alt_url = alt_url.replace("/ArcGIS/", "/arcgis/")
    
    if alt_url != url:
        logging.info(f"Discovery C (Alt Case): {alt_url}")
        try:
            resp = requests.get(alt_url, params={"f": "json"}, headers=headers, timeout=30, verify=verify_ssl)
            if resp.ok:
                data = resp.json()
                if "fields" in data:
                    logging.info("Schema found via C.")
                    return [{field["name"]: None for field in data["fields"]}]
        except: pass

    # Discovery D: Try Service level
    service_url = base_layer_url.rsplit("/", 1)[0] if base_layer_url[-1].isdigit() else base_layer_url
    logging.info(f"Discovery D (Service): {service_url}")
    try:
        resp = requests.get(service_url, params={"f": "json"}, headers=headers, timeout=30, verify=verify_ssl)
        if resp.ok:
            data = resp.json()
            if "layers" in data:
                logging.info("Service found via D. Confirming layer...")
                target_id = path_segments[-1] if path_segments[-1].isdigit() else "0"
                for l in data["layers"]:
                    if str(l.get("id")) == target_id:
                        if "fields" in l:
                            return [{field["name"]: None for field in l["fields"]}]
    except: pass

    raise RuntimeError(f"All schema discovery stages failed for {url}")


# ---------------------------------------------------------------------------
# Step 2: Resolve county against geo_index.json
# ---------------------------------------------------------------------------
def resolve_county(county_input: str, state_abbrev: str) -> dict:
    """
    Finds the canonical Census county entry in geo_index.json.
    Returns the full county dict: {county, county_fips, state, state_abbrev, zips}
    """
    if not os.path.exists(GEO_INDEX_PATH):
        raise FileNotFoundError(
            f"geo_index.json not found at {GEO_INDEX_PATH}. "
            "Run: python execution/build_geo_index.py --no-cities"
        )

    with open(GEO_INDEX_PATH, "r", encoding="utf-8") as f:
        geo_index = json.load(f)

    by_county = geo_index.get("by_county", {})
    search_term = county_input.lower().strip()
    state_upper = state_abbrev.upper().strip()

    matches = []
    for fips, county_data in by_county.items():
        county_name_lower = county_data.get("county", "").lower()
        county_state = county_data.get("state_abbrev", "").upper()

        if county_state != state_upper:
            continue

        # Accept "hamilton", "hamilton county", or partial match
        if search_term in county_name_lower or county_name_lower.startswith(search_term):
            matches.append(county_data)

    if not matches:
        raise ValueError(
            f"Could not find county matching '{county_input}' in state '{state_abbrev}' "
            f"within geo_index.json. Check spelling or run build_geo_index.py again."
        )

    if len(matches) > 1:
        names = [m["county"] for m in matches]
        raise ValueError(
            f"Ambiguous county name '{county_input}' matched multiple counties in {state_abbrev}: {names}. "
            "Please be more specific."
        )

    result = matches[0]
    logging.info(
        f"Resolved to: '{result['county']}' (FIPS: {result['county_fips']}, "
        f"State: {result['state_abbrev']}, ZIPs: {len(result.get('zips', []))})"
    )
    return result


# ---------------------------------------------------------------------------
# Step 3: Build a profile key (slug)
# ---------------------------------------------------------------------------
def build_profile_key(county_name: str, state_abbrev: str) -> str:
    """
    Generates a stable, URL-safe profile key from county name + state.
    e.g. "Hamilton County" + "IN" -> "hamilton_county_in"
    """
    slug = re.sub(r"[^a-z0-9]+", "_", county_name.lower().strip()) 
    slug = slug.strip("_")
    return f"{slug}_{state_abbrev.lower()}"


# ---------------------------------------------------------------------------
# Step 4: Use Vertex AI to infer the field_map
# ---------------------------------------------------------------------------
def infer_field_map_via_ai(
    sample_records: list[dict],
    county_name: str,
    state_abbrev: str,
) -> dict:
    """
    Sends sample ArcGIS records to Vertex AI and asks it to produce a field_map.
    Returns: {standard_field_name: actual_arcgis_field_name_or_null}
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ImportError("google-genai not installed. Run: pip install google-genai")

    api_key = os.getenv("VERTEX_API_KEY")
    project_id = os.getenv("VERTEX_PROJECT_ID")
    location = os.getenv("VERTEX_LOCATION", "us-central1")
    model = os.getenv("VERTEX_TEXT_MODEL", "gemini-2.0-flash-exp")

    if api_key:
        # API key auth (Google AI / Vertex Express)
        client = genai.Client(api_key=api_key)
        logging.info("Using API key authentication.")
    elif project_id:
        # Full Vertex AI project auth
        client = genai.Client(vertexai=True, project=project_id, location=location)
        logging.info(f"Using Vertex AI project auth: {project_id} / {location}")
    else:
        raise EnvironmentError(
            "No Vertex AI credentials found. Set VERTEX_API_KEY or VERTEX_PROJECT_ID in .env/.env"
        )

    # Build a clean representation of the schema: field -> sample values (non-null preferred)
    all_fields = list(sample_records[0].keys())
    field_samples = {}
    for field in all_fields:
        values = [r.get(field) for r in sample_records if r.get(field) is not None]
        field_samples[field] = values[0] if values else None

    standard_fields_desc = "\n".join(
        f'  - "{k}": {v}' for k, v in STANDARD_FIELDS.items()
    )

    prompt = f"""You are analyzing an ArcGIS parcel dataset for {county_name}, {state_abbrev}.

Below are the field names from this county's FeatureServer with a sample value for each:

{json.dumps(field_samples, indent=2)}

Your task: Map the above ArcGIS field names to the following standard fields.

Standard fields to map to:
{standard_fields_desc}

Rules:
1. For each standard field, return the EXACT ArcGIS field name from the list above that best matches.
2. If a standard field has NO clear match in the data, return null for that field.
3. Only use field names that actually appear in the data above. Do NOT invent or guess new field names.
4. If there are two candidate fields for the same standard field (e.g., DEEDEDOWNR and OWNNAME both could be owner_name), pick the one that is the primary/deeded owner.
5. Prefer physical/situs address fields (LOC*) over mailing/owner address fields for address, city, zip.

Return ONLY a valid JSON object like this (no explanation, no markdown, just JSON):
{{
  "field_map": {{
    "address": "LOCADDRESS",
    "zip": "LOCZIP",
    ...
  }},
  "notes": "Optional short notes about ambiguous mappings or data quality observations"
}}"""

    system_instruction = (
        "You are a GIS data expert. You map county parcel dataset field names to a standard schema. "
        "Respond only with valid JSON. Do not include markdown code fences."
    )

    config = types.GenerateContentConfig(
        temperature=0.1,  # Low temperature — we want deterministic field mapping
        system_instruction=system_instruction,
    )

    logging.info(f"Calling Vertex AI ({model}) to infer field_map...")

    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[prompt],
                config=config,
            )
            raw_text = response.text or ""

            # gemini-2.5 models can include thinking tokens before the JSON.
            # Extract the JSON block robustly using regex.
            json_match = re.search(r'\{[\s\S]*\}', raw_text)
            if not json_match:
                raise ValueError(f"No JSON object found in model response. Raw text: {raw_text[:300]}")

            result = json.loads(json_match.group())
            logging.info("Vertex AI response received and parsed successfully.")
            if "notes" in result and result["notes"]:
                logging.info(f"AI notes: {result['notes']}")
            return result.get("field_map", {})

        except Exception as e:
            error_str = str(e)
            retryable = (
                "429" in error_str or "RESOURCE_EXHAUSTED" in error_str
                or "503" in error_str or "UNAVAILABLE" in error_str
            )
            if retryable and attempt < max_retries - 1:
                delay = min((5.0 * (2 ** attempt)) + random.uniform(0, 1), 60.0)
                logging.warning(f"Transient error, retrying in {delay:.1f}s... ({attempt+1}/{max_retries})")
                time.sleep(delay)
            else:
                raise


# ---------------------------------------------------------------------------
# Step 5: Validate the field_map against actual field names
# ---------------------------------------------------------------------------
def validate_field_map(field_map: dict, actual_fields: list[str]) -> dict:
    """
    Ensures every value in the field_map is a real field in the ArcGIS response.
    Removes any hallucinated field names with a warning.
    Returns the cleaned field_map.
    """
    actual_set = set(actual_fields)
    validated = {}
    for standard_key, arcgis_field in field_map.items():
        if arcgis_field is None:
            validated[standard_key] = None
            continue
        if arcgis_field in actual_set:
            validated[standard_key] = arcgis_field
        else:
            logging.warning(
                f"Validation: AI suggested '{arcgis_field}' for '{standard_key}' "
                f"but that field does not exist in the data. Setting to null."
            )
            validated[standard_key] = None

    mapped = sum(1 for v in validated.values() if v is not None)
    logging.info(f"Validation complete: {mapped}/{len(validated)} standard fields mapped.")
    return validated


# ---------------------------------------------------------------------------
# Step 6: Read/write county_profiles.json
# ---------------------------------------------------------------------------
def load_county_profiles() -> dict:
    if not os.path.exists(COUNTY_PROFILES_PATH):
        return {}
    with open(COUNTY_PROFILES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_county_profiles(profiles: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(COUNTY_PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2)
    logging.info(f"Saved {len(profiles)} profiles to {COUNTY_PROFILES_PATH}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="AI-assisted county ArcGIS profile onboarding."
    )
    parser.add_argument(
        "--url", required=True,
        help='ArcGIS FeatureServer layer URL, e.g. "https://services5.arcgis.com/.../FeatureServer/0"'
    )
    parser.add_argument(
        "--county", required=True,
        help='County name or partial name, e.g. "Hamilton" or "Hamilton County"'
    )
    parser.add_argument(
        "--state", required=True,
        help="Two-letter state abbreviation, e.g. IN"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the profile without writing to county_profiles.json"
    )
    parser.add_argument(
        "--sample-count", type=int, default=5,
        help="Number of sample records to fetch for schema discovery (default: 5)"
    )
    parser.add_argument(
        "--print-sample", action="store_true",
        help="Print sample records and exit"
    )
    parser.add_argument(
        "--field-map-json",
        help="Provide the field map as a JSON string (bypasses AI)"
    )
    parser.add_argument(
        "--no-verify", action="store_true",
        help="Disable SSL certificate verification"
    )
    parser.add_argument(
        "--layer", type=int,
        help="Explicitly specify the layer index (e.g. 0)"
    )
    args = parser.parse_args()

    # Create a global args for fetch_sample_records to pick up no_verify
    global current_args
    current_args = args

    # 1. Fetch sample records
    target_url = args.url
    if args.layer is not None:
        target_url = args.url.rstrip("/")
        if not target_url.endswith(str(args.layer)):
             target_url += f"/{args.layer}"

    sample_records = fetch_sample_records(target_url, sample_count=args.sample_count)
    actual_fields = list(sample_records[0].keys())

    # 2. Resolve canonical county name + FIPS from geo_index
    county_info = resolve_county(args.county, args.state)

    # 3. Build profile key
    profile_key = build_profile_key(county_info["county"], county_info["state_abbrev"])
    logging.info(f"Profile key: '{profile_key}'")

    if args.print_sample:
        print("\n--- SAMPLE RECORDS ---")
        print(json.dumps(sample_records, indent=2))
        return

    # 4. Field mapping (AI or Manual)
    if args.field_map_json:
        logging.info("Using provided manual field map JSON.")
        raw_field_map = json.loads(args.field_map_json)
    else:
        # 4. AI field mapping
        raw_field_map = infer_field_map_via_ai(sample_records, county_info["county"], county_info["state_abbrev"])

    # 5. Validate field names
    validated_field_map = validate_field_map(raw_field_map, actual_fields)

    # 6. Assemble the full profile
    # Determine the final layer URL used for fetching
    clean_base = args.url.split("?")[0].rstrip("/")
    if clean_base.endswith("/query"):
        clean_base = clean_base[:-6].rstrip("/")
    
    if args.layer is not None:
        final_layer_url = f"{clean_base}/{args.layer}"
    else:
        # If no layer was specified, use the cleaned base (which might have had /0 added in fetch_sample_records)
        # But we want to be consistent. Let's re-derive what fetch_sample_records does.
        final_layer_url = clean_base
        if final_layer_url.endswith("FeatureServer") or final_layer_url.endswith("MapServer"):
            final_layer_url += "/0"

    profile = {
        "county": county_info["county"],
        "county_fips": county_info["county_fips"],
        "state": county_info["state"],
        "state_abbrev": county_info["state_abbrev"],
        "layer_url": final_layer_url,
        "zip_codes": county_info.get("zips", []),
        "field_map": validated_field_map,
    }

    print("\n--- GENERATED PROFILE ---")
    print(json.dumps({profile_key: profile}, indent=2))

    if args.dry_run:
        print("\n[Dry-run] Profile NOT written to county_profiles.json.")
        return

    # 7. Load existing profiles and upsert
    profiles = load_county_profiles()
    if profile_key in profiles:
        logging.warning(f"Profile '{profile_key}' already exists — overwriting.")
    profiles[profile_key] = profile
    save_county_profiles(profiles)

    print(f"\n[DONE] Profile '{profile_key}' written to data/county_profiles.json")
    print("Next: Re-run build_geo_index.py to embed profile_key links into geo_index.json")
    print(f"  python execution/build_geo_index.py --states {county_info['state_abbrev']} --no-cities")


if __name__ == "__main__":
    main()
