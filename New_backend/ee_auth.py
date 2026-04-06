import ee

def initialize_ee():
    """
    Initialize Earth Engine with service account logic.
    """
    try:
        service_account = 'ansh-347@karshizest.iam.gserviceaccount.com'
        key_file = 'karshizest-a7b3c3acdeee.json'
        
        credentials = ee.ServiceAccountCredentials(service_account, key_file)
        ee.Initialize(credentials)
        print("Earth Engine initialized successfully.")
    except Exception as e:
        print(f"Failed to initialize Earth Engine: {e}")
        # Fallback to default if SA fails (for dev/testing without key)
        try:
            ee.Initialize()
            print("Earth Engine initialized with default credentials.")
        except Exception as e2:
            print(f"Final EE initialization failure: {e2}")
            raise e
