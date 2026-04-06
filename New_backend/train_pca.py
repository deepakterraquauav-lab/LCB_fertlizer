import ee_auth
import ee

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
import pickle
import os
from datetime import datetime
import warnings
import tempfile

warnings.filterwarnings('ignore')

# Initialize Earth Engine
try:
    ee_auth.initialize_ee()
except Exception as e:
    print(f"EE Init failed: {e}")
    raise

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
        'start_date': '2024-11-01',
        'end_date': '2025-03-31'
    },
    'output_dir': os.path.join(os.path.dirname(__file__), 'models'),
    'scale': 100,  # Coarser scale for faster training data collection
    'sample_size': 1000 # Pixels per image to sample
}

# Create output directory
os.makedirs(CONFIG['output_dir'], exist_ok=True)

# ============================================
# FUNCTIONS
# ============================================

def calculate_indices(image):
    """Calculate NDVI, SAVI, and LAI using 'Red' and 'NIR' bands."""
    # Scale if necessary (S2/Landsat are distinct, handled in collection prep)
    
    nir = image.select('NIR')
    red = image.select('Red')
    
    # NDVI
    ndvi = nir.subtract(red).divide(nir.add(red)).rename('NDVI')
    
    # SAVI (L=0.5)
    savi = nir.subtract(red).multiply(1.5).divide(nir.add(red).add(0.5)).rename('SAVI')
    
    # LAI (simplified empirical)
    lai = ndvi.multiply(3.5).add(0.2).rename('LAI')
    lai = lai.where(lai.lt(0), 0).where(lai.gt(8), 8)
    
    return image.addBands([ndvi, savi, lai])

def get_sentinel2_collection(geometry, start_date, end_date):
    """Get Sentinel-2 collection, harmonized to Red/NIR."""
    
    def prep_s2(img):
        # S2 Scale factor is 10000. 
        # Bands: B4=Red, B8=NIR
        return img.select(['B4', 'B8'], ['Red', 'NIR']) \
                  .divide(10000) \
                  .copyProperties(img, ['system:time_start'])
        
    collection = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
        .filterBounds(geometry) \
        .filterDate(start_date, end_date) \
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30)) \
        .map(lambda img: img.updateMask(img.select('QA60').bitwiseAnd(1<<10).eq(0))) \
        .map(prep_s2)
    
    return collection

def get_landsat_collection(geometry, start_date, end_date):
    """Get Landsat 8/9 collection, harmonized to Red/NIR."""
    
    def prep_landsat(img):
        # Landsat Scale factors: 0.0000275 + -0.2
        # Bands: SR_B4=Red, SR_B5=NIR
        
        optical = img.select(['SR_B4', 'SR_B5'], ['Red', 'NIR']) \
                     .multiply(0.0000275).add(-0.2)
        
        # Cloud masking (QA_PIXEL bit 3 is cloud, bit 4 is cloud shadow)
        qa = img.select('QA_PIXEL')
        mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))
        
        return optical.updateMask(mask).copyProperties(img, ['system:time_start'])

    l8 = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
    l9 = ee.ImageCollection('LANDSAT/LC09/C02/T1_L2')
    
    merged = l8.merge(l9) \
        .filterBounds(geometry) \
        .filterDate(start_date, end_date) \
        .filter(ee.Filter.lt('CLOUD_COVER', 30)) \
        .map(prep_landsat)
        
    return merged

def get_combined_collection(geometry, start_date, end_date):
    """Refined combined collection."""
    s2 = get_sentinel2_collection(geometry, start_date, end_date)
    landsat = get_landsat_collection(geometry, start_date, end_date)
    
    # Add sensor tag for debugging/tracking
    s2 = s2.map(lambda img: img.set('sensor', 'Sentinel-2'))
    landsat = landsat.map(lambda img: img.set('sensor', 'Landsat'))
    
    combined = s2.merge(landsat).sort('system:time_start')
    
    # Calculate indices for everything
    return combined.map(calculate_indices)

def download_sample_data(image, geometry, scale, num_pixels):
    """Download a random sample of pixels from the image."""
    try:
        # Sample pixels using Stratified or Random sampler
        # We use sample() which is efficient for collection random points
        sample = image.select(['NDVI', 'SAVI', 'LAI']).sample(
            region=geometry,
            scale=scale,
            numPixels=num_pixels,
            geometries=False
        )
        
        # Get as list of features
        features = sample.getInfo()['features']
        
        if not features:
            return None
            
        # Extract properties
        data = []
        for f in features:
            props = f['properties']
            if all(k in props for k in ['NDVI', 'SAVI', 'LAI']):
                data.append([props['NDVI'], props['SAVI'], props['LAI']])
                
        return np.array(data)
        
    except Exception as e:
        print(f"  ❌ Sampling error: {e}")
        return None

# ============================================
# MAIN EXECUTION
# ============================================

if __name__ == "__main__":
    print("="*60)
    print("MULTI-SENSOR PCA TRAINING (Sentinel-2 + Landsat)")
    print("="*60)

    # 1. Setup
    coords = CONFIG['study_area']['coordinates']
    lons = [p[0] for p in coords]
    lats = [p[1] for p in coords]
    bbox = [min(lons), min(lats), max(lons), max(lats)]
    study_area = ee.Geometry.Rectangle(bbox)
    
    print(f"\n📍 Study Area: {bbox}")
    print(f"📅 Time Range: {CONFIG['time_range']['start_date']} to {CONFIG['time_range']['end_date']}")

    # 2. Get Data
    print("\n1. Fetching Collections...")
    collection = get_combined_collection(
        study_area, 
        CONFIG['time_range']['start_date'], 
        CONFIG['time_range']['end_date']
    )
    
    image_list = collection.toList(collection.size())
    n_images = image_list.size().getInfo()
    print(f"   Found {n_images} images (S2 + Landsat)")

    if n_images == 0:
        print("❌ No images found!")
        exit()

    # 3. Collect Training Data
    print(f"\n2. collecting Samples ({CONFIG['sample_size']} pixels per image)...")
    
    all_samples = []
    dates_processed = []
    
    for i in range(n_images):
        img_obj = ee.Image(image_list.get(i))
        timestamp = img_obj.get('system:time_start').getInfo()
        date_str = datetime.fromtimestamp(timestamp/1000).strftime('%Y-%m-%d')
        sensor = img_obj.get('sensor').getInfo()
        
        print(f"  Processing {date_str} ({sensor})...", end="\r")
        
        data = download_sample_data(img_obj, study_area, CONFIG['scale'], CONFIG['sample_size'])
        
        if data is not None and len(data) > 100:
            # Clean invalid
            valid_mask = np.all(np.isfinite(data), axis=1)
            data = data[valid_mask]
            
            if len(data) > 100:
                all_samples.append(data)
                dates_processed.append(f"{date_str} ({sensor})")
    
    print(f"\n   ✅ Collected data from {len(dates_processed)} images")
    
    if not all_samples:
        print("❌ No valid data collected!")
        exit()
        
    # Stack all data
    X = np.vstack(all_samples)
    print(f"   Total training pixels: {X.shape[0]}")

    # 4. Train Multi-Date PCA
    print("\n3. Training Multi-Date PCA...")
    
    # Standardize
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # PCA
    pca = PCA(n_components=2)
    pca.fit(X_scaled)
    
    print(f"   ✅ Training Complete")
    print(f"     Explained Variance: {pca.explained_variance_ratio_}")
    print(f"     PC1 Loadings (NDVI, SAVI, LAI): {pca.components_[0]}")

    # Calculate Global Min/Max for PC1 to ensure consistent scaling
    X_pca = pca.transform(X_scaled)
    pc1_scores = X_pca[:, 0]
    
    # We add a small buffer (1%) to min/max to avoid boundary issues
    global_min = np.min(pc1_scores)
    global_max = np.max(pc1_scores)
    
    print(f"     Global PC1 Range: {global_min:.4f} to {global_max:.4f}")

    # 5. Save Model
    success_model = {
        'scaler': scaler,
        'pca': pca,
        'feature_names': ['NDVI', 'SAVI', 'LAI'],
        'n_images': len(dates_processed),
        'n_pixels': X.shape[0],
        'training_dates': dates_processed,
        'pc1_min': global_min,
        'pc1_max': global_max
    }
    
    model_path = os.path.join(CONFIG['output_dir'], 'pca_multidate.pkl')
    with open(model_path, 'wb') as f:
        pickle.dump(success_model, f)
        
    print(f"\n💾 Model saved to: {model_path}")
