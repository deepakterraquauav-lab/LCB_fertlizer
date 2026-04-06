import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import './Auth.css';

function Register() {
    const [name, setName] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const { register, signInWithGoogle } = useAuth();
    const navigate = useNavigate();

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');
        setLoading(true);

        if (!name || !email || !password || !confirmPassword) {
            setError('Please fill in all fields');
            setLoading(false);
            return;
        }

        if (password !== confirmPassword) {
            setError('Passwords do not match');
            setLoading(false);
            return;
        }

        if (password.length < 6) {
            setError('Password must be at least 6 characters');
            setLoading(false);
            return;
        }

        const result = await register(name, email, password);

        if (result.success) {
            navigate('/dashboard');
        } else {
            setError(result.error);
        }

        setLoading(false);
    };

    const handleGoogleSignIn = async () => {
        setError('');
        setLoading(true);

        const result = await signInWithGoogle();

        if (result.success) {
            navigate('/dashboard');
        } else {
            setError(result.error);
        }

        setLoading(false);
    };

    return (
        <div className="auth-page">
            <div className="auth-container">
                <div className="auth-header">
                    <img src="/static/logo.png" alt="KrishiZest" className="auth-logo" />
                    <h1>Create Account</h1>
                    <p>Join KrishiZest and start monitoring your crops</p>
                </div>

                <form onSubmit={handleSubmit} className="auth-form">
                    {error && (
                        <div className="auth-error">
                            <i className="fas fa-exclamation-circle"></i>
                            {error}
                        </div>
                    )}

                    <div className="form-group">
                        <label htmlFor="name">
                            <i className="fas fa-user"></i>
                            Full Name
                        </label>
                        <input
                            type="text"
                            id="name"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder="Enter your full name"
                            required
                        />
                    </div>

                    <div className="form-group">
                        <label htmlFor="email">
                            <i className="fas fa-envelope"></i>
                            Email Address
                        </label>
                        <input
                            type="email"
                            id="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            placeholder="Enter your email"
                            required
                        />
                    </div>

                    <div className="form-group">
                        <label htmlFor="password">
                            <i className="fas fa-lock"></i>
                            Password
                        </label>
                        <input
                            type="password"
                            id="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            placeholder="Create a password"
                            required
                        />
                    </div>

                    <div className="form-group">
                        <label htmlFor="confirmPassword">
                            <i className="fas fa-lock"></i>
                            Confirm Password
                        </label>
                        <input
                            type="password"
                            id="confirmPassword"
                            value={confirmPassword}
                            onChange={(e) => setConfirmPassword(e.target.value)}
                            placeholder="Confirm your password"
                            required
                        />
                    </div>

                    <button type="submit" className="auth-btn" disabled={loading}>
                        {loading ? (
                            <>
                                <i className="fas fa-circle-notch fa-spin"></i>
                                Creating Account...
                            </>
                        ) : (
                            <>
                                <i className="fas fa-user-plus"></i>
                                Create Account
                            </>
                        )}
                    </button>
                    <div className="auth-divider">
                        <span>or continue with</span>
                    </div>

                    <button type="button" className="auth-btn google-btn" onClick={handleGoogleSignIn} disabled={loading}>
                        <i className="fab fa-google"></i>
                        Sign up with Google
                    </button>
                </form>

                <div className="auth-footer">
                    <p>
                        Already have an account?{' '}
                        <Link to="/login">Sign in</Link>
                    </p>
                </div>
            </div>

            <div className="auth-background">
                <div className="auth-overlay"></div>
                <div className="auth-tagline">
                    <h2>KrishiZest</h2>
                    <p>Smart Irrigation System<br />Powered by Terraqua UAV</p>
                </div>
            </div>
        </div >
    );
}

export default Register;
