import ee
import os
import json
import logging

logger = logging.getLogger('ee_auth')

def initialize_ee():
    """
    Initialize Earth Engine with service account logic.
    Supports GEE_JSON_KEY environment variable for cloud deployment.
    """
    try:
        # 1. Try to load from environment variable first (Best for Render/Heroku)
        gee_json = os.getenv('GEE_JSON_KEY')
        if gee_json:
            gee_json = gee_json.strip() # Remove any accidental spaces/newlines
            print(f"GEE_JSON_KEY found (length: {len(gee_json)})")
            try:
                # The env var can be the JSON string or a path to a file
                if gee_json.startswith('{'):
                    info = json.loads(gee_json)
                    # Use client_email and private_key from the JSON
                    credentials = ee.ServiceAccountCredentials(info['client_email'], key_data=info['private_key'])
                    ee.Initialize(credentials)
                    print("Earth Engine initialized successfully via GEE_JSON_KEY environment variable.")
                    return
                elif os.path.exists(gee_json):
                    # If it's a path, use it
                    with open(gee_json, 'r') as f:
                        info = json.load(f)
                    credentials = ee.ServiceAccountCredentials(info['client_email'], key_data=info['private_key'])
                    ee.Initialize(credentials)
                    print(f"Earth Engine initialized successfully via file path in GEE_JSON_KEY: {gee_json}")
                    return
            except Exception as env_err:
                print(f"Warning: Failed to initialize EE from GEE_JSON_KEY env var: {env_err}")

        # 2. Fallback to local hardcoded file (Dev mode)
        service_account = 'ansh-347@karshizest.iam.gserviceaccount.com'
        key_file = 'karshizest-a7b3c3acdeee.json'
        
        if os.path.exists(key_file):
            credentials = ee.ServiceAccountCredentials(service_account, key_file)
            ee.Initialize(credentials)
            print("Earth Engine initialized successfully via local service account file.")
        else:
            # 3. Final attempt: Default credentials (last resort)
            print("No service account key found. Attempting default initialization...")
            ee.Initialize()
            print("Earth Engine initialized with default credentials.")
            
    except Exception as e:
        print(f"Failed to initialize Earth Engine: {e}")
        raise e

