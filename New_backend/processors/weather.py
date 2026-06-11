import ee

def get_eto_image(date):
    """
    Get Reference Evapotranspiration (ETo) safely using the Server-Side Conditional Fallback pattern.
    """
    # 1. Process actual data (if it exists)
    eto_col = ee.ImageCollection("MODIS/061/MOD16A2") \
                .filterDate(date, date.advance(4, 'day')) \
                .select('PET') \
                .map(lambda img: img.multiply(0.1).divide(8).toFloat().rename('ETo'))
                
    # 2. Create an UNMASKED default canvas (Guarantees 1 band, value 4.0)
    fallback_eto = ee.Image.constant(4.0).toFloat().rename('ETo')
    
    # 3. Use server-side conditional logic: if MODIS has data, use its mosaic, else fallback
    eto_img = ee.Image(ee.Algorithms.If(
        eto_col.size().gt(0),
        eto_col.mosaic().toFloat().rename('ETo'),
        fallback_eto
    ))
    
    # Calculate size on the original collection for your logs
    eto_count = eto_col.size()
    
    return eto_img, eto_count

def get_rainfall_image(date):
    """
    Get Rainfall from CHIRPS safely using the Server-Side Conditional Fallback pattern.
    """
    # 1. Get actual data and rename band to 'Rain' so it matches the canvas
    chirps_col = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY") \
                  .filterDate(date, date.advance(1, 'day')) \
                  .select(['precipitation'], ['Rain']) 
                
                  
    # 2. Create an UNMASKED default canvas (Guarantees 1 band, value 0)
    fallback_rain = ee.Image.constant(0.0).toFloat().rename('Rain')
    
    # 3. Safely pick actual data or fallback using If, avoiding merge type conflicts
    count = chirps_col.size()
    rain_img = ee.Image(ee.Algorithms.If(
        count.gt(0),
        ee.Image(chirps_col.first()).unmask(0).toFloat(),
        fallback_rain
    ))
    
    # Calculate effective rainfall
    eff_rain = rain_img.multiply(0.8).toFloat().rename('EffRain')
    
    chirps_count = count
    
    return rain_img, eff_rain, chirps_count