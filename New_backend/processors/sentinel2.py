import ee
from . import common

def mask_s2_clouds(img):
    """
    Cloud masking for Sentinel-2 using QA60.
    Relaxed mask - mirroring the JS logic: qa.bitwiseAnd(cloudBitMask).eq(0)
    """
    qa = img.select('QA60')
    cloud_bit_mask = 1 << 10
    cirrus_bit_mask = 1 << 11
    # JS: var mask = qa.bitwiseAnd(cloudBitMask).eq(0);
    # This ignores cirrus in the JS code provided ('cloudBitMask' used only in bitwiseAnd)
    # But usually good to mask both. I'll stick to JS logic which seemed to focus on cloudBitMask?
    # Actually JS said: var cloudBitMask = 1 << 10; ... mask = qa.bitwiseAnd(cloudBitMask).eq(0);
    mask = qa.bitwiseAnd(cloud_bit_mask).eq(0)
    
    return img.updateMask(mask).divide(10000).copyProperties(img, ['system:time_start', 'CLOUDY_PIXEL_PERCENTAGE'])

def get_s2_collection(aoi, start_date, end_date, cloud_filter=20):
    """
    Get Sentinel-2 collection, handling mosaics for partial tiles.
    
    Args:
        cloud_filter: Scene-level cloud cover threshold (default 30%).
                      Relaxed because per-pixel QA60 masking handles actual clouds.
    """
    s2_raw = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
        .filterBounds(aoi) \
        .filterDate(start_date, end_date) \
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20)) # Max 30% cloud cover
        
    s2 = s2_raw.map(mask_s2_clouds).map(lambda img: img.set('date_str', img.date().format('YYYY-MM-dd')))
    
    # Mosaic by date
    unique_dates = s2.aggregate_array('date_str').distinct().sort()
    
    def make_mosaic(d):
        d = ee.String(d)
        daily_images = s2.filterDate(ee.Date(d), ee.Date(d).advance(1, 'day'))
        mosaic = daily_images.mosaic().clip(aoi)
        
        # Metadata recovery (min cloud cover of constituent images)
        min_cloud = daily_images.aggregate_min('CLOUDY_PIXEL_PERCENTAGE')
        
        return mosaic.set('selected_date', d) \
                     .set('system:time_start', ee.Date(d).millis()) \
                     .set('cloud_cover', min_cloud)

    s2_daily = ee.ImageCollection(unique_dates.map(make_mosaic))
    
    # Filter by 'cloud_cover' which we set from min CLOUDY_PIXEL_PERCENTAGE
    return s2_daily.filter(ee.Filter.lt('cloud_cover', cloud_filter))

def process_s2_image(img, aoi, ndvi_min_img, ndvi_max_img, mask_agri=True):
    """
    Process S2 image — vegetation indices only (no LST/CWSI).
    MODIS LST was removed because its 1km resolution produces a single
    uniform value for small AOIs, making derived CWSI meaningless.
    LST and CWSI are only available on Landsat dates.
    """
    date_str = img.get('selected_date')
    date = ee.Date(date_str)
    
    # Standard S2 bands
    nir = img.select('B8')
    red = img.select('B4')
    blue = img.select('B2')
    
    ndvi = img.normalizedDifference(['B8', 'B4']).rename('NDVI')
    img = img.addBands(ndvi)
    
    # Indices (SAVI, EVI, LAI, Kc)
    img = common.get_common_indices(img, nir, red, blue, ndvi_min_img, ndvi_max_img)
    
    # NDMI (S2 specific)
    ndmi = img.normalizedDifference(['B8', 'B11']).rename('NDMI')
    img = img.addBands(ndmi)
    
    # CLRe — Red-Edge Chlorophyll Index (Sentinel-2 only)
    # Safer formula using NIR & Red-Edge2:
    #   CLRe = (NIR / RedEdge2) - 1  ≈ (B8 / B6) - 1
    # Native band scales are preserved; visualization uses 10m.
    clre = img.expression(
        '(NIR / RE2) - 1',
        {
            'NIR': img.select('B8'),
            'RE2': img.select('B6')
        }
    ).rename('CLRe')
    img = img.addBands(clre)
    
    # Apply Water Mask (NDVI > 0) to remove water bodies from ALL layers
    # This renders water bodies transparent in visualization
    water_mask = img.select('NDVI').gt(0)
    img = img.updateMask(water_mask)
    
    # Apply Agricultural Mask (Water & Trees) -- Optional
    if mask_agri:
        agri_mask = common.get_agri_mask(aoi, date)
        img = img.updateMask(agri_mask)
    
    return img
