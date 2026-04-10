import { useState, useRef, useEffect } from 'react';
import { useApp } from '../context/AppContext';

const layerLegends = {
    ndvi: {
        title: 'NDVI',
        continuous: true,
        items: [
            { color: '#006400', label: 'Excellent' },
            { color: '#228B22', label: 'Good' },
            { color: '#32CD32', label: 'Moderate' },
            { color: '#FFD700', label: 'Needs Attention' },
            { color: '#8B4513', label: 'Poor' },
        ],
    },
    savi: {
        title: 'SAVI',
        continuous: true,
        items: [
            { color: '#006400', label: 'Full Crop' },
            { color: '#32CD32', label: 'Healthy Crop' },
            { color: '#FFFF00', label: 'Sparse Crop' },
            { color: '#8B4513', label: 'Mostly Soil' },
        ],
    },
    evi: {
        title: 'EVI ',
        continuous: true,
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
            { color: '#FF0000', label: 'Extreme' },
            { color: '#FF6666', label: 'Moderate' },
            { color: '#FFFF00', label: 'Need Attention' },
            { color: '#87CEEB', label: 'Fair' },
            { color: '#0000FF', label: 'Healthy' },
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
            { color: '#00FF00', label: 'High (Peak Growth)' },
            { color: '#7FFF00', label: 'Mid-High Growth' },
            { color: '#FFFF00', label: 'Moderate (Mid Season)' },
            { color: '#FF7F00', label: 'Early Growth' },
            { color: '#FF0000', label: 'Low (Initial Phase)' },
        ],
    },
    etc: {
        title: 'ETc (mm/day)',
        continuous: true,
        items: [
            { color: '#D7191C', label: 'Very High Water Use' },
            { color: '#FDAE61', label: 'High Water Use' },
            { color: '#FFFFBF', label: 'Moderate Water Use' },
            { color: '#ABD9E9', label: 'Low Water Use' },
            { color: '#2C7BB6', label: 'Very Low Water Use' },




        ],
    },
    irrigation_need: {
        title: 'Irrigation Need (mm/day)',
        continuous: true,
        items: [
            { color: '#C62828', label: 'Heavy Watering Needed' },
            { color: '#F57C00', label: 'Medium Watering Needed' },
            { color: '#FFB74D', label: 'Light Watering Needed' },
            { color: '#FFF9C4', label: 'Minimal Watering Needed' },
            { color: '#E8F5E9', label: 'No Watering Needed' },
        ],
    },
    vra_ndvi: {
        title: 'NDVI Zones',
        continuous: true,
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
        continuous: true,
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
        continuous: true,
        items: [
            { color: '#00441b', label: 'Highest' },
            { color: '#238b45', label: 'High' },
            { color: '#74c476', label: 'Moderate' },
            { color: '#a1d99b', label: 'Low' },
            { color: '#c7e9c0', label: 'Lowest' },
        ],
    },
    vra_cwsi: {
        title: 'Water Stress Zones',
        continuous: true,
        items: [
            { color: '#E57373', label: 'Severe Stress' },
            { color: '#FFB74D', label: 'High Stress' },
            { color: '#FFFF8D', label: 'Moderate' },
            { color: '#4FC3F7', label: 'Low Stress' },
            { color: '#81D4FA', label: 'No Stress' },
        ],
    },
    vra_irrigation_need: {
        title: 'Irrigation Need Zones',
        continuous: true,
        items: [
            { color: '#08306b', label: 'Highest Need' },
            { color: '#2171b5', label: 'High Need' },
            { color: '#6baed6', label: 'Moderate' },
            { color: '#c6dbef', label: 'Low Need' },
            { color: '#f7fbff', label: 'Minimal' },
        ],
    },
    vra_kc: {
        title: 'Crop Coefficient Zones',
        continuous: true,
        items: [
            { color: '#004529', label: 'Highest' },
            { color: '#238443', label: 'High' },
            { color: '#78C679', label: 'Moderate' },
            { color: '#D9F0A3', label: 'Low' },
            { color: '#FFFFE5', label: 'Lowest' },
        ],
    },
    vra_soilmoisture: {
        title: 'Soil Moisture Zones',
        continuous: true,
        items: [
            { color: '#08306b', label: 'Highest' },
            { color: '#2171b5', label: 'High' },
            { color: '#6baed6', label: 'Moderate' },
            { color: '#c6dbef', label: 'Low' },
            { color: '#f7fbff', label: 'Lowest' },
        ],
    },
    vra_lst: {
        title: 'Temperature Zones',
        continuous: true,
        items: [
            { color: '#bd0026', label: 'Hottest' },
            { color: '#f03b20', label: 'Hot' },
            { color: '#feb24c', label: 'Moderate' },
            { color: '#ffeda0', label: 'Cool' },
            { color: '#ffffcc', label: 'Coolest' },
        ],
    },
    vra_etc: {
        title: 'Evapotranspiration Zones',
        continuous: true,
        items: [
            { color: '#54278f', label: 'Highest' },
            { color: '#756bb1', label: 'High' },
            { color: '#9e9ac8', label: 'Moderate' },
            { color: '#c6dbef', label: 'Low' },
            { color: '#f7fcfd', label: 'Lowest' },
        ],
    },
    vra_irrigation: {
        title: 'Irrigation Zones',
        items: [
            { color: '#FF0000', label: 'Urgent Irrigation' },
            { color: '#FFFF00', label: 'Moderate Irrigation' },
            { color: '#00FF00', label: 'No Irrigation' },
        ],
    },

    soilmoisture: {
        title: 'Soil Moisture (%)',
        continuous: true,
        items: [
            { color: 'blue', label: 'Very High (> 80%)' },
            { color: 'darkgreen', label: 'High (60 - 80%)' },
            { color: 'lightgreen', label: 'Moderate (40 - 60%)' },
            { color: 'yellow', label: 'Low (20 - 40%)' },
            { color: 'brown', label: 'Very Low (< 20%)' },
        ],
    },
    pca: {
        title: 'Crop Health',
        continuous: true,
        items: [
            { color: '#1a9850', label: 'Very Healthy' },
            { color: '#91cf60', label: 'Healthy' },
            { color: '#fee08b', label: 'Average' },
            { color: '#fc8d59', label: 'Poor' },
            { color: '#d73027', label: 'Very Poor' },
        ],
    },
    vra_pca: {
        title: 'Crop Health Zones',
        continuous: true,
        items: [
            { color: '#00441b', label: 'Highest' },
            { color: '#238b45', label: 'High' },
            { color: '#74c476', label: 'Moderate' },
            { color: '#a1d99b', label: 'Low' },
            { color: '#c7e9c0', label: 'Lowest' },
        ],
    },
    // Chlorophyll Red-Edge Index (CLRe = B7/B5 - 1) — continuous gradient legend
    chlorophyll: {
        title: 'Chlorophyll (CLRe)',
        continuous: true,
        unit: '0 → 2+',
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
        continuous: true,
        items: [
            { color: '#2e6b2d', label: 'Highest' },
            { color: '#4d9c44', label: 'High' },
            { color: '#7bbf6a', label: 'Moderate' },
            { color: '#a8d5a2', label: 'Low' },
            { color: '#d0f0c0', label: 'Lowest' },
        ],
    },
    // RGB/TCC layers don't need a legend - they're visual representations
};

function MapLegend({ layerType, stats, opacity, onOpacityChange, layerLabel, initialPosition }) {
    const { isDarkMode } = useApp();
    const [position, setPosition] = useState(initialPosition || { x: 20, y: 80 });
    const [isDragging, setIsDragging] = useState(false);
    const dragStartRef = useRef({ x: 0, y: 0 });
    const legendRef = useRef(null);

    const legend = layerLegends[layerType];

    // Determine items to display: Prefer dynamic 'stats' if it's an array (VRA classes), otherwise use static legend
    const displayItems = Array.isArray(stats) ? stats.map((item, i) => {
        // Initialize label with descriptive text if possible, otherwise keep 'Zone X' as last resort
        let label = `Zone ${item['class']}`;

        // ----------------------------------------------------------------------------------
        // DYNAMIC LEGEND LABEL MATCHING LOGIC
        // ----------------------------------------------------------------------------------
        if (legend && legend.items) {
            // 1. Try Precise Color Match (Best)
            let staticItem = legend.items.find(si =>
                si.color.toLowerCase() === item.color.toLowerCase()
            );

            // 2. Fallback: Structural Match (Reverse Order)
            // Backend lists classes Low->High (Ascending). 
            // Frontend legend usually lists High->Low (Descending).
            // IF counts match (e.g. 5 vs 5), map index i to (len - 1 - i).
            // This ensures we always show a descriptive label even if colors slightly differ.
            if (!staticItem) {
                if (legend.items.length === stats.length) {
                    staticItem = legend.items[legend.items.length - 1 - i];
                }
            }

            if (staticItem) {
                label = staticItem.label;
            }
        }

        return {
            color: item.color,
            label: label
        };
    }) : (legend ? legend.items : []);



    const title = legend ? legend.title : layerType;

    const handleMouseDown = (e) => {
        setIsDragging(true);
        dragStartRef.current = {
            x: e.clientX - position.x,
            y: e.clientY - position.y,
        };
    };

    const handleMouseMove = (e) => {
        if (!isDragging || !legendRef.current) return;

        // Get legend dimensions
        const legendRect = legendRef.current.getBoundingClientRect();
        const legendWidth = legendRect.width;
        const legendHeight = legendRect.height;

        // Get map container bounds (assuming legend is inside .main-panel)
        const mapContainer = legendRef.current.closest('.main-panel');
        if (!mapContainer) return;

        const containerRect = mapContainer.getBoundingClientRect();

        // Calculate new position
        let newX = e.clientX - dragStartRef.current.x;
        let newY = e.clientY - dragStartRef.current.y;

        // Constrain within map bounds
        const minX = 10;
        const minY = 10;
        const maxX = containerRect.width - legendWidth - 10;
        const maxY = containerRect.height - legendHeight - 10;

        newX = Math.max(minX, Math.min(newX, maxX));
        newY = Math.max(minY, Math.min(newY, maxY));

        setPosition({
            x: newX,
            y: newY,
        });
    };

    const handleMouseUp = () => {
        setIsDragging(false);
    };

    useEffect(() => {
        if (isDragging) {
            document.addEventListener('mousemove', handleMouseMove);
            document.addEventListener('mouseup', handleMouseUp);
        } else {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
        }
        return () => {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
        };
    }, [isDragging]);

    if (!legend && !Array.isArray(stats)) return null;

    // Continuous gradient rendering for CLRe (and any future continuous legend)
    const isContinuous = legend?.continuous;
    const gradientColors = isContinuous
        ? [...legend.items].reverse().map(i => i.color) // low → high
        : null;
    const gradientCSS = isContinuous
        ? `linear-gradient(to top, ${gradientColors.join(', ')})`
        : null;

    return (
        <div
            ref={legendRef}
            className="map-legend"
            style={{
                position: 'absolute',
                top: position.y,
                right: 'auto',
                left: position.x,
                cursor: isDragging ? 'grabbing' : 'grab',
            }}
            onMouseDown={handleMouseDown}
        >
            {/* When used inside ComparisonView: show layer name + opacity slider */}
            {onOpacityChange && (
                <>
                    <h4 style={{ marginTop: 0, marginBottom: 6 }}>{layerLabel || title}</h4>
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        marginBottom: 8,
                        paddingBottom: 8,
                        borderBottom: '1px solid rgba(0,0,0,0.1)',
                        fontSize: '0.75em',
                    }}>
                        <label style={{ whiteSpace: 'nowrap', color: isDarkMode ? '#ccc' : '#555' }}>Op: {opacity}%</label>
                        <input
                            type="range"
                            min="0"
                            max="100"
                            value={opacity}
                            onChange={(e) => onOpacityChange(parseInt(e.target.value))}
                            onMouseDown={(e) => e.stopPropagation()}
                            style={{ flex: 1, cursor: 'pointer' }}
                        />
                    </div>
                    <h4 style={{ marginTop: 0 }}>{title}</h4>
                </>
            )}
            {!onOpacityChange && <h4>{title}</h4>}

            {isContinuous ? (
                /* ── Continuous gradient bar ── */
                <div style={{ display: 'flex', alignItems: 'stretch', gap: 8 }}>
                    {/* Gradient bar */}
                    <div style={{
                        width: 18,
                        height: 130,
                        borderRadius: 6,
                        background: gradientCSS,
                        flexShrink: 0,
                        boxShadow: '0 1px 4px rgba(0,0,0,0.18)',
                    }} />
                    {/* Tick labels — evenly spaced */}
                    <div style={{
                        display: 'flex',
                        flexDirection: 'column',
                        justifyContent: 'space-between',
                        height: 130,
                    }}>
                        {legend.items.map((item, idx) => (
                            <div key={idx} style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: 5,
                                fontSize: '0.72em',
                                lineHeight: 1.2,
                                color: isDarkMode ? '#e0e0e0' : '#333',
                            }}>
                                {/* Small tick dot matching the gradient colour at this level */}
                                <span style={{
                                    width: 7,
                                    height: 7,
                                    borderRadius: '50%',
                                    background: item.color,
                                    border: '1px solid rgba(0,0,0,0.25)',
                                    flexShrink: 0,
                                }} />
                                {item.label}
                            </div>
                        ))}
                    </div>
                </div>
            ) : (
                /* ── Discrete swatches (existing behaviour) ── */
                <div className="legend-scale">
                    {displayItems.map((item, index) => (
                        <div key={index} className="legend-item">
                            <span className="legend-color" style={{ backgroundColor: item.color }}></span>
                            <span className="legend-label">{item.label}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

export default MapLegend;
