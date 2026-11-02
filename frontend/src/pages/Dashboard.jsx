import { useState, useEffect, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Chart } from 'chart.js/auto';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import Swal from 'sweetalert2';
import { getFields, saveField, getLastIrrigationCalendar } from '../utils/api';
import { kml } from '@mapbox/togeojson';
import './Dashboard.css';

function Dashboard() {
    const { user, logout } = useAuth();
    const navigate = useNavigate();
    const [isDarkMode, setIsDarkMode] = useState(false);
    const [showProfileMenu, setShowProfileMenu] = useState(false);
    const [fields, setFields] = useState([]);
    const [irrigationData, setIrrigationData] = useState(null);
    const [cropHealthData, setCropHealthData] = useState(null);
    const [loading, setLoading] = useState({ fields: true, irrigation: true, cropHealth: true });

    // New state for file upload naming step
    const [pendingFieldData, setPendingFieldData] = useState(null);
    const [fieldNameInput, setFieldNameInput] = useState('');

    // Modal states for fullscreen cards
    const [irrigationModalOpen, setIrrigationModalOpen] = useState(false);
    const [cropHealthModalOpen, setCropHealthModalOpen] = useState(false);

    const mapRef = useRef(null);
    const mapInstanceRef = useRef(null);
    const fieldsLayerRef = useRef(null);
    const diseaseChartRef = useRef(null);
    const cropHealthChartRef = useRef(null);
    const vegCoverChartRef = useRef(null);

    // Dark mode toggle
    useEffect(() => {
        const savedMode = localStorage.getItem('darkMode') === 'true';
        setIsDarkMode(savedMode);
        if (savedMode) {
            document.body.classList.add('dark-mode');
        }
    }, []);

    const toggleDarkMode = () => {
        const newMode = !isDarkMode;
        setIsDarkMode(newMode);
        document.body.classList.toggle('dark-mode', newMode);
        localStorage.setItem('darkMode', newMode);
    };

    // Initialize map
    useEffect(() => {
        if (!mapRef.current || mapInstanceRef.current) return;

        const map = L.map(mapRef.current, {
            zoomControl: false,
            attributionControl: false
        }).setView([20.5937, 78.9629], 3);

        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            maxZoom: 19
        }).addTo(map);

        mapInstanceRef.current = map;
        fieldsLayerRef.current = new L.FeatureGroup().addTo(map);

        const timer = setTimeout(() => {
            if (map && map.getContainer()) {
                map.invalidateSize();
            }
        }, 100);

        return () => {
            clearTimeout(timer);
            if (mapInstanceRef.current) {
                mapInstanceRef.current.remove();
                mapInstanceRef.current = null;
            }
        };
    }, []);

    // Load fields (Data Fetching)
    useEffect(() => {
        async function loadFields() {
            let loadedFromBackend = false;
            try {
                // Try backend first using centralized API
                const data = await getFields();
                setFields(data);
                loadedFromBackend = true;
            } catch (error) {
                console.log('Backend fields not available, checking localStorage');
            }

            if (!loadedFromBackend) {
                try {
                    const localFields = JSON.parse(localStorage.getItem('fields') || '[]');
                    setFields(localFields);
                } catch (e) {
                    console.error('Error loading fields from localStorage', e);
                }
            }
            setLoading(prev => ({ ...prev, fields: false }));
        }
        loadFields();
    }, []);

    // Render Fields on Map (Visualization)
    useEffect(() => {
        if (!mapInstanceRef.current || !fieldsLayerRef.current) return;

        const layerGroup = fieldsLayerRef.current;
        layerGroup.clearLayers();

        // 1. Render usage fields
        fields.forEach((field, index) => {
            const fieldNumber = index + 1;
            let layer;

            // Draw shape
            if (field.type === 'circle') {
                layer = L.circle(field.geometry.center, {
                    radius: field.geometry.radius,
                    color: 'white',
                    weight: 2,
                    fillOpacity: 0
                });
            } else if (field.geometry) {
                layer = L.geoJSON(field.geometry, {
                    style: { color: 'white', weight: 2, fillOpacity: 0 }
                });
            }

            if (layer) {
                layerGroup.addLayer(layer);

                // Click to navigate
                layer.on('click', () => {
                    navigate(`/app?field_id=${field.id}`);
                });

                // Draw Label Marker
                let center;
                if (field.type === 'circle') {
                    center = field.geometry.center;
                } else {
                    // For GeoJSON layer, getBounds might be on the internal layer
                    center = layer.getBounds().getCenter();
                }

                const marker = L.marker(center, {
                    icon: L.divIcon({
                        className: 'field-number-label',
                        html: `<div class="field-marker">${fieldNumber}</div>`,
                        iconSize: [40, 40]
                    })
                });

                marker.on('click', () => {
                    navigate(`/app?field_id=${field.id}`);
                });

                layerGroup.addLayer(marker);
            }
        });

        // 2. Render Pending Field (Uploaded but not saved)
        if (pendingFieldData && pendingFieldData.geometry) {
            const pendingLayer = L.geoJSON(pendingFieldData.geometry, {
                style: {
                    color: '#00e676', // Bright Green
                    weight: 3,
                    dashArray: '10, 10',
                    fillOpacity: 0.2
                }
            });
            layerGroup.addLayer(pendingLayer);
        }

        // 3. Fit Bounds
        if (layerGroup.getLayers().length > 0) {
            mapInstanceRef.current.fitBounds(layerGroup.getBounds(), { padding: [50, 50] });
        }

    }, [fields, pendingFieldData, navigate]);

    // Load irrigation calendar from backend or localStorage (unchanged)
    useEffect(() => {
        const fetchIrrigation = async () => {
            let backendSuccess = false;
            try {
                const data = await getLastIrrigationCalendar();
                // Only use backend data if it has actual calendar events
                if (data && data.calendar && data.calendar.length > 0) {
                    setIrrigationData(data);
                    localStorage.setItem('lastIrrigationCalendar', JSON.stringify(data));
                    backendSuccess = true;
                    console.log('✅ Dashboard: Loaded fresh irrigation data from backend');
                } else {
                    console.log('⚠️ Dashboard: Backend returned empty irrigation data, checking localStorage...');
                }
            } catch (e) {
                console.log('Fetching irrigation from backend failed:', e);
            }

            // Fallback to localStorage if backend failed or returned empty data
            if (!backendSuccess) {
                const stored = localStorage.getItem('lastIrrigationCalendar');
                if (stored) {
                    try {
                        const data = JSON.parse(stored);
                        console.log('📊 Dashboard: Loaded irrigation data from localStorage fallback:', data);
                        setIrrigationData(data);
                    } catch (parseError) {
                        console.error('Error parsing stored irrigation data:', parseError);
                    }
                }
            }

            setLoading(prev => ({ ...prev, irrigation: false }));
        };

        fetchIrrigation();
    }, []);

    // Load crop health data from localStorage (unchanged)
    useEffect(() => {
        const stored = localStorage.getItem('lastCropHealthData');
        if (stored) {
            try {
                const data = JSON.parse(stored);
                setCropHealthData(data);
            } catch (e) {
                console.error('Error parsing crop health data:', e);
            }
        }
        setLoading(prev => ({ ...prev, cropHealth: false }));
    }, []);

    // Initialize disease chart (unchanged)
    useEffect(() => {
        if (!diseaseChartRef.current) return;

        const ctx = diseaseChartRef.current.getContext('2d');
        if (diseaseChartRef.current.chartInstance) {
            diseaseChartRef.current.chartInstance.destroy();
        }

        const chart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: ['No advice', 'Other'],
                datasets: [{
                    data: [fields.length || 0, 0],
                    backgroundColor: ['#e0e0e0', '#ffffff'],
                    borderWidth: 0,
                    cutout: '80%'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { enabled: false }
                }
            }
        });

        diseaseChartRef.current.chartInstance = chart;
        return () => chart.destroy();
    }, [fields.length]);

    // Render crop health mini chart (unchanged)
    useEffect(() => {
        if (!cropHealthData?.data || !cropHealthChartRef.current) return;

        const ctx = cropHealthChartRef.current.getContext('2d');
        if (cropHealthChartRef.current.chartInstance) {
            cropHealthChartRef.current.chartInstance.destroy();
        }

        const chartData = cropHealthData.data.slice(-30);
        const labels = chartData.map(d => new Date(d.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }));
        const ndviData = chartData.map(d => d.ndvi);

        const gradient = ctx.createLinearGradient(0, 0, 0, 100);
        gradient.addColorStop(0, 'rgba(0, 200, 83, 0.3)');
        gradient.addColorStop(1, 'rgba(0, 200, 83, 0.05)');

        const chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: 'NDVI',
                    data: ndviData,
                    borderColor: 'rgb(0, 200, 83)',
                    backgroundColor: gradient,
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { display: false },
                    y: {
                        display: true,
                        grid: { display: true, color: 'rgba(0,0,0,0.05)' },
                        ticks: { font: { size: 9 }, color: '#999', maxTicksLimit: 4 }
                    }
                }
            }
        });

        cropHealthChartRef.current.chartInstance = chart;
        return () => chart.destroy();
    }, [cropHealthData]);

    const handleLogout = () => {
        logout();
        navigate('/login');
    };

    // New: Function to handle map resize after fullscreen toggle
    const handleMapResize = () => {
        const mapElement = mapRef.current;
        const isFullscreen = document.fullscreenElement === mapElement ||
            document.mozFullScreenElement === mapElement ||
            document.webkitFullscreenElement === mapElement ||
            document.msFullscreenElement === mapElement;

        // Leaflet needs to re-calculate size after the browser finishes the transition
        setTimeout(() => {
            if (mapInstanceRef.current) {
                mapInstanceRef.current.invalidateSize();
            }
        }, 350);

        // Optional: You might want to toggle a class on the map-card element if necessary
        // mapElement.classList.toggle('is-fullscreen', isFullscreen); 
    };

    // New: Function to handle fullscreen button click
    const handleFullscreen = () => {
        const mapElement = mapRef.current;
        if (!mapElement) return;

        if (document.fullscreenElement) {
            // Exit fullscreen
            if (document.exitFullscreen) {
                document.exitFullscreen();
            } else if (document.mozCancelFullScreen) { /* Firefox */
                document.mozCancelFullScreen();
            } else if (document.webkitExitFullscreen) { /* Chrome, Safari and Opera */
                document.webkitExitFullscreen();
            } else if (document.msExitFullscreen) { /* IE/Edge */
                document.msExitFullscreen();
            }
        } else {
            // Enter fullscreen
            if (mapElement.requestFullscreen) {
                mapElement.requestFullscreen();
            } else if (mapElement.mozRequestFullScreen) { /* Firefox */
                mapElement.mozRequestFullScreen();
            } else if (mapElement.webkitRequestFullscreen) { /* Chrome, Safari and Opera */
                mapElement.webkitRequestFullscreen();
            } else if (mapElement.msRequestFullscreen) { /* IE/Edge */
                mapElement.msRequestFullscreen();
            }
        }
    };

    // Attach event listeners for map resize on fullscreen change
    useEffect(() => {
        document.addEventListener('fullscreenchange', handleMapResize);
        document.addEventListener('webkitfullscreenchange', handleMapResize);
        document.addEventListener('mozfullscreenchange', handleMapResize);
        document.addEventListener('msfullscreenchange', handleMapResize);

        // Cleanup listeners on component unmount
        return () => {
            document.removeEventListener('fullscreenchange', handleMapResize);
            document.removeEventListener('webkitfullscreenchange', handleMapResize);
            document.removeEventListener('mozfullscreenchange', handleMapResize);
            document.removeEventListener('msfullscreenchange', handleMapResize);
        };
    }, []);

    // Upload + store AOI with name input step
    const handleFileUpload = (event) => {
        const file = event.target.files[0];
        if (!file) return;
        event.target.value = null;

        const isKml = file.name.toLowerCase().endsWith('.kml');
        const isGeoJson = file.name.toLowerCase().endsWith('.geojson') || file.name.toLowerCase().endsWith('.json');

        if (!isKml && !isGeoJson) {
            Swal.fire({
                icon: 'error',
                title: 'Invalid File',
                text: 'Please upload a GeoJSON (.json, .geojson) or KML (.kml) file.',
            });
            return;
        }

        const reader = new FileReader();
        reader.onload = async (e) => {
            try {
                const content = e.target.result;
                let parsedData = null;

                // 1. Parse the file based on type
                if (isKml) {
                    const parser = new DOMParser();
                    const kmlDom = parser.parseFromString(content, 'text/xml');
                    // Convert KML to GeoJSON
                    parsedData = kml(kmlDom);
                } else {
                    // Parse GeoJSON
                    parsedData = JSON.parse(content);
                }

                // 2. Extract the Geometry
                // The backend likely expects a raw Geometry object (Polygon), 
                // but files often contain a "FeatureCollection" or a "Feature".
                let geometry = null;

                if (parsedData.type === 'FeatureCollection' && parsedData.features.length > 0) {
                    // Take the geometry of the first feature
                    geometry = parsedData.features[0].geometry;
                } else if (parsedData.type === 'Feature') {
                    geometry = parsedData.geometry;
                } else if (parsedData.type === 'Polygon' || parsedData.type === 'MultiPolygon') {
                    geometry = parsedData;
                }

                // 3. Validate and Update State
                if (geometry) {
                    // Strip 3D altitude/Z coordinate so coordinates are strictly 2D [lon, lat]
                    const stripZ = (coords) => {
                        if (!coords) return coords;
                        if (Array.isArray(coords)) {
                            if (coords.length > 0 && typeof coords[0] === 'number') {
                                return coords.slice(0, 2);
                            }
                            return coords.map(stripZ);
                        }
                        return coords;
                    };

                    if (geometry.coordinates) {
                        geometry = {
                            ...geometry,
                            coordinates: stripZ(geometry.coordinates)
                        };
                    }

                    setPendingFieldData({ geometry });

                    // Auto-fill the name input with the file name (removing extension)
                    const nameFromFile = file.name.replace(/\.[^/.]+$/, "");
                    setFieldNameInput(nameFromFile);
                } else {
                    throw new Error("No valid geometry found in file.");
                }

            } catch (err) {
                console.error("File parsing error:", err);
                Swal.fire({
                    icon: 'error',
                    title: 'Parsing Error',
                    text: 'Could not read geometry from this file. Please ensure it is valid KML or GeoJSON.',
                });
            }
        };

        // Read the file as text
        reader.readAsText(file);
    };

    const handleSaveField = async () => {
        if (!pendingFieldData || !fieldNameInput.trim()) {
            Swal.fire({
                icon: 'warning',
                title: 'Missing Information',
                text: 'Please enter a field name.',
                confirmButtonColor: '#2f7a2f'
            });
            return;
        }

        let area = 0;
        let type = 'polygon';

        // Calculate area
        try {
            const layer = L.geoJSON(pendingFieldData.geometry).getLayers()[0];
            if (layer) {
                if (layer instanceof L.Circle) {
                    type = 'circle';
                    const radius = layer.getRadius();
                    area = Math.PI * radius * radius;
                } else {
                    // Polygon or Rectangle
                    type = 'polygon'; // Default for GeoJSON usually
                    const latLngs = layer.getLatLngs()[0]; // Assume simple polygon

                    // Geodesic Area Calculation (Pixel-perfect match to CreateField.jsx logic)
                    const pointsCount = latLngs.length;
                    const d2r = Math.PI / 180;

                    if (pointsCount > 2) {
                        for (let i = 0; i < pointsCount; i++) {
                            const p1 = latLngs[i];
                            const p2 = latLngs[(i + 1) % pointsCount];
                            area += ((p2.lng - p1.lng) * d2r) *
                                (2 + Math.sin(p1.lat * d2r) + Math.sin(p2.lat * d2r));
                        }
                        area = Math.abs(area * 6378137.0 * 6378137.0 / 2.0);
                    }
                }
            }
        } catch (e) {
            console.error("Error calculating area:", e);
        }

        const payload = {
            name: fieldNameInput.trim(),
            type: type,
            geometry: pendingFieldData.geometry,
            areaHectares: (area / 10000).toFixed(2),
            areaAcres: (area / 4046.86).toFixed(2)
        };

        let backendSaved = false;
        let backendId = null;

        try {
            // Try backend save using centralized API
            const result = await saveField(payload);
            if (result.success) {
                backendSaved = true;
                backendId = result.id;
            }
        } catch (error) {
            console.log('Backend save failed, ignoring error and saving locally');
        }

        // Always save locally if backend fails or even if it succeeds (to sync)
        const newField = {
            id: backendId || Date.now().toString(),
            ...payload
        };

        const fieldsLS = JSON.parse(localStorage.getItem('fields') || '[]');
        const updatedFields = [...fieldsLS, newField];
        localStorage.setItem('fields', JSON.stringify(updatedFields));

        setFields(prev => [...prev, newField]); // Update React state

        setPendingFieldData(null);
        setFieldNameInput('');

        await Swal.fire({
            icon: 'success',
            title: backendSaved ? 'Field Saved!' : 'Field Saved Locally',
            text: backendSaved
                ? `"${payload.name}" has been saved successfully.`
                : `"${payload.name}" has been saved to your browser (Backend unavailable).`,
            confirmButtonColor: '#2f7a2f',
            timer: 2000
        });

        // Redirect to the detail page with the new ID
        navigate(`/app?field_id=${newField.id}`);
    };

    const handleCancelUpload = () => {
        setPendingFieldData(null);
        setFieldNameInput('');
    };

    const totalAreaAcres = fields.reduce((sum, f) => sum + (parseFloat(f.areaAcres) || 0), 0);
    const totalAreaHectares = fields.reduce((sum, f) => sum + (parseFloat(f.areaHectares) || 0), 0);

    return (
        <div className="dashboard-page">
            {/* Header (unchanged) */}
            <header className="dashboard-header">
                <div className="nav-left">
                    <Link to="/dashboard" className="brand">
                        <img src="/static/logo.png" alt="MapZest" style={{ height: 32 }} />
                    </Link>
                    <nav className="nav-links">
                        <Link to="/dashboard" className="nav-link active">Dashboard</Link>
                        <Link to="/fields" className="nav-link">Fields</Link>
                    </nav>
                </div>
                <div className="nav-right">
                    {/* NEW: User Name Display */}

                    <button className="theme-toggle" onClick={toggleDarkMode}>
                        <i className={`fas ${isDarkMode ? 'fa-sun' : 'fa-moon'}`}></i>
                    </button>
                    <div className={`profile-dropdown ${showProfileMenu ? 'active' : ''}`}>
                        <button className="profile-btn" onClick={() => setShowProfileMenu(!showProfileMenu)}>
                            {user?.photoURL ? (
                                <img src={user.photoURL} alt="Profile" className="avatar-image" />
                            ) : (
                                <div className="avatar">
                                    {user?.name?.[0]?.toUpperCase() || user?.email?.[0]?.toUpperCase() || 'U'}
                                </div>
                            )}
                        </button>
                        <div className="profile-menu">
                            <div className="user-info">
                                <div className="user-name">{user?.name || 'User'}</div>
                                <div className="user-email">{user?.email}</div>
                            </div>
                            <button className="dropdown-item" onClick={handleLogout}>
                                <i className="fas fa-sign-out-alt"></i> Logout
                            </button>
                        </div>
                    </div>
                </div>
            </header>

            {/* Main Content */}
            <div className="dashboard-container">
                <div className="page-header">
                    <div>
                        <h1 className="page-title">
                            {/* MODIFIED: RENDER THE FULL NAME AND "DASHBOARD" */}
                            {user?.name ? (
                                <span>
                                    {user.name}
                                    &nbsp;Dashboard
                                </span>
                            ) : (
                                'Dashboard' // Fallback if no user name exists
                            )}
                        </h1>
                    </div>
                    <div className="header-actions"></div>
                </div>

                <div className="dashboard-grid">
                    {/* Create Field Card - Centered Design */}
                    <Link to="/create-field" className="card create-field-card">
                        <div className="create-field-content">
                            <div className="create-field-icon">
                                <i className="fas fa-plus"></i>
                            </div>
                            <div className="create-field-text">
                                Draw a new AOI
                                <i className="fas fa-arrow-right" style={{ marginLeft: '8px', fontSize: '14px' }}></i>
                            </div>
                        </div>
                    </Link>

                    {/* NEW 2: "Upload Field" Card (with name input) */}
                    <div className="card upload-field-card">
                        <div className="card-header">
                            <i className="fas fa-upload card-icon"></i>
                            <span className="card-title">Upload Field (Geo/KML)</span>
                        </div>
                        <div className="card-body upload-field-body">
                            <div className="card-body upload-field-body">
                                {pendingFieldData ? (
                                    <div style={{ width: '100%', padding: '0 16px' }}>
                                        <h4 style={{ marginBottom: 12, fontSize: 14 }}>Enter Field Name</h4>
                                        <input
                                            type="text"
                                            value={fieldNameInput}
                                            onChange={(e) => setFieldNameInput(e.target.value)}
                                            placeholder="Field Name"
                                            style={{
                                                width: '100%',
                                                padding: '8px 12px',
                                                marginBottom: '12px',
                                                borderRadius: '6px',
                                                border: '1px solid var(--border-color)',
                                                background: 'var(--bg-light)',
                                                color: 'var(--text-main)',
                                                outline: 'none'
                                            }}
                                            autoFocus
                                        />
                                        <div style={{ display: 'flex', gap: '8px' }}>
                                            <button
                                                className="btn btn-save"
                                                onClick={handleSaveField}
                                            >
                                                Save
                                            </button>
                                            <button
                                                className="btn btn-cancel"
                                                onClick={handleCancelUpload}
                                            >
                                                Cancel
                                            </button>
                                        </div>
                                    </div>
                                ) : (
                                    <>
                                        <input
                                            type="file"
                                            id="file-upload"
                                            style={{ display: 'none' }}
                                            accept=".geojson,.json,.kml"
                                            onChange={handleFileUpload}
                                        />
                                        <label htmlFor="file-upload" className="upload-label">
                                            <i className="fas fa-file-upload upload-icon"></i>
                                            <div className="upload-title">Upload from File</div>
                                            <div className="upload-subtitle">Click to select GeoJSON or KML file</div>
                                        </label>
                                    </>
                                )}
                            </div>
                        </div>
                    </div>

                    {/* Map Card (Add onClick for Fullscreen) */}
                    <div className="card map-card">
                        <div ref={mapRef} className="fields-map"></div>
                        <button
                            className="map-overlay-btn"
                            title="Fullscreen"
                            onClick={handleFullscreen}   /* <--- NEW: Fullscreen handler added */
                        >
                            <i className="fas fa-expand"></i>
                        </button>
                    </div>




                    {/* Crop Health Card */}
                    <div className="card">
                        <div className="card-header">
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                <i className="fas fa-chart-line card-icon"></i>
                                <span className="card-title">Crop Health</span>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <span className={`badge ${cropHealthData?.data?.length ? 'badge-success' : 'badge-default'}`}>
                                    {loading.cropHealth ? 'Loading...' : cropHealthData?.data?.length ? 'Recent Activity' : 'No Data'}
                                </span>
                                <button
                                    className="card-fullscreen-btn"
                                    onClick={() => setCropHealthModalOpen(true)}
                                    title="View Fullscreen"
                                >
                                    <i className="fas fa-expand"></i>
                                </button>
                            </div>
                        </div>
                        <div className="card-body">
                            {loading.cropHealth ? (
                                <div className="loading-state">
                                    <i className="fas fa-circle-notch fa-spin"></i>
                                    <p>Loading Crop Health...</p>
                                </div>
                            ) : cropHealthData?.data?.length > 0 ? (
                                <div className="crop-health-content">
                                    <div style={{ marginBottom: 12 }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                                            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)' }}>NDVI Trend</span>
                                            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--primary-green)' }}>
                                                {(cropHealthData.data.reduce((a, b) => a + (b.ndvi || 0), 0) / cropHealthData.data.length).toFixed(3)}
                                            </span>
                                        </div>
                                        <div style={{ height: 100 }}>
                                            <canvas ref={cropHealthChartRef}></canvas>
                                        </div>
                                    </div>
                                    <div className="crop-stats">
                                        <div>
                                            <div className="stat-value">{cropHealthData.data.length}</div>
                                            <div className="stat-label">Data Points</div>
                                        </div>
                                        <div>
                                            <div className="stat-value">
                                                {new Date(cropHealthData.startDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                                            </div>
                                            <div className="stat-label">Start Date</div>
                                        </div>
                                    </div>
                                </div>
                            ) : (
                                <div className="empty-state">
                                    <i className="fas fa-leaf"></i>
                                    <div className="empty-title">No Crop Data</div>
                                    <div className="empty-text">Generate crop health analysis in Fields.</div>
                                </div>
                            )}
                        </div>
                    </div>



                    {/* Crops Card (unchanged) */}
                    <div className="card">
                        <div className="card-header">
                            <i className="fas fa-seedling card-icon"></i>
                            <span className="card-title">Crops</span>
                            <span className="crop-header-right">Total: {totalAreaHectares.toFixed(2)} ha / {totalAreaAcres.toFixed(2)} acre</span>
                        </div>
                        <div className="card-body">
                            <div className="crop-data-value">{fields.length}</div>
                            <div className="crop-data-label">{fields.length === 0 ? 'Empty' : 'Fields'}</div>
                        </div>
                        <Link to="/fields" className="view-all-link">View All</Link>
                    </div>
                </div>
            </div>

            {/* Irrigation Modal Popup */}
            {irrigationModalOpen && (
                <div className="modal-overlay" onClick={() => setIrrigationModalOpen(false)}>
                    <div className="modal-content modal-large" onClick={e => e.stopPropagation()}>
                        <div className="modal-header">
                            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>

                                <h2>Irrigation Calendar</h2>
                            </div>
                            <button className="modal-close-btn" onClick={() => setIrrigationModalOpen(false)}>
                                <i className="fas fa-times"></i>
                            </button>
                        </div>
                        <div className="modal-body">
                            {irrigationData?.calendar?.length > 0 ? (
                                <div>
                                    {/* Summary Stats */}
                                    <div className="modal-stats-grid">
                                        <div className="modal-stat-card">
                                            <div className="modal-stat-icon">
                                                <i className="fas fa-calendar-day"></i>
                                            </div>
                                            <div className="modal-stat-info">
                                                <div className="modal-stat-value">{irrigationData.summary?.irrigation_events || 0}</div>
                                                <div className="modal-stat-label">Total Events</div>
                                            </div>
                                        </div>
                                        <div className="modal-stat-card">
                                            <div className="modal-stat-icon">
                                                <i className="fas fa-tint"></i>
                                            </div>
                                            <div className="modal-stat-info">
                                                <div className="modal-stat-value">{irrigationData.summary?.total_water_mm?.toFixed(1) || 0} mm</div>
                                                <div className="modal-stat-label">Total Water</div>
                                            </div>
                                        </div>
                                        <div className="modal-stat-card">
                                            <div className="modal-stat-icon">
                                                <i className="fas fa-percentage"></i>
                                            </div>
                                            <div className="modal-stat-info">
                                                <div className="modal-stat-value">
                                                    {(() => {
                                                        const saved = irrigationData.summary?.water_saved_mm || 0;
                                                        const total = irrigationData.summary?.total_water_mm || 0;
                                                        const original = total + saved;
                                                        return original > 0 ? ((saved / original) * 100).toFixed(1) : 0;
                                                    })()}%
                                                </div>
                                                <div className="modal-stat-label">Water Saved</div>
                                            </div>
                                        </div>
                                        <div className="modal-stat-card">
                                            <div className="modal-stat-icon">
                                                <i className="fas fa-bell"></i>
                                            </div>
                                            <div className="modal-stat-info">
                                                <div className="modal-stat-value">{irrigationData.summary?.urgent_count || 0}</div>
                                                <div className="modal-stat-label">Total Urgent</div>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Events Table */}
                                    <h3 style={{ marginTop: 24, marginBottom: 16 }}>Irrigation Events</h3>
                                    <div className="modal-table-container">
                                        <table className="modal-table">
                                            <thead>
                                                <tr>
                                                    <th>Date</th>
                                                    <th>Priority</th>
                                                    <th>Amount (mm)</th>
                                                    <th>Advice</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {irrigationData.calendar
                                                    .filter(event => event.should_irrigate)
                                                    .map((event, idx) => {
                                                        const priorityColors = {
                                                            'URGENT': '#d32f2f',
                                                            'HIGH': '#f57c00',
                                                            'MEDIUM': '#fbc02d',
                                                            'LOW': '#388e3c'
                                                        };
                                                        return (
                                                            <tr key={idx}>
                                                                <td>{new Date(event.date).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}</td>
                                                                <td>
                                                                    <span className="priority-badge" style={{ background: priorityColors[event.priority] || '#999' }}>
                                                                        {event.priority}
                                                                    </span>
                                                                </td>
                                                                <td>{event.final_irrigation_mm?.toFixed(1)}</td>
                                                                <td>{event.advice}</td>
                                                            </tr>
                                                        );
                                                    })}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            ) : (
                                <div className="empty-state" style={{ padding: 40 }}>
                                    <i className="fas fa-cloud-rain" style={{ fontSize: 48 }}></i>
                                    <div className="empty-title">No Irrigation Data</div>
                                    <div className="empty-text">Generate irrigation calendar in Field Analysis page.</div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* Crop Health Modal Popup */}
            {cropHealthModalOpen && (
                <div className="modal-overlay" onClick={() => setCropHealthModalOpen(false)}>
                    <div className="modal-content modal-large" onClick={e => e.stopPropagation()}>
                        <div className="modal-header">
                            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>

                                <h2>Crop Health Analysis</h2>
                            </div>
                            <button className="modal-close-btn" onClick={() => setCropHealthModalOpen(false)}>
                                <i className="fas fa-times"></i>
                            </button>
                        </div>
                        <div className="modal-body">
                            {cropHealthData?.data?.length > 0 ? (
                                <div>
                                    {/* Summary Stats */}
                                    <div className="modal-stats-grid">
                                        <div className="modal-stat-card">
                                            <div className="modal-stat-icon">
                                                <i className="fas fa-leaf"></i>
                                            </div>
                                            <div className="modal-stat-info">
                                                <div className="modal-stat-value">
                                                    {(cropHealthData.data.reduce((a, b) => a + (b.ndvi || 0), 0) / cropHealthData.data.length).toFixed(3)}
                                                </div>
                                                <div className="modal-stat-label">Avg Crop Health</div>
                                            </div>
                                        </div>
                                        <div className="modal-stat-card">
                                            <div className="modal-stat-icon">
                                                <i className="fas fa-chart-bar"></i>
                                            </div>
                                            <div className="modal-stat-info">
                                                <div className="modal-stat-value">{cropHealthData.data.length}</div>
                                                <div className="modal-stat-label">Data Points</div>
                                            </div>
                                        </div>
                                        <div className="modal-stat-card">
                                            <div className="modal-stat-icon">
                                                <i className="fas fa-calendar"></i>
                                            </div>
                                            <div className="modal-stat-info">
                                                <div className="modal-stat-value">
                                                    {new Date(cropHealthData.startDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                                                </div>
                                                <div className="modal-stat-label">Start Date</div>
                                            </div>
                                        </div>
                                        <div className="modal-stat-card">
                                            <div className="modal-stat-icon">
                                                <i className="fas fa-calendar-check"></i>
                                            </div>
                                            <div className="modal-stat-info">
                                                <div className="modal-stat-value">
                                                    {new Date(cropHealthData.endDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                                                </div>
                                                <div className="modal-stat-label">End Date</div>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Data Table - NDVI Only */}
                                    <h3 style={{ marginTop: 24, marginBottom: 16 }}>Crop Health Values</h3>
                                    <div className="modal-table-container">
                                        <table className="modal-table">
                                            <thead>
                                                <tr>
                                                    <th>Date</th>
                                                    <th>Health value</th>
                                                    <th>Health Status</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {cropHealthData.data.slice(0, 50).map((item, idx) => {
                                                    const ndvi = item.ndvi;
                                                    let status = 'Poor';
                                                    let statusColor = '#d32f2f';
                                                    if (ndvi > 0.6) {
                                                        status = 'Excellent';
                                                        statusColor = 'var(--primary-green)';
                                                    } else if (ndvi > 0.4) {
                                                        status = 'Good';
                                                        statusColor = '#4caf50';
                                                    } else if (ndvi > 0.2) {
                                                        status = 'Moderate';
                                                        statusColor = '#ff9800';
                                                    }

                                                    return (
                                                        <tr key={idx}>
                                                            <td>{new Date(item.date).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}</td>
                                                            <td style={{ fontWeight: 600, color: statusColor }}>
                                                                {item.ndvi?.toFixed(3) || '—'}
                                                            </td>
                                                            <td>
                                                                <span style={{
                                                                    display: 'inline-block',
                                                                    padding: '4px 12px',
                                                                    borderRadius: '12px',
                                                                    fontSize: '11px',
                                                                    fontWeight: 600,
                                                                    color: 'white',
                                                                    background: statusColor
                                                                }}>
                                                                    {status}
                                                                </span>
                                                            </td>
                                                        </tr>
                                                    );
                                                })}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            ) : (
                                <div className="empty-state" style={{ padding: 40 }}>
                                    <i className="fas fa-leaf" style={{ fontSize: 48 }}></i>
                                    <div className="empty-title">No Crop Health Data</div>
                                    <div className="empty-text">Fetch data in Field Analysis page first.</div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

export default Dashboard;