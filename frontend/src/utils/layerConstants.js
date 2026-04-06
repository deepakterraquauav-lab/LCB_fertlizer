// Layer Display Names Mapping
export const LAYER_DISPLAY_NAMES = {
    // Standard Layers
    'rgb': 'FCC',
    'ndvi': 'NDVI (Vegetation)',
    'savi': 'SAVI (Soil Adjusted)',
    'cwsi': 'CWSI (Water Stress)',
    'lst': 'LST (Land Temp)',
    'lai': 'LAI (Leaf Area)',
    'kc': 'Kc (Crop Coeff.)',
    'etc': 'ETc (Evapotranspiration)',
    'irrigation_need': 'Irrigation Need',
    'soilmoisture': 'Soil Moisture',
    'weather': 'Weather',
    'pca': 'Crop Health',

    // Zonal / VRA Layers
    'vra_ndvi': 'NDVI Zonal Map',
    'vra_savi': 'SAVI Zonal Map',
    'vra_cwsi': 'CWSI Zonal Map',
    'vra_lai': 'LAI Zonal Map',
    'vra_lst': 'LST Zonal Map',
    'vra_etc': 'ETc Zonal Map',
    'vra_irrigation_need': 'Irrigation Need Zonal Map',
    'vra_soilmoisture': 'Soil Moisture Zonal Map',
    'vra_irrigation': 'Irrigation Zonal Map',
    'vra_kc': 'Kc Zonal Map',
    'vra_pca': 'Crop Health Zonal Map',
};

// Start logic can vary, but usually `vra_` prefix check or direct lookup
export const getLayerDisplayName = (layerId) => {
    return LAYER_DISPLAY_NAMES[layerId] || layerId.toUpperCase().replace('VRA_', 'VRA - ');
};
