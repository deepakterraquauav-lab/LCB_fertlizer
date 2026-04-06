import { useEffect, useState } from 'react';
import { useApp } from '../context/AppContext';
import './NotificationContainer.css';

const NotificationItem = ({ notification, onClose }) => {
    const [isExiting, setIsExiting] = useState(false);
    const { id, message, type, duration } = notification;

    useEffect(() => {
        if (duration) {
            const timer = setTimeout(() => {
                handleClose();
            }, duration);
            return () => clearTimeout(timer);
        }
    }, [duration]);

    const handleClose = () => {
        setIsExiting(true);
        setTimeout(() => {
            onClose(id);
        }, 300); // Match CSS animation duration
    };

    const icons = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
    };

    const colors = {
        success: '#4caf50',
        error: '#f44336',
        warning: '#ff9800',
        info: '#2196f3'
    };

    return (
        <div
            className={`notification-toast ${type} ${isExiting ? 'exiting' : ''}`}
            onClick={handleClose}
            style={{ borderLeftColor: colors[type] || colors.info }}
        >
            <div className="notification-icon" style={{ color: colors[type] || colors.info }}>
                <i className={`fa-solid ${icons[type] || icons.info}`}></i>
            </div>
            <div className="notification-content">
                <span className="notification-message">{message}</span>
            </div>
            <button className="notification-close" onClick={(e) => { e.stopPropagation(); handleClose(); }}>
                &times;
            </button>
            {duration && (
                <div
                    className="notification-progress"
                    style={{
                        backgroundColor: colors[type] || colors.info,
                        animationDuration: `${duration}ms`
                    }}
                />
            )}
        </div>
    );
};

const NotificationContainer = () => {
    const { notifications, removeNotification } = useApp();

    return (
        <div className="notification-container">
            {notifications.map(notification => (
                <NotificationItem
                    key={notification.id}
                    notification={notification}
                    onClose={removeNotification}
                />
            ))}
        </div>
    );
};

export default NotificationContainer;
