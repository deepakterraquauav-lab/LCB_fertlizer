import ee
import requests
import numpy as np
import pickle
import os
import warnings
from datetime import datetime
import ee_auth

# Import data preparation functions from train_pca
try:
    from train_pca import get_combined_collection
except ImportError:
    # If running from different directory, simplified fallback
    sys.path.append(os.path.dirname(__file__))
    from train_pca import get_combined_collection

warnings.filterwarnings('ignore')

# Initialize Earth Engine
try:
    ee_auth.initialize_ee()
except Exception:
    print("Fallback to default auth")
    ee.Authenticate()
    ee.Initialize()

# ============================================
# CONFIGURATION
# ============================================

CONFIG = {
    'study_area': {
        'name': 'Punjab',
        'coordinates': [[74.75475127597738, 30.56461953089272],
          [74.75475127597738, 30.459913582830946],
          [74.9315624942391, 30.459913582830946],
          [74.9315624942391, 30.56461953089272]], 
        'crs': 'EPSG:4326'
    },
    'time_range': {
        'start_date': '2025-01-01',  # Generate for Jan 2025 onwards
        'end_date': '2025-03-31'
    },
    'models_dir': os.path.join(os.path.dirname(__file__), 'models'),
    'output_dir': os.path.join(os.path.dirname(__file__), 'rasters'),
    'scale': 10  # Sentinel-2 resolution
}

os.makedirs(CONFIG['output_dir'], exist_ok=True)

# ============================================
# FUNCTIONS
# ============================================

def load_pca_model(model_path):
    """Load the trained PCA model and extract params for EE."""
    with open(model_path, 'rb') as f:
        model_data = pickle.load(f)
        
    scaler = model_data['scaler']
    pca = model_data['pca']
    
    # Extract parameters
    # StandardScaler params
    means = scaler.mean_
    scales = scaler.scale_
    
    # PCA params (components_ is [n_components, n_features])
    # We only want PC1 (index 0)
    pc1_loadings = pca.components_[0]
    
    params = {
        'mean_ndvi': means[0],
        'mean_savi': means[1],
        'mean_lai': means[2],
        'scale_ndvi': scales[0],
        'scale_savi': scales[1],
        'scale_lai': scales[2],
        'load_ndvi': pc1_loadings[0],
        'load_savi': pc1_loadings[1],
        'load_lai': pc1_loadings[2],
    }
    
    print("Loaded PCA Model Parameters:")
    for k, v in params.items():
        print(f"  {k}: {v:.4f}")
        
    return params

def apply_pca_ee(image, params):
    """Apply PCA transformation using EE expressions (Server-side)."""
    
    # 1. Standardize: (Val - Mean) / Scale
    # 2. Transform: Sum(StdVal * Loading)
    
    # Formula for PC1:
    # PC1 = ((NDVI - mean_ndvi)/scale_ndvi * load_ndvi) + 
    #       ((SAVI - mean_savi)/scale_savi * load_savi) + 
    #       ((LAI - mean_lai)/scale_lai * load_lai)
    
    expression = (
        "((b('NDVI') - mean_ndvi) / scale_ndvi * load_ndvi) + "
        "((b('SAVI') - mean_savi) / scale_savi * load_savi) + "
        "((b('LAI') - mean_lai) / scale_lai * load_lai)"
    )
    
    pc1 = image.expression(expression, {
        'NDVI': image.select('NDVI'),
        'SAVI': image.select('SAVI'),
        'LAI': image.select('LAI'),
        **params
    }).rename('PC1')
    
    return image.addBands(pc1)

# ============================================
# MAIN
# ============================================

if __name__ == "__main__":
    print("="*60)
    print("GENERATING PCA RASTERS (SERVER-SIDE)")
    print("="*60)
    
    # 1. Load Model
    model_path = os.path.join(CONFIG['models_dir'], 'pca_multidate.pkl')
    if not os.path.exists(model_path):
        print(f"❌ Model not found: {model_path}")
        print("   Run train_pca.py first.")
        exit()
        
    params = load_pca_model(model_path)
    
    # 2. Setup EE
    coords = CONFIG['study_area']['coordinates']
    lons = [p[0] for p in coords]
    lats = [p[1] for p in coords]
    bbox = [min(lons), min(lats), max(lons), max(lats)]
    study_area = ee.Geometry.Rectangle(bbox)
    
    # 3. Get Data
    print(f"\nFetching imagery from {CONFIG['time_range']['start_date']}...")
    collection = get_combined_collection(
        study_area, 
        CONFIG['time_range']['start_date'], 
        CONFIG['time_range']['end_date']
    )
    
    # 4. Process and Export
    image_list = collection.toList(collection.size())
    n_images = image_list.size().getInfo()
    print(f"Found {n_images} images to process.")
    
    for i in range(n_images):
        img = ee.Image(image_list.get(i))
        
        # Get metadata
        timestamp = img.get('system:time_start').getInfo()
        date_str = datetime.fromtimestamp(timestamp/1000).strftime('%Y-%m-%d')
        sensor = img.get('sensor').getInfo()
        
        filename = f"pca_{date_str}_{sensor}.tif"
        filepath = os.path.join(CONFIG['output_dir'], filename)
        
        if os.path.exists(filepath):
            print(f"  Skipping {date_str} (already exists)")
            continue
            
        print(f"  Processing {date_str} ({sensor})...")
        
        # Apply PCA
        pca_img = apply_pca_ee(img, params)
        
        # Export PC1 band
        try:
            url = pca_img.select('PC1').getDownloadURL({
                'scale': CONFIG['scale'],
                'region': study_area,
                'format': 'GEO_TIFF'
            })
            
            print(f"  Downloading from EE...")
            response = requests.get(url)
            
            if response.status_code == 200:
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                print(f"  ✅ Exported: {filename}")
            else:
                print(f"  ❌ Download failed: {response.status_code}")
                
        except Exception as e:
            print(f"  ❌ Export failed: {e}")

    print("\n✅ Batch generation complete!")
