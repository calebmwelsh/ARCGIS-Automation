# ArcGIS Data Explorer — Hamilton County, IN

A powerful, user-friendly tool for exploring, filtering, and extracting property data from ArcGIS Feature Services. Currently scoped to **Hamilton County, Indiana**. Additional counties may be added in future branches as the tooling matures.

![ArcGIS Data Explorer UI](assets/ui_screenshot.png)

## 🚀 Key Features

- **Semantic Configuration**: Filter parcels by ZIP Code (multi-select, Hamilton County only) and Year Built without writing a single line of SQL.
- **Web UI Control**: A modern, interactive dashboard to manage your search parameters and view results.
- **Smart Map Integration**: 
    - **ArcGIS Experience Map**: Direct links that use the address search widget to focus on specific properties.
    - **Google Maps**: One-click navigation to the property location.
- **Robust Save Logic**: Real-time feedback with a "Saved!" confirmation when updating environment variables via the UI.
- **JSON Data Extraction**: Saves raw results to a temporary directory for further analysis.

## 🛠 Project Architecture

The project follows a **3-Layer Architecture** to ensure reliability and maintainability:

1.  **Directive Layer**: Instructions and SOPs (found in `directives/`).
2.  **Orchestration Layer**: The `ui_server.py` which routes requests and manages the UI.
3.  **Execution Layer**: Deterministic scripts like `fetch_arcgis_data.py` that handle API interactions.

## 📋 Prerequisites

- **Python 3.8+**
- **pip** (Python package manager)

## 🔧 Setup

1.  **Install Dependencies**:
    ```bash
    pip install requests python-dotenv
    ```

2.  **Configure Environment**:
    The `.env/.env` file is the central source of truth. It is automatically managed by the UI, but can also be manually edited.
    ```env
    ARCGIS_FEATURE_SERVICE_URL=your_arcgis_url_here
    ZIP_CODE=46060
    YEAR_BUILT_CONDITION=any
    YEAR_BUILD_1=
    ```

## 🏃 Getting Started

1.  **Start the UI Server**:
    ```bash
    python execution/tools/ui_server.py
    ```

2.  **Open the Explorer**:
    Navigate to [http://localhost:8003](http://localhost:8003) in your web browser.

3.  **Filter & Extract**:
    - Select one or more **ZIP Codes** from the Hamilton County dropdown and set **Year Built** criteria.
    - Choose the **Data Output Options** (fields to extract).
    - Click **Save Env Variables** to persist settings.
    - Click **Extract Data** to run the fetcher and view results in the table below.

## 📂 Directory Structure

- `.env/`: Configuration storage.
- `.tmp/`: Intermediate data results (e.g., `arcgis_raw_results.json`).
- `execution/`:
    - `fetch_arcgis_data.py`: Core data extraction logic.
    - `tools/`: UI Server and frontend templates.
- `directives/`: SOPs and workflow documentation.

---

## 🗺 County Coverage

| County | State | Status |
|---|---|---|
| Hamilton County | Indiana | ✅ Active |
| *(additional counties)* | Indiana / Other | 🔜 Planned |

> **Note:** This branch is dedicated to Hamilton County, IN, which is entirely within Indiana — no state filter is needed. Future branches or configuration profiles may extend support to neighboring counties (Boone, Madison, Tipton, etc.) or other states as needed.

---
