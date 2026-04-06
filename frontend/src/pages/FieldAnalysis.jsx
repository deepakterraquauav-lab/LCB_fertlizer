import { useCallback, useRef, useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AppProvider, useApp } from '../context/AppContext';
import Header from '../components/Header';
import Sidebar from '../components/Sidebar';
import MapComponent from '../components/MapComponent';
import ChartPanel from '../components/ChartPanel';
import AnalyticsSidebar from '../components/AnalyticsSidebar';
import LoadingOverlay from '../components/LoadingOverlay';
import IrrigationCalendarPanel from '../components/IrrigationCalendarPanel';
import MapLegend from '../components/MapLegend';
import ComparisonView from '../components/ComparisonView';
import NotificationContainer from '../components/NotificationContainer';
import DateCarousel from '../components/DateCarousel';
import { fetchDailyData, fetchIrrigationCalendar, fetchGeeTile, fetchVraMap, generateReport, getFields } from '../utils/api';
import { getLayerDisplayName } from '../utils/layerConstants';
import Swal from 'sweetalert2';
import '../index.css';
import '@fortawesome/fontawesome-free/css/all.min.css';

// --- 1. DEFINE CONSTANTS HERE (Must be outside the function) ---
const FETCH_MESSAGES = [
  "Connecting to Earth Engine...",
  "Filtering cloud cover...",
  "Calculating NDVI & ETo indices...",
  "Aggregating daily statistics...",
  "Finalizing data visualization..."
];

const LAYER_MESSAGES = [
  "Fetching satellite tiles...",
  "Applying color palette...",
  "Enhancing resolution...",
  "Rendering map layer...",
  "Optimizing visuals..."
];

const IRRIGATION_MESSAGES = [
  "Analyzing soil moisture data...",
  "Calculating crop water requirements...",
  "Evaluating weather forecast...",
  "Scheduling irrigation events...",
  "Finalizing calendar..."
];

const REPORT_MESSAGES = [
  "Compiling field statistics...",
  "Generating trend charts...",
  "Formatting layout...",
  "Creating PDF document...",
  "Preparing download..."
];



// --- 2. SMART LOADER COMPONENT ---
function SmartLoader({ visible, title, messages }) {
  const [progress, setProgress] = useState(0);
  const [messageIndex, setMessageIndex] = useState(0);

  // Use provided messages or fallback
  const currentMessages = messages && messages.length > 0 ? messages : FETCH_MESSAGES;

  useEffect(() => {
    if (!visible) {
      setProgress(0);
      return;
    }

    // Progress Bar Animation
    const interval = setInterval(() => {
      setProgress((oldProgress) => {
        if (oldProgress >= 90) return 90;
        return Math.min(oldProgress + Math.random() * 10, 90);
      });
    }, 500);

    // Message Rotation
    const msgInterval = setInterval(() => {
      setMessageIndex(prev => (prev + 1) % currentMessages.length);
    }, 2000);

    return () => {
      clearInterval(interval);
      clearInterval(msgInterval);
    };
  }, [visible, currentMessages]);

  if (!visible) return null;

  return (
    <div className="smart-loader-overlay">
      <div className="smart-loader-content">
        <div className="loader-header">
          <div className="satellite-spinner-small">
            <i className="fas fa-satellite"></i>
          </div>
          <h3 className="loader-title">{title || 'Analyzing...'}</h3>
        </div>

        <div className="progress-container">
          <div className="progress-bar" style={{ width: `${progress}%` }}></div>
        </div>

        <div className="loader-status">
          {currentMessages[messageIndex]}
        </div>


      </div>
    </div>
  );
}

function AppContent() {
  const {
    startDate,
    endDate,
    drawnAOI,
    setDrawnAOI,
    selectedLayer,
    setSelectedLayer,
    opacity,
    setChartData,
    chartData,
    setNdviStats,
    irrigationCalendar,
    setIrrigationCalendar,
    clearAllData,
    isSidebarOpen,
    isRightPanelOpen,
    ensureRightPanelOpen,
    language,
    setLoadingState,
    notify,
    removeNotification
  } = useApp();

  const [searchParams] = useSearchParams();
  const fieldId = searchParams.get('field_id');

  const mapCenterFunctionRef = useRef(null);
  const layerRequestRef = useRef(null);
  const abortControllerRef = useRef(null);
  const [showCalendar, setShowCalendar] = useState(false);
  const currentTileDataRef = useRef(null);
  const [currentLayerType, setCurrentLayerType] = useState(null);
  const [layerStats, setLayerStats] = useState(null);
  const [selectedImageryDate, setSelectedImageryDate] = useState(null);
  const [dateCarouselKey, setDateCarouselKey] = useState(0); // Add a key to force re-render/re-fetch

  // New State for Smart Loader (Dynamic)
  const [smartLoader, setSmartLoader] = useState({
    visible: false,
    title: '',
    messages: []
  });

  // Comparison view state
  const [showComparison, setShowComparison] = useState(false);
  const [comparisonLayers, setComparisonLayers] = useState([]);

  // Load field from URL if present
  useEffect(() => {
    async function loadField() {
      if (fieldId && !drawnAOI) {
        let loadingSwal;
        try {
          loadingSwal = Swal.fire({
            title: 'Loading Field...',
            html: 'Please wait while we fetch the field data.',
            allowOutsideClick: false,
            didOpen: () => {
              Swal.showLoading();
            }
          });

          // Try backend first, fallback to localStorage
          let field = null;
          try {
            const fields = await getFields();
            field = fields.find(f => f.id.toString() === fieldId);
          } catch (e) {
            console.log('Backend fetch failed, checking localStorage');
          }

          if (!field) {
            const localFields = JSON.parse(localStorage.getItem('fields') || '[]');
            field = localFields.find(f => f.id.toString() === fieldId);
          }

          if (field) {
            console.log('Loaded field:', field);
            let geometry = field.geometry;
            const feature = {
              type: 'Feature',
              geometry: geometry,
              properties: { name: field.name, type: field.type }
            };
            setDrawnAOI(feature);
            Swal.close();
          } else {
            Swal.fire({
              icon: 'error',
              title: 'Field Not Found',
              text: 'Could not locate the requested field.',
              confirmButtonColor: 'var(--krishi-green)'
            });
          }
        } catch (e) {
          console.error("Error loading field", e);
          Swal.fire({
            icon: 'error',
            title: 'Error',
            text: 'Failed to load field data.',
            confirmButtonColor: 'var(--krishi-green)'
          });
        }
      }
    }
    loadField();
  }, [fieldId, drawnAOI, setDrawnAOI, notify]);

  // Handle location select from header search
  const handleLocationSelectSetup = useCallback((centerFunction) => {
    mapCenterFunctionRef.current = centerFunction;
  }, []);

  const handleLocationSelect = useCallback((lat, lon, name) => {
    if (mapCenterFunctionRef.current) {
      mapCenterFunctionRef.current(lat, lon, name);
    }
  }, []);

  // Handle AOI creation
  const handleAOICreated = useCallback((geojson) => {
    console.log('AOI Created:', geojson);
    setDrawnAOI(geojson);
  }, [setDrawnAOI]);

  // Handle fetch data
  const handleFetchData = useCallback(async () => {
    if (!drawnAOI) {
      Swal.fire({
        icon: 'warning',
        title: 'Missing Information',
        text: 'Please draw an Area of Interest (AOI) on the map first.',
        confirmButtonColor: 'var(--krishi-green)',
      });
      return;
    }

    const start = new Date(startDate);
    const end = new Date(endDate);
    const diffDays = Math.ceil((end - start) / (1000 * 60 * 60 * 24));

    if (diffDays > 365) {
      Swal.fire({
        icon: 'warning',
        title: 'Date Range Too Large',
        text: 'Please select ≤ 12 months (≤ 365 days).',
        confirmButtonColor: 'var(--krishi-green)',
      });
      return;
    }

    // START SMART LOADER
    setSmartLoader({
      visible: true,
      title: 'Fetching Field Data...',
      messages: FETCH_MESSAGES
    });
    setLoadingState('isFetchingData', true);

    try {
      console.log('Sending AOI:', drawnAOI);

      const result = await fetchDailyData(drawnAOI, startDate, endDate, fieldId);

      // Handle non-ok response
      if (!result.ok) {
        setSmartLoader(prev => ({ ...prev, visible: false })); // Stop loader immediately on error

        const serverMessage = result.data && (result.data.message || result.data.error)
          ? result.data.message || result.data.error
          : `Server error (${result.status})`;
        const availability = result.data && result.data.availability ? result.data.availability : null;

        let html = `<div>${serverMessage}</div>`;
        if (availability) {
          html += '<br><b>Dataset availability:</b><br>';
          for (const k of Object.keys(availability)) {
            html += `${k}: ${availability[k]}<br>`;
          }
        }

        Swal.fire({
          icon: 'warning',
          title: 'Processing Error',
          html,
          confirmButtonColor: 'var(--krishi-green)',
        });
        return;
      }

      const data = result.data;

      if (!data || (Array.isArray(data) && data.length === 0) || (data && data.error)) {
        setSmartLoader(prev => ({ ...prev, visible: false })); // Stop loader

        let errorMessage = 'No data was found for the selected area and date range.';
        let errorDetails = '';

        if (data && data.error) {
          errorMessage = data.error;
          if (errorMessage.includes('No cloud-free Landsat imagery')) {
            errorDetails = '<br><br><strong>Suggestions:</strong><br>• Try adjusting the date range<br>• Increase cloud filter tolerance<br>• Select a different area';
          } else if (errorMessage.includes('Date range too large')) {
            errorMessage = 'Date Range Too Large';
            errorDetails = '<br><br>Please select ≤ 12 months (≤ 365 days).';
          }
        }

        Swal.fire({
          icon: 'info',
          title: 'No Data Available',
          html: errorMessage + errorDetails,
          confirmButtonColor: 'var(--krishi-green)',
        });
        return;
      }

      // Success Path
      setChartData(data);

      try {
        const cropHealthData = {
          data: data,
          startDate: startDate,
          endDate: endDate,
          timestamp: new Date().toISOString()
        };
        localStorage.setItem('lastCropHealthData', JSON.stringify(cropHealthData));
        console.log('✅ Crop health data saved to localStorage');
      } catch (e) {
        console.warn('Failed to save crop health data to localStorage:', e);
      }

      // NDVI stats and right analytics panel are intentionally not updated/opened
      // here to keep the right panel hidden after fetching data.

      // Trigger DateCarousel refresh
      setDateCarouselKey(prev => prev + 1);

      // IMPORTANT: Stop the loader before showing the success alert
      setSmartLoader(prev => ({ ...prev, visible: false }));

      Swal.fire({
        icon: 'success',
        title: 'Analysis Complete!',
        html: `
          <div style="text-align: left; font-size: 0.95em;">
            <p><strong><i class="fas fa-check-circle" style="color:var(--krishi-green)"></i> Status:</strong> Data successfully analyzed.</p>
            <p><strong><i class="fas fa-database" style="color:#2196f3"></i> Data Points:</strong> ${data.length} records.</p>
            <p><strong><i class="fas fa-calendar-alt" style="color:#ff9800"></i> Range:</strong> ${startDate} to ${endDate}</p>
          </div>
        `,
        confirmButtonText: 'View Charts',
        confirmButtonColor: 'var(--krishi-green)',
        timer: 3000,
        timerProgressBar: true
      });

    } catch (error) {
      console.error('Error fetching data:', error);
      setSmartLoader(prev => ({ ...prev, visible: false })); // Stop loader on error
      Swal.fire({
        icon: 'error',
        title: 'Fetch Failed',
        text: error.message || 'Could not fetch data. Please try again.',
        confirmButtonColor: 'var(--krishi-green)',
      });
    } finally {
      setLoadingState('isFetchingData', false);
    }
  }, [drawnAOI, startDate, endDate, setLoadingState, notify, removeNotification, setChartData]);

  // Handle layer change
  const handleLayerChange = useCallback(async (layer, specificDateOverride = null) => {
    if (!drawnAOI) {
      Swal.fire({
        icon: 'info',
        title: 'Draw Area First',
        text: 'Please draw an area on the map before selecting a layer.',
        confirmButtonColor: 'var(--krishi-green)',
      });
      return;
    }

    if (!startDate || !endDate) {
      Swal.fire({
        icon: 'info',
        title: 'Select Dates First',
        text: 'Please select dates and fetch data first.',
        confirmButtonColor: 'var(--krishi-green)',
      });
      return;
    }

    // Special handling for 'weather' - no map layer to load
    if (layer === 'weather') {
      // Update current layer state so UI reflects selection, but don't fetch tiles
      if (!specificDateOverride) {
        setSelectedImageryDate(null);
        setCurrentLayerType(layer);
      }

      // Show confirmation toast
      Swal.fire({
        icon: 'success',
        title: 'Weather Chart Loaded!',
        text: 'View the data in the bottom chart panel.',
        position: 'center',
        showConfirmButton: true,
        confirmButtonColor: 'var(--krishi-green)',
        timer: 2000,
        timerProgressBar: true
      });

      return;
    }

    // START SMART LOADER
    setSmartLoader({
      visible: true,
      title: `Loading ${layer === 'pca' ? 'Crop Health' : getLayerDisplayName(layer)}...`,
      messages: LAYER_MESSAGES
    });
    setLoadingState('isFetchingLayer', true);

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();
    const signal = abortControllerRef.current.signal;

    // const notifId = notify(`Loading ${displayName}...`, 'info', null); // Removed old notify

    if (!specificDateOverride) {
      setSelectedImageryDate(null);
      setCurrentLayerType(layer);
    }

    const currentRequestId = Symbol('layer_request');
    layerRequestRef.current = currentRequestId;



    try {
      const isVraLayer = layer.startsWith('vra_');
      let tileData;

      if (isVraLayer) {
        const parameter = layer.replace('vra_', '');
        const dateToUse = specificDateOverride;
        tileData = await fetchVraMap(drawnAOI, parameter, dateToUse, startDate, endDate, signal);
      } else {
        const dateToUse = specificDateOverride;
        tileData = dateToUse
          ? await fetchGeeTile(drawnAOI, layer, null, null, dateToUse, signal)
          : await fetchGeeTile(drawnAOI, layer, startDate, endDate, signal);
      }

      if (layerRequestRef.current !== currentRequestId) {
        console.log('Layer request was superseded, aborting map update.');
        return;
      }

      if (tileData.error) throw new Error(tileData.error);

      if (window.mapFunctions && tileData.urlFormat) {
        window.mapFunctions.addTileLayer(tileData.urlFormat, {
          opacity: opacity / 100,
          maxZoom: 20,
          minZoom: 3,
        });

        setCurrentLayerType(layer);
        setLayerStats(tileData.stats || tileData.classes);

        currentTileDataRef.current = {
          url: tileData.urlFormat,
          type: layer,
          stats: tileData.stats || tileData.classes,
          date: { start: startDate, end: endDate, specific: specificDateOverride },
          opacity: opacity
        };

        // notify(`${displayName} added to map.`, 'success'); // Optional: success toast or just hide loader
        // removeNotification(notifId);
      } else {
        throw new Error('No tile URL returned from server');
      }

    } catch (error) {
      if (error.name === 'AbortError') {
        console.log(`Fetch for layer ${layer} was aborted.`);
        return;
      }

      console.error('Error loading layer:', error);

      // Customize error for LST/CWSI when no Landsat data is found
      if ((layer === 'lst' || layer === 'cwsi') && error.message && error.message.includes('No Landsat imagery found')) {
        Swal.fire({
          icon: 'info',
          title: 'Data Not Available',
          confirmButtonColor: 'var(--krishi-green)',
        });
      } else {
        Swal.fire({
          icon: 'error',
          title: 'Layer Load Failed',
          text: error.message || 'Could not load the layer.',
          confirmButtonColor: 'var(--krishi-green)',
        });
      }
    } finally {
      // if (notifId) removeNotification(notifId);
      // Only hide loader and set fetching layer to false if this was the latest request
      if (layerRequestRef.current === currentRequestId) {
        setSmartLoader(prev => ({ ...prev, visible: false })); // Hide loader
        setLoadingState('isFetchingLayer', false);
      }
    }
  }, [drawnAOI, startDate, endDate, opacity, setLoadingState, notify, removeNotification, selectedImageryDate]);

  const handleClearMap = useCallback(() => {
    clearAllData();
    setCurrentLayerType(null);
    setLayerStats(null);
    setShowCalendar(false);
    setDateCarouselKey(0); // Reset carousel
    if (window.mapFunctions) {
      window.mapFunctions.clearAllLayers();
    }
    Swal.fire({
      icon: 'success',
      title: 'Map Cleared',
      text: 'All layers and data have been removed.',
      confirmButtonColor: 'var(--krishi-green)',
      timer: 2000,
      showConfirmButton: false,
    });
  }, [clearAllData]);

  // Handle vector upload
  const handleVectorUpload = useCallback((file, onSuccess) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        let geojsonData;
        if (file.name.endsWith('.kml')) {
          Swal.fire({
            icon: 'info',
            title: 'KML Support',
            text: 'KML file support coming soon. Please use GeoJSON format.',
            confirmButtonColor: 'var(--krishi-green)',
          });
          return;
        } else {
          geojsonData = JSON.parse(e.target.result);
        }
        let featureToUse = null;
        if (geojsonData.type === 'FeatureCollection' && geojsonData.features && geojsonData.features.length > 0) {
          featureToUse = geojsonData.features[0];
        } else if (geojsonData.type === 'Feature') {
          featureToUse = geojsonData;
        } else if (geojsonData.geometry) {
          featureToUse = geojsonData;
        }
        if (featureToUse) {
          setDrawnAOI(featureToUse);
        }
        onSuccess({ name: file.name });
        Swal.fire({
          icon: 'success',
          title: 'File Uploaded',
          text: `${file.name} has been loaded.`,
          confirmButtonColor: 'var(--krishi-green)',
          timer: 2000,
          showConfirmButton: false,
        });
      } catch (error) {
        Swal.fire({
          icon: 'error',
          title: 'Invalid File',
          text: 'Could not parse the file. Please ensure it is valid GeoJSON.',
          confirmButtonColor: 'var(--krishi-green)',
        });
      }
    };
    reader.onerror = () => {
      Swal.fire({
        icon: 'error',
        title: 'Read Error',
        text: 'Could not read the file.',
        confirmButtonColor: 'var(--krishi-green)',
      });
    };
    reader.readAsText(file);
  }, [setDrawnAOI]);

  // Handle generate calendar
  const handleGenerateCalendar = useCallback(async () => {
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
        text: 'Please select start and end dates.',
        confirmButtonColor: 'var(--krishi-green)',
      });
      return;
    }
    setLoadingState('isGeneratingCalendar', true);
    // const notifId = notify('Generating Irrigation Calendar...', 'info', null);
    setSmartLoader({
      visible: true,
      title: 'Generating Calendar...',
      messages: IRRIGATION_MESSAGES
    });

    try {
      const calendarResponse = await fetchIrrigationCalendar(drawnAOI, startDate, endDate, fieldId);
      if (calendarResponse.error) {
        throw new Error(calendarResponse.error);
      }
      setIrrigationCalendar(calendarResponse);
      localStorage.setItem('lastIrrigationCalendar', JSON.stringify(calendarResponse));
      setShowCalendar(true);
      // notify('Calendar Generated!', 'success');
      // removeNotification(notifId);
    } catch (error) {
      Swal.fire({
        icon: 'error',
        title: 'Generation Failed',
        text: error.message || 'Could not generate irrigation calendar.',
        confirmButtonColor: 'var(--krishi-green)',
      });
    } finally {
      // if (notifId) removeNotification(notifId);
      setSmartLoader(prev => ({ ...prev, visible: false }));
      setLoadingState('isGeneratingCalendar', false);
    }
  }, [drawnAOI, startDate, endDate, setLoadingState, notify, removeNotification, setIrrigationCalendar]);

  // View existing calendar
  const handleViewCalendar = useCallback(() => {
    setShowCalendar(true);
  }, []);

  // Handle CSV Download — fixed columns matching the 4 visible dashboard layers
  const handleDownloadCSV = useCallback(() => {
    if (!chartData || chartData.length === 0) {
      Swal.fire({
        icon: 'warning',
        title: 'No Data',
        text: 'Please fetch data first before downloading CSV.',
        confirmButtonColor: 'var(--krishi-green)',
      });
      return;
    }

    try {
      // Derive AOI centroid for lat/lon columns
      let centroidLat = '';
      let centroidLon = '';
      if (drawnAOI?.geometry?.coordinates) {
        const coords = drawnAOI.geometry.type === 'Polygon'
          ? drawnAOI.geometry.coordinates[0]
          : drawnAOI.geometry.coordinates[0][0]; // MultiPolygon fallback
        if (coords && coords.length > 0) {
          const sumLon = coords.reduce((s, c) => s + c[0], 0);
          const sumLat = coords.reduce((s, c) => s + c[1], 0);
          centroidLon = (sumLon / coords.length).toFixed(6);
          centroidLat = (sumLat / coords.length).toFixed(6);
        }
      }

      // Fixed columns — in the exact order the user requested
      const COLUMNS = [
        { header: 'Date', key: 'date' },
        { header: 'Latitude', key: '_lat' },   // centroid — filled below
        { header: 'Longitude', key: '_lon' },   // centroid — filled below
        { header: 'Crop_Health', key: 'pc1' },    // PCA / Crop Health
        { header: 'LAI', key: 'lai' },
        { header: 'Chlorophyll', key: 'clre' },   // CLRe = (B7/B5) - 1
        { header: 'Soil_Moisture', key: 'soilmoisture_mm' },
      ];

      const fmt = (val) => (val === null || val === undefined) ? '' : Number(val).toFixed(4);

      const csvRows = [COLUMNS.map(c => c.header).join(',')];

      for (const row of chartData) {
        const values = COLUMNS.map(col => {
          if (col.key === '_lat') return centroidLat;
          if (col.key === '_lon') return centroidLon;
          if (col.key === 'date') return row.date || '';
          return fmt(row[col.key]);
        });
        csvRows.push(values.join(','));
      }

      const csvString = csvRows.join('\n');
      const blob = new Blob([csvString], { type: 'text/csv' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `KrishiZest_Data_${startDate}_to_${endDate}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (e) {
      console.error(e);
      Swal.fire({
        icon: 'error',
        title: 'Download Failed',
        text: 'Could not generate CSV file.',
        confirmButtonColor: 'var(--krishi-green)',
      });
    }
  }, [chartData, startDate, endDate, drawnAOI]);

  // Helper to calculate series metrics
  const calculateMetrics = (data) => {
    if (!data || data.length === 0) return {};
    const metrics = {};
    const keys = ['ndvi', 'cwr_mm', 'kc', 'lst_c', 'etc_mm', 'soilmoisture_mm', 'deltas_mm'];
    keys.forEach(key => {
      const values = data.map(d => d[key]).filter(v => v !== null && !isNaN(v));
      if (values.length > 0) {
        const sum = values.reduce((a, b) => a + b, 0);
        const mean = sum / values.length;
        const sorted = [...values].sort((a, b) => a - b);
        const min = sorted[0];
        const max = sorted[sorted.length - 1];
        let reportKey = key;
        if (key === 'cwr_mm') reportKey = 'cwr';
        if (key === 'lst_c') reportKey = 'lst';
        if (key === 'etc_mm') reportKey = 'etc';
        if (key === 'soilmoisture_mm') reportKey = 'soilmoisture';
        if (key === 'deltas_mm') reportKey = 'deltas';
        metrics[reportKey] = {
          mean: mean,
          min: min,
          max: max,
          stdDev: Math.sqrt(values.reduce((s, v) => s + Math.pow(v - mean, 2), 0) / values.length)
        };
      }
    });
    return metrics;
  };

  // Handle generate report
  const handleGenerateReport = useCallback(async () => {
    if (!drawnAOI) {
      Swal.fire({
        icon: 'warning',
        title: 'No Data',
        text: 'Please draw an area and fetch data first.',
        confirmButtonColor: 'var(--krishi-green)',
      });
      return;
    }
    if (!chartData || chartData.length === 0) {
      Swal.fire({
        icon: 'warning',
        title: 'No Data',
        text: 'Please fetch data first before generating a report.',
        confirmButtonColor: 'var(--krishi-green)',
      });
      return;
    }
    setLoadingState('isGeneratingReport', true);
    // const notifId = notify('Generating PDF Report...', 'info', null);
    setSmartLoader({
      visible: true,
      title: 'Generating Report...',
      messages: REPORT_MESSAGES
    });

    try {
      let currentCalendar = irrigationCalendar;
      if (!currentCalendar) {
        try {
          const calendarResponse = await fetchIrrigationCalendar(drawnAOI, startDate, endDate, fieldId);
          if (!calendarResponse.error) {
            currentCalendar = calendarResponse;
            setIrrigationCalendar(calendarResponse);
            localStorage.setItem('lastIrrigationCalendar', JSON.stringify(calendarResponse));
          }
        } catch (e) {
          console.warn("Could not fetch irrigation calendar for report:", e);
        }
      }
      const computedMetrics = calculateMetrics(chartData);
      const reportPayload = {
        aoi: drawnAOI,
        start_date: startDate,
        end_date: endDate,
        series: chartData,
        irrigation_calendar: currentCalendar?.calendar || [],
        irrigation_summary: currentCalendar?.summary || {},
        metrics: computedMetrics,
        language: language || 'en',
        crop_name: 'General Crop',
        area_ha: 0,
        location: '',
      };
      const blob = await generateReport(reportPayload);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `KrishiZest_Report_${startDate}_to_${endDate}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
      // notify('Report Downloaded!', 'success');
      // removeNotification(notifId);
    } catch (error) {
      Swal.fire({
        icon: 'error',
        title: 'Report Generation Failed',
        text: error.message || 'Could not generate the PDF report.',
        confirmButtonColor: 'var(--krishi-green)',
      });
    } finally {
      // if (notifId) removeNotification(notifId);
      setSmartLoader(prev => ({ ...prev, visible: false }));
      setLoadingState('isGeneratingReport', false);
    }
  }, [drawnAOI, startDate, endDate, chartData, irrigationCalendar, setLoadingState, notify, removeNotification, setIrrigationCalendar, language]);

  // Getter for Sidebar
  const getCurrentLayerInfo = useCallback(() => {
    if (!currentTileDataRef.current) return null;
    return {
      ...currentTileDataRef.current,
      opacity: opacity
    };
  }, [opacity]);

  // Handle comparison view
  const handleCompare = useCallback((selectedLayers) => {
    if (!drawnAOI) {
      Swal.fire({
        icon: 'warning',
        title: 'Missing AOI',
        text: 'Please draw an area on the map first.',
        confirmButtonColor: 'var(--krishi-green)',
      });
      return;
    }
    setComparisonLayers(selectedLayers);
    setShowComparison(true);
  }, [drawnAOI]);

  return (
    <div className="app">
      <NotificationContainer />
      <LoadingOverlay />

      {/* --- SMART LOADER ADDED HERE --- */}
      <SmartLoader
        visible={smartLoader.visible}
        title={smartLoader.title}
        messages={smartLoader.messages}
      />

      <Header onLocationSelect={handleLocationSelect} />

      <div className={`main-container ${!isSidebarOpen ? 'sidebar-collapsed' : ''}`}>
        <Sidebar
          onFetchData={handleFetchData}
          onLayerChange={handleLayerChange}
          onClearMap={handleClearMap}
          onVectorUpload={handleVectorUpload}
          onGenerateCalendar={handleGenerateCalendar}
          onViewCalendar={handleViewCalendar}
          onGenerateReport={handleGenerateReport}
          onQueryCurrentLayer={getCurrentLayerInfo}
          onCompare={handleCompare}
          onDownloadCSV={handleDownloadCSV}
        />

        <section className="workspace">
          <div className={`main-panel ${isRightPanelOpen ? 'right-panel-open' : ''}`}>
            <MapComponent
              onAOICreated={handleAOICreated}
              onLocationSelect={handleLocationSelectSetup}
              fieldId={fieldId}
            />

            {/* Date Carousel */}
            {currentLayerType && drawnAOI && dateCarouselKey > 0 && (
              <DateCarousel
                key={dateCarouselKey} // Force full unmount and remount on trigger
                onDateSelect={(date) => {
                  setSelectedImageryDate(date);
                  if (currentLayerType) {
                    handleLayerChange(currentLayerType, date);
                  }
                }}
              />
            )}

            {/* Map Legend */}
            {currentLayerType && (
              <MapLegend layerType={currentLayerType} stats={layerStats} />
            )}

            {/* Irrigation Calendar Panel */}
            {showCalendar && irrigationCalendar && (
              <IrrigationCalendarPanel onClose={() => setShowCalendar(false)} />
            )}
          </div>

          <AnalyticsSidebar />
        </section>
      </div>

      {/* Comparison View */}
      {showComparison && (
        <ComparisonView
          layers={comparisonLayers}
          onClose={() => setShowComparison(false)}
          drawnAOI={drawnAOI}
          startDate={startDate}
          endDate={endDate}
        />
      )}
    </div>
  );
}

function FieldAnalysis() {
  return (
    <AppProvider>
      <AppContent />
    </AppProvider>
  );
}

export default FieldAnalysis;