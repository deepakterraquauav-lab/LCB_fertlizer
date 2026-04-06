import ee
import numpy as np

def lee_filter(image, kernel_size=3):
    """
    Simplified Lee filter for SAR speckle reduction while preserving edges.
    Uses a fixed noise variance estimate to avoid slow server-side computations.
    
    Args:
        image: ee.Image - Input SAR image in linear power units
        kernel_size: int - Kernel size in pixels (default 3 for 30m at 10m resolution)
    
    Returns:
        ee.Image - Filtered image
    """
    # Convert kernel size to meters (Sentinel-1 is 10m resolution)
    kernel_meters = kernel_size * 10
    
    # Calculate local mean and variance
    mean = image.focalMean(kernel_meters, 'square', 'meters')
    variance = image.focalVariance(kernel_meters, 'square', 'meters')
    
    # Use a fixed noise variance estimate for Sentinel-1 VV backscatter
    # Typical value for agricultural areas in linear power units
    # This avoids the slow reduceRegion operation
    noise_var = ee.Image.constant(0.001)  # Fixed estimate
    
    # Calculate weighting factor: W = Var / (Var + NoiseVar)
    # Where W approaches 1 in high-variance (edge) areas and 0 in low-variance (smooth) areas
    weights = variance.divide(variance.add(noise_var)).clamp(0, 1)
    
    # Apply Lee filter: Filtered = Mean + W * (Original - Mean)
    filtered = mean.add(weights.multiply(image.subtract(mean)))
    
    return filtered

def get_nearest_image_with_coverage(collection, target_date, aoi, coverage_threshold=0.95):
    """
    Find the image nearest to target_date.
    Simplified version without coverage checking to avoid slow server-side operations.
    
    Args:
        collection: ee.ImageCollection - Collection to search
        target_date: ee.Date - Target date to find nearest image
        aoi: ee.Geometry - Area of interest (not used in simplified version)
        coverage_threshold: float - Not used in simplified version
    
    Returns:
        ee.Image or None - Nearest image, or None if collection is empty
    """
    try:
        # Add time difference property to each image
        def add_time_diff(img):
            diff = ee.Number(img.get('system:time_start')).subtract(target_date.millis()).abs()
            return img.set('time_diff', diff)
        
        # Sort by time difference (nearest first) and get the first image
        sorted_col = collection.map(add_time_diff).sort('time_diff')
        
        # Check if collection is empty
        size = sorted_col.size().getInfo()
        if size == 0:
            print("No images found in collection")
            return None
        
        # Return the nearest image
        nearest_img = sorted_col.first()
        print(f"Selected nearest Sentinel-1 image from collection of {size} images")
        return nearest_img
        
    except Exception as e:
        print(f"Error in nearest image selection: {e}")
        return None

def get_sentinel1_soil_moisture_simple(aoi, start_date, end_date):
    """
    Sentinel-1 soil moisture with minimal processing for performance.
    Uses focal median for light speckle reduction and adjusted fixed bounds.
    """
    try:
        # 1. Fetch Sentinel-1 Data
        sen1 = ee.ImageCollection("COPERNICUS/S1_GRD") \
                 .filterDate(start_date, end_date) \
                 .filterBounds(aoi) \
                 .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV')) \
                 .filter(ee.Filter.eq('instrumentMode', 'IW')) \
                 .select('VV')
        
        # Safety Check: Return None immediately if no Sentinel-1 data
        if sen1.size().getInfo() == 0:
            return None

        def process_simple(img):
            """
            Minimal processing to preserve native 10m resolution.
            No smoothing filter - shows true Sentinel-1 spatial detail.
            """
            # Convert from dB to linear power (sigma naught)
            # Formula: sigma = 10^(dB/10)
            sigma = ee.Image(10).pow(img.divide(10))
            
            # NO FILTERING - preserve native 10m resolution
            # This shows maximum spatial detail but may have speckle
            # Trade-off: High resolution vs some noise
            
            # ADJUSTED FIXED BOUNDS based on typical agricultural backscatter
            # Dry soil: ~-20dB (0.01 linear) to Wet soil: ~-8dB (0.16 linear)
            # Using slightly wider range to capture variation
            min_sigma = 0.005  # Very dry conditions
            max_sigma = 0.25   # Very wet conditions
            
            # Normalize to 0-100%
            # Higher backscatter = more moisture
            normalized = sigma.subtract(min_sigma) \
                              .divide(max_sigma - min_sigma) \
                              .clamp(0, 1) \
                              .multiply(100) \
                              .rename('soil_moisture')
            
            return normalized.copyProperties(img, img.propertyNames())
        
        # Process collection
        processed = sen1.map(process_simple)
        
        return processed
        
    except Exception as e:
        print(f"Sentinel-1 processing failed: {e}")
        return None

def get_combined_soil_moisture(aoi, date, sentinel1_col):
    """
    Get Soil Moisture combining Sentinel-1 and SMAP fallback.
    Returns: soil_moisture, sm_prev, deltaS, source_info
    """
    # Sentinel-1 (7-day window)
    if sentinel1_col:
        sm_window = sentinel1_col.filterDate(
            date.advance(-5, 'day'),
            date.advance(5, 'day')
        )
        sm_count = sm_window.size()
        sm_available = sm_count.gt(0)
    else:
        sm_count = ee.Number(0)
        sm_available = ee.Number(0)

    # SMAP
    smap_col = ee.ImageCollection("NASA/SMAP/SPL3SMP_E/006") \
                 .filterDate(date, date.advance(1, 'day')) \
                 .select('soil_moisture_am')
    smap_count = smap_col.size()

    # Determine Current Soil Moisture
    if sentinel1_col:
        sm_img = ee.Algorithms.If(
            sm_available,
            sm_window.mean().rename('SoilMoisture'),
            ee.Algorithms.If(
                smap_count.gt(0),
                smap_col.mean().multiply(200).rename('SoilMoisture'),
                ee.Image.constant(35).rename('SoilMoisture')
            )
        )
    else:
        sm_img = ee.Algorithms.If(
            smap_count.gt(0),
            smap_col.mean().multiply(200).rename('SoilMoisture'),
            ee.Image.constant(35).rename('SoilMoisture')
        )
    
    sm_img = ee.Image(sm_img)

    # Previous day soil moisture for deltaS
    if sentinel1_col:
        sm_prev_window = sentinel1_col.filterDate(
            date.advance(-5, 'day'),
            date.advance(-1, 'day')
        )
        sm_prev_available = sm_prev_window.size().gt(0)
        sm_prev_img = ee.Algorithms.If(
            sm_prev_available,
            sm_prev_window.mean().rename('SoilMoisturePrev'),
            sm_img.rename('SoilMoisturePrev')
        )
    else:
        sm_prev_col = ee.ImageCollection("NASA/SMAP/SPL3SMP_E/006") \
                        .filterDate(date.advance(-1, 'day'), date) \
                        .select('soil_moisture_am')
        sm_prev_img = ee.Algorithms.If(
            sm_prev_col.size().gt(0),
            sm_prev_col.mean().multiply(200).rename('SoilMoisturePrev'),
            sm_img.rename('SoilMoisturePrev')
        )
    
    sm_prev_img = ee.Image(sm_prev_img)

    deltaS_mm = sm_img.subtract(sm_prev_img).rename('DeltaS_mm')
    
    source = ee.Algorithms.If(
        sentinel1_col,
        ee.Algorithms.If(sm_available, 'Sentinel-1', 
                        ee.Algorithms.If(smap_count.gt(0), 'SMAP', 'Default')),
        ee.Algorithms.If(smap_count.gt(0), 'SMAP', 'Default')
    )
    
    return sm_img, deltaS_mm, source, sm_count, smap_count

def get_soil_moisture(aoi, start_date, end_date):
    """
    Main entry point for getting soil moisture collection.
    Prioritizes Sentinel-1, falls back to SMAP.
    Returns: ee.ImageCollection with 'soil_moisture' band (0-100 scale)
    """
    # 1. Try Sentinel-1
    s1_col = get_sentinel1_soil_moisture_simple(aoi, start_date, end_date)
    
    if s1_col and s1_col.size().getInfo() > 0:
        return s1_col
        
    # 2. Fallback to SMAP
    print("Sentinel-1 data not available, falling back to SMAP...")
    try:
        smap = ee.ImageCollection("NASA/SMAP/SPL3SMP_E/006") \
                 .filterDate(start_date, end_date) \
                 .filterBounds(aoi) \
                 .select('soil_moisture_am')
        
        if smap.size().getInfo() > 0:
             # Normalize SMAP (approximate) - raw is cm^3/cm^3, scale to 0-100 like S1
             return smap.map(lambda img: img.multiply(200).rename('soil_moisture').copyProperties(img, img.propertyNames()))
    except Exception as e:
        print(f"SMAP fallback failed: {e}")
        
    return None
