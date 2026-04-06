import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

print("Checking imports...")
try:
    import app
    import ee_auth
    from services import irrigation_service
    from processors import landsat, sentinel2, common, soil_moisture, weather
    print("Imports successful!")
except Exception as e:
    print(f"Import failed: {e}")
    sys.exit(1)

print("Verifying functions...")
try:
    # Check if functions exist
    assert hasattr(irrigation_service, 'get_combined_data')
    assert hasattr(landsat, 'get_landsat_collection')
    assert hasattr(sentinel2, 'get_s2_collection')
    print("Function checks passed!")
except AssertionError as e:
    print(f"Assertion failed: {e}")
    sys.exit(1)

print("Verification complete.")
