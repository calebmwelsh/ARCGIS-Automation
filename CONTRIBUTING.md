# Contributing to ArcGIS Data Explorer

Thank you for your interest in improving the ArcGIS Data Explorer! This project relies on accurate county profiles to provide high-quality data extraction.

## 🏗 Architecture Overview

We use a **3-Layer Architecture** to maintain reliability:

1.  **Directive Layer (`directives/`)**: Natural language SOPs and task lists.
2.  **Orchestration Layer**: High-level routing and UI management (e.g., `ui_server.py`).
3.  **Execution Layer (`execution/`)**: Deterministic Python scripts that do the actual work.

## 🛠 How to Help

The primary way to contribute is by **repairing skeleton counties**. A skeleton county is one that exists in `data/county_profiles.json` but has no field mappings.

### 1. Identify a Skeleton
Run the audit script to see the current list:
```bash
python list_skeletons.py
```

### 2. Find an Authoritative ArcGIS REST URL
Search for the county's official GIS portal or tax assessment maps. Look for URLs ending in `/FeatureServer/0` or `/MapServer/0`.

**Tips for finding URLs:**
*   Search: `"County Name" "State" ArcGIS REST parcels`
*   Look for "Hub" or "Open Data" portals.
*   Verify the layer contains attributes like `Owner`, `Address`, or `Parcel ID`.

### 3. Onboard the County
Use the `onboard_county.py` script to automatically discover field mappings using AI:
```bash
python execution/onboard_county.py --url "HTTPS_URL" --county "County Name" --state "ST"
```

### 4. Rebuild the Geo-Index
After adding or updating a profile, you MUST rebuild the geo-index to fix the link between ZIP codes and profile keys:
```bash
python execution/build_geo_index.py --states ST --no-cities
```

### 5. Verify the Repair
Run the check script to ensure the county is no longer a skeleton:
```bash
python list_skeletons.py
```

## 📜 Principles

- **Be Pragmatic**: Use existing tools before writing new ones.
- **Be Reliable**: Ensure scripts handle errors gracefully (Self-anneal).
- **No Placeholders**: Only commit profiles with verified data.
- **Maintain the Index**: Always run `build_geo_index.py` after profile changes.

---

Thank you for making this tool better for everyone!
