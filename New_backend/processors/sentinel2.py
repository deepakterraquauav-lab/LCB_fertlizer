import ee
from . import common


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
    """Attach Cloud Score+ 'cs' band to each Sentinel-2 image when available."""
    cs_plus = ee.ImageCollection('GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED')
    join = ee.Join.saveFirst('cs_img')
    joined = join.apply(
        primary=s2_collection,
        secondary=cs_plus,
        condition=ee.Filter.equals(leftField='system:index', rightField='system:index')
    )

    def add_cs_band(img):
        img = ee.Image(img)
        return ee.Image(
            ee.Algorithms.If(
                img.get('cs_img'),
                img.addBands(ee.Image(img.get('cs_img')).select('cs')),
                img
            )
        )

    return ee.ImageCollection(joined).map(add_cs_band)


def mask_s2_clouds(img, cs_threshold=0.60):
    """Per-pixel cloud masking for Sentinel-2 using SCL classes plus Cloud Score+."""
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
    """
    Build daily Sentinel-2 mosaics with relaxed scene filtering and strict per-pixel masking.
    """
    s2_raw = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
        .filterBounds(aoi) \
        .filterDate(start_date, end_date) \
        .filter(ee.Filter.lte('CLOUDY_PIXEL_PERCENTAGE', cloud_filter))

    s2_with_cs = _attach_cloud_score_plus(s2_raw)
    s2 = s2_with_cs.map(lambda img: mask_s2_clouds(img, cs_threshold)) \
                   .map(lambda img: img.set('date_str', img.date().format('YYYY-MM-dd')))

    unique_dates = s2.aggregate_array('date_str').distinct().sort()

    def make_mosaic(d):
        d = ee.String(d)
        daily_images = s2.filterDate(ee.Date(d), ee.Date(d).advance(1, 'day'))
        mosaic = daily_images.mosaic().clip(aoi)
        min_cloud = daily_images.aggregate_min('CLOUDY_PIXEL_PERCENTAGE')

        return (
            mosaic
            .set('selected_date', d)
            .set('system:time_start', ee.Date(d).millis())
            .set('cloud_cover', min_cloud)
        )

    return ee.ImageCollection(unique_dates.map(make_mosaic))


def get_s2_date_cloud_info(aoi, start_date, end_date, cloud_filter=100, cs_threshold=0.60, scale=20):
    """
    Compute AOI-only cloud proxy (percent) per available Sentinel-2 date.
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


def process_s2_image(img, aoi, ndvi_min_img, ndvi_max_img, mask_agri=True):
    """
    Process S2 image for vegetation indices only.
    LST and CWSI are intentionally Landsat-based.
    """
    date_str = img.get('selected_date')
    date = ee.Date(date_str)

    nir = img.select('B8')
    red = img.select('B4')
    blue = img.select('B2')

    ndvi = img.normalizedDifference(['B8', 'B4']).rename('NDVI')
    img = img.addBands(ndvi)

    img = common.get_common_indices(img, nir, red, blue, ndvi_min_img, ndvi_max_img)

    ndmi = img.normalizedDifference(['B8', 'B11']).rename('NDMI')
    img = img.addBands(ndmi)

    clre = img.expression(
        '(NIR / RE2) - 1',
        {
            'NIR': img.select('B8'),
            'RE2': img.select('B6')
        }
    ).rename('CLRe')
    img = img.addBands(clre)

    water_mask = img.select('NDVI').gt(0)
    img = img.updateMask(water_mask)

    if mask_agri:
        agri_mask = common.get_agri_mask(aoi, date)
        img = img.updateMask(agri_mask)

    return img
