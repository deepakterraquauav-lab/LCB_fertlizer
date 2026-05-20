import ee
import logging

# Initialize Logger
logger = logging.getLogger('smart_irrigation_logger')

def get_common_indices(img, nir, red, blue, ndvi_min_img, ndvi_max_img):
    """
    Calculate common indices: SAVI, EVI, LAI, FV, Emissivity.
    Assuming NDVI is already in img.
    """
    ndvi = img.select('NDVI')
    
    # SAVI
    # SAVI (Standard Soil Adjusted Vegetation Index with L=0.5)
    # Dynamic L calculation was suppressing values too much for moderate vegetation
    # Standard L=0.5 is robust for most agricultural applications
    l_factor = 0.5
    savi = nir.subtract(red).divide(nir.add(red).add(l_factor)).multiply(1 + l_factor).rename('SAVI')
    
    # EVI
    evi = img.expression(
        '2.5 * (NIR - RED) / (NIR + 6*RED - 7.5*BLUE + 1)',
        {'NIR': nir, 'RED': red, 'BLUE': blue}
    ).rename('EVI')
    
    # LAI
    lai = evi.expression('3.618 * EVI - 0.118', {'EVI': evi}).rename('LAI')
    
    # Fractional vegetation
    fv = ndvi.subtract(ndvi_min_img).divide(ndvi_max_img.subtract(ndvi_min_img)).clamp(0, 1).pow(2).rename('FV')
    
    # Emissivity
    em = fv.multiply(0.004).add(0.986).rename('Emissivity')

    # Crop coefficient (Kc) - Generic formula used in original code
    # Formula: Kc = 1.797 * SAVI - 0.287
    # FIX: Clamp to min 0.15 for bare soil to avoid zero-values breaking downstream ETc/CWR calculations
    kc = savi.multiply(1.796634562654909).add(-0.2869936095897908).max(0.15).rename('Kc')
    
    return img.addBands([savi, evi, lai, fv, em, kc])

def calculate_cwsi(lst, ndvi, ndvi_min_img, ndvi_max_img, aoi, default_t_cold=300, default_t_hot=320):
    """
    Calculate CWSI using LST and NDVI-based dynamic thresholds.
    
    Fallback Strategy:
      1. Seasonal Mask (NDVI > seasonal_max / NDVI < seasonal_min)
      2. Dynamic Mask (NDVI > 80th percentile / NDVI < 20th percentile of THIS image)
      3. Direct LST percentiles (5th / 95th)
      4. Hardcoded defaults (only if image is completely empty)
    """
    # --- Step 1: Seasonal Masks (Primary) ---
    cold_mask = ndvi.gt(ndvi_max_img)
    hot_mask = ndvi.lt(ndvi_min_img)
    
    t_cold_raw = lst.updateMask(cold_mask).reduceRegion(
        reducer=ee.Reducer.percentile([10]),
        geometry=aoi, scale=30, bestEffort=True
    ).get('LST')
    
    t_hot_raw = lst.updateMask(hot_mask).reduceRegion(
        reducer=ee.Reducer.percentile([85]),
        geometry=aoi, scale=30, bestEffort=True
    ).get('LST')

    # --- Step 2: Compute Dynamic Fallback Values ---
    # NDVI percentiles for dynamic masks
    ndvi_percs = ndvi.reduceRegion(
        reducer=ee.Reducer.percentile([20, 80]),
        geometry=aoi, scale=30, bestEffort=True
    )
    ndvi_p20 = ndvi_percs.get('NDVI_p20')
    ndvi_p80 = ndvi_percs.get('NDVI_p80')
    
    # Dynamic cold: LST of top 20% greenest pixels
    dyn_cold = lst.updateMask(ndvi.gt(ee.Number(ee.Algorithms.If(
        ee.Algorithms.IsEqual(ndvi_p80, None), 999, ndvi_p80
    )))).reduceRegion(
        reducer=ee.Reducer.percentile([10]),
        geometry=aoi, scale=30, bestEffort=True
    ).get('LST')

    # Dynamic hot: LST of bottom 20% driest pixels
    dyn_hot = lst.updateMask(ndvi.lt(ee.Number(ee.Algorithms.If(
        ee.Algorithms.IsEqual(ndvi_p20, None), -999, ndvi_p20
    )))).reduceRegion(
        reducer=ee.Reducer.percentile([90]),
        geometry=aoi, scale=30, bestEffort=True
    ).get('LST')

    # --- Step 3: Safety Fallback (Direct LST percentiles) ---
    lst_percs = lst.reduceRegion(
        reducer=ee.Reducer.percentile([5, 95]),
        geometry=aoi, scale=30, bestEffort=True
    )
    saf_cold = lst_percs.get('LST_p5')
    saf_hot = lst_percs.get('LST_p95')

    # --- Step 4: Chain Fallbacks (IsEqual + swapped branches, no Not needed) ---
    # Cold: seasonal -> dynamic -> safety -> hardcoded
    val_cold = ee.Algorithms.If(
        ee.Algorithms.IsEqual(t_cold_raw, None),
        ee.Algorithms.If(
            ee.Algorithms.IsEqual(dyn_cold, None),
            ee.Algorithms.If(ee.Algorithms.IsEqual(saf_cold, None), default_t_cold, saf_cold),
            dyn_cold
        ),
        t_cold_raw
    )

    # Hot: seasonal -> dynamic -> safety -> hardcoded
    val_hot = ee.Algorithms.If(
        ee.Algorithms.IsEqual(t_hot_raw, None),
        ee.Algorithms.If(
            ee.Algorithms.IsEqual(dyn_hot, None),
            ee.Algorithms.If(ee.Algorithms.IsEqual(saf_hot, None), default_t_hot, saf_hot),
            dyn_hot
        ),
        t_hot_raw
    )

    t_cold = ee.Image.constant(val_cold)
    t_hot = ee.Image.constant(val_hot)

    cwsi = lst.subtract(t_cold).divide(t_hot.subtract(t_cold)).clamp(0, 1).rename('CWSI')
    return cwsi

def get_ndvi_range(collection, aoi):
    """
    Calculate NDVI min/max for CWSI thresholds from a collection (Landsat or S2).
    Expects collection to have NDVI band.
    """
    ndvi_perc = collection.reduce(ee.Reducer.percentile([20, 90])).rename(['NDVI_p20', 'NDVI_p90'])
    ndvi_stats = ndvi_perc.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=aoi,
        scale=30,
        maxPixels=1e9,
        bestEffort=True
    )
    
    p20_raw = ndvi_stats.get('NDVI_p20')
    p90_raw = ndvi_stats.get('NDVI_p90')
    
    # Safely handle null values (e.g. if chunk has no uncloudy images)
    ndvi_p20_safe = ee.Number(ee.Algorithms.If(ee.Algorithms.IsEqual(p20_raw, None), 0.1, p20_raw))
    ndvi_p90_safe = ee.Number(ee.Algorithms.If(ee.Algorithms.IsEqual(p90_raw, None), 0.8, p90_raw))
    
    ndvi_min = ndvi_p20_safe.clamp(0.05, 0.2)
    ndvi_max = ndvi_p90_safe.clamp(0.4, 0.9)
    
    return ndvi_min, ndvi_max

def get_agri_mask(aoi, date):
    """
    Create a mask for agricultural areas (excluding Water and Trees/Forest) 
    using Dynamic World V1.
    """
    dw = ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1") \
            .filterBounds(aoi) \
            .filterDate(date.advance(-15, 'day'), date.advance(15, 'day')) \
            .select('label')
    
    # Check if collection has any images
    count = dw.size()
    
    # If no images found, return a default mask (all 1s - no masking)
    def create_mask():
        classification = dw.mode()
        # Dynamic World Classes:
        # 0=Water, 1=Trees, 2=Grass, 3=Flooded Veg, 4=Crops, 5=Shrub, 6=Built, 7=Bare, 8=Snow
        # We mask out Water (0) and Trees (1).
        return classification.neq(0).And(classification.neq(1))
    
    def default_mask():
        return ee.Image.constant(1)
    
    mask = ee.Algorithms.If(count.gt(0), create_mask(), default_mask())
    
    return ee.Image(mask)

def get_water_mask(aoi, date):
    """
    Create a mask specifically for water bodies using Dynamic World V1.
    """
    dw = ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1") \
            .filterBounds(aoi) \
            .filterDate(date.advance(-15, 'day'), date.advance(15, 'day')) \
            .select('label')
    
    # Check if collection has any images
    count = dw.size()
    
    # If no images found, return a default mask (all 1s - no masking)
    def create_mask():
        classification = dw.mode()
        # Dynamic World Classes: 0=Water
        return classification.neq(0)
    
    def default_mask():
        return ee.Image.constant(1)
    
    mask = ee.Algorithms.If(count.gt(0), create_mask(), default_mask())
    
    return ee.Image(mask)

def get_dynamic_stats(image, band_name, aoi):
    """Calculate dynamic min/max and percentiles for proper visualization"""
    try:
        stats = image.select(band_name).reduceRegion(
            reducer=ee.Reducer.percentile([2, 5, 10, 25, 30, 33, 50, 66, 70, 75, 90, 95, 98]).combine(
                ee.Reducer.min(), '', True
            ).combine(
                ee.Reducer.max(), '', True
            ),
            geometry=aoi,
            scale=30,
            maxPixels=1e13,
            bestEffort=True
        ).getInfo()
        
        return {
            'min': stats.get(f'{band_name}_min'),
            'max': stats.get(f'{band_name}_max'),
            'p2': stats.get(f'{band_name}_p2'),
            'p5': stats.get(f'{band_name}_p5'),
            'p10': stats.get(f'{band_name}_p10'),
            'p25': stats.get(f'{band_name}_p25'),
            'p30': stats.get(f'{band_name}_p30'),
            'p33': stats.get(f'{band_name}_p33'),
            'p50': stats.get(f'{band_name}_p50'),
            'p66': stats.get(f'{band_name}_p66'),
            'p70': stats.get(f'{band_name}_p70'),
            'p75': stats.get(f'{band_name}_p75'),
            'p90': stats.get(f'{band_name}_p90'),
            'p95': stats.get(f'{band_name}_p95'),
            'p98': stats.get(f'{band_name}_p98')
        }
    except Exception as e:
        logger.warning(f"Error calculating dynamic stats: {e}")
        # Return safe defaults if it fails
        return {
            'min': 0, 'max': 1, 'p2': 0, 'p5': 0.05, 'p10': 0.1, 'p25': 0.25, 
            'p50': 0.5, 'p75': 0.75, 'p90': 0.9, 'p95': 0.95, 'p98': 0.98
        }
