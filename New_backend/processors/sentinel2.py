import ee
from . import common

<<<<<<< HEAD
def _get_bad_scl_mask(scl_img):
    """Return mask for pixels considered cloudy/invalid from SCL."""
    return (
        scl_img.eq(0)   # no data
        .Or(scl_img.eq(1))   # saturated / defective
        .Or(scl_img.eq(2))   # dark area pixels
        .Or(scl_img.eq(3))   # cloud shadows
        .Or(scl_img.eq(7))   # unclassified
        .Or(scl_img.eq(8))   # cloud medium probability
        .Or(scl_img.eq(9))   # cloud high probability
        .Or(scl_img.eq(10))  # thin cirrus
    )

def _attach_cloud_score_plus(s2_collection):
    """Attach Cloud Score+ `cs` band to each Sentinel-2 image when available."""
    cs_plus = ee.ImageCollection('GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED')
    join = ee.Join.saveFirst('cs_img')
    joined = join.apply(
        primary=s2_collection,
        secondary=cs_plus,
        condition=ee.Filter.equals(leftField='system:index', rightField='system:index')
    )

    def add_cs_band(img):
        img = ee.Image(img)
        cs_img = ee.Image(img.get('cs_img'))
        return ee.Image(
            ee.Algorithms.If(
                img.get('cs_img'),
                img.addBands(cs_img.select('cs')),
                img
            )
        )

    return ee.ImageCollection(joined).map(add_cs_band)

def mask_s2_clouds(img, cs_threshold=0.60):
    """
    Per-pixel cloud masking for Sentinel-2 using SCL classes + Cloud Score+.
    """
    scl = img.select('SCL')
    bad_scl = _get_bad_scl_mask(scl)
    mask = bad_scl.Not()

    has_cs = img.bandNames().contains('cs')
    cs_mask = ee.Image(
        ee.Algorithms.If(has_cs, img.select('cs').gte(cs_threshold), ee.Image(1))
    )

    return (
        img.updateMask(mask)
           .updateMask(cs_mask)
           .divide(10000)
           .copyProperties(img, ['system:time_start', 'CLOUDY_PIXEL_PERCENTAGE'])
    )

def get_s2_collection(aoi, start_date, end_date, cloud_filter=100, cs_threshold=0.60):
=======
# ---------------------------------------------------------------------------
# Stage 2 – Per-pixel masking helpers
# ---------------------------------------------------------------------------

def mask_s2_scl(img):
    """
    Per-pixel cloud masking for Sentinel-2 SR using the Scene Classification
    Layer (SCL) produced by the Sen2Cor algorithm.

    SCL values REMOVED (bad pixels → transparent):
        0  – No data
        1  – Saturated / Defective
        2  – Dark Area Pixels (misclassified shadows / water edges)
        3  – Cloud Shadows
        7  – Unclassified (cloud edges, complex boundaries)
        8  – Cloud (Medium Probability)
        9  – Cloud (High Probability)
        10 – Thin Cirrus

    SCL values KEPT (valid land / water surface):
        4  – Vegetation
        5  – Bare Soils
        6  – Water
        11 – Snow / Ice
    """
    scl = img.select('SCL')

    # Build a boolean mask: True where pixel is VALID
    bad = (
        scl.eq(0)   # No data
        .Or(scl.eq(1))   # Saturated / Defective
        .Or(scl.eq(2))   # Dark Area Pixels
        .Or(scl.eq(3))   # Cloud Shadows
        .Or(scl.eq(7))   # Unclassified
        .Or(scl.eq(8))   # Cloud – Medium Probability
        .Or(scl.eq(9))   # Cloud – High Probability
        .Or(scl.eq(10))  # Thin Cirrus
    )
    good = bad.Not()

    # Apply the pixel mask ONLY — do NOT divide or copyProperties here.
    # copyProperties() returns ee.Element (not ee.Image), which breaks any
    # subsequent .select() / .updateMask() calls on the result.
    # divide(10000) here would also corrupt the cs band (0–1 float) before
    # the CS+ threshold check in mask_s2_clouds.
    return img.updateMask(good)


def mask_s2_clouds(img):
    """
    Combined Stage-2 mask applied per-image inside .map():
      1. SCL-based per-pixel mask (Sen2Cor) — bad pixels become transparent.
      2. Cloud Score+ threshold (cs >= 0.60) — thin/diffuse cloud cleanup.
      3. Scale optical bands ÷ 10000 to surface-reflectance units.

    Ordering is critical:
      • cs is a 0–1 float band linked at collection level — it MUST be
        thresholded BEFORE dividing optical bands (otherwise cs ÷ 10000
        would make the 0.60 threshold meaningless).
      • Only B.* bands are divided; cs / SCL / QA bands are left unchanged.
      • Metadata is preserved via .set() — NOT .copyProperties(), which
        returns ee.Element and breaks subsequent .select() calls.
>>>>>>> 7c525ac2ef6b10a0131a7d038a872fe7621d2e06
    """
    # Stage 2a: SCL per-pixel mask (returns ee.Image with bad pixels masked)
    img = mask_s2_scl(img)

    # Stage 2b: CS+ threshold — must run BEFORE divide; cs values are 0–1
    cs_mask = img.select('cs').gte(0.60)
    img = img.updateMask(cs_mask)

    # Stage 2c: Scale optical bands only (B.* → surface reflectance 0–1)
    # Use addBands with overwrite=True so scaled bands replace the raw DN bands
    optical_scaled = img.select('B.*').divide(10000)
    img = img.addBands(optical_scaled, None, True)

    # Preserve essential metadata using .set() (copyProperties returns ee.Element)
    return (img
            .set('system:time_start', img.get('system:time_start'))
            .set('CLOUDY_PIXEL_PERCENTAGE', img.get('CLOUDY_PIXEL_PERCENTAGE')))


# ---------------------------------------------------------------------------
# Stage 1 – Scene-level relaxed gate + collection builder
# ---------------------------------------------------------------------------

def get_s2_collection(aoi, start_date, end_date, cloud_filter=100):
    """
    Get Sentinel-2 SR collection using the two-stage cloud filtering strategy.

    Stage 1 – Scene-level Relaxed Gate:
        Only discard scenes where CLOUDY_PIXEL_PERCENTAGE == 100 (completely
        useless). Partially cloudy scenes are retained so that clean
        sub-regions within the AOI are NOT discarded.

    Stage 2 – Per-pixel SCL + CS+ masking:
        mask_s2_clouds() removes individual cloud / shadow / defective pixels,
        making them transparent (NaN) for downstream temporal compositing.

    The daily mosaic step then automatically gap-fills: any masked pixel on
    overpass A is replaced by a clear pixel from overlapping overpass B on
    the same acquisition date.

    Args:
<<<<<<< HEAD
        cloud_filter: Relaxed scene gate for CLOUDY_PIXEL_PERCENTAGE (default 100%).
        cs_threshold: Cloud Score+ `cs` minimum threshold (default 0.60).
    """
    s2_raw = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
        .filterBounds(aoi) \
        .filterDate(start_date, end_date) \
        .filter(ee.Filter.lte('CLOUDY_PIXEL_PERCENTAGE', cloud_filter))

    s2_with_cs = _attach_cloud_score_plus(s2_raw)
    s2 = s2_with_cs.map(lambda img: mask_s2_clouds(img, cs_threshold)) \
                   .map(lambda img: img.set('date_str', img.date().format('YYYY-MM-dd')))
    
    # Mosaic by date
=======
        aoi        : ee.Geometry – Area of interest.
        start_date : str – Start date 'YYYY-MM-DD'.
        end_date   : str – End date 'YYYY-MM-DD'.
        cloud_filter: Scene-level gate (default 100 → keep everything that
                      isn't 100 % cloud-covered). Adjust to 50 for stricter
                      scene rejection while still benefiting from pixel masking.
    """
    # Stage 1: Relaxed scene-level gate
    s2_raw = (
        ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterBounds(aoi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', cloud_filter))
    )

    # Link Cloud Score+ 'cs' band to every S2 image ONCE at collection level.
    # This is the correct pattern: linkCollection() returns an ImageCollection
    # where each image has the 'cs' band attached. Doing this inside a per-image
    # map() function would return an ImageCollection per call, not an Image,
    # breaking any downstream band operations like .gte().
    cs_plus = ee.ImageCollection('GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED')
    s2_with_cs = s2_raw.linkCollection(cs_plus, ['cs'])

    # Stage 2: Per-pixel SCL + CS+ masking (cs band already present on each image)
    s2 = s2_with_cs.map(mask_s2_clouds) \
                   .map(lambda img: img.set('date_str', img.date().format('YYYY-MM-dd')))

    # -----------------------------------------------------------------------
    # Daily mosaic – gap-filling across same-day overpasses
    # -----------------------------------------------------------------------
>>>>>>> 7c525ac2ef6b10a0131a7d038a872fe7621d2e06
    unique_dates = s2.aggregate_array('date_str').distinct().sort()

    def make_mosaic(d):
        d = ee.String(d)
        daily_images = s2.filterDate(ee.Date(d), ee.Date(d).advance(1, 'day'))
        mosaic = daily_images.mosaic().clip(aoi)

        # Propagate the minimum CLOUDY_PIXEL_PERCENTAGE for bookkeeping
        min_cloud = daily_images.aggregate_min('CLOUDY_PIXEL_PERCENTAGE')

        return (
            mosaic
            .set('selected_date', d)
            .set('system:time_start', ee.Date(d).millis())
            .set('cloud_cover', min_cloud)
        )

    s2_daily = ee.ImageCollection(unique_dates.map(make_mosaic))
<<<<<<< HEAD
    
    # Collection already uses relaxed scene gate + strict per-pixel masks.
    return s2_daily

def get_s2_date_cloud_info(aoi, start_date, end_date, cloud_filter=100, cs_threshold=0.60, scale=20):
    """
    Compute AOI-only cloud proxy (%) per available Sentinel-2 date.

    Cloud proxy:
      100 - (clear_pixels / observed_pixels * 100)
    where:
      clear_pixels    -> pixels that pass SCL + Cloud Score+ filters
      observed_pixels -> SCL != 0 (observed pixels in AOI)
    """
    s2_raw = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
        .filterBounds(aoi) \
        .filterDate(start_date, end_date) \
        .filter(ee.Filter.lte('CLOUDY_PIXEL_PERCENTAGE', cloud_filter))

    s2_with_cs = _attach_cloud_score_plus(s2_raw) \
        .map(lambda img: img.set('date_str', img.date().format('YYYY-MM-dd')))

    unique_dates = s2_with_cs.aggregate_array('date_str').distinct().sort()

    def summarize_date(d):
        d = ee.String(d)
        daily = s2_with_cs.filterDate(ee.Date(d), ee.Date(d).advance(1, 'day'))
        mosaic = ee.Image(daily.mosaic().clip(aoi))

        scl = mosaic.select('SCL')
        observed = scl.neq(0)
        bad_scl = _get_bad_scl_mask(scl)

        has_cs = mosaic.bandNames().contains('cs')
        clear_cs = ee.Image(ee.Algorithms.If(has_cs, mosaic.select('cs').gte(cs_threshold), ee.Image(1)))
        clear_mask = observed.And(bad_scl.Not()).And(clear_cs)

        # Use count of unmasked pixels (more robust than sum on booleans).
        count_img = ee.Image.cat([
            observed.selfMask().rename('observed_px'),
            clear_mask.selfMask().rename('clear_px')
        ])

        counts = count_img.reduceRegion(
            reducer=ee.Reducer.count(),
            geometry=aoi,
            scale=scale,
            maxPixels=1e10,
            bestEffort=False,
            tileScale=4
        )

        observed_px = ee.Number(ee.Algorithms.If(counts.get('observed_px'), counts.get('observed_px'), 0))
        clear_px = ee.Number(ee.Algorithms.If(counts.get('clear_px'), counts.get('clear_px'), 0))
        clear_pct = ee.Number(
            ee.Algorithms.If(
                observed_px.gt(0),
                clear_px.divide(observed_px).multiply(100),
                0
            )
        )
        cloud_pct = ee.Number(100).subtract(clear_pct).max(0).min(100)

        return ee.Feature(None, {
            'date': d,
            'cloud_pct_aoi': cloud_pct,
            'observed_px': observed_px,
            'clear_px': clear_px
        })

    return ee.FeatureCollection(unique_dates.map(summarize_date))
=======

    return s2_daily


# ---------------------------------------------------------------------------
# Index computation
# ---------------------------------------------------------------------------
>>>>>>> 7c525ac2ef6b10a0131a7d038a872fe7621d2e06

def process_s2_image(img, aoi, ndvi_min_img, ndvi_max_img, mask_agri=True):
    """
    Process S2 image — vegetation indices only (no LST/CWSI).

    LST / CWSI are computed exclusively from Landsat because MODIS LST at
    1 km resolution produces a single uniform value for small AOIs, making
    the derived CWSI meaningless.
    """
    date_str = img.get('selected_date')
    date = ee.Date(date_str)

    # Standard S2 bands
    nir  = img.select('B8')
    red  = img.select('B4')
    blue = img.select('B2')

    ndvi = img.normalizedDifference(['B8', 'B4']).rename('NDVI')
    img  = img.addBands(ndvi)

    # SAVI, EVI, LAI, Kc (common across sensors)
    img = common.get_common_indices(img, nir, red, blue, ndvi_min_img, ndvi_max_img)

    # NDMI – Normalized Difference Moisture Index (Sentinel-2 specific)
    ndmi = img.normalizedDifference(['B8', 'B11']).rename('NDMI')
    img  = img.addBands(ndmi)

    # CLRe – Red-Edge Chlorophyll Index (Sentinel-2 only)
    # Formula: CLRe = (B8 / B6) - 1
    clre = img.expression(
        '(NIR / RE2) - 1',
        {
            'NIR': img.select('B8'),
            'RE2': img.select('B6')
        }
    ).rename('CLRe')
    img = img.addBands(clre)

    # Water mask: keep only pixels with NDVI > 0 (removes open water bodies)
    water_mask = img.select('NDVI').gt(0)
    img = img.updateMask(water_mask)

    # Optional: agricultural mask (removes forests, built-up areas, etc.)
    if mask_agri:
        agri_mask = common.get_agri_mask(aoi, date)
        img = img.updateMask(agri_mask)

    return img
