import ee

def get_eto_image(date):
    """
    Get Reference Evapotranspiration (ETo) safely using the Mosaic Fallback pattern.
    """
    # 1. Process actual data (if it exists)
    eto_col = ee.ImageCollection("MODIS/061/MOD16A2") \
                .filterDate(date, date.advance(4, 'day')) \
                .select('PET') \
                .map(lambda img: img.multiply(0.1).divide(8).toFloat().rename('ETo'))
                
    # 2. Create an UNMASKED default canvas (Guarantees 1 band, value 4.0)
    fallback_eto = ee.Image.constant(4.0).toFloat().rename('ETo')
    
    # 3. Put fallback FIRST, then merge actual data. 
    # mosaic() paints the actual data on top of the fallback.
    # If no actual data exists, you just get the 4.0 canvas!
    eto_img = ee.ImageCollection([fallback_eto]).merge(eto_col).mosaic()
    
    # Calculate size on the original collection for your logs
    eto_count = eto_col.size()
    
    return eto_img, eto_count

def get_rainfall_image(date):
    """
    Get Rainfall from CHIRPS safely using the Mosaic Fallback pattern.
    """
    # 1. Get actual data and rename band to 'Rain' so it matches the canvas
    chirps_col = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY") \
                  .filterDate(date, date.advance(1, 'day')) \
                  .select(['precipitation'], ['Rain']) \
                  .map(lambda img: img.toFloat())
                  
    # 2. Create an UNMASKED default canvas (Guarantees 1 band, value 0)
    fallback_rain = ee.Image.constant(0.0).toFloat().rename('Rain')
    
    # 3. Merge and Mosaic (Actual rainfall paints over the 0)
    rain_img = ee.ImageCollection([fallback_rain]).merge(chirps_col).mosaic()
    
    # Calculate effective rainfall
    eff_rain = rain_img.multiply(0.8).toFloat().rename('EffRain')
    
    chirps_count = chirps_col.size()
    
    return rain_img, eff_rain, chirps_count