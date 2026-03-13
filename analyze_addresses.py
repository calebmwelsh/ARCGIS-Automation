import json
import os

raw_path = '.tmp/arcgis_raw_results.json'

if os.path.exists(raw_path):
    with open(raw_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    features = data.get('features', [])
    total = len(features)
    
    # Check for Situs (Alpine's address field)
    with_address = []
    for f in features:
        addr = f['attributes'].get('Situs', '')
        if addr and addr.strip():
            with_address.append(addr.strip())
            
    print(f"Verified Results:")
    print(f"Total Records Extracted: {total}")
    print(f"Records with Physical Address: {len(with_address)}")
    print("-" * 30)
    print("Sample of Addresses Found:")
    for addr in with_address[:10]:
        print(f" - {addr}")
else:
    print(f"Error: {raw_path} not found.")
