import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import Login from './pages/Login';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import Fields from './pages/Fields';
import CreateField from './pages/CreateField';
import FieldAnalysis from './pages/FieldAnalysis';
import './index.css';
import '@fortawesome/fontawesome-free/css/all.min.css';

// Protected Route component
function ProtectedRoute({ children }) {
    const { isAuthenticated, loading } = useAuth();

    if (loading) {
        return (
            <div className="loading-screen">
                <div className="loading-content">
                    <i className="fas fa-seedling fa-spin"></i>
                    <p>Loading...</p>
                </div>
            </div>
        );
    }

    if (!isAuthenticated) {
        return <Navigate to="/login" replace />;
    }

    return children;
}

// Public Route component (redirects to dashboard if already logged in)
function PublicRoute({ children }) {
    const { isAuthenticated, loading } = useAuth();

    if (loading) {
        return (
            <div className="loading-screen">
                <div className="loading-content">
                    <i className="fas fa-seedling fa-spin"></i>
                    <p>Loading...</p>
                </div>
            </div>
        );
    }

    if (isAuthenticated) {
        return <Navigate to="/dashboard" replace />;
    }

    return children;
}

function AppRoutes() {
    return (
        <Routes>
            {/* Public routes */}
            <Route
                path="/login"
                element={
                    <PublicRoute>
                        <Login />
                    </PublicRoute>
                }
            />
            <Route
                path="/register"
                element={
                    <PublicRoute>
                        <Register />
                    </PublicRoute>
                }
            />

            {/* Protected routes */}
            <Route
                path="/dashboard"
                element={
                    <ProtectedRoute>
                        <Dashboard />
                    </ProtectedRoute>
                }
            />
            <Route
                path="/fields"
                element={
                    <ProtectedRoute>
                        <Fields />
                    </ProtectedRoute>
                }
            />
            <Route
                path="/create-field"
                element={
                    <ProtectedRoute>
                        <CreateField />
                    </ProtectedRoute>
                }
            />
            <Route
                path="/app"
                element={
                    <ProtectedRoute>
                        <FieldAnalysis />
                    </ProtectedRoute>
                }
            />

            {/* Default redirect */}
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
    );
}

function App() {
    return (
        <Router>
            <AuthProvider>
                <AppRoutes />
            </AuthProvider>
        </Router>
    );
}

export default App;
