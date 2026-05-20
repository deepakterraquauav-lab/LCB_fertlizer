import { useRef, useState } from 'react';
import { useApp } from '../context/AppContext';
import { t } from '../utils/translations';
import Swal from 'sweetalert2';
import './MapControls.css';

import img_rgb from '../assets/img_rgb.png';
import img_ndvi from '../assets/img_ndvi.png';
import img_cwsi from '../assets/img_cwsi.png';
import img_lst from '../assets/img_lst.png';
import img_soil from '../assets/img_soil.png';
import img_irrigation from '../assets/img_irrigation.png';
import img_kc from '../assets/img_kc.png';
import img_etc from '../assets/img_etc.png';
import img_weather from '../assets/img_weather.png';
import img_lai from '../assets/img_lai.png';
import img_chlorophyll from '../assets/img_chlorophyll.png';
import { getLayerDisplayName } from '../utils/layerConstants';

function Sidebar({ onFetchData, onLayerChange, onClearMap, onVectorUpload, onGenerateCalendar, onViewCalendar, onGenerateReport, onQueryCurrentLayer, onCompare, onDownloadCSV }) {
    const {
        isSidebarOpen,
        toggleSidebar,
        startDate,
        setStartDate,
        endDate,
        setEndDate,
        selectedLayer,
        setSelectedLayer,
        opacity,
        setOpacity,
        isLoading,
        irrigationCalendar,
        setActiveChartParam,
        isFetchingData,
        isFetchingLayer,
        isGeneratingCalendar,
        isGeneratingReport,
        dateMode,
        setDateMode,
        baselineDate,
        setBaselineDate,
        baselineYears,
        setBaselineYears,
        isDarkMode,
        setShowBaselineWarning
    } = useApp();

    const [uploadedLayers, setUploadedLayers] = useState([]);
    const [isDragOver, setIsDragOver] = useState(false);
    const fileInputRef = useRef(null);

    const handleBaselineDateChange = (e) => {
        const selectedDate = e.target.value;
        setBaselineDate(selectedDate);
        setEndDate(selectedDate);
        
        const dateObj = new Date(selectedDate);
        dateObj.setFullYear(dateObj.getFullYear() - baselineYears);
        setStartDate(dateObj.toISOString().split('T')[0]);
    };

    const handleBaselineYearsChange = (e) => {
        const years = parseInt(e.target.value);
        setBaselineYears(years);
        
        const dateObj = new Date(baselineDate);
        dateObj.setFullYear(dateObj.getFullYear() - years);
        setStartDate(dateObj.toISOString().split('T')[0]);
    };

    // Map Controls Tab State
    const [activeMapTab, setActiveMapTab] = useState('select'); // select, aoi, add, clear
    const [managedLayers, setManagedLayers] = useState([]);
    const [isVraFolderOpen, setIsVraFolderOpen] = useState(true); // Default open

    const addToManagedLayers = () => {
        // Use the callback to get REAL layer info
        const currentLayerInfo = onQueryCurrentLayer ? onQueryCurrentLayer() : null;

        if (!currentLayerInfo) {
            // Fallback: If map is loaded but simple add requested? 
            // Better to enforce fetching.
            alert("Please load a layer on the map first!");
            return;
        }

        // Check if already added
        if (managedLayers.some(l => l.id === currentLayerInfo.type)) { // Simple check by type? or allow duplicates with diff dates?
            // Allow duplicates if timestamp differs? For now, unique by type/id logic from app2.
            // app2 uses Date.now() ID.
        }

        const newLayer = {
            id: Date.now(),
            ...currentLayerInfo, // url, type, stats, date, opacity
            visible: false
        };
        setManagedLayers([...managedLayers, newLayer]);
    };

    const toggleManagedLayer = (id) => {
        const layer = managedLayers.find(l => l.id === id);
        if (!layer) return;

        if (layer.visible) {
            // Hide
            window.mapFunctions?.removeOverlayLayer(id);
            setManagedLayers(managedLayers.map(l => l.id === id ? { ...l, visible: false } : l));
        } else {
            // Show
            if (window.mapFunctions?.addOverlayLayer) {
                window.mapFunctions.addOverlayLayer(id, layer.url, { opacity: layer.opacity / 100 });
                setManagedLayers(managedLayers.map(l => l.id === id ? { ...l, visible: true } : l));
            }
        }
    };

    const removeManagedLayer = (id) => {
        // Ensure removed from map
        window.mapFunctions?.removeOverlayLayer(id);
        setManagedLayers(managedLayers.filter(l => l.id !== id));
    };


    const handleCompare = () => {
        const selectedLayers = managedLayers.filter(l => l.visible);

        if (selectedLayers.length < 2) {
            alert("Please select at least 2 layers to compare!");
            return;
        }

        // Call parent callback to show comparison view
        if (onCompare) {
            onCompare(selectedLayers);
        }
    };

    // Handle date change
    const handleStartDateChange = (e) => {
        setStartDate(e.target.value);
    };

    const handleEndDateChange = (e) => {
        setEndDate(e.target.value);
    };

    // Map layer IDs to chart parameters
    const getChartParamForLayer = (layerId) => {
        // Handle VRA layers - extract base parameter
        if (layerId.startsWith('vra_')) {
            return layerId.replace('vra_', '');
        }

        // Map specific layers to chart parameters
        const layerToChartMap = {
            'ndvi': 'ndvi',
            'savi': 'savi',
            'cwsi': 'cwsi',
            'lst': 'lst',
            'lai': 'lai',
            'kc': 'kc',
            'etc': 'etc',
            'irrigation_need': 'irrigation_need',
            'soilmoisture': 'soilmoisture_mm',
            'chlorophyll': 'chlorophyll',
            'rgb': null, // RGB has no chart data
        };

        return layerToChartMap[layerId] || null;
    };

    // Helper to show baseline notification bar for exactly 5 seconds
    const showBaselineAlert = () => {
        setShowBaselineWarning(true);
    };

    // Handle layer selection change - AUTO-LOAD like app2.html
    const handleLayerSelectChange = (e) => {
        const value = e.target.value;
        setSelectedLayer(value);

        // Sync time series graph with selected layer (except RGB)
        const chartParam = getChartParamForLayer(value);
        if (chartParam) {
            setActiveChartParam(chartParam);
        }

        // If baseline mode, block layer loading on the map and show premium info alert
        if (dateMode === 'baseline') {
            showBaselineAlert();
            return;
        }

        // Auto-load layer when selected from dropdown (if AOI is drawn) - matches app2.html line 5089
        if (value && onLayerChange) {
            onLayerChange(value);
        }
    };

    // Handle Add Layer button click
    const handleAddLayer = () => {
        if (dateMode === 'baseline') {
            showBaselineAlert();
            return;
        }
        if (selectedLayer && onLayerChange) {
            onLayerChange(selectedLayer);
        }
    };

    // Handle opacity change
    const handleOpacityChange = (e) => {
        setOpacity(parseInt(e.target.value));
    };

    // Handle file upload
    const handleFileSelect = (file) => {
        if (!file) return;

        const validExtensions = ['.geojson', '.json', '.kml'];
        const isValid = validExtensions.some(ext => file.name.toLowerCase().endsWith(ext));

        if (!isValid) {
            alert('Please select a valid .geojson, .json, or .kml file.');
            return;
        }

        if (onVectorUpload) {
            onVectorUpload(file, (layerInfo) => {
                setUploadedLayers(prev => [...prev, layerInfo]);
            });
        }
    };

    // Handle drag events
    const handleDragEnter = (e) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragOver(true);
    };

    const handleDragLeave = (e) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragOver(false);
    };

    const handleDragOver = (e) => {
        e.preventDefault();
        e.stopPropagation();
    };

    const handleDrop = (e) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragOver(false);

        if (e.dataTransfer.files.length > 0) {
            handleFileSelect(e.dataTransfer.files[0]);
        }
    };

    // Remove uploaded layer
    const removeLayer = (index) => {
        setUploadedLayers(prev => prev.filter((_, i) => i !== index));
    };

    // Get today's date for max attribute
    const today = new Date().toISOString().split('T')[0];



    // Define available layers for the grid
    const allLayers = [
        { id: 'rgb', icon: 'fa-layer-group', label: 'FCC', color: '#3f51b5', img: img_rgb },
        { id: 'pca', icon: 'fa-wand-magic-sparkles', label: 'Crop Health', color: '#9c27b0', img: img_ndvi }, // Use NDVI or similar
        // { id: 'ndvi', icon: 'fa-leaf', label: 'NDVI', color: '#4caf50', img: img_ndvi },
        // { id: 'savi', icon: 'fa-seedling', label: 'Soil Adjusted (SAVI)', color: '#8bc34a' },
        // { id: 'cwsi', icon: 'fa-droplet', label: 'Water Stress (CWSI)', color: '#03a9f4', img: img_cwsi },
        // { id: 'lst', icon: 'fa-temperature-high', label: 'Land Temp (LST)', color: '#ff5722', img: img_lst },
        { id: 'lai', icon: 'fa-tree', label: 'Leaf Area (LAI)', color: '#009688', img: img_lai },
        { id: 'chlorophyll', icon: 'fa-leaf', label: 'Chlorophyll', color: '#8bc34a', img: img_chlorophyll },
        // { id: 'kc', icon: 'fa-chart-line', label: 'Crop Coeff. (Kc)', color: '#9c27b0', img: img_kc },
        // { id: 'etc', icon: 'fa-cloud-rain', label: 'Evap (ETc)', color: '#607d8b', img: img_etc },
        // { id: 'irrigation_need', icon: 'fa-faucet-drip', label: 'Irrigation', color: '#2196f3', img: img_irrigation },
        { id: 'soilmoisture', icon: 'fa-droplet-slash', label: 'Soil Moisture', color: '#795548', img: img_soil },
        // { id: 'weather', icon: 'fa-cloud-sun', label: 'Weather', color: '#607d8b', img: img_weather },
    ];

    // Define Zonal Map layers
    const zonalLayers = [
        { id: 'vra_pca', icon: 'fa-wand-magic-sparkles', label: 'Crop Health', color: '#9c27b0', img: img_ndvi },
        // { id: 'vra_ndvi', icon: 'fa-leaf', label: 'NDVI', color: '#4caf50', img: img_ndvi },
        // { id: 'vra_savi', icon: 'fa-seedling', label: 'SAVI', color: '#8bc34a' },
        // { id: 'vra_cwsi', icon: 'fa-droplet', label: 'CWSI', color: '#03a9f4', img: img_cwsi },
        { id: 'vra_lai', icon: 'fa-tree', label: 'LAI', color: '#009688', img: img_lai },
        { id: 'vra_chlorophyll', icon: 'fa-leaf', label: 'Chlorophyll', color: '#8bc34a', img: img_chlorophyll },        // { id: 'vra_kc', icon: 'fa-chart-line', label: 'Kc', color: '#9c27b0', img: img_kc },
        // { id: 'vra_lst', icon: 'fa-temperature-high', label: 'LST', color: '#ff5722', img: img_lst },
        // { id: 'vra_etc', icon: 'fa-cloud-rain', label: 'ETc', color: '#9c27b0', img: img_etc },
        // { id: 'vra_irrigation_need', icon: 'fa-faucet-drip', label: 'Irrigation Need', color: '#2196f3', img: img_irrigation },
        { id: 'vra_soilmoisture', icon: 'fa-droplet-slash', label: 'Soil Moisture', color: '#795548', img: img_soil },
    ];



    return (
        <aside className={`sidebar ${!isSidebarOpen ? 'collapsed' : ''}`}>
            <button
                className="close-sidebar-btn"
                onClick={toggleSidebar}
                title="Close Controls"
            >
                &times;
            </button>

            {/* Sidebar Header: Date Range - Made Compact */}
            <div className="sidebar-header">
                <div className="panel compact-panel">
                    <div className="date-mode-tabs" style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
                        <button 
                            onClick={() => setDateMode('custom')}
                            style={{ flex: 1, padding: '6px', fontSize: '12px', border: '1px solid var(--krishi-green)', background: dateMode === 'custom' ? 'var(--krishi-green)' : 'transparent', color: dateMode === 'custom' ? '#fff' : 'var(--text-main)', borderRadius: '4px', cursor: 'pointer' }}
                        >Custom Range</button>
                        <button 
                            onClick={() => {
                                setDateMode('baseline');
                                showBaselineAlert();
                            }}
                            style={{ flex: 1, padding: '6px', fontSize: '12px', border: '1px solid var(--krishi-green)', background: dateMode === 'baseline' ? 'var(--krishi-green)' : 'transparent', color: dateMode === 'baseline' ? '#fff' : 'var(--text-main)', borderRadius: '4px', cursor: 'pointer' }}
                        >Baseline Mode</button>
                    </div>

                    {dateMode === 'custom' ? (
                        <div className="date-inputs-row">
                            <div className="date-field">
                                <label htmlFor="start">Start Date</label>
                                <input
                                    id="start"
                                    type="date"
                                    max={today}
                                    value={startDate}
                                    onChange={handleStartDateChange}
                                />
                            </div>
                            <div className="date-field">
                                <label htmlFor="end">End Date</label>
                                <input
                                    id="end"
                                    type="date"
                                    max={today}
                                    value={endDate}
                                    onChange={handleEndDateChange}
                                />
                            </div>
                        </div>
                    ) : (
                        <div className="date-inputs-row" style={{ flexDirection: 'column', gap: '10px' }}>
                            <div className="date-field" style={{ width: '100%' }}>
                                <label htmlFor="baseline">Baseline Date</label>
                                <input
                                    id="baseline"
                                    type="date"
                                    max={today}
                                    value={baselineDate}
                                    onChange={handleBaselineDateChange}
                                    style={{ width: '100%', boxSizing: 'border-box' }}
                                />
                            </div>
                            <div className="date-field" style={{ width: '100%' }}>
                                <label>Historical Data</label>
                                <select 
                                    value={baselineYears} 
                                    onChange={handleBaselineYearsChange}
                                    style={{ width: '100%', padding: '6px', borderRadius: '4px', border: '1px solid var(--border-color)', background: 'var(--bg-light)', color: 'var(--text-main)', boxSizing: 'border-box' }}
                                >
                                    <option value={1}>1 Year</option>
                                    <option value={2}>2 Years</option>
                                    <option value={3}>3 Years</option>
                                </select>
                            </div>
                        </div>
                    )}
                    <button
                        className="btn action-btn-sm"
                        onClick={onFetchData}
                        disabled={isFetchingData}
                        style={{ marginTop: '12px', width: '100%', display: 'block' }}
                    >
                        {isFetchingData ? t('loading') || 'Loading...' : t('fetch_data')}
                    </button>
                </div>
            </div>

            {/* Sidebar Body: Map Controls (Expands) */}
            <div className="sidebar-body">

                <div className="panel map-controls-panel" style={{ border: 'none', padding: '0', boxShadow: 'none' }}>
                    <h3 className="panel-title">

                        <span>{t('map_controls')}</span>
                    </h3>

                    {/* Creative Segmented Control Tabs */}
                    <div className="segmented-control-container">
                        <div className="segmented-control">
                            {[
                                { id: 'select', icon: 'fa-layer-group', label: 'Layers' },
                                { id: 'aoi', icon: 'fa-pen-to-square', label: 'Draw' },
                                { id: 'add', icon: 'fa-plus', label: 'Add' },
                                { id: 'clear', icon: 'fa-eraser', label: 'Clear' }
                            ].map(tab => (
                                <button
                                    key={tab.id}
                                    onClick={() => setActiveMapTab(tab.id)}
                                    className={`segment-btn ${activeMapTab === tab.id ? 'active' : ''}`}
                                    title={tab.label}
                                >
                                    <i className={`fa-solid ${tab.icon}`}></i>
                                    <span>{tab.label}</span>
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Tab Content */}
                    <div className="tab-content" style={{ minHeight: '150px', paddingTop: '16px' }}>
                        {activeMapTab === 'select' && (
                            <>
                                <div className="section-label">{t('choose_layer')}</div>

                                {/* Start of Opacity Control - Moved here for better visibility */}
                                <div className="opacity-control-modern" style={{ marginBottom: '20px' }}>
                                    <div className="opacity-header">
                                        <span className="label">Layer Opacity</span>
                                        <span className="value">{opacity}%</span>
                                    </div>
                                    <input
                                        type="range"
                                        className="modern-range"
                                        min="0"
                                        max="100"
                                        value={opacity}
                                        onChange={handleOpacityChange}
                                        style={{
                                            background: `linear-gradient(to right, var(--krishi-green) ${opacity}%, #e0e0e0 ${opacity}%)`
                                        }}
                                    />
                                </div>
                                {/* End of Opacity Control */}

                                <div className="section-header" style={{ marginTop: '10px', marginBottom: '8px', fontSize: '0.85em', color: '#666', textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: 'bold' }}>
                                    Analysis Layers
                                </div>
                                {/* Icon Grid Layer Switcher */}
                                <div style={{ marginBottom: '16px' }}>
                                    {/* Active Layer Label Display */}
                                    <div style={{
                                        marginBottom: '10px',
                                        padding: '8px 12px',
                                        background: '#f8fafc',
                                        borderRadius: '8px',
                                        border: '1px solid #e2e8f0',
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '10px',
                                        justifyContent: 'center'
                                    }}>
                                        {(() => {
                                            const current = allLayers.find(l => l.id === selectedLayer);
                                            // Only show if selected layer is in this group
                                            if (current) {
                                                return (
                                                    <>
                                                        <i className={`fa-solid ${current.icon}`} style={{ color: current.color }}></i>
                                                        <span style={{ fontWeight: 600, color: '#334155', fontSize: '0.9em' }}>{current.label}</span>
                                                    </>
                                                );
                                            } else {
                                                return <span style={{ color: '#94a3b8', fontSize: '0.85em' }}>Select a layer below</span>;
                                            }
                                        })()}
                                    </div>


                                    <div style={{
                                        display: 'grid',
                                        gridTemplateColumns: 'repeat(4, 1fr)',
                                        gap: '10px'
                                    }}>
                                        {allLayers.map(layer => (
                                            <div
                                                key={layer.id}
                                                onClick={() => handleLayerSelectChange({ target: { value: layer.id } })}
                                                style={{
                                                    cursor: 'pointer',
                                                    display: 'flex',
                                                    flexDirection: 'column',
                                                    alignItems: 'center',
                                                    gap: '6px'
                                                }}
                                            >
                                                {/* Icon Button WITH IMAGE */}
                                                <div
                                                    className={`layer-icon-btn ${selectedLayer === layer.id ? 'active' : ''}`}
                                                    style={{
                                                        aspectRatio: '1',
                                                        width: '100%',
                                                        // Use Image if available, fallback to color
                                                        background: layer.img ? `url(${layer.img})` : (selectedLayer === layer.id ? layer.color : 'white'),
                                                        backgroundSize: 'cover',
                                                        backgroundPosition: 'center',
                                                        border: `2px solid ${selectedLayer === layer.id ? layer.color : '#e2e8f0'}`,
                                                        borderRadius: '8px',
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                        justifyContent: 'center',
                                                        transition: 'all 0.2s ease',
                                                        color: 'white', // Always white icon for visibility on image
                                                        // Add text shadow or overlay for icon visibility
                                                        textShadow: '0 2px 4px rgba(0,0,0,0.8)',
                                                        fontSize: '1.2em',
                                                        boxShadow: selectedLayer === layer.id ? `0 4px 6px -1px ${layer.color}40` : 'none',
                                                        position: 'relative',
                                                        overflow: 'hidden'
                                                    }}
                                                >
                                                    {/* Dark Overlay for contrast */}
                                                    <div style={{
                                                        position: 'absolute',
                                                        top: 0,
                                                        left: 0,
                                                        right: 0,
                                                        bottom: 0,
                                                        background: 'rgba(0,0,0,0.3)', // Slight dark tint
                                                        zIndex: 1
                                                    }}></div>

                                                    <i className={`fa-solid ${layer.icon}`} style={{ zIndex: 2 }}></i>
                                                </div>
                                                {/* Label */}
                                                <span style={{
                                                    fontSize: '0.7em',
                                                    fontWeight: selectedLayer === layer.id ? 600 : 500,
                                                    color: selectedLayer === layer.id ? layer.color : '#64748b',
                                                    textAlign: 'center',
                                                    lineHeight: '1.1',
                                                    wordBreak: 'break-word',
                                                    transition: 'all 0.2s ease'
                                                }}>
                                                    {layer.label}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </div>

                                {/* VRA Layers Folder */}
                                {/* Zonal Maps Icon Grid */}
                                <div className="section-header" style={{ marginTop: '20px', marginBottom: '8px', fontSize: '0.85em', color: '#666', textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: 'bold' }}>
                                    Zonal Maps
                                </div>
                                <div style={{ marginBottom: '16px' }}>
                                    {/* Active Layer Label Display */}
                                    <div style={{
                                        marginBottom: '10px',
                                        padding: '8px 12px',
                                        background: '#f8fafc',
                                        borderRadius: '8px',
                                        border: '1px solid #e2e8f0',
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '10px',
                                        justifyContent: 'center'
                                    }}>
                                        {(() => {
                                            const current = zonalLayers.find(l => l.id === selectedLayer);
                                            // Only show if selected layer is in this group
                                            if (current) {
                                                return (
                                                    <>
                                                        <i className={`fa-solid ${current.icon}`} style={{ color: current.color }}></i>
                                                        <span style={{ fontWeight: 600, color: '#334155', fontSize: '0.9em' }}>{current.label}</span>
                                                    </>
                                                );
                                            } else {
                                                return <span style={{ color: '#94a3b8', fontSize: '0.85em' }}>Select a map</span>;
                                            }
                                        })()}
                                    </div>


                                    <div style={{
                                        display: 'grid',
                                        gridTemplateColumns: 'repeat(4, 1fr)',
                                        gap: '10px'
                                    }}>
                                        {zonalLayers.map(layer => (
                                            <div
                                                key={layer.id}
                                                onClick={() => handleLayerSelectChange({ target: { value: layer.id } })}
                                                style={{
                                                    cursor: 'pointer',
                                                    display: 'flex',
                                                    flexDirection: 'column',
                                                    alignItems: 'center',
                                                    gap: '6px'
                                                }}
                                            >
                                                {/* Icon Button WITH IMAGE */}
                                                <div
                                                    className={`layer-icon-btn ${selectedLayer === layer.id ? 'active' : ''}`}
                                                    style={{
                                                        aspectRatio: '1',
                                                        width: '100%',
                                                        // Use Image if available
                                                        background: layer.img ? `url(${layer.img})` : (selectedLayer === layer.id ? layer.color : 'white'),
                                                        backgroundSize: 'cover',
                                                        backgroundPosition: 'center',
                                                        border: `2px solid ${selectedLayer === layer.id ? layer.color : '#e2e8f0'}`,
                                                        borderRadius: '8px',
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                        justifyContent: 'center',
                                                        transition: 'all 0.2s ease',
                                                        color: 'white', // White icon
                                                        textShadow: '0 2px 4px rgba(0,0,0,0.8)',
                                                        fontSize: '1.2em',
                                                        boxShadow: selectedLayer === layer.id ? `0 4px 6px -1px ${layer.color}40` : 'none',
                                                        position: 'relative',
                                                        overflow: 'hidden'
                                                    }}
                                                >
                                                    <div style={{
                                                        position: 'absolute',
                                                        top: 0,
                                                        left: 0,
                                                        right: 0,
                                                        bottom: 0,
                                                        background: 'rgba(0,0,0,0.3)',
                                                        zIndex: 1
                                                    }}></div>
                                                    <i className={`fa-solid ${layer.icon}`} style={{ zIndex: 2 }}></i>
                                                </div>
                                                {/* Label */}
                                                <span style={{
                                                    fontSize: '0.7em',
                                                    fontWeight: selectedLayer === layer.id ? 600 : 500,
                                                    color: selectedLayer === layer.id ? layer.color : '#64748b',
                                                    textAlign: 'center',
                                                    lineHeight: '1.1',
                                                    wordBreak: 'break-word',
                                                    transition: 'all 0.2s ease'
                                                }}>
                                                    {layer.label}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </div>


                            </>
                        )}

                        {activeMapTab === 'aoi' && (
                            <>
                                <div className="section-label">Drawing Tools</div>

                                {/* Draw Tools */}
                                <div className="draw-tools-section">
                                    <div className="tool-card" onClick={() => window.mapFunctions?.startDrawPolygon()}>
                                        <div className="tool-icon" style={{ background: 'linear-gradient(135deg, var(--krishi-green), #0a8f42)' }}>
                                            <i className="fa-solid fa-draw-polygon"></i>
                                        </div>
                                        <div className="tool-info">
                                            <span className="tool-name">Polygon</span>
                                            <span className="tool-desc">Draw custom shape</span>
                                        </div>
                                    </div>

                                    <div className="tool-card" onClick={() => window.mapFunctions?.startDrawRectangle()}>
                                        <div className="tool-icon" style={{ background: 'linear-gradient(135deg, var(--krishi-green), #0a8f42)' }}>
                                            <i className="fa-regular fa-square"></i>
                                        </div>
                                        <div className="tool-info">
                                            <span className="tool-name">Rectangle</span>
                                            <span className="tool-desc">Draw box area</span>
                                        </div>
                                    </div>
                                </div>

                                {/* Edit Tools */}
                                <div className="section-label" style={{ marginTop: '16px' }}>Edit & Manage</div>
                                <div className="action-tools-grid">
                                    <button className="action-tool-btn edit-btn" onClick={() => window.mapFunctions?.startEditShapes()}>
                                        <i className="fa-solid fa-pen-to-square"></i>
                                        <span>Edit</span>
                                    </button>
                                    <button className="action-tool-btn save-btn" onClick={() => window.mapFunctions?.saveEdits()}>
                                        <i className="fa-solid fa-check-circle"></i>
                                        <span>Save</span>
                                    </button>
                                    <button className="action-tool-btn delete-btn" onClick={() => window.mapFunctions?.deleteShapes()}>
                                        <i className="fa-solid fa-trash-alt"></i>
                                        <span>Delete</span>
                                    </button>
                                </div>
                            </>
                        )}

                        {activeMapTab === 'add' && (
                            <>
                                <button onClick={addToManagedLayers} className="btn" style={{ width: '100%', marginBottom: '15px' }}>
                                    <i className="fa-solid fa-plus-circle"></i> {t('add_layer')}
                                </button>

                                {managedLayers.length > 0 ? (
                                    <div className="managed-layers-list" style={{ maxHeight: '150px', overflowY: 'auto', border: '1px solid #eee', borderRadius: '4px' }}>
                                        {managedLayers.map(l => (
                                            <div key={l.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px', borderBottom: '1px solid #eee', fontSize: '12px' }}>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                    <input
                                                        type="checkbox"
                                                        checked={l.visible}
                                                        onChange={() => toggleManagedLayer(l.id)}
                                                        style={{ cursor: 'pointer' }}
                                                    />

                                                    <span>
                                                        <strong>{l.type ? getLayerDisplayName(l.type) : 'LAYER'}</strong> <span style={{ color: '#888' }}>({l.opacity}%)</span>
                                                    </span>
                                                </div>
                                                <button
                                                    onClick={() => removeManagedLayer(l.id)}
                                                    style={{ background: 'none', border: 'none', color: '#f44336', cursor: 'pointer', fontSize: '16px' }}
                                                >
                                                    &times;
                                                </button>
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <p style={{ fontSize: '12px', color: '#888', textAlign: 'center', padding: '10px' }}>No layers added yet.</p>
                                )}

                                {managedLayers.length > 1 && (
                                    <button onClick={handleCompare} className="btn" style={{ width: '100%', marginTop: '15px', background: '#2196f3' }}>
                                        <i className="fa-solid fa-code-compare"></i> Compare Layers
                                    </button>
                                )}
                            </>
                        )}

                        {activeMapTab === 'clear' && (
                            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
                                <p style={{ fontSize: '12px', color: '#666', marginBottom: '15px', textAlign: 'center' }}>
                                    Remove all layers, shapes, and AOI from the map.
                                </p>
                                <button
                                    className="btn"
                                    onClick={() => {
                                        // Clear local sidebar state
                                        setManagedLayers([]);
                                        setUploadedLayers([]);
                                        // Call parent handler to clear map and AOI
                                        if (onClearMap) {
                                            onClearMap();
                                        }
                                    }}
                                    style={{ width: '100%', background: '#f44336' }}
                                >
                                    <i className="fa-solid fa-rotate-left"></i> {t('clear_all_layers')}
                                </button>
                            </div>
                        )}
                    </div>
                </div>

            </div>

            {/* Sidebar Footer: Actions */}
            <div className="sidebar-footer">
                <div className="footer-actions-grid">
                    {/* CSV Download Button */}
                    <button
                        className="footer-btn"
                        onClick={onDownloadCSV}
                        title="Download CSV"
                    >
                        <i className="fa-solid fa-file-csv"></i>
                        <span>Download CSV</span>
                    </button>

                    {/* Report Button */}
                    <button
                        className="footer-btn"
                        onClick={onGenerateReport}
                        disabled={isGeneratingReport}
                        title={t('generate_report')}
                    >
                        <i className="fa-solid fa-file-pdf"></i>
                        <span>Report</span>
                    </button>
                </div>
            </div>
        </aside>
    );
}

export default Sidebar;