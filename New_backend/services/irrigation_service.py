import ee
import logging
from processors import landsat, sentinel2, soil_moisture, weather, common, pca_processor

logger = logging.getLogger('smart_irrigation_logger')



def get_combined_data(aoi, start_date, end_date, mask_agri=False):
    """
    Get daily data combining Landsat and Sentinel-2 sources.
    mask_agri: Boolean, whether to mask Water/Trees using Dynamic World.
    """
    # 1. Prepare Collections
    logger.info("Fetching Landsat collection...")
    landsat_col = landsat.get_landsat_collection(aoi, start_date, end_date)
    
    logger.info("Fetching Sentinel-2 collection...")
    s2_col = sentinel2.get_s2_collection(aoi, start_date, end_date)
    
    logger.info("Fetching Sentinel-1 Soil Moisture...")
    sentinel1_col = soil_moisture.get_sentinel1_soil_moisture_simple(aoi, start_date, end_date)

    # 2. Get Unique Dates
    l8_dates = landsat_col.aggregate_array('selected_date')
    s2_dates = s2_col.aggregate_array('selected_date')
    
    # Merge and Sort Unique Dates
    all_dates = l8_dates.cat(s2_dates).distinct().sort()
    dates_list = all_dates.getInfo()

    logger.info(f"Found {len(dates_list)} unique dates total.")

    if not dates_list:
        logger.info("No unique dates found for imagery. Returning empty FeatureCollection.")
        return ee.FeatureCollection([])

    # 3. Calculate Global NDVI Thresholds (from Landsat preferably, or S2 fallback)
    logger.info("Calculating seasonal NDVI thresholds...")
    landsat_count = landsat_col.size().getInfo()
    if landsat_count > 0:
         ndvi_min, ndvi_max = common.get_ndvi_range(landsat_col.map(landsat.apply_scale_factors).map(lambda img: img.normalizedDifference(['SR_B5', 'SR_B4']).rename('NDVI')), aoi)
    else:
         # Fallback to S2 if no landsat
         s2_ndvi_col = s2_col.map(lambda img: img.normalizedDifference(['B8', 'B4']).rename('NDVI'))
         ndvi_min, ndvi_max = common.get_ndvi_range(s2_ndvi_col, aoi)

    ndvi_min_img = ee.Image.constant(ndvi_min)
    ndvi_max_img = ee.Image.constant(ndvi_max)
    
    logger.info(f"NDVI Range: {ndvi_min.getInfo()} - {ndvi_max.getInfo()}")

    # 4. Integrate Data Per Day
    def compute_daily(date_str):
        date = ee.Date(date_str)
        
        # Check sensors available for this date
        l8_img = landsat_col.filter(ee.Filter.eq('selected_date', date_str)).first()
        s2_img = s2_col.filter(ee.Filter.eq('selected_date', date_str)).first()
        
        # Dummy image for fallbacks
        dummy = ee.Image.constant(0).selfMask()

        # Process Both (if available) - wrapped in Algorithms.If to avoid computation on nulls
        # Note: We duplicate args to pass into scopes
        
        # Process Landsat
        l8_proc = ee.Image(ee.Algorithms.If(
            l8_img,
            landsat.process_landsat_image(l8_img, aoi, ndvi_min_img, ndvi_max_img, mask_agri),
            dummy
        ))

        # Process Sentinel-2 (vegetation indices only — no LST/CWSI)
        s2_proc = ee.Image(ee.Algorithms.If(
            s2_img,
            sentinel2.process_s2_image(s2_img, aoi, ndvi_min_img, ndvi_max_img, mask_agri),
            dummy
        ))

        # ---------------------------------------------------------
        # FUSION LOGIC:
        #   Vegetation (NDVI, SAVI, EVI, LAI, Kc, PCA): Prioritize S2
        #   Thermal (LST, CWSI): Landsat ONLY (S2 no longer has these)
        # ---------------------------------------------------------
        
        # Source for Vegetation Indices: Prioritize Sentinel-2
        veg_img = ee.Image(ee.Algorithms.If(s2_img, s2_proc, l8_proc))

        # PCA Calculation (using Vegetation Source)
        veg_with_pca = pca_processor.get_pca_image(veg_img)

        # Add CLRe null-band fallback: CLRe (B7/B5-1) only exists on Sentinel-2.
        # On Landsat-only dates, inject a masked placeholder so the select() doesn't fail.
        no_clre = ee.Image.constant(0.0).toFloat().selfMask().rename('CLRe')
        veg_with_clre = ee.Image(ee.Algorithms.If(
            s2_img,
            veg_with_pca,                         # S2 date: CLRe band is real
            veg_with_pca.addBands(no_clre)        # Landsat-only date: CLRe = masked null
        ))

        # Vegetation bands
        b_veg = veg_with_clre.select(['NDVI', 'SAVI', 'EVI', 'LAI', 'Kc', 'PC1', 'CLRe'],
                                     ['NDVI', 'SAVI', 'EVI', 'LAI', 'Kc', 'PC1', 'CLRe'])
        
        # Thermal bands: Landsat only. On S2-only dates, LST/CWSI are null.
        no_thermal = ee.Image.cat([
            ee.Image.constant(0.0).toFloat().selfMask().rename('LST'),
            ee.Image.constant(0.0).toFloat().selfMask().rename('CWSI')
        ])
        b_therm = ee.Image(ee.Algorithms.If(
            l8_img,
            l8_proc.select(['LST', 'CWSI']),
            no_thermal
        ))
        
        # Combine vegetation + thermal
        processed_img = b_veg.addBands(b_therm)

        # Record source info string for debugging
        processing_source = ee.Algorithms.If(
            s2_img,
            ee.Algorithms.If(l8_img, 'Fused (S2+L8)', 'Sentinel-2'),
            ee.Algorithms.If(l8_img, 'Landsat', 'None')
        )

        
        # Environmental Data
        eto_img, eto_count = weather.get_eto_image(date)
        rain_img, eff_rain, chirps_count = weather.get_rainfall_image(date)
        sm_img, deltaS_mm, sm_source, sm_count, smap_count = soil_moisture.get_combined_soil_moisture(aoi, date, sentinel1_col)
        
        # Irrigation Calculations (Use fused Kc)
        kc = processed_img.select('Kc')
        etc_img = kc.multiply(eto_img).rename('ETc')
        
        # CWR = ETc - Effective Rainfall (simple water balance)
        # Note: deltaS_mm removed — soil moisture delta was causing Irrigation_Need
        # to be null on dates with partial Sentinel-1 coverage.
        cwr_safe = etc_img.expression(
            '(ETc - Rain) < 0 ? 0 : (ETc - Rain)', {
                'ETc': etc_img,
                'Rain': eff_rain
            }
        ).rename('CWR')
        
        irrigation_need = cwr_safe.expression(
            'CWR / 0.7', {
                'CWR': cwr_safe
            }
        ).rename('Irrigation_Need')
        
        # Combine all for reduction
        combined = ee.Image.cat([
            processed_img, # Contains NDVI, SAVI, EVI, LAI, Kc, PC1, LST, CWSI (LST/CWSI null on S2-only dates)
            eto_img, rain_img, eff_rain, deltaS_mm, sm_img,
            etc_img, cwr_safe, irrigation_need
        ])
        
        stats = combined.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=aoi,
            scale=30,
            maxPixels=1e13
        )
        
        # Check availability (using server-side logic)
        l8_available = ee.Number(ee.Algorithms.If(l8_img, 1, 0))
        s2_available = ee.Number(ee.Algorithms.If(s2_img, 1, 0))
        
        return ee.Feature(None, stats) \
            .set('date', date_str) \
            .set('source_sensor', processing_source) \
            .set('soil_moisture_source', sm_source) \
            .set('landsat_available', l8_available) \
            .set('s2_available', s2_available)

    # Process all dates
    daily_data = ee.FeatureCollection(all_dates.map(compute_daily))
    
    return daily_data
