import ee
from . import common

def apply_scale_factors(img):
    """Apply scale factors to Landsat surface reflectance and thermal bands"""
    opt = img.select('SR_B.*').multiply(0.0000275).add(-0.2)
    thm = img.select('ST_B.*').multiply(0.00341802).add(149.0)
    return img.addBands(opt, None, True).addBands(thm, None, True)

def cloud_mask_landsat(img):
    """Per-pixel cloud masking for Landsat 8/9 using QA_PIXEL bits 1-4."""
    qa = img.select('QA_PIXEL')
    dilated_cloud_clear = qa.bitwiseAnd(1 << 1).eq(0)
    cirrus_clear = qa.bitwiseAnd(1 << 2).eq(0)
    cloud_clear = qa.bitwiseAnd(1 << 3).eq(0)
    cloud_shadow_clear = qa.bitwiseAnd(1 << 4).eq(0)
    clear_mask = dilated_cloud_clear.And(cirrus_clear).And(cloud_clear).And(cloud_shadow_clear)
    return img.updateMask(clear_mask)

def get_landsat_collection(aoi, start_date, end_date, cloud_filter=100):
    """Get merged Landsat 8/9 collection with one image per day
    
    Args:
        cloud_filter: Relaxed scene gate for CLOUD_COVER (default 100%).
    """
    merged = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2') \
               .merge(ee.ImageCollection('LANDSAT/LC09/C02/T1_L2')) \
               .filterBounds(aoi) \
               .filterDate(start_date, end_date) \
               .filter(ee.Filter.lte('CLOUD_COVER', cloud_filter))
    
    # Add date string for grouping
    with_date = merged.map(lambda img: img.set('date_str', img.date().format('YYYY-MM-dd')))
    
    # Get unique dates and select best image per day
    unique_dates = with_date.aggregate_array('date_str').distinct()
    
    one_per_day = ee.ImageCollection(
        unique_dates.map(lambda d: 
            with_date.filterDate(d, ee.Date(d).advance(1, 'day'))
                     .sort('CLOUD_COVER')
                     .first()
                     .set('selected_date', d)
        )
    ).sort('system:time_start')
    
    return one_per_day

def process_landsat_image(img, aoi, ndvi_min_img, ndvi_max_img, mask_agri=True):
    """
    Process a single Landsat image: indices, CWSI, etc.
    """
    # CRITICAL: Cloud mask MUST come BEFORE scale factors
    # QA bands are integers - bitwise operations fail on floats
    img = cloud_mask_landsat(img)
    img = apply_scale_factors(img)
    
    nir = img.select('SR_B5')
    red = img.select('SR_B4')
    blue = img.select('SR_B2')
    lst = img.select('ST_B10').rename('LST')
    
    # Add NDVI first as it's needed for everything
    ndvi = img.normalizedDifference(['SR_B5', 'SR_B4']).rename('NDVI')
    img = img.addBands([ndvi, lst], None, True) # Overwrite LST with renamed
    
    # CWSI
    cwsi = common.calculate_cwsi(lst, ndvi, ndvi_min_img, ndvi_max_img, aoi)
    
    # Common Indices (SAVI, etc)
    img = common.get_common_indices(img, nir, red, blue, ndvi_min_img, ndvi_max_img)
    
    # Add CWSI band
    img = img.addBands(cwsi)
    
    # Apply Water Mask (NDVI > 0) to remove water bodies from ALL layers
    # This renders water bodies transparent in visualization
    water_mask = img.select('NDVI').gt(0)
    img = img.updateMask(water_mask)
    
    # Apply Agricultural Mask (Water & Trees) -- Optional
    if mask_agri:
        agri_mask = common.get_agri_mask(aoi, img.date())
        img = img.updateMask(agri_mask)
    
    return img
