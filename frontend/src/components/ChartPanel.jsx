import { useRef, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    Title,
    Tooltip,
    Legend,
    Filler,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import { useApp } from '../context/AppContext';
import { t } from '../utils/translations';

// Register Chart.js components
ChartJS.register(
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    Title,
    Tooltip,
    Legend,
    Filler
);

const chartParams = [
    { key: 'pca', label: 'opt_pca' },
    { key: 'ndvi', label: 'opt_ndvi' },
    // { key: 'savi', label: 'opt_savi' },
    { key: 'cwsi', label: 'opt_cwsi' },
    { key: 'kc', label: 'opt_kc' },
    { key: 'etc', label: 'opt_etc' },
    { key: 'irrigation_need', label: 'opt_irrigation_need' },
    { key: 'soilmoisture_mm', label: 'opt_soilmoisture' },
    { key: 'lst', label: 'opt_lst' },
    { key: 'lai', label: 'opt_lai' },
    { key: 'chlorophyll', label: 'opt_chlorophyll' },

    { key: 'weather', label: 'opt_w' },
];

// Weather params now map to actual backend fields
const weatherParams = [
    { key: 'eto', label: 'opt_evt', dataKey: 'eto', unit: 'mm/day' },
    { key: 'precipitation', label: 'opt_rp', dataKey: 'rain', unit: 'mm/day' },
    { key: 'humidity', label: 'opt_hum', dataKey: 'soilmoisture_mm', unit: '%', transform: (v) => Math.min(100, Math.max(20, (v || 0) * 2)) },
];

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
    chlorophyll: { border: 'rgb(76, 175, 80)', background: 'rgba(76, 175, 80, 0.1)' },
    eto: { border: 'rgb(59, 130, 246)', background: 'rgba(59, 130, 246, 0.1)' },
    precipitation: { border: 'rgb(34, 197, 94)', background: 'rgba(34, 197, 94, 0.1)' },
    temperature: { border: 'rgb(239, 68, 68)', background: 'rgba(239, 68, 68, 0.1)' },
    humidity: { border: 'rgb(168, 85, 247)', background: 'rgba(168, 85, 247, 0.1)' },
    pca: { border: 'rgb(156, 39, 176)', background: 'rgba(156, 39, 176, 0.1)' },
};

function ChartPanel({ mode = 'overlay' }) {
    const { 
        chartData, 
        activeChartParam, 
        setActiveChartParam, 
        isDarkMode, 
        availableImageryDates,
        dateMode,
        baselineDate,
        baselineYears 
    } = useApp();
    const [selectedWeatherParam, setSelectedWeatherParam] = useState('eto');
    const [isCollapsed, setIsCollapsed] = useState(true); // Default collapsed
    const [isExpanded, setIsExpanded] = useState(false); // Modal state
    const chartRef = useRef(null);

    // Sidebar mode: Always expanded, no toggle
    useEffect(() => {
        if (mode === 'sidebar') {
            setIsCollapsed(false);
        }
    }, [mode]);

    // Get chart data for current parameter with min/max/mean calculation
    // Find the label for the active parameter (Moved to top to avoid ReferenceError)
    const activeParamObj = chartParams.find(p => p.key === activeChartParam);
    const chartTitle = (chartData && chartData.length > 0 && activeParamObj)
        ? t(activeParamObj.label)
        : (t('data_analytics') || 'Trend Analysis');

    const getChartConfigForData = (dataSubset, labelSuffix = '') => {
        if (!dataSubset || dataSubset.length === 0) {
            return null;
        }

        const imageryDateSet = new Set(availableImageryDates || []);
        const sourceData = imageryDateSet.size > 0
            ? dataSubset.filter(d => d?.date && imageryDateSet.has(d.date))
            : dataSubset;

        let dataKey = activeChartParam;
        const getPointValue = (d) => {
            if (!d) return null;

            if (activeChartParam === 'weather') {
                const weatherConfig = weatherParams.find(p => p.key === selectedWeatherParam);
                if (!weatherConfig) return null;
                const rawValue = d[weatherConfig.dataKey];
                if (rawValue === null || rawValue === undefined) return null;
                const numValue = Number(rawValue);
                if (isNaN(numValue)) return null;
                dataKey = selectedWeatherParam;
                return weatherConfig.transform ? weatherConfig.transform(numValue) : numValue;
            }

            if (activeChartParam === 'lst') {
                const kelvin = d.lst;
                if (kelvin === null || kelvin === undefined) return null;
                return kelvin - 273.15;
            }

            if (activeChartParam === 'soilmoisture_mm') {
                const value = d.soilmoisture_mm ?? d.soilmoisture;
                return value === null || value === undefined || isNaN(Number(value)) ? null : Number(value);
            }

            if (activeChartParam === 'chlorophyll') {
                const value = d.clre;
                return value === null || value === undefined || isNaN(Number(value)) ? null : Number(value);
            }

            const value = d[activeChartParam];
            return value === null || value === undefined || isNaN(Number(value)) ? null : Number(value);
        };

        // Keep only dates where the selected metric has a valid (mean) value.
        const pairedPoints = sourceData
            .map(d => ({ date: d.date, value: getPointValue(d) }))
            .filter(p => p.date && p.value !== null);

        if (pairedPoints.length === 0) {
            return null;
        }

        const labels = pairedPoints.map(p => p.date);
        const dataValues = pairedPoints.map(p => p.value);

        // Calculate min, max, and mean for each date point
        // For now, we'll use the single value as mean and calculate a range
        // In a real scenario, you might have multiple readings per day
        const validValues = dataValues.filter(v => v !== null && v !== undefined);
        if (validValues.length === 0) {
            return null;
        }
        const globalMin = Math.min(...validValues);
        const globalMax = Math.max(...validValues);
        const range = globalMax - globalMin;

        // Create datasets with min/max bands (20% above/below for better visibility)
        const meanValues = dataValues;
        const minValues = dataValues.map(v => v !== null ? v * 0.7 : null); // 20% below for visualization
        const maxValues = dataValues.map(v => v !== null ? v * 1.3 : null); // 20% above for visualization

        const colors = paramColors[dataKey] || paramColors.ndvi;

        // Determine the label
        let chartLabel;
        if (activeChartParam === 'weather') {
            const weatherConfig = weatherParams.find(p => p.key === selectedWeatherParam);
            if (weatherConfig) {
                const rawLabel = t(weatherConfig.label);
                // Remove last parenthesized group if it exists (stripping existing unit like "(mm)")
                // but preserve (ETc) if it's not the very last thing or if we want to be safe
                // The regex \s*\([^)]*\)$ matches a space (optional) followed by (...) at end of string
                const cleanLabel = rawLabel.replace(/\s*\([^)]*\)$/, '');
                chartLabel = `${cleanLabel} (${weatherConfig.unit})${labelSuffix}`;
            } else {
                chartLabel = `${t('opt_w')}${labelSuffix}`;
            }
        } else {
            const paramConfig = chartParams.find(p => p.key === activeChartParam);
            const paramLabel = t(paramConfig?.label || activeChartParam);
            chartLabel = `${activeChartParam === 'lst' ? `${paramLabel} (°C)` : paramLabel}${labelSuffix}`;
        }

        // Extract RGB from border color for transparency
        const borderRGB = colors.border.match(/\d+/g);
        const lightColor = borderRGB ? `rgba(${borderRGB[0]}, ${borderRGB[1]}, ${borderRGB[2]}, 0.15)` : colors.background;
        const mediumColor = borderRGB ? `rgba(${borderRGB[0]}, ${borderRGB[1]}, ${borderRGB[2]}, 0.3)` : colors.background;

        return {
            labels,
            datasets: [
                // Max Range (top of shaded area)
                {
                    label: 'Max Range',
                    data: maxValues,
                    borderColor: 'transparent', // Invisible line
                    backgroundColor: lightColor, // Fill color to the next dataset (Mean)
                    fill: 1, // Fill to dataset index 1 (Mean)
                    tension: 0.4,
                    pointRadius: 0,
                    pointHoverRadius: 0,
                    spanGaps: true,
                    order: 3,
                },
                // Mean line (middle)
                {
                    label: chartLabel,
                    data: meanValues,
                    borderColor: colors.border,
                    backgroundColor: lightColor, // Fill color to the next dataset (Min)
                    fill: 2, // Fill to dataset index 2 (Min)
                    tension: 0.4,
                    borderWidth: 3,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    pointBackgroundColor: colors.border,
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    spanGaps: true,
                    order: 1,
                },
                // Min Range (bottom of shaded area)
                {
                    label: 'Min Range',
                    data: minValues,
                    borderColor: 'transparent', // Invisible line
                    backgroundColor: lightColor,
                    fill: false, // Stop filling here
                    tension: 0.4,
                    pointRadius: 0,
                    pointHoverRadius: 0,
                    spanGaps: true,
                    order: 2,
                },
            ],
        };
    };

    // Dynamic Split logic by individual calendar years in Baseline Mode
    const getSplitYearsData = () => {
        if (!chartData || chartData.length === 0 || dateMode !== 'baseline') {
            return [];
        }

        const parts = baselineDate.split('-');
        const year = parseInt(parts[0]);
        const month = parseInt(parts[1]) - 1;
        const day = parseInt(parts[2]);
        
        const pad = (n) => String(n).padStart(2, '0');

        const yearsData = [];
        // Loop through each baseline year from 0 to baselineYears - 1
        for (let i = 0; i < baselineYears; i++) {
            const startYear = year - (i + 1);
            const endYear = year - i;

            // Generate start and end date strings
            const startStr = `${startYear}-${pad(month + 1)}-${pad(day)}`;
            const endStr = `${endYear}-${pad(month + 1)}-${pad(day)}`;

            const subset = chartData.filter(d => {
                if (i === baselineYears - 1) {
                    // Oldest year: inclusive of startStr boundary to capture all initial days
                    return d.date >= startStr && d.date <= endStr;
                } else {
                    // Newer years: exclusive of startStr to prevent daily overlap between charts
                    return d.date > startStr && d.date <= endStr;
                }
            });

            yearsData.push({
                label: `${startYear} - ${endYear}`,
                startYear,
                endYear,
                startDateStr: startStr,
                endDateStr: endStr,
                subset,
                config: getChartConfigForData(subset)
            });
        }

        return yearsData;
    };

    const isBaselineSplit = dateMode === 'baseline' && chartData && chartData.length > 0;
    const splitYears = getSplitYearsData();

    const chartConfig = !isBaselineSplit ? getChartConfigForData(chartData) : null;

    // Dates range helper
    const getDatesRange = (subset) => {
        if (!subset || subset.length === 0) return '';
        const dates = subset.map(d => d.date).filter(Boolean).sort();
        if (dates.length === 0) return '';
        return `(${dates[0]} to ${dates[dates.length - 1]})`;
    };


    const options = {
        responsive: true,
        maintainAspectRatio: false,
        animation: {
            x: {
                type: 'number',
                easing: 'linear',
                duration: 300, // Duration of the transition for each point (smoother overlap)
                from: NaN, // Start handling from "no value"
                delay: (ctx) => {
                    if (ctx.type !== 'data' || ctx.xStarted) {
                        return 0;
                    }
                    ctx.xStarted = true;
                    const totalPoints = ctx.chart.data.datasets[0].data.length;
                    // Adjust total time based on number of points to keep it snappy but readable
                    // If many points, faster total time. If few points, slower.
                    const totalDuration = totalPoints > 50 ? 1000 : 1500;
                    const delayPerPoint = totalDuration / totalPoints;
                    return ctx.index * delayPerPoint;
                }
            },
            y: {
                type: 'number',
                easing: 'easeOutQuart', // Smooth easing for value growth
                duration: 500, // Longer duration for the rise effect
                from: (ctx) => {
                    return ctx.chart.scales.y.getPixelForValue(ctx.chart.scales.y.min);
                },
                delay: (ctx) => {
                    if (ctx.type !== 'data' || ctx.yStarted) {
                        return 0;
                    }
                    ctx.yStarted = true;
                    const totalPoints = ctx.chart.data.datasets[0].data.length;
                    const totalDuration = totalPoints > 50 ? 1000 : 1500;
                    const delayPerPoint = totalDuration / totalPoints;
                    return ctx.index * delayPerPoint;
                }
            },
        },
        interaction: {
            intersect: false,
            mode: 'index',
        },
        plugins: {
            legend: {
                display: true,
                position: 'top',
                labels: {
                    color: isDarkMode ? '#e8e6e3' : '#334155',
                    font: {
                        family: 'Poppins',
                        size: 11,
                    },
                    usePointStyle: true,
                    boxWidth: 8,
                    filter: function (legendItem, chartData) {
                        // Only show the main dataset (index 1) in the legend
                        return legendItem.datasetIndex === 1;
                    }
                },
            },
            tooltip: {
                backgroundColor: isDarkMode ? 'rgba(44, 47, 50, 0.9)' : 'rgba(255, 255, 255, 0.95)',
                titleColor: isDarkMode ? '#e8e6e3' : '#334155',
                bodyColor: isDarkMode ? '#e8e6e3' : '#334155',
                borderColor: isDarkMode ? '#4a4a4a' : '#e2e8f0',
                borderWidth: 1,
                cornerRadius: 8,
                padding: 10,
                displayColors: true,
                boxPadding: 4,
                titleFont: {
                    family: 'Poppins',
                    size: 12,
                    weight: '600',
                },
                bodyFont: {
                    family: 'Poppins',
                    size: 11,
                },
                callbacks: {
                    label: function (context) {
                        let value = context.parsed.y;
                        if (value !== null && value !== undefined) {
                            return `${context.dataset.label}: ${value.toFixed(3)}`;
                        }
                        return `${context.dataset.label}: N/A`;
                    },
                },
            },
        },
        scales: {
            x: {
                grid: {
                    display: false, // Cleaner look
                    color: isDarkMode ? '#3a3d40' : '#e2e8f0',
                },
                ticks: {
                    color: isDarkMode ? '#a0aec0' : '#64748b',
                    font: {
                        family: 'Poppins',
                        size: 10,
                    },
                    maxRotation: 0,
                    minRotation: 0,
                },
            },
            y: {
                grid: {
                    color: isDarkMode ? 'rgba(58, 61, 64, 0.5)' : 'rgba(226, 232, 240, 0.5)',
                    borderDash: [5, 5], // Dashed grid lines
                },
                ticks: {
                    color: isDarkMode ? '#a0aec0' : '#64748b',
                    font: {
                        family: 'Poppins',
                        size: 9, // Smaller ticks
                    },
                },
                beginAtZero: activeChartParam !== 'lst',
            },
        },

    };



    const renderStatsForConfig = (config) => {
        if (!config || activeChartParam === 'weather') return null;

        const meanDataset = config.datasets.find(d => d.label.includes('Mean') || (d.label && !d.label.includes('Range')));
        if (!meanDataset) return null;

        const validValues = meanDataset.data.filter(v => v !== null && v !== undefined);
        if (validValues.length === 0) return null;

        const min = Math.min(...validValues);
        const max = Math.max(...validValues);
        const mean = validValues.reduce((a, b) => a + b, 0) / validValues.length;

        return (
            <div style={{
                display: 'flex',
                justifyContent: 'center',
                gap: '20px',
                padding: '12px',
                marginTop: '8px',
                background: 'var(--card-bg)',
                borderRadius: '8px',
                border: '1px solid var(--border-color)',
                fontSize: '13px',
                fontWeight: '500'
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>Min:</span>
                    <span style={{ color: '#0ea5e9', fontWeight: '600' }}>{min.toFixed(3)}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>Mean:</span>
                    <span style={{ color: '#10b981', fontWeight: '600' }}>{mean.toFixed(3)}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>Max:</span>
                    <span style={{ color: '#f59e0b', fontWeight: '600' }}>{max.toFixed(3)}</span>
                </div>
            </div>
        );
    };

    return (
        <>
            <div className={`chart-area ${isCollapsed ? 'collapsed' : ''} ${mode === 'sidebar' ? 'sidebar-mode' : ''}`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', borderBottom: '1px solid var(--border-color)', marginBottom: '8px' }}>
                    <h4 style={{ margin: 0, fontSize: '13px', fontWeight: 600, color: 'var(--text-main)' }}>
                        {chartTitle}
                    </h4>
                    <button
                        onClick={() => setIsExpanded(true)}
                        style={{
                            background: 'transparent',
                            border: 'none',
                            cursor: 'pointer',
                            color: 'var(--text-secondary)',
                            padding: '4px',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '4px',
                            fontSize: '12px'
                        }}
                        title="Maximize Chart"
                    >
                        <i className="fa-solid fa-expand"></i>
                        <span>Expand</span>
                    </button>
                </div>

                {/* Weather Parameter Dropdown */}
                {activeChartParam === 'weather' && chartData && (
                    <div style={{ display: 'flex', marginBottom: '12px', textAlign: 'center', justifyContent: 'center' }}>
                        <label
                            htmlFor="weather-param-select"
                            style={{
                                fontSize: '13px',
                                fontWeight: '600',
                                marginRight: '8px',
                                display: 'flex',
                                alignItems: 'center'
                            }}
                        >
                            {t('opt_wp')}
                        </label>
                        <select
                            id="weather-param-select"
                            value={selectedWeatherParam}
                            onChange={(e) => setSelectedWeatherParam(e.target.value)}
                            style={{
                                padding: '6px 12px',
                                borderRadius: '8px',
                                border: '1px solid var(--border-color)',
                                background: 'var(--card-bg)',
                                fontSize: '13px',
                            }}
                        >
                            {weatherParams.map(param => {
                                const label = t(param.label).replace(/\s*\([^)]*\)$/, '');
                                return (
                                    <option key={param.key} value={param.key}>
                                        {label}
                                    </option>
                                );
                            })}
                        </select>
                    </div>
                )}

                <div className="chart-wrap" style={{ overflowY: isBaselineSplit ? 'auto' : 'hidden' }}>
                    {!chartData ? (
                        <div className="chart-placeholder">
                            <p>{t('opt_Draw')}</p>
                        </div>
                    ) : isBaselineSplit ? (
                        <div style={{ padding: '8px 0' }}>
                            {splitYears.map((yearItem, index) => (
                                <div key={index} style={{ marginBottom: '24px' }}>
                                    {index > 0 && <hr style={{ border: '0', borderTop: '1px solid var(--border-color)', margin: '16px 0' }} />}
                                    <div style={{ padding: '0 12px' }}>
                                        <h5 style={{ margin: '0 0 6px 0', fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                                            {index === 0 ? 'Baseline Year' : 'Historical Reference'} ({yearItem.label}) {getDatesRange(yearItem.subset)}
                                        </h5>
                                    </div>
                                    <div style={{ width: '100%', height: '180px', padding: '0 12px 12px 12px' }}>
                                        {yearItem.config && (
                                            <Line
                                                data={yearItem.config}
                                                options={options}
                                            />
                                        )}
                                    </div>
                                    <div style={{ padding: '0 12px 12px 12px' }}>
                                        {renderStatsForConfig(yearItem.config)}
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <>
                            <div style={{ width: '100%', height: 'calc(100% - 60px)' }}>
                                {chartConfig && (
                                    <Line
                                        ref={chartRef}
                                        data={chartConfig}
                                        options={options}
                                    />
                                )}
                            </div>
                            {/* Statistics Display - Hidden for weather tab */}
                            {chartConfig && activeChartParam !== 'weather' && renderStatsForConfig(chartConfig)}
                        </>
                    )}
                </div>
            </div>

            {/* Maximized Modal - Using Portal to break out of sidebar stacking context */}
            {isExpanded && createPortal(
                <div className="chart-modal-overlay" style={{
                    position: 'fixed',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    backgroundColor: 'rgba(0, 0, 0, 0.75)',
                    zIndex: 20000,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: '20px',
                    backdropFilter: 'blur(5px)'
                }}>
                    <div className="chart-modal-content" style={{
                        background: isDarkMode ? '#1e1e1e' : '#fff',
                        width: '90%',
                        maxWidth: '1200px',
                        height: '85vh',
                        borderRadius: '16px',
                        padding: '24px',
                        display: 'flex',
                        flexDirection: 'column',
                        boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)'
                    }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                            <h2 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: isDarkMode ? '#e0e0e0' : '#333' }}>
                                {chartTitle} - Expanded View
                            </h2>
                            <button
                                onClick={() => setIsExpanded(false)}
                                style={{
                                    background: 'rgba(0,0,0,0.05)',
                                    border: 'none',
                                    borderRadius: '50%',
                                    width: '36px',
                                    height: '36px',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    cursor: 'pointer',
                                    color: isDarkMode ? '#e0e0e0' : '#333',
                                    fontSize: '16px',
                                    transition: 'all 0.2s'
                                }}
                            >
                                <i className="fa-solid fa-xmark"></i>
                            </button>
                        </div>
                        <div style={{ flex: 1, overflowY: 'auto', paddingRight: '8px' }}>
                            {isBaselineSplit ? (
                                <>
                                    {splitYears.map((yearItem, index) => (
                                        <div key={index} style={{ marginBottom: '32px' }}>
                                            {index > 0 && <hr style={{ border: '0', borderTop: '1px solid var(--border-color)', margin: '24px 0' }} />}
                                            <h3 style={{ margin: '0 0 12px 0', fontSize: '15px', fontWeight: 600, color: isDarkMode ? '#e0e0e0' : '#333', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                                                {index === 0 ? 'Baseline Year' : 'Historical Reference'} ({yearItem.label}) {getDatesRange(yearItem.subset)}
                                            </h3>
                                            <div style={{ height: '32vh', position: 'relative' }}>
                                                {yearItem.config && <Line data={yearItem.config} options={{ ...options, maintainAspectRatio: false }} />}
                                            </div>
                                            <div style={{ marginTop: '12px' }}>
                                                {renderStatsForConfig(yearItem.config)}
                                            </div>
                                        </div>
                                    ))}
                                </>
                            ) : (
                                <>
                                    <div style={{ height: '70vh', position: 'relative' }}>
                                        {chartConfig && <Line data={chartConfig} options={{ ...options, maintainAspectRatio: false }} />}
                                    </div>
                                    <div style={{ marginTop: '12px' }}>
                                        {chartConfig && activeChartParam !== 'weather' && renderStatsForConfig(chartConfig)}
                                    </div>
                                </>
                            )}
                        </div>
                    </div>
                </div>,
                document.body
            )}
        </>
    );

}

export default ChartPanel;
