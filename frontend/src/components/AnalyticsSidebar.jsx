import { useState, useRef, useEffect } from 'react';
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    BarElement,
    ArcElement,
    Title,
    Tooltip,
    Legend,
    Filler,
} from 'chart.js';
import { Bar, Pie, Doughnut } from 'react-chartjs-2';
import ChartPanel from './ChartPanel';
import { useApp } from '../context/AppContext';
import { t } from '../utils/translations';
import { fetchLandCoverAnalysis } from '../utils/api';
import Swal from 'sweetalert2';

// Register Chart.js components
ChartJS.register(
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    BarElement,
    ArcElement,
    Title,
    Tooltip,
    Legend,
    Filler
);

const paramColors = {
    ndvi: { border: 'rgb(34, 197, 94)', background: 'rgba(34, 197, 94, 0.1)' },
    savi: { border: 'rgb(168, 85, 247)', background: 'rgba(168, 85, 247, 0.1)' },
    cwsi: { border: 'rgb(239, 68, 68)', background: 'rgba(239, 68, 68, 0.1)' },
    kc: { border: 'rgb(59, 130, 246)', background: 'rgba(59, 130, 246, 0.1)' },
    etc: { border: 'rgb(249, 115, 22)', background: 'rgba(249, 115, 22, 0.1)' },
    irrigation_need: { border: 'rgb(6, 182, 212)', background: 'rgba(6, 182, 212, 0.1)' },
    soilmoisture_mm: { border: 'rgb(139, 92, 246)', background: 'rgba(139, 92, 246, 0.1)' },
    lst: { border: 'rgb(234, 88, 12)', background: 'rgba(234, 88, 12, 0.1)' },
    lai: { border: 'rgb(34, 211, 238)', background: 'rgba(34, 211, 238, 0.1)' },
    eto: { border: 'rgb(59, 130, 246)', background: 'rgba(59, 130, 246, 0.1)' },
    precipitation: { border: 'rgb(34, 197, 94)', background: 'rgba(34, 197, 94, 0.1)' },
    temperature: { border: 'rgb(239, 68, 68)', background: 'rgba(239, 68, 68, 0.1)' },
    humidity: { border: 'rgb(168, 85, 247)', background: 'rgba(168, 85, 247, 0.1)' },
};

function AnalyticsSidebar() {
    const {
        isRightPanelOpen,
        ndviStats,
        irrigationCalendar,
        isDarkMode,
        chartData,
        drawnAOI,
        startDate,
        endDate,
        selectedLayer,
        activeChartParam,
        setActiveChartParam,
        setIsRightPanelOpen
    } = useApp();

    const [activeTab, setActiveTab] = useState('overview');
    const [showDashboard, setShowDashboard] = useState(false);
    const [landCoverData, setLandCoverData] = useState(null);
    const [landCoverLoading, setLandCoverLoading] = useState(false);
    const [timeScale, setTimeScale] = useState('monthly');
    const [selectedPeriod, setSelectedPeriod] = useState(0);

    // Sync chart param with selected layer
    useEffect(() => {
        if (!selectedLayer) return;

        const layerToParam = {
            'ndvi': 'ndvi',
            'savi': 'savi',
            'cwsi': 'cwsi',
            'lst': 'lst',
            'kc': 'kc',
            'etc': 'etc',
            'irrigation_need': 'irrigation_need',
            'soilmoisture': 'soilmoisture_mm',
            'pca': 'pca',
            'chlorophyll': 'chlorophyll',
            'lai': 'lai',
            // VRA layers
            'vra_ndvi': 'ndvi',
            'vra_savi': 'savi',
            'vra_cwsi': 'cwsi',
            'vra_lst': 'lst',
            'vra_kc': 'kc',
            'vra_etc': 'etc',
            'vra_irrigation_need': 'irrigation_need',
            'vra_soilmoisture': 'soilmoisture_mm',
            'vra_pca': 'pca',
            'vra_chlorophyll': 'chlorophyll',
            'weather': 'weather'
        };

        const targetParam = layerToParam[selectedLayer];
        if (targetParam) {
            setActiveChartParam(targetParam);
        }
    }, [selectedLayer, setActiveChartParam]);

    // Parameter display names
    const paramLabels = {
        ndvi: 'opt_ndvi', // We'll use t() inside the render or mapping
        savi: 'opt_savi',
        cwsi: 'opt_cwsi',
        kc: 'opt_kc',
        etc: 'opt_etc',
        irrigation_need: 'opt_irrigation_need',
        soilmoisture_mm: 'opt_soilmoisture',
        lst: 'opt_lst',
        lai: 'opt_lai',
        weather: 'opt_w',
        pca: 'opt_pca',
        chlorophyll: 'Chlorophyll (CLRe)',
    };

    // Helper to toggle panel
    const togglePanel = () => {
        setIsRightPanelOpen(!isRightPanelOpen);
    };

    // Toggle Button UI
    const renderToggleButton = () => (
        <button
            onClick={togglePanel}
            className="panel-toggle-btn"
            title={isRightPanelOpen ? "Collapse Panel" : "Expand Panel"}
        >
            <i className={`fa-solid fa-chevron-${isRightPanelOpen ? 'right' : 'left'}`}></i>
        </button>
    );

    // Calculate generic stats
    const calculateGenericStats = () => {
        if (!chartData || chartData.length === 0) return null;

        // Determine the data key based on activeChartParam
        // We need to handle special cases like 'soilmoisture_mm', 'chlorophyll', or 'weather'
        let dataKey = activeChartParam;
        if (activeChartParam === 'soilmoisture_mm') {
            // Try 'soilmoisture_mm' then 'soilmoisture'
            if (chartData[0].hasOwnProperty('soilmoisture_mm')) dataKey = 'soilmoisture_mm';
            else if (chartData[0].hasOwnProperty('soilmoisture')) dataKey = 'soilmoisture';
        } else if (activeChartParam === 'chlorophyll') {
            // Backend stores Chlorophyll Red-Edge index under 'clre' key
            dataKey = 'clre';
        }

        // Weather is complex, simplest generic handling for now or skip
        if (activeChartParam === 'weather') return null;

        const values = chartData
            .map(d => d[dataKey])
            .filter(v => v !== null && v !== undefined && !isNaN(v));

        if (values.length === 0) return null;

        const meanVal = values.reduce((a, b) => a + b, 0) / values.length;
        const maxVal = Math.max(...values);
        const minVal = Math.min(...values);
        const sorted = [...values].sort((a, b) => a - b);
        const medianVal = sorted.length % 2 === 0
            ? (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2
            : sorted[Math.floor(sorted.length / 2)];

        // Check for Temperature (Kelvin)
        // Heuristic: If mean > 200, assume Kelvin (max ~350), or check param name
        const isKelvin = meanVal > 200 || ['lst', 'temperature'].includes(activeChartParam);

        let mean = meanVal;
        let min = minVal;
        let max = maxVal;
        let median = medianVal;
        let paramLabel = t(paramLabels[activeChartParam] || activeChartParam);

        if (isKelvin) {
            mean = meanVal - 273.15;
            min = minVal - 273.15;
            max = maxVal - 273.15;
            median = medianVal - 273.15;
            paramLabel += ' (°C)';
        }

        // Normalize for gauge
        let normalizedMean;
        if (isKelvin) {
            // Assume range 0-60°C for gauge visualization
            normalizedMean = Math.max(0, Math.min(1, mean / 60));
        } else if (activeChartParam === 'chlorophyll') {
            // CLRe range is typically 0-2
            normalizedMean = Math.max(0, Math.min(1, mean / 2));
        } else if (activeChartParam === 'soilmoisture_mm') {
            // Soil moisture is 0-100%
            normalizedMean = Math.max(0, Math.min(1, mean / 100));
        } else {
            // Standard 0-1 indices (NDVI, SAVI, EVI, Kc, LAI scaled, etc.)
            normalizedMean = Math.max(0, Math.min(1, mean));
        }

        return {
            mean,
            median,
            min,
            max,
            normalizedMean,
            label: paramLabel
        };
    };

    const genericStats = calculateGenericStats();

    // Auto-switch view modes
    useEffect(() => {
        if (selectedLayer === 'ndvi') {
            setShowDashboard(true);
        } else {
            setShowDashboard(false);
        }
    }, [selectedLayer]);

    useEffect(() => {
        // Only hide dashboard when switching chart params if we're not on NDVI layer
        if (activeChartParam && selectedLayer !== 'ndvi') {
            setShowDashboard(false);
        }
    }, [activeChartParam, selectedLayer]);

    // Data Report Charts
    const getReportCharts = () => {
        if (!genericStats) return null;

        const { mean, normalizedMean, label } = genericStats;

        const colorObj = paramColors[activeChartParam] || paramColors.ndvi;
        const primaryColor = colorObj.border || '#8e44ad';

        // Gauge Data
        const gaugeData = {
            labels: ['Value', 'Remaining'],
            datasets: [{
                data: [normalizedMean, 1 - normalizedMean],
                backgroundColor: [
                    primaryColor,
                    isDarkMode ? '#4a4a4a' : '#ecf0f1'
                ],
                borderWidth: 0,
                cutout: '75%',
                rotation: -90,
                circumference: 180,
            }]
        };

        const gaugeOptions = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: { enabled: false },
            },
        };

        // Horizontal Bar Data
        const barData = {
            labels: [label],
            datasets: [{
                label: 'Average',
                data: [mean],
                backgroundColor: primaryColor,
                borderRadius: 5,
                barThickness: 40,
            }]
        };

        const barOptions = {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                title: { display: false }
            },
            scales: {
                x: {
                    display: true,
                    grid: { display: false },
                    ticks: { color: isDarkMode ? '#a0aec0' : '#64748b' }
                },
                y: {
                    display: true,
                    grid: { display: false },
                    ticks: {
                        color: isDarkMode ? '#a0aec0' : '#64748b',
                        font: { size: 11 }
                    }
                }
            }
        };

        return (
            <div className="data-report-container" style={{ padding: '12px', flex: '0 1 auto', maxHeight: '60%', overflowY: 'auto' }}>
                <div style={{
                    textAlign: 'center',
                    marginBottom: '12px',
                    color: '#006064', // Dark teal title
                    fontWeight: 600,
                    fontSize: '14px'
                }}>
                    Data Report
                </div>

                <div className="report-card" style={{
                    borderRadius: '12px',
                    padding: '16px',
                    boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
                    marginBottom: '12px'
                }}>
                    <h3 style={{
                        textAlign: 'center',
                        fontSize: '15px',
                        color: isDarkMode ? '#e8e6e3' : '#333',
                        marginBottom: '12px',
                        fontWeight: 600
                    }}>
                        Average {label}
                    </h3>

                    {/* Gauge Chart */}
                    <div style={{ height: '140px', position: 'relative', marginBottom: '6px' }}>
                        <Doughnut data={gaugeData} options={gaugeOptions} />
                        <div style={{
                            position: 'absolute',
                            top: '60%',
                            left: '50%',
                            transform: 'translate(-50%, -50%)',
                            fontSize: '24px',
                            fontWeight: 'bold',
                            fontFamily: 'serif', // Matching the font in image
                            color: isDarkMode ? '#e8e6e3' : '#333'
                        }}>
                            {mean.toFixed(2)}
                        </div>
                    </div>

                    <div style={{
                        textAlign: 'center',
                        fontSize: '13px',
                        fontWeight: 600,
                        marginBottom: '12px',
                        color: isDarkMode ? '#e8e6e3' : '#333'
                    }}>
                        Average: {mean.toFixed(2)}
                    </div>

                    {/* Additional Stats Grid */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '6px' }}>
                        <div style={{ padding: '10px', background: isDarkMode ? '#2c2f32' : '#f8fafc', borderRadius: '8px', textAlign: 'center' }}>
                            <div style={{ fontSize: '11px', color: 'var(--muted)' }}>Min</div>
                            <div style={{ fontWeight: 'bold', fontSize: '14px', color: isDarkMode ? '#e8e6e3' : '#333' }}>{genericStats.min?.toFixed(2)}</div>
                        </div>
                        <div style={{ padding: '10px', background: isDarkMode ? '#2c2f32' : '#f8fafc', borderRadius: '8px', textAlign: 'center' }}>
                            <div style={{ fontSize: '11px', color: 'var(--muted)' }}>Max</div>
                            <div style={{ fontWeight: 'bold', fontSize: '14px', color: isDarkMode ? '#e8e6e3' : '#333' }}>{genericStats.max?.toFixed(2)}</div>
                        </div>
                        <div style={{ padding: '10px', background: isDarkMode ? '#2c2f32' : '#f8fafc', borderRadius: '8px', textAlign: 'center' }}>
                            <div style={{ fontSize: '11px', color: 'var(--muted)' }}>Median</div>
                            <div style={{ fontWeight: 'bold', fontSize: '14px', color: isDarkMode ? '#e8e6e3' : '#333' }}>{genericStats.median?.toFixed(2)}</div>
                        </div>
                        <div style={{ padding: '10px', background: isDarkMode ? '#2c2f32' : '#f8fafc', borderRadius: '8px', textAlign: 'center' }}>
                            <div style={{ fontSize: '11px', color: 'var(--muted)' }}>Range</div>
                            <div style={{ fontWeight: 'bold', fontSize: '14px', color: isDarkMode ? '#e8e6e3' : '#333' }}>{(genericStats.max - genericStats.min)?.toFixed(2)}</div>
                        </div>
                    </div>
                </div>
            </div>
        );
    };

    // Calculate stats from chart data (Existing function logic kept but using it only for NDVI)
    const calculateStats = () => {
        if (!chartData || chartData.length === 0) return null;

        const ndviValues = chartData
            .map(d => d.ndvi)
            .filter(v => v !== null && v !== undefined && !isNaN(v));

        if (ndviValues.length === 0) return null;

        const sorted = [...ndviValues].sort((a, b) => a - b);
        const mean = ndviValues.reduce((a, b) => a + b, 0) / ndviValues.length;
        const min = sorted[0];
        const max = sorted[sorted.length - 1];
        const median = sorted.length % 2 === 0
            ? (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2
            : sorted[Math.floor(sorted.length / 2)];

        const p25Index = Math.floor(sorted.length * 0.25);
        const p75Index = Math.floor(sorted.length * 0.75);
        const p10Index = Math.floor(sorted.length * 0.10);
        const p90Index = Math.floor(sorted.length * 0.90);

        const variance = ndviValues.reduce((sum, v) => sum + Math.pow(v - mean, 2), 0) / ndviValues.length;
        const stdDev = Math.sqrt(variance);

        return {
            mean,
            median,
            min,
            max,
            stdDev,
            range: max - min,
            p25: sorted[p25Index],
            p75: sorted[p75Index],
            p10: sorted[p10Index],
            p90: sorted[p90Index],
        };
    };

    const stats = calculateStats() || ndviStats;

    // Get health status based on mean NDVI
    const getHealthStatus = (mean) => {
        if (mean >= 0.7) return { text: 'Excellent', emoji: '🌿', color: '#22c55e' };
        if (mean >= 0.5) return { text: 'Good', emoji: '👍', color: '#4ade80' };
        if (mean >= 0.3) return { text: 'Moderate', emoji: '😐', color: '#facc15' };
        return { text: 'Poor', emoji: '⚠️', color: '#ef4444' };
    };

    const healthStatus = stats ? getHealthStatus(stats.mean) : { text: '--', emoji: '😐', color: '#9ca3af' };

    // Get progress bar width (NDVI ranges from -1 to 1, normalize to 0-100)
    const getNormalizedValue = (value) => {
        if (value === null || value === undefined) return 0;
        // NDVI ranges from -1 to 1, normalize to 0-100%
        return Math.max(0, Math.min(100, ((value + 1) / 2) * 100));
    };

    // Get progress bar color based on NDVI value
    const getProgressColor = (value) => {
        if (value >= 0.7) return '#22c55e';
        if (value >= 0.5) return '#4ade80';
        if (value >= 0.3) return '#facc15';
        return '#ef4444';
    };

    // Run land cover analysis
    const runLandCoverAnalysis = async () => {
        if (!drawnAOI) {
            Swal.fire({
                icon: 'warning',
                title: 'No Area Selected',
                text: 'Please draw a polygon or rectangle on the map first.',
                confirmButtonColor: 'var(--krishi-green)',
            });
            return;
        }

        if (!startDate || !endDate) {
            Swal.fire({
                icon: 'warning',
                title: 'Select Dates',
                text: 'Please select start and end dates first.',
                confirmButtonColor: 'var(--krishi-green)',
            });
            return;
        }

        setLandCoverLoading(true);
        try {
            const data = await fetchLandCoverAnalysis(drawnAOI, startDate, endDate, timeScale);

            if (data.error) {
                throw new Error(data.error);
            }

            setLandCoverData(data);
            setSelectedPeriod(0);

            Swal.fire({
                icon: 'success',
                title: 'Analysis Complete!',
                text: `Loaded ${data.data?.length || 0} periods of land cover data.`,
                confirmButtonColor: 'var(--krishi-green)',
                timer: 2000,
                showConfirmButton: false,
            });
        } catch (error) {
            console.error('Land cover analysis error:', error);
            Swal.fire({
                icon: 'error',
                title: 'Analysis Failed',
                text: error.message || 'Could not complete land cover analysis.',
                confirmButtonColor: 'var(--krishi-green)',
            });
        } finally {
            setLandCoverLoading(false);
        }
    };

    // Get current period data for the land cover chart
    const getCurrentPeriodData = () => {
        if (!landCoverData?.data || landCoverData.data.length === 0) return null;
        return landCoverData.data[selectedPeriod];
    };

    // Land cover pie chart data
    const landCoverChartData = () => {
        const periodData = getCurrentPeriodData();
        if (!periodData) return null;

        const percentages = periodData.percentages || {};
        return {
            labels: ['Water', 'Bare Land', 'Built-up', 'Sparse Veg', 'Full Veg'],
            datasets: [{
                data: [
                    percentages['Water'] || 0,
                    percentages['Bare Land'] || 0,
                    percentages['Built-up'] || 0,
                    percentages['Sparse Vegetation'] || 0,
                    percentages['Dense Vegetation'] || 0,
                ],
                backgroundColor: ['#1e88e5', '#8d6e63', '#78909c', '#c0ca33', '#43a047'],
                borderWidth: 1,
                borderColor: isDarkMode ? '#2c2f32' : '#ffffff',
            }],
        };
    };

    const landCoverChartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: false,
            },
            tooltip: {
                callbacks: {
                    label: function (context) {
                        return `${context.label}: ${context.parsed}%`;
                    },
                },
                backgroundColor: isDarkMode ? '#2c2f32' : 'rgba(255, 255, 255, 0.95)',
                titleColor: isDarkMode ? '#e8e6e3' : '#334155',
                bodyColor: isDarkMode ? '#e8e6e3' : '#334155',
            },
        },
    };

    // Chart for visual tab
    const comparisonChartData = stats ? {
        labels: ['Min', 'P25', 'Median', 'P75', 'Max'],
        datasets: [{
            label: 'NDVI Distribution',
            data: [stats.min, stats.p25, stats.median, stats.p75, stats.max].map(v => v?.toFixed(3) || 0),
            backgroundColor: [
                'rgba(239, 68, 68, 0.7)',
                'rgba(250, 204, 21, 0.7)',
                'rgba(59, 130, 246, 0.7)',
                'rgba(74, 222, 128, 0.7)',
                'rgba(34, 197, 94, 0.7)',
            ],
            borderColor: [
                'rgb(239, 68, 68)',
                'rgb(250, 204, 21)',
                'rgb(59, 130, 246)',
                'rgb(74, 222, 128)',
                'rgb(34, 197, 94)',
            ],
            borderWidth: 1,
        }],
    } : null;

    const comparisonChartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: false,
            },
            tooltip: {
                backgroundColor: isDarkMode ? '#2c2f32' : 'rgba(255, 255, 255, 0.95)',
                titleColor: isDarkMode ? '#e8e6e3' : '#334155',
                bodyColor: isDarkMode ? '#e8e6e3' : '#334155',
            },
        },
        scales: {
            y: {
                beginAtZero: true,
                max: 1,
                ticks: {
                    color: isDarkMode ? '#a0aec0' : '#64748b',
                },
                grid: {
                    color: isDarkMode ? '#3a3d40' : '#e2e8f0',
                },
            },
            x: {
                ticks: {
                    color: isDarkMode ? '#a0aec0' : '#64748b',
                },
                grid: {
                    display: false,
                },
            },
        },
    };

    // MAIN RENDER LOGIC

    // Case 0: Weather Tab - Show Weather Dashboard
    if (activeChartParam === 'weather') {
        return (
            <aside className={`analytics-sidebar ${!isRightPanelOpen ? 'collapsed' : ''}`}>
                <div className="weather-dashboard" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflowY: 'hidden' }}>
                    {/* Header */}
                    <div style={{
                        textAlign: 'center',
                        padding: '10px',
                        borderBottom: '1px solid var(--border-color)',
                        flexShrink: 0
                    }}>
                        <h3 style={{
                            margin: 0,
                            fontSize: '16px',
                            fontWeight: 600,
                            color: '#607d8b'
                        }}>
                            <i className="fa-solid fa-cloud-sun" style={{ marginRight: '8px' }}></i>
                            {t('opt_w') || 'Weather Analysis'}
                        </h3>
                    </div>

                    <div style={{ flex: '0 1 auto', padding: '12px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)' }}>
                        <i className="fa-solid fa-cloud-showers-heavy" style={{ fontSize: '48px', marginBottom: '16px', opacity: 0.5 }}></i>
                        <p style={{ textAlign: 'center', maxWidth: '80%' }}>
                            Select specific weather parameters from the chart dropdown below to analyze trends.
                        </p>
                    </div>

                    {/* Chart Panel - Sidebar Mode */}
                    <div style={{ flex: 1, padding: '0 10px 10px 10px', display: 'flex', flexDirection: 'column' }}>
                        <ChartPanel mode="sidebar" />
                    </div>
                </div>
            </aside>
        );
    }

    // Case 1: Data is available
    if ((chartData && chartData.length > 0) || ndviStats) {

        // Context A: Layer Selection Context -> Show Full Dashboard
        if (showDashboard && selectedLayer === 'ndvi') {
            return (
                <aside className={`analytics-sidebar ${!isRightPanelOpen ? 'collapsed' : ''}`}>
                    {renderToggleButton()}
                    <div className="ndvi-dashboard" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflowY: 'hidden' }}>
                        {/* Header */}
                        <div style={{
                            textAlign: 'center',
                            padding: '10px',
                            borderBottom: '1px solid var(--border-color)',
                            flexShrink: 0
                        }}>
                            <h3 style={{
                                margin: 0,
                                fontSize: '14px',
                                fontWeight: 600,
                                color: 'var(--krishi-green)'
                            }}>
                                <i className="fa-solid fa-leaf" style={{ marginRight: '8px' }}></i>
                                Average Crop Health
                            </h3>
                        </div>

                        {/* Tabs */}
                        <div className="ndvi-tabs" style={{ padding: '8px', display: 'flex', gap: '4px' }}>
                            <button
                                className={`ndvi-tab-btn ${activeTab === 'overview' ? 'active' : ''}`}
                                onClick={() => setActiveTab('overview')}
                                style={{ flex: 1, padding: '6px', borderRadius: '6px', border: '1px solid transparent', cursor: 'pointer', background: activeTab === 'overview' ? 'var(--krishi-green)' : 'transparent', color: activeTab === 'overview' ? 'white' : 'inherit' }}
                            >
                                <i className="fa-solid fa-chart-pie" style={{ marginRight: '5px' }}></i>
                                {t('opt_overview')}
                            </button>
                            <button
                                className={`ndvi-tab-btn ${activeTab === 'detailed' ? 'active' : ''}`}
                                onClick={() => setActiveTab('detailed')}
                                style={{ flex: 1, padding: '6px', borderRadius: '6px', border: '1px solid transparent', cursor: 'pointer', background: activeTab === 'detailed' ? 'var(--krishi-green)' : 'transparent', color: activeTab === 'detailed' ? 'white' : 'inherit' }}
                            >
                                <i className="fa-solid fa-list-ol" style={{ marginRight: '5px' }}></i>
                                {t('opt_detailed')}
                            </button>
                            <button
                                className={`ndvi-tab-btn ${activeTab === 'visual' ? 'active' : ''}`}
                                onClick={() => setActiveTab('visual')}
                                style={{ flex: 1, padding: '6px', borderRadius: '6px', border: '1px solid transparent', cursor: 'pointer', background: activeTab === 'visual' ? 'var(--krishi-green)' : 'transparent', color: activeTab === 'visual' ? 'white' : 'inherit' }}
                            >
                                <i className="fa-solid fa-chart-bar" style={{ marginRight: '5px' }}></i>
                                {t('opt_visual')}
                            </button>
                        </div>

                        {/* Tab Content */}
                        <div className="ndvi-content-wrapper" style={{ flex: '0 1 auto', maxHeight: '60%', overflowY: 'auto', padding: '12px' }}>

                            {/* Overview Tab */}
                            {activeTab === 'overview' && (
                                <div className="fade-in">
                                    {/* Mean Card */}
                                    <div className="overview-stat-card" style={{ padding: '12px', borderRadius: '8px', marginBottom: '10px', borderLeft: '4px solid var(--krishi-green)', borderRight: '1px solid #e2e8f0', borderTop: '1px solid #e2e8f0', borderBottom: '1px solid #e2e8f0' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                                            <span style={{ fontWeight: 600, color: 'var(--krishi-green)' }}>{t('opt_meana')}</span>
                                            <i className="fa-solid fa-bullseye" style={{ color: 'var(--krishi-green)' }}></i>
                                        </div>
                                        <div style={{ height: '8px', background: 'rgba(34, 197, 94, 0.1)', borderRadius: '4px', overflow: 'hidden' }}>
                                            <div style={{ width: `${getNormalizedValue(stats?.mean)}%`, height: '100%', background: 'var(--krishi-green)' }}></div>
                                        </div>
                                        <div style={{ marginTop: '8px', textAlign: 'right', fontWeight: 'bold', color: '#166534' }}>{stats?.mean?.toFixed(3) || '--'}</div>
                                    </div>

                                    {/* Median Card */}
                                    <div className="overview-stat-card" style={{ padding: '12px', borderRadius: '8px', marginBottom: '10px', borderLeft: '4px solid #166534', borderRight: '1px solid #e2e8f0', borderTop: '1px solid #e2e8f0', borderBottom: '1px solid #e2e8f0' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                                            <span style={{ fontWeight: 600, color: '#166534' }}>{t('opt_median')}</span>
                                            <i className="fa-solid fa-sort" style={{ color: '#166534' }}></i>
                                        </div>
                                        <div style={{ height: '8px', background: 'rgba(34, 197, 94, 0.1)', borderRadius: '4px', overflow: 'hidden' }}>
                                            <div style={{ width: `${getNormalizedValue(stats?.median)}%`, height: '100%', background: '#166534' }}></div>
                                        </div>
                                        <div style={{ marginTop: '8px', textAlign: 'right', fontWeight: 'bold', color: '#166534' }}>{stats?.median?.toFixed(3) || '--'}</div>
                                    </div>

                                    {/* Health Status */}
                                    <div style={{ padding: '16px', borderRadius: '8px', background: 'linear-gradient(135deg, var(--krishi-green), #15803d)', color: 'white', textAlign: 'center', marginTop: '12px', boxShadow: '0 4px 15px rgba(34, 197, 94, 0.2)' }}>
                                        <div style={{ fontSize: '32px', marginBottom: '10px' }}>{healthStatus.emoji}</div>
                                        <h3 style={{ margin: '0 0 5px 0' }}>{t('opt_overall_health')}</h3>
                                        <div style={{ fontSize: '18px', fontWeight: 'bold' }}>{healthStatus.text}</div>
                                        <div style={{ fontSize: '12px', marginTop: '8px', opacity: 0.9 }}>
                                            {t('opt_average')}: {stats?.mean?.toFixed(3)} | {t('opt_range')}: {stats?.range?.toFixed(3)}
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Detailed Tab */}
                            {activeTab === 'detailed' && (
                                <div className="fade-in">
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '12px' }}>
                                        {[
                                            { label: 'opt_min', val: stats?.min, icon: 'fa-arrow-down', color: '#ef4444' },
                                            { label: 'opt_max', val: stats?.max, icon: 'fa-arrow-up', color: '#22c55e' },
                                            { label: 'opt_stddev', val: stats?.stdDev, icon: 'fa-wave-square', color: '#f59e0b' },
                                            { label: 'opt_range', val: stats?.range, icon: 'fa-arrows-left-right', color: '#64748b' }
                                        ].map((item, i) => (
                                            <div key={i} className="detailed-stat-card" style={{ padding: '10px', borderRadius: '8px', textAlign: 'center' }}>
                                                <div style={{ fontSize: '12px', color: 'var(--muted)', marginBottom: '4px' }}>{t(item.label)}</div>
                                                <div style={{ fontWeight: 'bold', fontSize: '14px' }}>{item.val?.toFixed(3) || '--'}</div>
                                            </div>
                                        ))}
                                    </div>

                                    {/* Vegetation Cover Share */}
                                    <div className="section-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '15px' }}>
                                        <h4 style={{ margin: 0, fontSize: '14px' }}>Vegetation Cover Share</h4>
                                    </div>

                                    <div style={{ marginBottom: '15px', display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
                                        <select
                                            value={timeScale}
                                            onChange={(e) => setTimeScale(e.target.value)}
                                            style={{ padding: '6px', borderRadius: '4px', border: '1px solid var(--border-color)', fontSize: '12px', background: 'var(--card-bg)' }}
                                        >
                                            <option value="monthly">Monthly</option>
                                            <option value="weekly">Weekly</option>
                                        </select>
                                        <button
                                            onClick={runLandCoverAnalysis}
                                            disabled={landCoverLoading}
                                            style={{ padding: '6px 12px', borderRadius: '4px', background: 'var(--krishi-green)', color: 'white', border: 'none', cursor: 'pointer', fontSize: '12px' }}
                                        >
                                            {landCoverLoading ? <i className="fa-solid fa-spinner fa-spin"></i> : 'Analyze'}
                                        </button>
                                    </div>

                                    {landCoverData?.data?.length > 0 && (
                                        <div style={{ marginBottom: '15px' }}>
                                            <select
                                                value={selectedPeriod}
                                                onChange={(e) => setSelectedPeriod(parseInt(e.target.value))}
                                                style={{ width: '100%', padding: '6px', borderRadius: '4px', border: '1px solid var(--border-color)', fontSize: '12px', background: 'var(--card-bg)' }}
                                            >
                                                {landCoverData.data.map((p, i) => (
                                                    <option key={i} value={i}>{p.period}</option>
                                                ))}
                                            </select>
                                        </div>
                                    )}

                                    <div style={{ height: '220px', position: 'relative', marginBottom: '15px' }}>
                                        {landCoverChartData() ? (
                                            <Pie data={landCoverChartData()} options={landCoverChartOptions} />
                                        ) : (
                                            <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)', fontSize: '12px', textAlign: 'center', border: '1px dashed var(--border-color)', borderRadius: '8px' }}>
                                                Click Analyze to view vegetation distribution
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )}

                            {/* Visual Tab */}
                            {activeTab === 'visual' && (
                                <div className="fade-in">
                                    <h4 style={{ margin: '0 0 15px 0', fontSize: '14px' }}>NDVI Distribution</h4>
                                    <div style={{ height: '250px' }}>
                                        {comparisonChartData ? (
                                            <Bar data={comparisonChartData} options={comparisonChartOptions} />
                                        ) : (
                                            <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)' }}>No distribution data</div>
                                        )}
                                    </div>
                                    <div style={{ marginTop: '20px', padding: '15px', borderRadius: '8px', background: isDarkMode ? '#2c2f32' : '#f0f9ff', border: '1px solid rgba(59, 130, 246, 0.2)' }}>
                                        <h5 style={{ margin: '0 0 10px 0', fontSize: '13px', color: '#0369a1' }}><i className="fa-solid fa-circle-info"></i> Guide</h5>
                                        <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '12px', color: isDarkMode ? '#e8e6e3' : '#334155' }}>
                                            <li>Median value represents the central tendency of crop health.</li>
                                            <li>Wide range between Min/Max suggests variable field conditions.</li>
                                            <li>Compare P25 and P75 to understand uniformity.</li>
                                        </ul>
                                    </div>
                                </div>
                            )}

                        </div>

                        {/* Chart Panel - Sidebar Mode */}
                        <div style={{ flex: 1, padding: '0 10px 10px 10px', display: 'flex', flexDirection: 'column' }}>
                            <ChartPanel mode="sidebar" />
                        </div>
                    </div>
                </aside>
            );
        }

        // Context B: Chart Tab Context -> Show Data Report
        const reportCharts = getReportCharts();
        if (reportCharts) {
            return (
                <aside className={`analytics-sidebar ${!isRightPanelOpen ? 'collapsed' : ''}`}>
                    {renderToggleButton()}
                    {reportCharts}
                    {/* Chart Panel - Sidebar Mode */}
                    <div style={{ flex: 1, padding: '4px 10px', display: 'flex', flexDirection: 'column' }}>
                        <ChartPanel mode="sidebar" />
                    </div>
                </aside>
            );
        }
    }

    // Case 2: No Data - Logic for Placeholders
    // Only show Crop Health Statistics if NDVI layer is selected (Pre-computation/Map View)
    if (selectedLayer !== 'ndvi') {
        return (
            <aside className={`analytics-sidebar ${!isRightPanelOpen ? 'collapsed' : ''}`}>
                {renderToggleButton()}
                <div className="default-analytics-placeholder">
                    <h3>{t('data_analytics')}</h3>
                    <div className="analytics-chart-wrap">
                        <div style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            height: '100%',
                            color: 'var(--muted)',
                            textAlign: 'center',
                            padding: '20px',
                        }}>
                            <p>Select "Crop Health" (NDVI) layer to view statistics</p>
                        </div>
                    </div>
                </div>
                {/* Chart Panel - Sidebar Mode */}
                <div style={{ flex: 1, padding: '4px 10px', display: 'flex', flexDirection: 'column' }}>
                    <ChartPanel mode="sidebar" />
                </div>
            </aside >
        );
    }

    // If no data, show placeholder (NDVI selected but no data fetched)
    return (
        <aside className={`analytics-sidebar ${!isRightPanelOpen ? 'collapsed' : ''}`}>
            {renderToggleButton()}
            <div className="default-analytics-placeholder">
                <h3>{t('data_analytics')}</h3>
                <div className="analytics-chart-wrap">
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        height: '100%',
                        color: 'var(--muted)',
                        textAlign: 'center',
                        padding: '20px',
                    }}>
                        <p>Fetch data to view analytics</p>
                    </div>
                </div>
            </div>
            {/* Chart Panel - Sidebar Mode */}
            <div style={{ flex: 1, padding: '4px 10px', display: 'flex', flexDirection: 'column' }}>
                <ChartPanel mode="sidebar" />
            </div>
        </aside>
    );
}

export default AnalyticsSidebar;
