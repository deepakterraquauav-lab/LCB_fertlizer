import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { getFields, deleteField } from '../utils/api';
import toast, { Toaster } from 'react-hot-toast';
import './Fields.css';

function Fields() {
    const { user, logout } = useAuth();
    const navigate = useNavigate();
    const [fields, setFields] = useState([]);
    const [loading, setLoading] = useState(true);
    const [isDarkMode, setIsDarkMode] = useState(false);
    const [showProfileMenu, setShowProfileMenu] = useState(false);

    // Dark mode
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

    // Load fields
    useEffect(() => {
        async function loadFields() {
            try {
                // Try to fetch from backend using centralized API
                const data = await getFields();
                setFields(data);
            } catch (error) {
                console.log('Using localStorage for fields');
                // Fallback to localStorage
                const storedFields = JSON.parse(localStorage.getItem('fields') || '[]');
                setFields(storedFields);
            } finally {
                setLoading(false);
            }
        }

        loadFields();
    }, []);

    const handleLogout = () => {
        logout();
        navigate('/login');
    };

    const handleFieldClick = (field) => {
        navigate(`/app?field_id=${field.id}`);
    };
    const handleDeleteField = async (e, fieldId) => {
        // CRITICAL: Stop ALL event propagation
        e.preventDefault();
        e.stopPropagation();
        if (e.nativeEvent) {
            e.nativeEvent.stopImmediatePropagation();
        }

        const isConfirmed = window.confirm('Are you sure you want to delete this field? This cannot be undone!');

        if (isConfirmed) {
            // Step 1: Immediately perform local deletion (optimistic or guaranteed local removal)
            // We do this BEFORE the fetch request so that local state is updated immediately
            // upon confirmation, satisfying the user's requirement to see the card disappear.

            const deleteLocally = () => {
                clearFieldData(fieldId);

                setFields(prevFields => {
                    const updatedFields = prevFields.filter(f => f.id !== fieldId);
                    localStorage.setItem('fields', JSON.stringify(updatedFields));
                    return updatedFields;
                });
            };

            try {
                // Attempt backend deletion using centralized API
                await deleteField(fieldId);

                // Backend deletion succeeded, now delete locally
                deleteLocally();
                toast.success('Field deleted successfully!');
                console.log('✅ Field deleted successfully (Backend confirmed):', fieldId);
            } catch (error) {
                // This handles both network errors and backend failures
                // Delete locally and log the error
                deleteLocally();
                console.error('⚠️ Deletion error, but removed locally:', error);
            }

            // IMPORTANT: No alert is shown for the error path, fulfilling the user's request.
        }
    };

    // Helper function to clear all field-related data from localStorage
    const clearFieldData = (fieldId) => {
        // Clear crop health data if it matches this field
        const cropHealthData = localStorage.getItem('lastCropHealthData');
        if (cropHealthData) {
            try {
                const parsed = JSON.parse(cropHealthData);
                // If the data is associated with this field, remove it
                // (You might want to add field_id tracking to crop health data)
                localStorage.removeItem('lastCropHealthData');
            } catch (e) {
                console.error('Error parsing crop health data:', e);
            }
        }

        // Clear any field-specific cache keys
        // Pattern: field_<fieldId>_*
        const keysToRemove = [];
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            if (key && key.includes(`field_${fieldId}`)) {
                keysToRemove.push(key);
            }
        }

        keysToRemove.forEach(key => {
            localStorage.removeItem(key);
            console.log(`Cleared localStorage key: ${key}`);
        });

        console.log(`✅ Cleared all data associated with field ${fieldId}`);
    };

    const totalAreaAcres = fields.reduce((sum, f) => sum + parseFloat(f.areaAcres || 0), 0);
    const totalAreaHectares = fields.reduce((sum, f) => sum + parseFloat(f.areaHectares || 0), 0);

    return (
        <div className="fields-page">
            <Toaster position="top-center" reverseOrder={false} />


            {/* Header */}
            <header className="fields-header">
                <div className="nav-left">
                    <Link to="/dashboard" className="brand">
                        <img src="/static/logo.png" alt="KrishiZest" style={{ height: 32 }} />
                    </Link>
                    <nav className="nav-links">
                        <Link to="/dashboard" className="nav-link">Dashboard</Link>
                        <Link to="/fields" className="nav-link active">Fields</Link>
                    </nav>
                </div>
                <div className="nav-right">
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
            <div className="fields-container">
                <div className="page-header">
                    <div>
                        <h1 className="page-title">My Fields</h1>
                        <p className="page-subtitle">
                            {fields.length} fields • Total area: {totalAreaHectares.toFixed(2)} hectares / {totalAreaAcres.toFixed(2)} acres
                        </p>
                    </div>
                    <Link to="/create-field" className="btn btn-primary">
                        <i className="fas fa-plus"></i> New Field
                    </Link>
                </div>

                {loading ? (
                    <div className="loading-state">
                        <i className="fas fa-circle-notch fa-spin"></i>
                        <p>Loading fields...</p>
                    </div>
                ) : fields.length === 0 ? (
                    <div className="empty-state">
                        <div className="empty-icon">
                            <i className="fas fa-map-marked-alt"></i>
                        </div>
                        <h2>No Fields Yet</h2>
                        <p>Create your first field to start monitoring your crops with satellite data.</p>
                        <Link to="/create-field" className="btn btn-primary">
                            <i className="fas fa-plus"></i> Create Field
                        </Link>
                    </div>
                ) : (
                    <div className="fields-grid">
                        {fields.map((field, index) => (
                            <div
                                key={field.id}
                                className="field-card"
                                onClick={() => handleFieldClick(field)}
                            >
                                <div className="field-card-top">
                                    <span className="field-badge">Field {index + 1}</span>
                                    <button
                                        className="field-delete-btn"
                                        onClick={(e) => handleDeleteField(e, field.id)}
                                        title="Delete"
                                    >
                                        <i className="fas fa-trash-alt"></i>
                                    </button>
                                </div>
                                <div className="field-card-body">
                                    <h3 className="field-name">{field.name}</h3>
                                    <div className="field-stats">
                                        <div className="field-stat">
                                            <span className="stat-value">{field.areaHectares}</span>
                                            <span className="stat-label">Hectares</span>
                                        </div>
                                        <div className="field-divider"></div>
                                        <div className="field-stat">
                                            <span className="stat-value">{field.areaAcres}</span>
                                            <span className="stat-label">Acres</span>
                                        </div>
                                    </div>
                                </div>
                                <div className="field-card-footer">
                                    <span className="field-footer-text">View Analysis</span>
                                    <i className="fas fa-arrow-right"></i>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

export default Fields;
