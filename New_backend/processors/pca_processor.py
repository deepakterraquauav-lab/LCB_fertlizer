import ee
import ee_auth
import numpy as np
import pickle
import os
import logging

logger = logging.getLogger(__name__)

class PCAProcessor:
    def __init__(self, models_dir):
        self.models_dir = models_dir
        self.model_params = None
        self.model_path = os.path.join(models_dir, 'pca_multidate.pkl')
        
    def load_model(self):
        """Load the trained PCA model and extract params for EE (Cached)."""
        if self.model_params:
            return self.model_params
            
        if not os.path.exists(self.model_path):
            logger.error(f"PCA Model not found at {self.model_path}")
            return None
            
        try:
            with open(self.model_path, 'rb') as f:
                model_data = pickle.load(f)
                
            scaler = model_data['scaler']
            pca = model_data['pca']
            
            # Extract parameters
            means = scaler.mean_
            scales = scaler.scale_
            pc1_loadings = pca.components_[0]
            
            # Get global min/max for scaling (default to estimated if not present)
            pc1_min = model_data.get('pc1_min', -3.0)
            pc1_max = model_data.get('pc1_max', 5.0)
            
            self.model_params = {
                'mean_ndvi': means[0],
                'mean_savi': means[1],
                'mean_lai': means[2],
                'scale_ndvi': scales[0],
                'scale_savi': scales[1],
                'scale_lai': scales[2],
                'load_ndvi': pc1_loadings[0],
                'load_savi': pc1_loadings[1],
                'load_lai': pc1_loadings[2],
                'pc1_min': pc1_min,
                'pc1_max': pc1_max
            }
            logger.info(f"PCA Model loaded. PC1 Range: {pc1_min:.2f} to {pc1_max:.2f}")
            return self.model_params
            
        except Exception as e:
            logger.error(f"Failed to load PCA model: {e}")
            return None

    def train_dynamic_model(self, aoi, date_obj):
        """
        Train a PCA model dynamically for the specific AOI and Season.
        Caches the model to avoid re-training on every request.
        """
        try:
            # 1. Determine Season / Cache Key
            # We use a 6-month window centered on the date to capture seasonal variance
            # effectively creating a "Season" model
            center_date = ee.Date(date_obj)
            start_date = center_date.advance(-3, 'month')
            end_date = center_date.advance(3, 'month')
            
            # Create a simple hash for AOI (centroid) + Season (Year-Month)
            # This is a bit rough but works for caching
            centroid = aoi.centroid(1).coordinates().getInfo()
            lat_lon_str = f"{centroid[1]:.4f}_{centroid[0]:.4f}"
            season_str = f"{center_date.format('YYYY_MM').getInfo()}"
            
            cache_key = f"pca_dynamic_{lat_lon_str}_{season_str}.pkl"
            cache_path = os.path.join(self.models_dir, 'dynamic', cache_key)
            
            os.makedirs(os.path.join(self.models_dir, 'dynamic'), exist_ok=True)
            
            # 2. Check Cache
            if os.path.exists(cache_path):
                # logger.info(f"⚡ Using cached dynamic PCA model: {cache_key}")
                with open(cache_path, 'rb') as f:
                    model_data = pickle.load(f)
                return self._extract_params(model_data)
                
            # 3. Train New Model
            logger.info(f"🧠 Training NEW dynamic PCA model for {lat_lon_str} {season_str}...")
            
            # Fetch Data (Sentinel-2 + Landsat)
            # Re-using logic similar to train_pca.py but streamlined for runtime
            from . import landsat, sentinel2, common
            
            # Get Collections
            l8 = landsat.get_landsat_collection(aoi, start_date, end_date)
            s2 = sentinel2.get_s2_collection(aoi, start_date, end_date)
            
            # Helper to harmonize and add indices
            def prep_image(img):
                # We need simple Red/NIR for indices
                # S2: B4, B8. L8: SR_B4, SR_B5.
                # All cols should already have 'NDVI' from get_*_collection if we look closely at logic?
                # Actually, our processors return images with specific bands.
                # Let's rely on standard band names if possible or recalculate.
                
                # We need to ensure we have NDVI, SAVI, LAI
                # Processors return valid images with these bands
                return img
                
            # We actually need raw-ish collections to sample from.
            # But our processor functions `process_*_image` do a lot of heavy lifting (cloud mask, etc).
            # Let's use the processor functions to get "analysis ready" pixels.
            
            # Sample from a few images (max 10 to save time)
            # Sort by cloud cover? Or just take a spread?
            # Taking a spread over time is better for variance.
            
            merged_col = l8.merge(s2).sort('system:time_start')
            count = merged_col.size().getInfo()
            
            if count == 0:
                 logger.warning("No imagery found for PCA training. Using default model.")
                 return self.load_model() # Fallback to static
                 
            # Take up to 5 images evenly spaced
            # Using lists is slow in EE, but for 5 items it's fine.
            img_list = merged_col.toList(count)
            step = max(1, count // 5)
            indices = list(range(0, count, step))[:5]
            
            samples = []
            
            # Import sklearn here to avoid top-level dependency if not used
            from sklearn.decomposition import PCA
            from sklearn.preprocessing import StandardScaler
            
            for i in indices:
                img = ee.Image(img_list.get(i))
                
                # We must recalculate indices cleanly here as raw collection might not have them
                # or they might be named differently.
                # Let's use a simplified calculation for speed
                
                # Check sensor
                # This is tricky without metadata. 
                # Let's try to deduce from band names or just use our robust processors?
                # Using processors is safest but slower.
                # FAST PATH:
                # We know get_landsat_collection returns one_per_day dicts, not computed images?
                # detailed logic:
                # landsat.get_landsat_collection returns images with 'selected_date'. 
                # They are raw (or close to). 
                # landsat.process_landsat_image computes NDVI/SAVI/LAI.
                
                # We need to distinguish L8 vs S2 to call right processor
                # But merged collection mixes them.
                # Try to check for 'SR_B4' (Landsat) vs 'B4' (Sentinel)
                bn = img.bandNames()
                is_landsat = ee.Algorithms.If(bn.contains('SR_B4'), True, False)
                
                # We can't easily mix server-side logic (Algorithms.If) with client-side sampling loop cleanly
                # unless we force evaluation.
                
                # Actual robust approach:
                # Just calculate NDVI/SAVI/LAI using a universal expression if bands are renamed?
                # No, bands differ.
                
                # Let's use the `process_` functions which standardize output to NDVI, SAVI, LAI
                processed = ee.Algorithms.If(
                    is_landsat,
                    landsat.process_landsat_image(img, aoi, ee.Image.constant(0.1), ee.Image.constant(0.8), mask_agri=False),
                    sentinel2.process_s2_image(img, aoi, ee.Image.constant(0.1), ee.Image.constant(0.8), mask_agri=False)
                )
                processed = ee.Image(processed)
                
                # Sample
                # Unmask to avoid issues? No, we want valid pixels.
                
                # Use a small scale (e.g. 100m) for speed
                try:
                    # Stratified sample or random sample?
                    # region sample is best
                    data = processed.select(['NDVI', 'SAVI', 'LAI']).sample(
                        region=aoi,
                        scale=100, # coarse scale
                        numPixels=200, # small sample per image
                        geometries=False
                    ).getInfo()
                    
                    if 'features' in data:
                        for f in data['features']:
                            p = f['properties']
                            if all(k in p for k in ['NDVI', 'SAVI', 'LAI']):
                                samples.append([p['NDVI'], p['SAVI'], p['LAI']])
                except Exception as e:
                    logger.warning(f"Failed to sample image {i}: {e}")
                    
            if len(samples) < 50:
                logger.warning("Not enough samples for Dynamic PCA. Fallback to static.")
                return self.load_model()
                
            # Train
            X = np.array(samples)
            # Filter NaNs
            X = X[~np.isnan(X).any(axis=1)]
            
            if len(X) < 50:
                 return self.load_model()
            
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
            
            pca = PCA(n_components=1) # We only strictly need PC1
            pca.fit(X_scaled)
            
            # Global Min/Max from this specific seasonal data
            X_pca = pca.transform(X_scaled)
            pc1_min = float(np.min(X_pca))
            pc1_max = float(np.max(X_pca))
            
            # Buffer
            pc1_min -= 0.1
            pc1_max += 0.1
            
            model_data = {
                'scaler': scaler,
                'pca': pca,
                'pc1_min': pc1_min,
                'pc1_max': pc1_max
            }
            
            # Cache
            with open(cache_path, 'wb') as f:
                pickle.dump(model_data, f)
                
            logger.info(f"✅ Dynamic Model Trained & Cached! Range: {pc1_min:.2f} to {pc1_max:.2f}")
            return self._extract_params(model_data)

        except Exception as e:
            logger.error(f"Dynamic Training Failed: {e}. using static fallback.")
            import traceback
            logger.error(traceback.format_exc())
            return self.load_model()

    def _extract_params(self, model_data):
        """Helper to extract EE-ready params from model dict"""
        scaler = model_data['scaler']
        pca = model_data['pca']
        
        means = scaler.mean_
        scales = scaler.scale_
        pc1_loadings = pca.components_[0]
        
        return {
            'mean_ndvi': means[0],
            'mean_savi': means[1],
            'mean_lai': means[2],
            'scale_ndvi': scales[0],
            'scale_savi': scales[1],
            'scale_lai': scales[2],
            'load_ndvi': pc1_loadings[0],
            'load_savi': pc1_loadings[1],
            'load_lai': pc1_loadings[2],
            'pc1_min': model_data.get('pc1_min', -3.0),
            'pc1_max': model_data.get('pc1_max', 5.0)
        }

    def apply_pca(self, image, params=None):
        """Apply PCA transformation. dynamically uses provided params or falls back to load_opt."""
        if params is None:
            params = self.load_model()
            
        if not params:
            return image.addBands(ee.Image.constant(0).rename('PC1'))
        
        # Formula for PC1: (Val - Mean) / Scale * Loading
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
        
        # Apply Global Min-Max Scaling (Dynamic or Static)
        min_val = ee.Number(params['pc1_min'])
        max_val = ee.Number(params['pc1_max'])
        
        pc1_scaled = pc1.subtract(min_val).divide(max_val.subtract(min_val)).clamp(0, 1)
        
        return image.addBands(pc1_scaled)

# Singleton instance
MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models')
processor = PCAProcessor(MODELS_DIR)

def get_pca_image(image):
    return processor.apply_pca(image)
