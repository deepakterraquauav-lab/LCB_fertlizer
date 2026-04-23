import { createContext, useContext, useState, useCallback, useEffect } from 'react';
import Swal from 'sweetalert2';

const AppContext = createContext(null);

export function AppProvider({ children }) {
    // Theme state
    const [isDarkMode, setIsDarkMode] = useState(false);

    // Language state
    const [language, setLanguage] = useState('en');

    // Sidebar states
    const [isSidebarOpen, setIsSidebarOpen] = useState(true);
    const [isRightPanelOpen, setIsRightPanelOpen] = useState(false);

    // Data states
    const today = new Date();
    const maxDate = today.toISOString().split('T')[0];

    const [startDate, setStartDate] = useState('');
    const [endDate, setEndDate] = useState('');
    const [selectedLayer, setSelectedLayer] = useState('');
    const [opacity, setOpacity] = useState(100);

    // Watch selectedLayer and toggle right panel
    useEffect(() => {
        if (selectedLayer) {
            setIsRightPanelOpen(true);
        } else {
            setIsRightPanelOpen(false);
        }
    }, [selectedLayer]);

    // Map data states
    const [drawnAOI, setDrawnAOI] = useState(null);
    const [currentLayer, setCurrentLayer] = useState(null);
    const [currentLayerData, setCurrentLayerData] = useState(null);
    const [fullChartData, setFullChartData] = useState(null);

    // Loading states
    const [isLoading, setIsLoading] = useState(false);
    const [loadingMessage, setLoadingMessage] = useState('');

    const [notifications, setNotifications] = useState([]);

    const removeNotification = useCallback((id) => {
        setNotifications(prev => prev.filter(n => n.id !== id));
    }, []);

    // Granular Loading States
    const [loadingStates, setLoadingStates] = useState({
        isFetchingData: false,
        isFetchingLayer: false,
        isGeneratingCalendar: false,
        isGeneratingReport: false
    });

    const setLoadingState = useCallback((key, value) => {
        setLoadingStates(prev => ({ ...prev, [key]: value }));
    }, []);

    // Non-blocking notification helper
    const notify = useCallback((message, type = 'info', duration = 3000) => {
        const id = Date.now() + Math.random();
        setNotifications(prev => [...prev, { id, message, type, duration }]);
        return id;
    }, []);

    // Chart data
    const [chartData, setChartData] = useState(null);
    const [activeChartParam, setActiveChartParam] = useState('ndvi');
    const [availableImageryDates, setAvailableImageryDates] = useState([]);

    // Analytics data
    const [ndviStats, setNdviStats] = useState(null);
    const [irrigationCalendar, setIrrigationCalendar] = useState(null);

    // Layer management
    const [addedLayers, setAddedLayers] = useState([]);

    // Toggle dark mode
    const toggleDarkMode = useCallback(() => {
        setIsDarkMode(prev => {
            const newValue = !prev;
            if (newValue) {
                document.body.classList.add('dark-mode');
            } else {
                document.body.classList.remove('dark-mode');
            }
            return newValue;
        });
    }, []);

    // Toggle sidebar
    const toggleSidebar = useCallback(() => {
        setIsSidebarOpen(prev => !prev);
    }, []);

    // Toggle right panel
    const toggleRightPanel = useCallback(() => {
        setIsRightPanelOpen(prev => !prev);
    }, []);

    // Ensure right panel is open
    const ensureRightPanelOpen = useCallback(() => {
        if (!isRightPanelOpen) {
            setIsRightPanelOpen(true);
        }
    }, [isRightPanelOpen]);

    // Show loader
    const showLoader = useCallback((message = 'Loading...') => {
        setIsLoading(true);
        setLoadingMessage(message);
    }, []);

    // Hide loader
    const hideLoader = useCallback(() => {
        setIsLoading(false);
        setLoadingMessage('');
    }, []);

    // Clear all data
    const clearAllData = useCallback(() => {
        setDrawnAOI(null);
        setCurrentLayer(null);
        setCurrentLayerData(null);
        setFullChartData(null);
        setChartData(null);
        setNdviStats(null);
        setIrrigationCalendar(null);
        setAddedLayers([]);
        setSelectedLayer('');
        setAvailableImageryDates([]);
    }, []);

    const value = {
        // Theme
        isDarkMode,
        toggleDarkMode,

        // Language
        language,
        setLanguage,

        // Sidebars
        isSidebarOpen,
        toggleSidebar,
        isRightPanelOpen,
        toggleRightPanel,
        ensureRightPanelOpen,

        // Dates
        startDate,
        setStartDate,
        endDate,
        setEndDate,

        // Layer selection
        selectedLayer,
        setSelectedLayer,
        opacity,
        setOpacity,

        // Map data
        drawnAOI,
        setDrawnAOI,
        currentLayer,
        setCurrentLayer,
        currentLayerData,
        setCurrentLayerData,
        fullChartData,
        setFullChartData,

        // Loading
        isLoading,
        loadingMessage,
        showLoader,
        hideLoader,

        // Granular Loading States
        isFetchingData: loadingStates.isFetchingData,
        isFetchingLayer: loadingStates.isFetchingLayer,
        isGeneratingCalendar: loadingStates.isGeneratingCalendar,
        isGeneratingReport: loadingStates.isGeneratingReport,
        setLoadingState,
        notifications,
        notify,
        removeNotification,

        // Charts
        chartData,
        setChartData,
        activeChartParam,
        setActiveChartParam,
        availableImageryDates,
        setAvailableImageryDates,

        // Analytics
        ndviStats,
        setNdviStats,
        irrigationCalendar,
        setIrrigationCalendar,

        // Layer management
        addedLayers,
        setAddedLayers,

        // Actions
        clearAllData,
    };

    return (
        <AppContext.Provider value={value}>
            {children}
        </AppContext.Provider>
    );
}

export function useApp() {
    const context = useContext(AppContext);
    if (!context) {
        throw new Error('useApp must be used within an AppProvider');
    }
    return context;
}

export default AppContext;
