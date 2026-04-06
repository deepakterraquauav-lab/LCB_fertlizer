import { useEffect, useRef, useState, useCallback } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './ComparisonView.css';
import { fetchGeeTile, fetchVraMap } from '../utils/api';
import { t } from '../utils/translations';
import DateCarousel from './DateCarousel';
import MapLegend from './MapLegend';

const LAYER_OPTIONS = [
    { value: 'rgb', label: 'FCC' },
    { value: 'ndvi', label: 'NDVI' },
    { value: 'savi', label: 'SAVI' },
    { value: 'cwsi', label: 'CWSI' },
    { value: 'lst', label: 'LST' },
    { value: 'lai', label: 'LAI' },
    { value: 'kc', label: 'Kc' },
    { value: 'etc', label: 'ETc' },
    { value: 'chlorophyll', label: 'Chlorophyll (CLRe)' },
    { value: 'irrigation_need', label: 'Irrigation Need' },
    { value: 'vra_ndvi', label: 'NDVI Zonal Map' },
    { value: 'vra_savi', label: 'SAVI Zonal Map' },
    { value: 'vra_cwsi', label: 'CWSI Zonal Map' },
    { value: 'vra_lai', label: 'LAI Zonal Map' },
    { value: 'vra_lst', label: 'LST Zonal Map' },
    { value: 'vra_etc', label: 'ETc Zonal Map' },
    { value: 'vra_irrigation_need', label: 'Irrigation Need Zonal Map' },
    { value: 'vra_soilmoisture', label: 'Soil Moisture Zonal Map' },
    { value: 'vra_irrigation', label: 'Irrigation Zonal Map' },
    { value: 'vra_kc', label: 'Kc Zonal Map' },
    { value: 'vra_pca', label: 'Crop Health Zonal Map' },
    { value: 'vra_chlorophyll', label: 'Chlorophyll Zonal Map' },
    { value: 'pca', label: 'Crop Health' },
];

const layerLegends = {
    ndvi: {
        title: 'NDVI (Crop Health)',
        continuous: true,
        items: [
            { color: '#006400', label: 'Very Dense (> 0.8)' },
            { color: '#228B22', label: 'Dense (0.6 - 0.8)' },
            { color: '#32CD32', label: 'Moderate (0.4 - 0.6)' },
            { color: '#FFD700', label: 'Sparse (0.2 - 0.4)' },
            { color: '#8B4513', label: 'Bare/Stress (< 0.2)' },
        ],
    },
    savi: {
        title: 'SAVI',
        continuous: true,
        items: [
            { color: '#006400', label: 'High (> 0.75)' },
            { color: '#32CD32', label: 'Moderate (0.5 - 0.75)' },
            { color: '#FFFF00', label: 'Low (0.25 - 0.5)' },
            { color: '#8B4513', label: 'Very Low (< 0.25)' },
        ],
    },
    evi: {
        title: 'EVI (Enhanced Vegetation Index)',
        items: [
            { color: '#006400', label: 'Very High (> 0.7)' },
            { color: '#00FF00', label: 'High (0.5 - 0.7)' },
            { color: '#7FFF00', label: 'Moderate (0.3 - 0.5)' },
            { color: '#FFFF00', label: 'Low (0.1 - 0.3)' },
            { color: '#F4A460', label: 'Very Low (0 - 0.1)' },
            { color: '#8B4513', label: 'Bare (< 0)' },
        ],
    },
    cwsi: {
        title: 'CWSI (Water Stress)',
        continuous: true,
        items: [
            { color: '#FF0000', label: 'Severe (> 0.6)' },
            { color: '#FF6666', label: 'High Stress (0.4 - 0.6)' },
            { color: '#FFFF00', label: 'Moderate (0.3 - 0.4)' },
            { color: '#87CEEB', label: 'Low Stress (0.15 - 0.3)' },
            { color: '#0000FF', label: 'No Stress (< 0.15)' },
        ],
    },
    lst: {
        title: 'Temperature (°C)',
        continuous: true,
        items: [
            { color: '#8B0000', label: '> 47°C (Hot)' },
            { color: '#FF4500', label: '37 - 47°C' },
            { color: '#FFA500', label: '27 - 37°C' },
            { color: '#FFFF00', label: '17 - 27°C' },
            { color: '#00FFFF', label: '7 - 17°C' },
            { color: '#0000FF', label: '< 7°C (Cool)' },
        ],
    },
    lai: {
        title: 'LAI (Leaf Area Index)',
        continuous: true,
        items: [
            { color: '#006400', label: 'High (> 4.5)' },
            { color: '#228B22', label: 'Moderate (3 - 4.5)' },
            { color: '#32CD32', label: 'Low (1.5 - 3)' },
            { color: '#FFD700', label: 'Very Low (0.5 - 1.5)' },
            { color: '#964B00', label: 'Minimal (< 0.5)' },
        ],
    },
    kc: {
        title: 'Kc (Crop Coefficient)',
        continuous: true,
        items: [
            { color: '#00FF00', label: 'Very High (> 1.2)' },
            { color: '#7FFF00', label: 'High (1.0 - 1.2)' },
            { color: '#FFFF00', label: 'Moderate (0.6 - 1.0)' },
            { color: '#FF7F00', label: 'Low (0.3 - 0.6)' },
            { color: '#FF0000', label: 'Initial (< 0.3)' },
        ],
    },
    etc: {
        title: 'ETc (mm/day)',
        continuous: true,
        items: [
            { color: '#2C7BB6', label: 'Very Low (< 2)' },
            { color: '#ABD9E9', label: 'Low (2 - 4)' },
            { color: '#FFFFBF', label: 'Mod (4 - 6)' },
            { color: '#FDAE61', label: 'High-Mod (6 - 8)' },
            { color: '#D7191C', label: 'High (> 8)' },
        ],
    },
    irrigation_need: {
        title: 'Irrigation Need (mm/day)',
        continuous: true,
        items: [
            { color: '#990000', label: 'High (> 5)' },
            { color: '#FF3300', label: 'Medium (3 - 5)' },
            { color: '#FF9900', label: 'Low-Med (1 - 3)' },
            { color: '#FFCC00', label: 'Low (< 1)' },
            { color: '#808080', label: 'Minimal/None' },
        ],
    },
    vra_ndvi: {
        title: 'Crop Health (NDVI)',
        items: [
            { color: '#00441b', label: 'Highest' },
            { color: '#238b45', label: 'High' },
            { color: '#74c476', label: 'Moderate' },
            { color: '#c7e9c0', label: 'Low' },
            { color: '#f7fcf5', label: 'Lowest' },
        ],
    },
    vra_savi: {
        title: 'SAVI',
        items: [
            { color: '#00441b', label: 'Highest' },
            { color: '#238b45', label: 'High' },
            { color: '#74c476', label: 'Moderate' },
            { color: '#c7e9c0', label: 'Low' },
            { color: '#f7fcf5', label: 'Lowest' },
        ],
    },
    vra_lai: {
        title: 'Leaf Area Index',
        items: [
            { color: '#00441b', label: 'Highest' },
            { color: '#238b45', label: 'High' },
            { color: '#74c476', label: 'Moderate' },
            { color: '#c7e9c0', label: 'Low' },
            { color: '#f7fcf5', label: 'Lowest' },
        ],
    },
    vra_cwsi: {
        title: 'Water Stress (CWSI)',
        items: [
            { color: '#E57373', label: 'Severe Stress' },
            { color: '#FFB74D', label: 'High Stress' },
            { color: '#FFFF8D', label: 'Moderate' },
            { color: '#4FC3F7', label: 'Low Stress' },
            { color: '#81D4FA', label: 'No Stress' },
        ],
    },
    vra_irrigation_need: {
        title: 'Irrigation Need',
        items: [
            { color: '#08306b', label: 'Highest Need' },
            { color: '#2171b5', label: 'High Need' },
            { color: '#6baed6', label: 'Moderate' },
            { color: '#c6dbef', label: 'Low Need' },
            { color: '#f7fbff', label: 'Minimal' },
        ],
    },
    vra_kc: {
        title: 'Crop Coefficient (Kc)',
        items: [
            { color: '#004529', label: 'Highest' },
            { color: '#238443', label: 'High' },
            { color: '#78C679', label: 'Moderate' },
            { color: '#D9F0A3', label: 'Low' },
            { color: '#FFFFE5', label: 'Lowest' },
        ],
    },
    vra_soilmoisture: {
        title: 'Soil Moisture',
        items: [
            { color: '#08306b', label: 'Highest' },
            { color: '#2171b5', label: 'High' },
            { color: '#6baed6', label: 'Moderate' },
            { color: '#c6dbef', label: 'Low' },
            { color: '#f7fbff', label: 'Lowest' },
        ],
    },
    vra_lst: {
        title: 'Temperature (LST)',
        items: [
            { color: '#bd0026', label: 'Hottest' },
            { color: '#f03b20', label: 'Hot' },
            { color: '#feb24c', label: 'Moderate' },
            { color: '#ffeda0', label: 'Cool' },
            { color: '#ffffcc', label: 'Coolest' },
        ],
    },
    vra_etc: {
        title: 'Evapotranspiration (ETc)',
        items: [
            { color: '#54278f', label: 'Highest' },
            { color: '#756bb1', label: 'High' },
            { color: '#9e9ac8', label: 'Moderate' },
            { color: '#c6dbef', label: 'Low' },
            { color: '#f7fcfd', label: 'Lowest' },
        ],
    },
    vra_irrigation: {
        title: 'VRA Irrigation Map',
        items: [
            { color: '#FF0000', label: 'Urgent Irrigation' },
            { color: '#FFFF00', label: 'Moderate Irrigation' },
            { color: '#00FF00', label: 'No Irrigation' },
        ],
    },
    soilmoisture: {
        title: 'Soil Moisture (%)',
        items: [
            { color: 'blue', label: 'Very High' },
            { color: 'darkgreen', label: 'High' },
            { color: 'lightgreen', label: 'Moderate' },
            { color: 'yellow', label: 'Low' },
            { color: 'brown', label: 'Very Low' },
        ],
    },
    pca: {
        title: 'Crop Health',
        items: [
            { color: '#1a9850', label: 'Very High Vigor' },
            { color: '#91cf60', label: 'High Vigor' },
            { color: '#d9ef8b', label: 'Moderate-High' },
            { color: '#fee08b', label: 'Moderate-Low' },
            { color: '#fc8d59', label: 'Low Vigor' },
            { color: '#d73027', label: 'Very Low' },
        ],
    },
    vra_pca: {
        title: 'PCA Management Zones',
        items: [
            { color: '#00441b', label: 'Zone 5 (Highest Potential)' },
            { color: '#238b45', label: 'Zone 4 (High Potential)' },
            { color: '#74c476', label: 'Zone 3 (Moderate)' },
            { color: '#c7e9c0', label: 'Zone 2 (Low Potential)' },
            { color: '#f7fcf5', label: 'Zone 1 (Lowest/Monitor)' },
        ],
    },
    rgb: { items: [{ color: '#FF0000', label: 'Veg' }, { color: '#00FFFF', label: 'Water' }, { color: '#808080', label: 'Bare' }] },
    // Chlorophyll Red-Edge Index (CLRe = B7/B5 - 1) — Sentinel-2 only
    chlorophyll: {
        title: 'Chlorophyll (CLRe)',
        continuous: true,
        items: [
            { color: '#2e6b2d', label: 'Very High (>1.5)' },
            { color: '#4d9c44', label: 'High (1.0–1.5)' },
            { color: '#7bbf6a', label: 'Moderate (0.7–1.0)' },
            { color: '#a8d5a2', label: 'Low (0.3–0.7)' },
            { color: '#d0f0c0', label: 'Very Low (<0.3)' },
        ],
    },
    vra_chlorophyll: {
        title: 'Chlorophyll Zones (CLRe)',
        items: [
            { color: '#2e6b2d', label: 'Zone 5 — Rich' },
            { color: '#4d9c44', label: 'Zone 4 — High' },
            { color: '#7bbf6a', label: 'Zone 3 — Moderate' },
            { color: '#a8d5a2', label: 'Zone 2 — Low' },
            { color: '#d0f0c0', label: 'Zone 1 — Deficient' },
        ],
    },
};

function ComparisonView({ layers, onClose, drawnAOI, startDate: globalStart, endDate: globalEnd }) {
    const mapsRef = useRef([]);
    const containerRef = useRef(null);
    const [paneConfigs, setPaneConfigs] = useState([]);
    const [isLoading, setIsLoading] = useState(true);

    // Initialize state from props
    useEffect(() => {
        if (!layers || layers.length < 2) return;

        // Map layers prop to config state with defaults
        const initialConfigs = layers.map(l => ({
            ...l,
            // Ensure we have a date, fallback to global props
            date: l.date || { start: globalStart, end: globalEnd },
            // Ensure opacity
            opacity: l.opacity !== undefined ? l.opacity : 100,
            highContrast: false // Default
        }));
        setPaneConfigs(initialConfigs);
    }, [layers, globalStart, globalEnd]);

    // Initialize Maps once state is ready
    useEffect(() => {
        if (paneConfigs.length === 0) return;

        const timer = setTimeout(() => {
            initializeMaps();
        }, 100);

        return () => {
            clearTimeout(timer);
            cleanup();
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [paneConfigs.length]); // Only run when count changes (init)

    const cleanup = () => {
        mapsRef.current.forEach(mapInst => {
            if (mapInst && mapInst.remove) {
                mapInst.remove();
            }
        });
        mapsRef.current = [];
    };

    const initializeMaps = async () => {
        setIsLoading(true);
        cleanup(); // Ensure clean slate

        const mapPromises = paneConfigs.map(async (config, index) => {
            const mapId = `comp-map-${index}`;
            const mapElement = document.getElementById(mapId);

            if (!mapElement) return null;

            // Init Map
            const compMap = L.map(mapId, {
                zoomControl: false,
                attributionControl: false,
                zoomSnap: 0.5 // Smoother zoom sync
            });

            // Base Layer
            L.tileLayer('https://{s}.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', {
                maxZoom: 22,
                subdomains: ['mt0', 'mt1', 'mt2', 'mt3']
            }).addTo(compMap);

            // Fit Bounds
            if (drawnAOI) {
                const bounds = L.geoJSON(drawnAOI).getBounds();
                compMap.fitBounds(bounds);
            } else {
                compMap.setView([20.59, 78.96], 5);
            }

            // Load Layer
            await updateOneMapLayer(compMap, config);

            // Invalidate size
            setTimeout(() => {
                compMap.invalidateSize();
            }, 200);

            return compMap;
        });

        const maps = await Promise.all(mapPromises);
        mapsRef.current = maps.filter(m => m !== null);

        if (mapsRef.current.length > 1) {
            setupMultiMapSync(mapsRef.current);
        }

        setIsLoading(false);
    };

    const updateOneMapLayer = async (mapInst, config) => {
        if (!mapInst || !config) return;

        // Remove existing overlay if any
        if (mapInst._overlayLayer) {
            mapInst.removeLayer(mapInst._overlayLayer);
            mapInst._overlayLayer = null;
        }

        let url = config.url;

        // If no URL (or changed parameters require new fetch), fetch it
        // Note: modify this logic if you want to force re-fetch on param change.
        // For now, if URL is invalid or missing, fetch.
        // If we want to support changing params, we need to clear URL in state update.
        if (!url) {
            try {
                const isVraLayer = config.type.startsWith('vra_');
                let tileData;

                if (isVraLayer) {
                    const parameter = config.type.replace('vra_', '');
                    tileData = await fetchVraMap(drawnAOI, parameter, config.date.specific || null, config.date.start, config.date.end);
                } else {
                    const dateToUse = config.date.specific || null;
                    tileData = dateToUse
                        ? await fetchGeeTile(drawnAOI, config.type, null, null, dateToUse)
                        : await fetchGeeTile(drawnAOI, config.type, config.date.start, config.date.end);
                }

                if (tileData.error) throw new Error(tileData.error);
                url = tileData.urlFormat;

                // Update local config ref? No need, just use local var
                // We *could* update state to save this URL for future, but simpler to just use it.
            } catch (err) {
                console.error("Comparison load error:", err);
                return; // Fail gracefully
            }
        }

        if (url) {
            const layer = L.tileLayer(url, {
                opacity: config.opacity / 100,
                maxZoom: 23
            });
            layer.addTo(mapInst);
            mapInst._overlayLayer = layer;
        }
    };

    // Update specific pane (Logic for handlers)
    const updatePane = async (index, updates) => {
        const newConfigs = [...paneConfigs];
        // If critical params change, clear URL to force fetch
        const needsFetch = updates.type || updates.date || (updates.highContrast !== undefined);
        const oldOpacity = newConfigs[index].opacity;

        newConfigs[index] = {
            ...newConfigs[index],
            ...updates,
            url: needsFetch ? null : newConfigs[index].url
        };
        setPaneConfigs(newConfigs);

        // Update map immediately
        const mapInst = mapsRef.current[index];
        if (mapInst) {
            // Re-fetch logic or simple opacity update
            if (updates.opacity !== undefined && !needsFetch) {
                if (mapInst._overlayLayer) {
                    mapInst._overlayLayer.setOpacity(updates.opacity / 100);
                }
            } else {
                await updateOneMapLayer(mapInst, newConfigs[index]);
            }
        }
    };

    const setupMultiMapSync = (maps) => {
        // (Keep existing sync logic)
        let syncing = false;
        maps.forEach((sourceMap, sourceIndex) => {
            sourceMap.on('move zoom', () => {
                if (!syncing) {
                    syncing = true;
                    // Using requestAnimationFrame for smoother sync?
                    const center = sourceMap.getCenter();
                    const zoom = sourceMap.getZoom();
                    maps.forEach((targetMap, targetIndex) => {
                        if (targetIndex !== sourceIndex && targetMap) {
                            targetMap.setView(center, zoom, { animate: false });
                        }
                    });
                    setTimeout(() => { syncing = false; }, 50);
                }
            });
        });
    };

    const getGridClass = () => {
        const count = paneConfigs.length; // Use paneConfigs instead of layers prop
        if (count === 2) return 'grid-2';
        if (count === 3) return 'grid-3';
        if (count === 4) return 'grid-4';
        if (count <= 6) return `grid-${count}`;
        return 'grid-many';
    };

    const handleDateSelect = async (date) => {
        setIsLoading(true);
        const newConfigs = paneConfigs.map(c => {
            const needsFetch = !c.date || c.date.specific !== date;
            return {
                ...c,
                date: { start: globalStart, end: globalEnd, specific: date },
                url: needsFetch ? null : c.url
            };
        });

        setPaneConfigs(newConfigs);

        await Promise.all(newConfigs.map(async (c, index) => {
            const mapInst = mapsRef.current[index];
            if (mapInst && !c.url) {
                await updateOneMapLayer(mapInst, c);
            }
        }));

        setIsLoading(false);
    };

    return (
        <div className="comparison-view-fullscreen" ref={containerRef}>
            <button className="close-comparison-btn" onClick={onClose} title="Exit Comparison Mode">
                <i className="fa-solid fa-times"></i>
            </button>

            {isLoading && (
                <div className="comparison-loading">
                    <i className="fa-solid fa-spinner fa-spin"></i>
                    <p>Loading comparison maps...</p>
                </div>
            )}

            <div className={`comparison-grid ${getGridClass()}`}>
                {paneConfigs.map((config, index) => (
                    <div key={index} className="comparison-pane">
                        <div id={`comp-map-${index}`} className="comparison-map-container"></div>

                        {/* Single legend card with opacity slider built in */}
                        <MapLegend
                            layerType={config.type}
                            layerLabel={LAYER_OPTIONS.find(opt => opt.value === config.type)?.label || config.type.toUpperCase()}
                            opacity={config.opacity}
                            onOpacityChange={(val) => updatePane(index, { opacity: val })}
                            initialPosition={{ x: 10, y: 10 }}
                        />

                    </div>
                ))}
            </div>

            {drawnAOI && (
                <div className="comparison-global-carousel" style={{ position: 'absolute', bottom: '20px', left: '50%', transform: 'translateX(-50%)', zIndex: 1000, width: '90%', maxWidth: '800px', pointerEvents: 'auto' }}>
                    <DateCarousel
                        initialDate={paneConfigs[0]?.date?.specific || null}
                        onDateSelect={handleDateSelect}
                        autoSelect={false}
                    />
                </div>
            )}
        </div>
    );
}

export default ComparisonView;
