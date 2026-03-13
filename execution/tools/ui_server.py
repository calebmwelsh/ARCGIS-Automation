import http.server
import json
import os
import socketserver
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

# Configuration
PORT = 8003  # Use a different port than NYC ingest
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(BASE_DIR))
ENV_PATH = os.path.join(PROJECT_ROOT, '.env', '.env')
FETCH_SCRIPT_PATH = os.path.join(PROJECT_ROOT, 'execution', 'fetch_arcgis_data.py')
RESULTS_JSON_PATH = os.path.join(PROJECT_ROOT, '.tmp', 'arcgis_raw_results.json')
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
GEO_INDEX_PATH = os.path.join(PROJECT_ROOT, 'data', 'geo_index.json')

current_process = None
server_logs = []
log_lock = threading.Lock()
geo_index = {}  # Loaded at startup from geo_index.json

def load_geo_index():
    """Load geo_index.json into memory at server startup."""
    global geo_index
    if not os.path.exists(GEO_INDEX_PATH):
        print(f"[Geo] geo_index.json not found at {GEO_INDEX_PATH}.")
        print("[Geo] Run: python execution/build_geo_index.py --states IN GA ...")
        return
    try:
        with open(GEO_INDEX_PATH, 'r', encoding='utf-8') as f:
            geo_index = json.load(f)
        meta = geo_index.get('meta', {})
        print(f"[Geo] Index loaded: {meta.get('zip_count', 0):,} ZIPs | "
              f"{meta.get('county_count', 0):,} counties | "
              f"{meta.get('state_count', 0):,} states")
    except Exception as e:
        print(f"[Geo] Failed to load geo_index.json: {e}")

def read_process_output(process):
    global server_logs
    try:
        for line in iter(process.stdout.readline, ''):
            if not line:
                break
            with log_lock:
                server_logs.append(line.strip())
                if len(server_logs) > 2000:
                    server_logs.pop(0)
    except Exception as e:
        with log_lock:
            server_logs.append(f"[Server Error]: {e}")
    finally:
        process.stdout.close()

class ArcGISRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urlparse(self.path)
        
        if parsed_url.path == '/' or parsed_url.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            with open(os.path.join(TEMPLATE_DIR, 'index.html'), 'rb') as f:
                self.wfile.write(f.read())
            return
            
        if parsed_url.path == '/api/config':
            self.handle_get_config()
            return
            
        if parsed_url.path == '/api/status':
            self.handle_get_status()
            return
            
        if parsed_url.path == '/api/logs':
            self.handle_get_logs()
            return

        if parsed_url.path == '/api/results':
            self.handle_get_results()
            return

        # Geo index endpoints
        if parsed_url.path == '/api/geo/zip':
            self.handle_geo_zip(parse_qs(parsed_url.query))
            return

        if parsed_url.path == '/api/geo/county':
            self.handle_geo_county(parse_qs(parsed_url.query))
            return

        if parsed_url.path == '/api/geo/state':
            self.handle_geo_state(parse_qs(parsed_url.query))
            return

        if parsed_url.path == '/api/geo/city':
            self.handle_geo_city(parse_qs(parsed_url.query))
            return

        if parsed_url.path == '/api/geo/index_meta':
            self.handle_geo_meta()
            return

        if parsed_url.path == '/api/geo/search':
            self.handle_geo_search(parse_qs(parsed_url.query))
            return

        return super().do_GET()

    def do_POST(self):
        parsed_url = urlparse(self.path)
        
        if parsed_url.path == '/api/save':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            self.handle_save_config(data)
            return
 
        if parsed_url.path == '/api/run':
            self.handle_run_fetch()
            return

        self.send_error(404, "Not Found")

    def handle_get_config(self):
        current_env = {}
        if os.path.exists(ENV_PATH):
            try:
                with open(ENV_PATH, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'): continue
                        if '=' in line:
                            key, val = line.split('=', 1)
                            current_env[key.strip()] = val.strip()
            except Exception as e:
                print(f"Error reading env file: {e}")

        response = {
            "current_env": {
                "ARCGIS_FEATURE_SERVICE_URL": current_env.get("ARCGIS_FEATURE_SERVICE_URL", ""),
                "SEARCH_SCOPE_TYPE": current_env.get("SEARCH_SCOPE_TYPE", "zip"),
                "SEARCH_SCOPE_VALUE": current_env.get("SEARCH_SCOPE_VALUE", ""),
                "ZIP_CODE": current_env.get("ZIP_CODE", ""),
                "YEAR_BUILT_CONDITION": current_env.get("YEAR_BUILT_CONDITION", "any"),
                "YEAR_BUILD_1": current_env.get("YEAR_BUILD_1", ""),
                "YEAR_BUILD_2": current_env.get("YEAR_BUILD_2", ""),
                "DATA_OUTPUT_OPTIONS": current_env.get("DATA_OUTPUT_OPTIONS", "*"),
                "RESULT_RECORD_COUNT": current_env.get("RESULT_RECORD_COUNT", "50")
            }
        }
        
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response).encode('utf-8'))

    def _save_config_internal(self, data):
        lines = []
        if os.path.exists(ENV_PATH):
            try:
                with open(ENV_PATH, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            except Exception as e:
                print(f"[Error] Could not read .env for update: {e}")
        
        # New Semantic Keys
        updates = {
            "ARCGIS_FEATURE_SERVICE_URL": data.get("ARCGIS_FEATURE_SERVICE_URL", ""),
            "SEARCH_SCOPE_TYPE": data.get("SEARCH_SCOPE_TYPE", "zip"),
            "SEARCH_SCOPE_VALUE": data.get("SEARCH_SCOPE_VALUE", ""),
            "ZIP_CODE": data.get("ZIP_CODE", ""),
            "YEAR_BUILT_CONDITION": data.get("YEAR_BUILT_CONDITION", "any"),
            "YEAR_BUILD_1": str(data.get("YEAR_BUILD_1", "")),
            "YEAR_BUILD_2": str(data.get("YEAR_BUILD_2", "")),
            "DATA_OUTPUT_OPTIONS": data.get("DATA_OUTPUT_OPTIONS", "*"),
            "RESULT_RECORD_COUNT": str(data.get("RESULT_RECORD_COUNT", "50"))
        }

        # Technical keys to remove automatically (keep config clean)
        legacy_keys = {
            "ARCGIS_WHERE_CLAUSE", "ARCGIS_OUT_FIELDS", "ARCGIS_RESULT_RECORD_COUNT",
            "ARCGIS_RESULT_OFFSET", "ARCGIS_ORDER_BY_FIELDS", "ARCGIS_RETURN_GEOMETRY",
            "ARCGIS_GEOMETRY", "ARCGIS_GEOMETRY_TYPE", "ARCGIS_SPATIAL_REL"
        }
        
        new_lines = []
        processed_keys = set()
        
        for line in lines:
            stripped = line.strip()
            # Preserve comments and empty lines
            if not stripped or stripped.startswith('#'):
                new_lines.append(line)
                continue
            
            if '=' in stripped:
                parts = stripped.split('=', 1)
                key = parts[0].strip()
                
                # Filter out legacy technical keys
                if key in legacy_keys:
                    continue
                    
                if key in updates:
                    new_lines.append(f"{key}={updates[key]}\n")
                    processed_keys.add(key)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        # Append any new keys that weren't already in the file
        for key, val in updates.items():
            if key not in processed_keys:
                new_lines.append(f"{key}={val}\n")
                
        try:
            with open(ENV_PATH, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            
            # Log successful save for Debug Logs
            with log_lock:
                server_logs.append(f"[Config] Saved updated environment variables: {list(updates.keys())}")
            return True, "saved"
        except Exception as e:
            print(f"[Error] Failed to write .env: {e}")
            return False, str(e)

    def handle_save_config(self, data):
        success, msg = self._save_config_internal(data)
        if success:
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "saved"}).encode('utf-8'))
        else:
            self.send_error(500, f"Error writing .env: {msg}")

    def handle_run_fetch(self):
        global current_process, server_logs
        if current_process and current_process.poll() is None:
            self.send_response(409)
            self.end_headers()
            self.wfile.write(json.dumps({"status": "already_running"}).encode('utf-8'))
            return

        with log_lock:
            server_logs = []

        try:
            cmd = [sys.executable, '-u', FETCH_SCRIPT_PATH]
                
            current_process = subprocess.Popen(
                cmd,
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding='utf-8',
                errors='replace'
            )
            
            t = threading.Thread(target=read_process_output, args=(current_process,), daemon=True)
            t.start()
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "started"}).encode('utf-8'))
        except Exception as e:
            self.send_error(500, str(e))

    def handle_get_status(self):
        global current_process
        status = "idle"
        
        if current_process:
            ret = current_process.poll()
            if ret is None:
                status = "running"
            else:
                status = "completed"
        
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"status": status}).encode('utf-8'))

    def handle_get_logs(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        with log_lock:
            self.wfile.write(json.dumps({"logs": server_logs}).encode('utf-8'))

    # ------------------------------------------------------------------
    # Geo Index Handlers
    # ------------------------------------------------------------------

    def _send_json(self, data, status=200):
        """Helper: send a JSON response."""
        encoded = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(encoded)

    def _geo_not_found(self, message):
        self._send_json({'error': message, 'result': None}, status=404)

    def handle_geo_zip(self, params):
        """
        GET /api/geo/zip?q=46060
        Returns: {zip, cities, county, county_fips, state, state_abbrev, profile_key?}
        """
        zip_code = (params.get('q', [''])[0]).strip().zfill(5)
        if not zip_code or zip_code == '00000':
            return self._send_json({'error': 'Missing ?q=ZIP_CODE'}, status=400)

        by_zip = geo_index.get('by_zip', {})
        result = by_zip.get(zip_code)
        if result:
            return self._send_json({'result': result})

        # Fallback: try live Zippopotam lookup if not in index
        try:
            import urllib.request
            url = f'https://api.zippopotam.us/us/{zip_code}'
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
            places = data.get('places', [])
            cities = list({p.get('place name', '') for p in places})
            state_abbrev = places[0].get('state abbreviation', '') if places else ''
            state_name = places[0].get('state', '') if places else ''
            fallback = {
                'zip': zip_code,
                'cities': cities,
                'county': None,
                'county_fips': None,
                'state': state_name,
                'state_abbrev': state_abbrev,
                '_source': 'live_fallback'
            }
            return self._send_json({'result': fallback})
        except Exception:
            return self._geo_not_found(f'ZIP code {zip_code} not found in index or live lookup.')

    def handle_geo_county(self, params):
        """
        GET /api/geo/county?fips=18057
        GET /api/geo/county?name=Hamilton&state=IN
        Returns: {county, county_fips, state, state_abbrev, zips, cities, profile_key?}
        """
        by_county = geo_index.get('by_county', {})
        fips = params.get('fips', [''])[0].strip().zfill(5)
        name = params.get('name', [''])[0].strip().lower()
        state = params.get('state', [''])[0].strip().upper()

        if fips and fips != '00000':
            result = by_county.get(fips)
            if result:
                return self._send_json({'result': result})
            return self._geo_not_found(f'County FIPS {fips} not found.')

        if name:
            # Search by name + state
            for fips_key, county_data in by_county.items():
                county_lower = county_data.get('county', '').lower()
                county_state = county_data.get('state_abbrev', '').upper()
                if name in county_lower and (not state or state == county_state):
                    return self._send_json({'result': county_data})
            return self._geo_not_found(f'County "{name}" in state "{state}" not found.')

        self._send_json({'error': 'Provide ?fips=XXXXX or ?name=Name&state=XX'}, status=400)

    def handle_geo_state(self, params):
        """
        GET /api/geo/state?abbrev=IN
        Returns: {state, state_abbrev, counties: {fips: name, ...}}
        """
        abbrev = params.get('abbrev', [''])[0].strip().upper()
        if not abbrev:
            # Return list of all states
            by_state = geo_index.get('by_state', {})
            summary = {k: {'state': v['state'], 'county_count': len(v.get('counties', {}))} for k, v in by_state.items()}
            return self._send_json({'result': summary})

        by_state = geo_index.get('by_state', {})
        result = by_state.get(abbrev)
        if result:
            return self._send_json({'result': result})
        self._geo_not_found(f'State abbreviation "{abbrev}" not found.')

    def handle_geo_city(self, params):
        """
        GET /api/geo/city?q=Noblesville&state=IN
        Returns: {city, state_abbrev, state, zips}
        """
        city = params.get('q', [''])[0].strip().lower()
        state = params.get('state', [''])[0].strip().upper()
        if not city:
            return self._send_json({'error': 'Missing ?q=CITY_NAME'}, status=400)

        city_key = f'{city}|{state}' if state else None
        by_city = geo_index.get('by_city', {})

        if city_key and city_key in by_city:
            return self._send_json({'result': by_city[city_key]})

        # Fuzzy fallback: partial name match
        matches = []
        for key, data in by_city.items():
            if city in key.split('|')[0] and (not state or data.get('state_abbrev') == state):
                matches.append(data)
        if matches:
            return self._send_json({'result': matches[0] if len(matches) == 1 else matches})
        self._geo_not_found(f'City "{city}" in state "{state}" not found.')

    def handle_geo_search(self, params):
        query = params.get('q', [''])[0].strip().lower()
        if not query or len(query) < 2:
            return self._send_json({'results': []})
            
        results = []
        # Search ZIPs
        for zip_code, data in geo_index.get('by_zip', {}).items():
            if query in zip_code:
                results.append({
                    'type': 'zip',
                    'label': f"Zip {zip_code} - {data['county']}, {data['state_abbrev']}",
                    'value': zip_code
                })
                if len(results) > 5: break
                
        # Search Counties
        for fips, data in geo_index.get('by_county', {}).items():
            county_name = data.get('county', '')
            if query in county_name.lower() or query in fips:
                results.append({
                    'type': 'county',
                    'label': f"{county_name}, {data['state_abbrev']}",
                    'value': fips
                })
                if len(results) > 10: break
                
        # Search Cities
        for city_key, data in geo_index.get('by_city', {}).items():
            city_name = data.get('city', '')
            if query in city_name.lower():
                results.append({
                    'type': 'city',
                    'label': f"{city_name}, {data['state_abbrev']}",
                    'value': city_key
                })
                if len(results) > 15: break
                
        return self._send_json({'results': results[:15]})

    def handle_geo_meta(self):
        """GET /api/geo/index_meta — returns build metadata for the geo index."""
        meta = geo_index.get('meta', {'error': 'geo_index not loaded'})
        self._send_json({'result': meta})

    def handle_get_results(self):
        # Reads the latest json dump from arcgis fetch
        if not os.path.exists(RESULTS_JSON_PATH):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"features": []}).encode('utf-8'))
            return

        try:
            with open(RESULTS_JSON_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            features = data.get('features', [])
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"features": features}).encode('utf-8'))
        except Exception as e:
            self.send_error(500, str(e))

if __name__ == "__main__":
    if not os.path.exists(TEMPLATE_DIR):
        os.makedirs(TEMPLATE_DIR, exist_ok=True)

    # Load geo index at startup (before serving)
    load_geo_index()

    print(f"Starting ArcGIS UI server at http://localhost:{PORT}")
    with socketserver.TCPServer(("", PORT), ArcGISRequestHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")
            httpd.shutdown()
