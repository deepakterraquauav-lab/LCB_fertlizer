import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { getFields, deleteField, updateField } from '../utils/api';
import toast, { Toaster } from 'react-hot-toast';
import Swal from 'sweetalert2';
import './Fields.css';

const CROP_CATEGORIES = {
    "Cereals / अनाज": ["Wheat / गेहूं", "Paddy (Rice) / धान (चावल)", "Maize / मक्का", "Barley / जौ", "Pearl Millet (Bajra) / बाजरा", "Sorghum (Jowar) / ज्वार"],
    "Pulses / दालें": ["Chickpea (Gram) / चना", "Pigeon Pea (Arhar) / अरहर", "Lentil (Masoor) / मसूर", "Black Gram (Urad) / उड़द", "Green Gram (Moong) / मूंग"],
    "Oilseeds / तिलहन": ["Mustard / सरसों", "Sesame (Til) / तिल", "Groundnut / मूंगफली", "Linseed / अलसी"],
    "Cash Crops / नकदी फसलें": ["Sugarcane / गन्ना", "Potato / आलू", "Cotton / कपास", "Tobacco / तंबाकू"]
};

function Fields() {
    const { user, logout } = useAuth();
    const navigate = useNavigate();
    const [fields, setFields] = useState([]);
    const [loading, setLoading] = useState(true);
    const [isDarkMode, setIsDarkMode] = useState(false);
    const [showProfileMenu, setShowProfileMenu] = useState(false);
    const [viewMode, setViewMode] = useState('grid'); // 'grid' or 'table'

    // Edit modal state
    const [editingField, setEditingField] = useState(null);
    const [editName, setEditName] = useState('');
    const [editVillage, setEditVillage] = useState('');
    const [editDistrict, setEditDistrict] = useState('');
    const [editState, setEditState] = useState('');
    const [editCropType, setEditCropType] = useState('');
    const [editCropName, setEditCropName] = useState('');
    const [editSowingDate, setEditSowingDate] = useState('');
    const [editHarvestingDate, setEditHarvestingDate] = useState('');

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
    const loadFields = async () => {
        setLoading(true);
        try {
            const data = await getFields();
            setFields(data);
        } catch (error) {
            console.log('Using localStorage for fields');
            const storedFields = JSON.parse(localStorage.getItem('fields') || '[]');
            setFields(storedFields);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadFields();
    }, []);

    const handleLogout = () => {
        logout();
        navigate('/login');
    };

    const handleFieldClick = (field) => {
        navigate(`/app?field_id=${field.id}`);
    };

    // Custom Purple Deletion Confirmation
    const handleDeleteField = async (e, fieldId) => {
        e.preventDefault();
        e.stopPropagation();

        const field = fields.find(f => f.id === fieldId);
        const name = field ? field.name : 'this field';

        Swal.fire({
            title: '<span style="color:#7c4dff;font-weight:700;font-family:\'Poppins\',sans-serif;">Delete Field / खेत हटाएं?</span>',
            html: `<div style="text-align: center; color: #b3b3b3; font-family: 'Poppins', sans-serif;">
                    <p>Are you sure you want to delete <strong>${name}</strong>? This action is permanent and will clear all historical data!</p>
                    <p style="color: #ea80fc; font-weight: 500;">क्या आप वाकई <strong>${name}</strong> को हटाना चाहते हैं? यह क्रिया स्थायी है और सारा इतिहास हटा देगी!</p>
                   </div>`,
            icon: 'warning',
            showCancelButton: true,
            background: '#1a1a24',
            confirmButtonColor: '#7c4dff',
            cancelButtonColor: '#455a64',
            confirmButtonText: 'Yes, Delete / हाँ, हटाएं',
            cancelButtonText: 'Cancel / रद्द करें',
            customClass: {
                popup: 'premium-purple-swal',
                confirmButton: 'purple-confirm-btn',
                cancelButton: 'purple-cancel-btn'
            }
        }).then(async (result) => {
            if (result.isConfirmed) {
                const deleteLocally = () => {
                    clearFieldData(fieldId);
                    setFields(prevFields => {
                        const updatedFields = prevFields.filter(f => f.id !== fieldId);
                        localStorage.setItem('fields', JSON.stringify(updatedFields));
                        return updatedFields;
                    });
                };

                try {
                    await deleteField(fieldId);
                    deleteLocally();
                    toast.success('Field deleted successfully!');
                } catch (error) {
                    deleteLocally();
                    console.error('Removed locally:', error);
                }
            }
        });
    };

    // Helper to clear localStorage
    const clearFieldData = (fieldId) => {
        const cropHealthData = localStorage.getItem('lastCropHealthData');
        if (cropHealthData) {
            try {
                localStorage.removeItem('lastCropHealthData');
            } catch (e) {
                console.error(e);
            }
        }
        const keysToRemove = [];
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            if (key && key.includes(`field_${fieldId}`)) {
                keysToRemove.push(key);
            }
        }
        keysToRemove.forEach(key => localStorage.removeItem(key));
    };

    // Edit button click handler
    const handleEditClick = (e, field) => {
        e.preventDefault();
        e.stopPropagation();
        setEditingField(field);
        setEditName(field.name || '');
        setEditVillage(field.village || '');
        setEditDistrict(field.district || '');
        setEditState(field.state || '');
        setEditCropType(field.cropType || '');
        setEditCropName(field.cropName || '');
        setEditSowingDate(field.sowingDate || '');
        setEditHarvestingDate(field.harvestingDate || '');
    };

    // Save Edit submit handler
    const handleSaveEdit = async (e) => {
        e.preventDefault();

        if (!editName.trim()) {
            toast.error('Field Name is required / खेत का नाम आवश्यक है');
            return;
        }
        if (!editVillage.trim()) {
            toast.error('Village is required / गाँव का नाम आवश्यक है');
            return;
        }
        if (!editCropType) {
            toast.error('Crop Type is required / फसल का प्रकार आवश्यक है');
            return;
        }
        if (!editCropName) {
            toast.error('Crop Name is required / फसल का नाम आवश्यक है');
            return;
        }
        if (!editSowingDate) {
            toast.error('Sowing Date is required / बुवाई की तिथि आवश्यक है');
            return;
        }

        const updatedData = {
            name: editName.trim(),
            village: editVillage.trim(),
            district: editDistrict.trim(),
            state: editState.trim(),
            cropType: editCropType,
            cropName: editCropName,
            sowingDate: editSowingDate,
            harvestingDate: editHarvestingDate
        };

        try {
            await updateField(editingField.id, updatedData);
            setFields(prevFields => {
                const updated = prevFields.map(f => f.id === editingField.id ? { ...f, ...updatedData } : f);
                localStorage.setItem('fields', JSON.stringify(updated));
                return updated;
            });
            toast.success('Field details updated successfully!');
            setEditingField(null);
        } catch (error) {
            console.error('Error updating field details:', error);
            toast.error('Saved locally.');
            setFields(prevFields => {
                const updated = prevFields.map(f => f.id === editingField.id ? { ...f, ...updatedData } : f);
                localStorage.setItem('fields', JSON.stringify(updated));
                return updated;
            });
            setEditingField(null);
        }
    };

    const totalAreaAcres = fields.reduce((sum, f) => sum + parseFloat(f.areaAcres || 0), 0);
    const totalAreaHectares = fields.reduce((sum, f) => sum + parseFloat(f.areaHectares || 0), 0);

    // Helper to get lat/long from field geometry
    const getFieldCentroid = (field) => {
        if (!field || !field.geometry) return null;

        try {
            const { type, coordinates, center } = field.geometry;

            if (type === 'Circle' && center) {
                return { lat: center[0], lon: center[1] };
            }

            let coords = [];
            if (type === 'Polygon') {
                coords = coordinates[0];
            } else if (type === 'MultiPolygon') {
                coords = coordinates[0][0];
            }

            if (coords && coords.length > 0) {
                const sumLon = coords.reduce((s, c) => s + c[0], 0);
                const sumLat = coords.reduce((s, c) => s + c[1], 0);
                return {
                    lat: (sumLat / coords.length).toFixed(6),
                    lon: (sumLon / coords.length).toFixed(6)
                };
            }
        } catch (e) {
            console.error('Error calculating centroid:', e);
        }
        return null;
    };

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
                <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
                    <div>
                        <h1 className="page-title">My Fields</h1>
                        <p className="page-subtitle">
                            {fields.length} fields • Total area: {totalAreaHectares.toFixed(2)} hectares / {totalAreaAcres.toFixed(2)} acres
                        </p>
                    </div>
                    <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                        <div className="view-toggle-container" style={{ display: 'inline-flex', background: '#f1f5f9', padding: '4px', borderRadius: '12px', border: '1px solid #e2e8f0', gap: '4px', boxShadow: 'inset 0 1px 2px rgba(0,0,0,0.02)' }}>
                            <button 
                                className={`toggle-btn ${viewMode === 'grid' ? 'active' : ''}`} 
                                onClick={() => setViewMode('grid')}
                                style={{ padding: '8px 12px', border: 'none', borderRadius: '8px', background: viewMode === 'grid' ? '#ffffff' : 'transparent', color: viewMode === 'grid' ? '#00c853' : '#64748b', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.2s', boxShadow: viewMode === 'grid' ? '0 1px 3px rgba(0,0,0,0.1), 0 1px 2px rgba(0,0,0,0.06)' : 'none', fontSize: '16px' }}
                                title="Grid View"
                            >
                                <i className="fas fa-th-large"></i>
                            </button>
                            <button 
                                className={`toggle-btn ${viewMode === 'table' ? 'active' : ''}`} 
                                onClick={() => setViewMode('table')}
                                style={{ padding: '8px 12px', border: 'none', borderRadius: '8px', background: viewMode === 'table' ? '#ffffff' : 'transparent', color: viewMode === 'table' ? '#00c853' : '#64748b', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.2s', boxShadow: viewMode === 'table' ? '0 1px 3px rgba(0,0,0,0.1), 0 1px 2px rgba(0,0,0,0.06)' : 'none', fontSize: '16px' }}
                                title="List View"
                            >
                                <i className="fas fa-list-ul"></i>
                            </button>
                        </div>
                        <Link to="/create-field" className="btn btn-primary" style={{ padding: '10px 20px', borderRadius: '8px', background: '#00c853', color: '#fff', textDecoration: 'none', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <i className="fas fa-plus"></i> New Field
                        </Link>
                    </div>
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
                ) : viewMode === 'grid' ? (
                    <div className="fields-grid">
                        {fields.map((field, index) => (
                            <div
                                key={field.id}
                                className="field-card"
                                onClick={() => handleFieldClick(field)}
                            >
                                <div className="field-card-top" onClick={(e) => e.stopPropagation()}>
                                    <span className="field-badge">Field {index + 1}</span>
                                    <div style={{ display: 'flex', gap: '8px' }}>
                                        <button
                                            className="field-edit-btn"
                                            onClick={(e) => handleEditClick(e, field)}
                                            title="Edit Details"
                                            style={{ background: '#f3e8ff', border: 'none', color: '#7c4dff', cursor: 'pointer', width: '32px', height: '32px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.2s' }}
                                            onMouseEnter={(e) => { e.currentTarget.style.background = '#7c4dff'; e.currentTarget.style.color = '#ffffff'; }}
                                            onMouseLeave={(e) => { e.currentTarget.style.background = '#f3e8ff'; e.currentTarget.style.color = '#7c4dff'; }}
                                        >
                                            <i className="fas fa-edit"></i>
                                        </button>
                                        <button
                                            className="field-delete-btn"
                                            onClick={(e) => handleDeleteField(e, field.id)}
                                            title="Delete"
                                            style={{ background: '#fee2e2', border: 'none', color: '#ef4444', cursor: 'pointer', width: '32px', height: '32px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.2s' }}
                                            onMouseEnter={(e) => { e.currentTarget.style.background = '#ef4444'; e.currentTarget.style.color = '#ffffff'; }}
                                            onMouseLeave={(e) => { e.currentTarget.style.background = '#fee2e2'; e.currentTarget.style.color = '#ef4444'; }}
                                        >
                                            <i className="fas fa-trash-alt"></i>
                                        </button>
                                    </div>
                                </div>
                                <div className="field-card-body">
                                    <h3 className="field-name">{field.name}</h3>
                                    
                                    {field.cropName && (
                                        <div style={{ margin: '8px 0', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                                                <span style={{ fontSize: '11px', background: 'rgba(0,200,83,0.15)', color: '#00c853', padding: '2px 8px', borderRadius: '4px', border: '1px solid rgba(0,200,83,0.3)', fontWeight: 600 }}>
                                                    {field.cropName.split(' / ')[0]}
                                                </span>
                                                {field.village && (
                                                    <span style={{ fontSize: '11px', background: 'rgba(255,255,255,0.05)', color: '#aaa', padding: '2px 8px', borderRadius: '4px', fontWeight: 500 }}>
                                                        {field.village}
                                                    </span>
                                                )}
                                            </div>
                                            {field.sowingDate && (
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px', color: '#88c399' }}>
                                                    <i className="fas fa-seedling" style={{ color: '#00c853' }}></i>
                                                    <span>Sown: {field.sowingDate}</span>
                                                    {field.harvestingDate && (
                                                        <>
                                                            <span style={{ color: '#555' }}>|</span>
                                                            <i className="fas fa-calendar-alt" style={{ color: '#888' }}></i>
                                                            <span style={{ color: '#aaa' }}>{field.harvestingDate}</span>
                                                        </>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    <div className="fields-stats" style={{ display: 'flex', margin: '14px 0', borderTop: '1px solid rgba(255,255,255,0.05)', paddingPt: '12px' }}>
                                        <div className="field-stat" style={{ flex: 1 }}>
                                            <span className="stat-value">{field.areaHectares}</span>
                                            <span className="stat-label">Hectares</span>
                                        </div>
                                        <div className="field-divider"></div>
                                        <div className="field-stat" style={{ flex: 1 }}>
                                            <span className="stat-value">{field.areaAcres}</span>
                                            <span className="stat-label">Acres</span>
                                        </div>
                                    </div>

                                    {/* Compass coordinate display */}
                                    <div className="field-location" style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#aaa', fontSize: '13px' }}>
                                        <i className="fas fa-compass" style={{ color: '#00c853' }}></i>
                                        <span>
                                            Lat: {parseFloat(field.latitude || getFieldCentroid(field)?.lat || 0).toFixed(5)}, Lng: {parseFloat(field.longitude || getFieldCentroid(field)?.lon || 0).toFixed(5)}
                                        </span>
                                    </div>
                                </div>
                                <div className="field-card-footer">
                                    <span className="field-footer-text">View Analysis</span>
                                    <i className="fas fa-arrow-right"></i>
                                </div>
                            </div>
                        ))}
                    </div>
                ) : (
                    /* Premium Table View */
                    <div className="fields-table-container" style={{ background: 'rgba(255,255,255,0.02)', backdropFilter: 'blur(10px)', borderRadius: '12px', padding: '16px', border: '1px solid rgba(255,255,255,0.05)', overflowX: 'auto' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', color: '#fff', minWidth: '900px' }}>
                            <thead>
                                <tr style={{ borderBottom: '2px solid rgba(255,255,255,0.05)', textAlign: 'left', color: '#aaa', fontSize: '13px' }}>
                                    <th style={{ padding: '12px 8px' }}>Field Name</th>
                                    <th style={{ padding: '12px 8px' }}>Coordinates</th>
                                    <th style={{ padding: '12px 8px' }}>Location (Village/District/State)</th>
                                    <th style={{ padding: '12px 8px' }}>Crop Details</th>
                                    <th style={{ padding: '12px 8px' }}>Area (ha / ac)</th>
                                    <th style={{ padding: '12px 8px', textAlign: 'center' }}>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {fields.map((field, index) => (
                                    <tr 
                                        key={field.id} 
                                        style={{ borderBottom: '1px solid rgba(255,255,255,0.03)', cursor: 'pointer', transition: 'background 0.2s', fontSize: '14px' }}
                                        onClick={() => handleFieldClick(field)}
                                        onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.01)'}
                                        onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                                    >
                                        <td style={{ padding: '16px 8px', fontWeight: 600 }}>{field.name}</td>
                                        <td style={{ padding: '16px 8px' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                                <i className="fas fa-compass" style={{ color: '#00c853' }}></i>
                                                <span>Lat: {parseFloat(field.latitude || getFieldCentroid(field)?.lat || 0).toFixed(5)}, Lng: {parseFloat(field.longitude || getFieldCentroid(field)?.lon || 0).toFixed(5)}</span>
                                            </div>
                                        </td>
                                        <td style={{ padding: '16px 8px', color: '#bbb' }}>
                                            {field.village ? `${field.village}${field.district ? `, ${field.district}` : ''}${field.state ? `, ${field.state}` : ''}` : 'Specify / निर्दिष्ट करें'}
                                        </td>
                                        <td style={{ padding: '16px 8px' }}>
                                            {field.cropName ? (
                                                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                                    <span style={{ fontSize: '11px', background: 'rgba(0,200,83,0.15)', color: '#00c853', padding: '2px 8px', borderRadius: '4px', border: '1px solid rgba(0,200,83,0.3)', fontWeight: 600, width: 'fit-content' }}>
                                                        {field.cropName.split(' / ')[0]}
                                                    </span>
                                                    {field.sowingDate && (
                                                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px', color: '#88c399' }}>
                                                            <i className="fas fa-seedling" style={{ color: '#00c853' }}></i>
                                                            <span>{field.sowingDate}</span>
                                                            {field.harvestingDate && (
                                                                <>
                                                                    <span style={{ color: '#555' }}>|</span>
                                                                    <i className="fas fa-calendar-alt" style={{ color: '#888' }}></i>
                                                                    <span style={{ color: '#aaa' }}>{field.harvestingDate}</span>
                                                                </>
                                                            )}
                                                        </div>
                                                    )}
                                                </div>
                                            ) : 'Specify / निर्दिष्ट करें'}
                                        </td>
                                        <td style={{ padding: '16px 8px' }}>
                                            {field.areaHectares} ha / {field.areaAcres} ac
                                        </td>
                                        <td style={{ padding: '16px 8px', textAlign: 'center' }} onClick={(e) => e.stopPropagation()}>
                                            <button 
                                                onClick={(e) => handleEditClick(e, field)}
                                                style={{ background: '#7c4dff', border: 'none', color: '#fff', padding: '6px 12px', borderRadius: '6px', marginRight: '8px', cursor: 'pointer', fontWeight: 600 }}
                                            >
                                                <i className="fas fa-edit"></i> Edit
                                            </button>
                                            <button 
                                                onClick={(e) => handleDeleteField(e, field.id)}
                                                style={{ background: '#d32f2f', border: 'none', color: '#fff', padding: '6px 12px', borderRadius: '6px', cursor: 'pointer', fontWeight: 600 }}
                                            >
                                                <i className="fas fa-trash-alt"></i> Delete
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {/* Premium Bilingual Edit Modal */}
            {editingField && (
                <div className="premium-modal-overlay" style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0, 0, 0, 0.75)', backdropFilter: 'blur(8px)', zIndex: 10000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px', overflowY: 'auto' }}>
                    <div className="premium-modal" style={{ background: '#121212', borderRadius: '16px', border: '1px solid rgba(255,255,255,0.1)', padding: '24px', width: '100%', maxWidth: '500px', boxShadow: '0 20px 40px rgba(0,0,0,0.5)', margin: 'auto' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '10px' }}>
                            <h2 style={{ color: '#00c853', margin: 0, fontSize: '20px', fontWeight: 700, fontFamily: 'Poppins' }}>Edit Details / विवरण संपादित करें</h2>
                            <button onClick={() => setEditingField(null)} style={{ background: 'none', border: 'none', color: '#aaa', fontSize: '24px', cursor: 'pointer' }}>&times;</button>
                        </div>
                        <form onSubmit={handleSaveEdit}>
                            <div style={{ marginBottom: '16px' }}>
                                <label style={{ color: '#fff', display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: 600 }}>Field Name * / खेत का नाम <span style={{ color: '#ff5252' }}>*</span></label>
                                <input 
                                    type="text" 
                                    value={editName} 
                                    onChange={(e) => setEditName(e.target.value)} 
                                    style={{ width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)', background: '#1e1e1e', color: '#fff' }}
                                    placeholder="e.g. North Field"
                                />
                            </div>
                            <div style={{ marginBottom: '16px' }}>
                                <label style={{ color: '#fff', display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: 600 }}>Village * / गाँव <span style={{ color: '#ff5252' }}>*</span></label>
                                <input 
                                    type="text" 
                                    value={editVillage} 
                                    onChange={(e) => setEditVillage(e.target.value)} 
                                    style={{ width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)', background: '#1e1e1e', color: '#fff' }}
                                    placeholder="e.g. Rampur"
                                />
                            </div>
                            <div style={{ marginBottom: '16px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                <div>
                                    <label style={{ color: '#fff', display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: 600 }}>District / जिला</label>
                                    <input 
                                        type="text" 
                                        value={editDistrict} 
                                        onChange={(e) => setEditDistrict(e.target.value)} 
                                        style={{ width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)', background: '#1e1e1e', color: '#fff' }}
                                        placeholder="e.g. Kanpur"
                                    />
                                </div>
                                <div>
                                    <label style={{ color: '#fff', display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: 600 }}>State / राज्य</label>
                                    <input 
                                        type="text" 
                                        value={editState} 
                                        onChange={(e) => setEditState(e.target.value)} 
                                        style={{ width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)', background: '#1e1e1e', color: '#fff' }}
                                        placeholder="e.g. Uttar Pradesh"
                                    />
                                </div>
                            </div>
                            <div style={{ marginBottom: '16px' }}>
                                <label style={{ color: '#fff', display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: 600 }}>Crop Type * / फसल का प्रकार <span style={{ color: '#ff5252' }}>*</span></label>
                                <select 
                                    value={editCropType} 
                                    onChange={(e) => {
                                        setEditCropType(e.target.value);
                                        setEditCropName('');
                                    }} 
                                    style={{ width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)', background: '#1e1e1e', color: '#fff', height: '42px' }}
                                >
                                    <option value="">-- Select Type / प्रकार चुनें --</option>
                                    {Object.keys(CROP_CATEGORIES).map(cat => <option key={cat} value={cat}>{cat}</option>)}
                                </select>
                            </div>
                            <div style={{ marginBottom: '16px' }}>
                                <label style={{ color: '#fff', display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: 600 }}>Crop Name * / फसल का नाम <span style={{ color: '#ff5252' }}>*</span></label>
                                <select 
                                    value={editCropName} 
                                    disabled={!editCropType}
                                    onChange={async (e) => {
                                        const val = e.target.value;
                                        if (val === 'Other') {
                                            const { value: customCrop } = await Swal.fire({
                                                title: 'Enter Custom Crop Name',
                                                input: 'text',
                                                inputLabel: 'Custom Crop Name / कस्टम फसल का नाम',
                                                inputPlaceholder: 'e.g. Mentha / पिपरमेंट',
                                                showCancelButton: true,
                                                confirmButtonColor: '#00c853',
                                                background: '#1b3b2f',
                                                inputValidator: (v) => {
                                                    if (!v) return 'Crop name cannot be empty!';
                                                }
                                            });

                                            if (customCrop) {
                                                setEditCropName(customCrop);
                                            } else {
                                                setEditCropName('');
                                            }
                                        } else {
                                            setEditCropName(val);
                                        }
                                    }} 
                                    style={{ width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)', background: '#1e1e1e', color: '#fff', height: '42px' }}
                                >
                                    {!editCropType ? (
                                        <option value="">-- First Select Crop Type --</option>
                                    ) : (
                                        <>
                                            <option value="">-- Select Crop / फसल चुनें --</option>
                                            {(CROP_CATEGORIES[editCropType] || []).map(crop => <option key={crop} value={crop}>{crop}</option>)}
                                            {editCropName && !(CROP_CATEGORIES[editCropType] || []).includes(editCropName) && editCropName !== 'Other' && (
                                                <option value={editCropName}>{editCropName} (Custom / कस्टम)</option>
                                            )}
                                            <option value="Other">Other (Specify) / अन्य (निर्दिष्ट करें)</option>
                                        </>
                                    )}
                                </select>
                            </div>
                            <div style={{ marginBottom: '24px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                <div>
                                    <label style={{ color: '#fff', display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: 600 }}>Sowing Date * / बुवाई की तिथि <span style={{ color: '#ff5252' }}>*</span></label>
                                    <input 
                                        type="date" 
                                        value={editSowingDate} 
                                        onChange={(e) => setEditSowingDate(e.target.value)} 
                                        style={{ width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)', background: '#1e1e1e', color: '#fff', outline: 'none' }}
                                    />
                                </div>
                                <div>
                                    <label style={{ color: '#fff', display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: 600 }}>Harvesting Date / कटाई की तिथि</label>
                                    <input 
                                        type="date" 
                                        value={editHarvestingDate} 
                                        onChange={(e) => setEditHarvestingDate(e.target.value)} 
                                        style={{ width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)', background: '#1e1e1e', color: '#fff', outline: 'none' }}
                                    />
                                </div>
                            </div>
                            <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
                                <button type="button" onClick={() => setEditingField(null)} style={{ background: '#cfd8dc', border: 'none', color: '#37474f', padding: '10px 20px', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}>Cancel / रद्द करें</button>
                                <button type="submit" style={{ background: '#00c853', border: 'none', color: '#fff', padding: '10px 20px', borderRadius: '8px', cursor: 'pointer', fontWeight: 600, flex: 1 }}>Save Changes / सहेजें</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}

export default Fields;
