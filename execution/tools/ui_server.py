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

current_process = None
server_logs = []
log_lock = threading.Lock()

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

    print(f"Starting ArcGIS UI server at http://localhost:{PORT}")
    with socketserver.TCPServer(("", PORT), ArcGISRequestHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")
            httpd.shutdown()
