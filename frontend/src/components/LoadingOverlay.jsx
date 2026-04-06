import { useApp } from '../context/AppContext';
import { useState, useEffect } from 'react';

function LoadingOverlay() {
    const { isLoading, loadingMessage } = useApp();
    const [progress, setProgress] = useState(0);

    useEffect(() => {
        if (isLoading) {
            setProgress(0);
            const interval = setInterval(() => {
                setProgress(prev => {
                    // Fast start, slow finish
                    let increment = 0;
                    if (prev < 30) increment = 4;
                    else if (prev < 60) increment = 2;
                    else if (prev < 85) increment = 1;
                    else if (prev < 98) increment = 0.2;

                    return Math.min(prev + increment, 99); // Never hit 100 until actually done
                });
            }, 100);
            return () => clearInterval(interval);
        }
    }, [isLoading]);

    if (!isLoading) return null;

    // Calculate stroke dashoffset for circle (r=40, C=2*PI*40 ≈ 251)
    const circumference = 251.2;
    const offset = circumference - (progress / 100) * circumference;

    return (
        <div className="crop-loader-overlay">
            <div className="creative-loader-card">
                <div className="creative-loader-visual">
                    <svg className="progress-ring" width="120" height="120">
                        <circle
                            className="progress-ring__circle-bg"
                            stroke="#e2e8f0"
                            strokeWidth="8"
                            fill="transparent"
                            r="40"
                            cx="60"
                            cy="60"
                        />
                        <circle
                            className="progress-ring__circle"
                            stroke="var(--krishi-green)"
                            strokeWidth="8"
                            fill="transparent"
                            r="40"
                            cx="60"
                            cy="60"
                            style={{ strokeDasharray: `${circumference} ${circumference}`, strokeDashoffset: offset }}
                        />
                    </svg>
                    <div className="visual-icon">
                        <i className={`fas ${loadingMessage?.toLowerCase().includes('pdf') ? 'fa-file-pdf' : 'fa-satellite-dish'}`}></i>
                    </div>
                </div>

                <div className="loader-content">
                    <div className="loader-percent">{Math.floor(progress)}%</div>
                    <div className="loader-message">{loadingMessage || 'Processing...'}</div>

                    <div className="loading-steps">
                        <div className={`step ${progress > 5 ? 'active' : ''}`}>
                            <div className="step-dot"></div> Preparing Request
                        </div>
                        <div className={`step ${progress > 40 ? 'active' : ''}`}>
                            <div className="step-dot"></div> Processing Data
                        </div>
                        <div className={`step ${progress > 80 ? 'active' : ''}`}>
                            <div className="step-dot"></div> Finalizing
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

export default LoadingOverlay;
