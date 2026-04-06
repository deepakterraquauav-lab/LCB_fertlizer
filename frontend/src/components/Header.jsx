import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { useAuth } from '../context/AuthContext';
import { t, setLanguage as setLang } from '../utils/translations';
import { searchLocation } from '../utils/api';
import Swal from 'sweetalert2';
import './Header.css';

function Header({ onLocationSelect }) {
    const { isDarkMode, toggleDarkMode, language, setLanguage, toggleSidebar } = useApp();
    const { user, logout } = useAuth();
    const navigate = useNavigate();

    const [showProfileMenu, setShowProfileMenu] = useState(false);
    const [showSettingsMenu, setShowSettingsMenu] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [searchResults, setSearchResults] = useState([]);
    const [showResults, setShowResults] = useState(false);
    const [selectedIndex, setSelectedIndex] = useState(-1);
    const searchTimeout = useRef(null);
    const searchRef = useRef(null);

    const settingsRef = useRef(null);
    const profileRef = useRef(null);

    // Handle logout
    const handleLogout = () => {
        logout();
        navigate('/login');
    };

    // Handle language change
    const handleLanguageChange = (lang) => {
        setLanguage(lang);
        setLang(lang);
    };

    // Search locations
    const performSearch = async (query, isSuggestion = false) => {
        setSelectedIndex(-1);

        if (query.length < 3) {
            setSearchResults([]);
            setShowResults(false);
            return;
        }

        try {
            if (isSuggestion) {
                setSearchResults([{ loading: true }]);
                setShowResults(true);
            }

            const coordRegex = /(-?\d{1,3}\.\d+)[\s,]+(-?\d{1,3}\.\d+)/;
            const match = query.match(coordRegex);

            let results = [];

            if (match) {
                const lat = parseFloat(match[1]);
                const lon = parseFloat(match[2]);

                if (lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
                    // Agar exact coordinate hai, toh fake result banake direct return kar do (API bypass)
                    results = [{
                        lat: lat.toString(),
                        lon: lon.toString(),
                        display_name: `${lat}, ${lon}` // Dropdown mein exactly yahi dikhega
                    }];
                }
            }
            if (results.length === 0) {
                results = await searchLocation(query);
            }

            // Agar upar coordinates nahi mile, tabhi original API call chalegi
            if (results.length === 0) {
                results = await searchLocation(query);
            }

            if (results.length === 0) {
                setSearchResults([{ noResults: true }]);
                setShowResults(true);
                return;
            }

            if (!isSuggestion && results.length > 0) {
                // Manual search - select first result
                selectResult(results[0]);
                return;
            }

            setSearchResults(results);
            setShowResults(true);
        } catch (error) {
            console.error('Search error:', error);
            setSearchResults([{ error: true }]);
            setShowResults(true);
        }
    };

    // Select a search result
    const selectResult = (result) => {
        const lat = parseFloat(result.lat);
        const lon = parseFloat(result.lon);
        const name = result.display_name;

        // Call parent callback to center map
        if (onLocationSelect) {
            onLocationSelect(lat, lon, name);
        }

        // Update search box
        setSearchQuery(name.split(',')[0]);
        setShowResults(false);
        setSearchResults([]);

        // Show success message
        Swal.fire({
            icon: 'success',
            title: t('opt_location_found'),
            text: `${t('opt_centered_map')} ${name.split(',')[0]}`,
            confirmButtonColor: 'var(--krishi-green)',
            timer: 2000,
            showConfirmButton: false,
        });
    };

    // Handle input change
    const handleInputChange = (e) => {
        const query = e.target.value;
        setSearchQuery(query);

        // Clear previous timeout
        if (searchTimeout.current) {
            clearTimeout(searchTimeout.current);
        }

        if (query.trim().length < 3) {
            setShowResults(false);
            setSearchResults([]);
            return;
        }

        // Debounced search
        searchTimeout.current = setTimeout(() => {
            performSearch(query.trim(), true);
        }, 400);
    };

    // Handle keyboard navigation
    const handleKeyDown = (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            if (selectedIndex >= 0 && searchResults[selectedIndex] && !searchResults[selectedIndex].loading && !searchResults[selectedIndex].noResults && !searchResults[selectedIndex].error) {
                selectResult(searchResults[selectedIndex]);
            } else {
                performSearch(searchQuery.trim(), false);
            }
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            const validResults = searchResults.filter(r => !r.loading && !r.noResults && !r.error);
            if (validResults.length > 0) {
                setSelectedIndex(prev => (prev + 1) % validResults.length);
            }
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            const validResults = searchResults.filter(r => !r.loading && !r.noResults && !r.error);
            if (validResults.length > 0) {
                setSelectedIndex(prev => (prev - 1 + validResults.length) % validResults.length);
            }
        }
    };

    // Close menus when clicking outside
    useEffect(() => {
        const handleClickOutside = (e) => {
            // Close search results if clicking outside
            if (searchRef.current && !searchRef.current.contains(e.target)) {
                setShowResults(false);
                setSearchResults([]);
            }

            // Close settings menu if clicking outside
            if (settingsRef.current && !settingsRef.current.contains(e.target)) {
                setShowSettingsMenu(false);
            }

            // Close profile menu if clicking outside
            if (profileRef.current && !profileRef.current.contains(e.target)) {
                setShowProfileMenu(false);
            }
        };

        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    return (
        <header className="header">
            <div className="brand">
                <button
                    className="hamburger-menu"
                    onClick={toggleSidebar}
                    title="Open Controls"
                >
                    <i className="fa-solid fa-bars"></i>
                </button>
                <img
                    src="/static/logo.png"
                    alt="KrishiZest logo"
                    className="brand-logo"
                />

            </div>

            <div className="header-actions">
                {/* Dashboard Button */}
                <button
                    onClick={() => navigate('/dashboard')}
                    title="Go to Dashboard"
                    className="dashboard-btn"
                >
                    {/* <i className="fa-solid fa-gauge-high"></i> */}
                    <span>Dashboard</span>
                </button>

                {/* Search Control */}
                <div className="search-control" ref={searchRef}>
                    <div className="search-container">
                        <input
                            type="text"
                            className="search-input"
                            placeholder={t('opt_search_placeholder')}
                            value={searchQuery}
                            onChange={handleInputChange}
                            onKeyDown={handleKeyDown}
                            autoComplete="off"
                        />
                        <button
                            className="search-btn"
                            onClick={() => performSearch(searchQuery.trim(), false)}
                        >
                            <i className="fa-solid fa-search"></i>
                        </button>
                    </div>

                    {/* Search Results Dropdown */}
                    {showResults && searchResults.length > 0 && (
                        <div className="search-results">
                            {searchResults.map((result, index) => {
                                if (result.loading) {
                                    return (
                                        <div key="loading" className="search-result-item">
                                            Searching...
                                        </div>
                                    );
                                }
                                if (result.noResults) {
                                    return (
                                        <div key="no-results" className="search-result-item">
                                            {t('opt_no_results')}
                                        </div>
                                    );
                                }
                                if (result.error) {
                                    return (
                                        <div key="error" className="search-result-item">
                                            {t('opt_search_failed')}
                                        </div>
                                    );
                                }
                                return (
                                    <div
                                        key={index}
                                        className={`search-result-item ${selectedIndex === index ? 'active' : ''}`}
                                        onMouseDown={(e) => {
                                            e.preventDefault();
                                            selectResult(result);
                                        }}
                                    >
                                        <div className="search-result-name">
                                            <i className="fa-regular fa-map-pin" style={{ color: '#2f7a2f', marginRight: '6px' }}></i>
                                            {result.display_name.split(',')[0]}
                                        </div>
                                        <div className="search-result-details">
                                            {result.display_name}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>

                {/* Settings Dropdown */}
                <div className={`profile-dropdown ${showSettingsMenu ? 'active' : ''}`} style={{ marginLeft: '8px' }} ref={settingsRef}>
                    <button
                        className="profile-btn"
                        onClick={() => setShowSettingsMenu(!showSettingsMenu)}
                        title="Settings"
                    >
                        <i className="fa-solid fa-gear" style={{ fontSize: '1.2rem', color: isDarkMode ? '#fff' : '#1b3b2f' }}></i>
                    </button>
                    <div className="profile-menu">
                        <div className="user-info">
                            <div className="user-name">App Settings</div>
                        </div>

                        <div className="dropdown-item" style={{ cursor: 'default' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', marginBottom: '8px' }}>
                                <span>Language</span>
                            </div>
                            <div className="lang-switch" role="tablist" aria-label="Language switch" style={{ display: 'flex', gap: '5px' }}>
                                <button
                                    className={`lang-btn ${language === 'en' ? 'active' : ''}`}
                                    onClick={() => handleLanguageChange('en')}
                                    style={{ flex: 1, textAlign: 'center', justifyContent: 'center' }}
                                >
                                    English
                                </button>
                                <button
                                    className={`lang-btn ${language === 'hi' ? 'active' : ''}`}
                                    onClick={() => handleLanguageChange('hi')}
                                    style={{ flex: 1, textAlign: 'center', justifyContent: 'center' }}
                                >
                                    Hindi
                                </button>
                            </div>
                        </div>

                        <div className="dropdown-item" onClick={toggleDarkMode}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                                <span>Dark Mode</span>
                                <i className={`fa-solid ${isDarkMode ? 'fa-toggle-on' : 'fa-toggle-off'}`} style={{ fontSize: '1.2rem', color: isDarkMode ? '#4caf50' : '#ccc' }}></i>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Profile Dropdown */}
                <div className={`profile-dropdown ${showProfileMenu ? 'active' : ''}`} ref={profileRef}>
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
    );
}

export default Header;
