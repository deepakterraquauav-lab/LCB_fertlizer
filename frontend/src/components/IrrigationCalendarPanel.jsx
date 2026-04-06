import { useState, useRef, useEffect, useCallback } from 'react';
import { useApp } from '../context/AppContext';
import { t } from '../utils/translations';

function IrrigationCalendarPanel({ onClose }) {
    const { irrigationCalendar, isDarkMode } = useApp();
    const [isExpanded, setIsExpanded] = useState(false);
    const [isDragging, setIsDragging] = useState(false);
    const [position, setPosition] = useState({ x: 20, y: 20 });
    const dragStartRef = useRef({ x: 0, y: 0 });
    const panelRef = useRef(null);

    if (!irrigationCalendar) return null;

    const { calendar, summary } = irrigationCalendar;

    // Handle drag with useCallback for stable references - constrained to map area
    const handleMouseMove = useCallback((e) => {
        e.preventDefault();

        // Get the map container (main-panel)
        const mapContainer = document.querySelector('.main-panel');
        if (!mapContainer || !panelRef.current) {
            setPosition({
                x: e.clientX - dragStartRef.current.x,
                y: e.clientY - dragStartRef.current.y,
            });
            return;
        }

        const mapRect = mapContainer.getBoundingClientRect();
        const panelRect = panelRef.current.getBoundingClientRect();

        // Calculate new position
        let newX = e.clientX - dragStartRef.current.x;
        let newY = e.clientY - dragStartRef.current.y;

        // Constrain within map bounds (relative to map container)
        const minX = 10;
        const minY = 10;
        const maxX = mapRect.width - panelRect.width - 10;
        const maxY = mapRect.height - panelRect.height - 10;

        newX = Math.max(minX, Math.min(newX, maxX));
        newY = Math.max(minY, Math.min(newY, maxY));

        setPosition({ x: newX, y: newY });
    }, []);

    const handleMouseUp = useCallback(() => {
        setIsDragging(false);
    }, []);

    const handleMouseDown = (e) => {
        if (e.target.closest('.panel-control-btn')) return;
        e.preventDefault();
        setIsDragging(true);
        dragStartRef.current = {
            x: e.clientX - position.x,
            y: e.clientY - position.y,
        };
    };

    useEffect(() => {
        if (isDragging) {
            document.addEventListener('mousemove', handleMouseMove);
            document.addEventListener('mouseup', handleMouseUp);
            // Prevent text selection while dragging
            document.body.style.userSelect = 'none';
        } else {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
            document.body.style.userSelect = '';
        }
        return () => {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
            document.body.style.userSelect = '';
        };
    }, [isDragging, handleMouseMove, handleMouseUp]);

    const getPriorityColor = (priority) => {
        switch (priority) {
            case 'URGENT': return '#ef4444';
            case 'MODERATE': return '#f97316';
            case 'LOW': return '#22c55e';
            default: return '#9ca3af';
        }
    };

    const getPriorityBgColor = (priority) => {
        switch (priority) {
            case 'URGENT': return 'rgba(239, 68, 68, 0.1)';
            case 'MODERATE': return 'rgba(249, 115, 22, 0.1)';
            case 'LOW': return 'rgba(34, 197, 94, 0.1)';
            default: return 'rgba(156, 163, 175, 0.1)';
        }
    };

    return (
        <div
            ref={panelRef}
            className={`irrigation-calendar-panel ${isExpanded ? 'expanded' : ''} ${isDragging ? 'dragging' : ''}`}
            style={{
                left: isExpanded ? '50%' : position.x,
                top: isExpanded ? '50%' : position.y,
                transform: isExpanded ? 'translate(-50%, -50%)' : 'none',
            }}
        >
            {/* Header */}
            <div
                className="irrigation-calendar-header"
                onMouseDown={handleMouseDown}
                style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
            >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <i className="fa-solid fa-calendar-check" style={{ color: 'var(--krishi-green)' }}></i>
                    <h3 style={{ margin: 0, fontSize: '14px', fontWeight: 600 }}>
                        {t('irrigation_calendar')}
                    </h3>
                </div>
                <div style={{ display: 'flex', gap: '4px' }}>
                    <button
                        className="panel-control-btn"
                        onClick={() => setIsExpanded(!isExpanded)}
                        title={isExpanded ? 'Minimize' : 'Expand'}
                    >
                        <i className={`fa-solid ${isExpanded ? 'fa-compress' : 'fa-expand'}`}></i>
                    </button>
                    <button
                        className="panel-control-btn"
                        onClick={onClose}
                        title="Close"
                    >
                        <i className="fa-solid fa-times"></i>
                    </button>
                </div>
            </div>

            {/* Content */}
            <div className="irrigation-calendar-content">
                {/* Summary Section */}
                {summary && (
                    <div style={{
                        padding: '16px',
                        borderBottom: '1px solid var(--border-color)',
                        background: isDarkMode ? '#1e2021' : '#f8fafc',
                    }}>
                        <h4 style={{ margin: '0 0 12px 0', fontSize: '13px', fontWeight: 600 }}>
                            Summary Statistics
                        </h4>
                        <div style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
                            gap: '10px',
                        }}>
                            <div style={{
                                background: isDarkMode ? '#2c2f32' : '#fff',
                                padding: '10px',
                                borderRadius: '8px',
                                textAlign: 'center',
                                border: '1px solid var(--border-color)',
                            }}>
                                <div style={{ fontSize: '10px', color: 'var(--muted)' }}>Total Days</div>
                                <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--krishi-green)' }}>
                                    {summary.total_days || calendar?.length || 0}
                                </div>
                            </div>
                            <div style={{
                                background: isDarkMode ? '#2c2f32' : '#fff',
                                padding: '10px',
                                borderRadius: '8px',
                                textAlign: 'center',
                                border: '1px solid var(--border-color)',
                            }}>
                                <div style={{ fontSize: '10px', color: 'var(--muted)' }}>Irrigation Days</div>
                                <div style={{ fontSize: '18px', fontWeight: 700, color: '#3b82f6' }}>
                                    {summary.irrigation_events || 0}
                                </div>
                            </div>
                            <div style={{
                                background: isDarkMode ? '#2c2f32' : '#fff',
                                padding: '10px',
                                borderRadius: '8px',
                                textAlign: 'center',
                                border: '1px solid var(--border-color)',
                            }}>
                                <div style={{ fontSize: '10px', color: 'var(--muted)' }}>Total Water (mm)</div>
                                <div style={{ fontSize: '18px', fontWeight: 700, color: '#06b6d4' }}>
                                    {summary.total_water_mm?.toFixed(1) || 0}
                                </div>
                            </div>
                            <div style={{
                                background: isDarkMode ? '#2c2f32' : '#fff',
                                padding: '10px',
                                borderRadius: '8px',
                                textAlign: 'center',
                                border: '1px solid var(--border-color)',
                            }}>
                                <div style={{ fontSize: '10px', color: 'var(--muted)' }}>Water Saved (mm)</div>
                                <div style={{ fontSize: '18px', fontWeight: 700, color: '#22c55e' }}>
                                    {summary.water_saved_mm?.toFixed(1) || 0}
                                </div>
                            </div>
                        </div>

                        {/* Priority counts */}
                        <div style={{ marginTop: '12px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                            {summary.urgent_count > 0 && (
                                <span style={{
                                    padding: '4px 10px',
                                    borderRadius: '12px',
                                    fontSize: '11px',
                                    fontWeight: 600,
                                    background: 'rgba(239, 68, 68, 0.15)',
                                    color: '#ef4444',
                                }}>
                                    {summary.urgent_count} Urgent
                                </span>
                            )}
                            {summary.moderate_count > 0 && (
                                <span style={{
                                    padding: '4px 10px',
                                    borderRadius: '12px',
                                    fontSize: '11px',
                                    fontWeight: 600,
                                    background: 'rgba(249, 115, 22, 0.15)',
                                    color: '#f97316',
                                }}>
                                    {summary.moderate_count} Moderate
                                </span>
                            )}
                        </div>
                    </div>
                )}

                {/* Calendar Events */}
                <div style={{
                    padding: '12px',
                    overflowY: 'auto',
                    maxHeight: isExpanded ? 'calc(80vh - 200px)' : '350px',
                }}>
                    <h4 style={{ margin: '0 0 12px 0', fontSize: '13px', fontWeight: 600 }}>
                        Daily Schedule
                    </h4>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {calendar && calendar.map((event, index) => (
                            <div
                                key={index}
                                className="irrigation-event"
                                style={{
                                    padding: '12px',
                                    borderRadius: '10px',
                                    border: `1px solid ${getPriorityColor(event.priority)}`,
                                    background: getPriorityBgColor(event.priority),
                                }}
                            >
                                <div style={{
                                    display: 'flex',
                                    justifyContent: 'space-between',
                                    alignItems: 'flex-start',
                                    marginBottom: '8px',
                                }}>
                                    <div>
                                        <div style={{ fontWeight: 600, fontSize: '13px' }}>
                                            {event.date}
                                        </div>
                                        <span style={{
                                            display: 'inline-block',
                                            padding: '2px 8px',
                                            borderRadius: '10px',
                                            fontSize: '10px',
                                            fontWeight: 600,
                                            background: getPriorityColor(event.priority),
                                            color: 'white',
                                            marginTop: '4px',
                                        }}>
                                            {event.priority}
                                        </span>
                                    </div>
                                    {event.should_irrigate && (
                                        <div style={{
                                            fontSize: '16px',
                                            fontWeight: 700,
                                            color: '#3b82f6',
                                        }}>
                                            {event.final_irrigation_mm?.toFixed(1) || 0} mm
                                        </div>
                                    )}
                                </div>
                                <div style={{
                                    fontSize: '12px',
                                    color: isDarkMode ? '#ccc' : '#555',
                                    marginBottom: '6px',
                                }}>
                                    {event.advice}
                                </div>
                                <div style={{
                                    display: 'flex',
                                    gap: '12px',
                                    fontSize: '10px',
                                    color: 'var(--muted)',
                                }}>
                                    <span> CWSI: {event.cwsi_mean?.toFixed(2) || '--'}</span>
                                    <span> SM: {event.soil_moisture_percent?.toFixed(1) || '--'}%</span>
                                    <span> Rain: {event.rain_mm?.toFixed(1) || 0} mm</span>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
}

export default IrrigationCalendarPanel;