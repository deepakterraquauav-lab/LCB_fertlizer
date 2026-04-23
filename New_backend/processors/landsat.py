import ee
from . import common

# ---------------------------------------------------------------------------
# Stage 2 – Per-pixel masking helpers
# ---------------------------------------------------------------------------

def apply_scale_factors(img):
    """Apply USGS Collection 2 scale factors to surface reflectance and thermal bands."""
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
        unique_dates.map(
            lambda d:
                with_date
                .filterDate(d, ee.Date(d).advance(1, 'day'))
                .sort('CLOUD_COVER')
                .first()
                .set('selected_date', d)
        )
    ).sort('system:time_start')
    
    return one_per_day


# ---------------------------------------------------------------------------
# Index computation
# ---------------------------------------------------------------------------

def process_landsat_image(img, aoi, ndvi_min_img, ndvi_max_img, mask_agri=True):
    """
    Process a single Landsat image: cloud masking → scale factors → indices → CWSI.

    IMPORTANT: cloud_mask_landsat() MUST run BEFORE apply_scale_factors().
    QA_PIXEL contains integer bit-flags; bitwise operations fail on the
    floating-point values produced by scale-factor application.
    """
    # Stage 2: Per-pixel QA_PIXEL masking (CFMask) – integers only
    img = cloud_mask_landsat(img)

    # Convert to physical surface-reflectance / brightness-temperature units
    img = apply_scale_factors(img)

    nir  = img.select('SR_B5')
    red  = img.select('SR_B4')
    blue = img.select('SR_B2')
    lst  = img.select('ST_B10').rename('LST')

    # NDVI (needed for CWSI and all downstream indices)
    ndvi = img.normalizedDifference(['SR_B5', 'SR_B4']).rename('NDVI')
    img  = img.addBands([ndvi, lst], None, True)

    # CWSI – Crop Water Stress Index (Landsat only; requires 30 m LST)
    cwsi = common.calculate_cwsi(lst, ndvi, ndvi_min_img, ndvi_max_img, aoi)

    # SAVI, EVI, LAI, Kc (common across sensors)
    img = common.get_common_indices(img, nir, red, blue, ndvi_min_img, ndvi_max_img)

    # Add CWSI band
    img = img.addBands(cwsi)

    # Water mask: keep only pixels with NDVI > 0 (removes open water bodies)
    water_mask = img.select('NDVI').gt(0)
    img = img.updateMask(water_mask)

    # Optional: agricultural mask (removes forests, built-up areas, etc.)
    if mask_agri:
        agri_mask = common.get_agri_mask(aoi, img.date())
        img = img.updateMask(agri_mask)

    return img
