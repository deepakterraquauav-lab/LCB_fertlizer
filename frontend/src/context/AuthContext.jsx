import { createContext, useContext, useState, useEffect } from 'react';
import {
    signInWithEmailAndPassword,
    createUserWithEmailAndPassword,
    signOut,
    onAuthStateChanged,
    updateProfile,
    GoogleAuthProvider,
    signInWithPopup,
    sendPasswordResetEmail
} from 'firebase/auth';
import { auth } from '../config/firebase';

const AuthContext = createContext();

export function useAuth() {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
}

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);

    // Listen to Firebase auth state changes
    useEffect(() => {
        const unsubscribe = onAuthStateChanged(auth, (firebaseUser) => {
            if (firebaseUser) {
                // User is signed in
                const userData = {
                    uid: firebaseUser.uid,
                    email: firebaseUser.email,
                    name: firebaseUser.displayName || firebaseUser.email.split('@')[0],
                    photoURL: firebaseUser.photoURL,
                };
                setUser(userData);
            } else {
                // User is signed out
                setUser(null);
            }
            setLoading(false);
        });

        // Cleanup subscription on unmount
        return unsubscribe;
    }, []);

    // Login with email and password
    const login = async (email, password) => {
        try {
            const result = await signInWithEmailAndPassword(auth, email, password);
            return { success: true, user: result.user };
        } catch (error) {
            console.error('Login error:', error);
            let errorMessage = 'Login failed';

            switch (error.code) {
                case 'auth/user-not-found':
                    errorMessage = 'No user found with this email';
                    break;
                case 'auth/wrong-password':
                    errorMessage = 'Incorrect password';
                    break;
                case 'auth/invalid-email':
                    errorMessage = 'Invalid email address';
                    break;
                case 'auth/user-disabled':
                    errorMessage = 'This account has been disabled';
                    break;
                case 'auth/too-many-requests':
                    errorMessage = 'Too many failed attempts. Please try again later';
                    break;
                default:
                    errorMessage = error.message;
            }

            return { success: false, error: errorMessage };
        }
    };

    // Register with email and password
    const register = async (name, email, password) => {
        try {
            const result = await createUserWithEmailAndPassword(auth, email, password);

            // Update user profile with display name
            await updateProfile(result.user, {
                displayName: name
            });

            return { success: true, user: result.user };
        } catch (error) {
            console.error('Registration error:', error);
            let errorMessage = 'Registration failed';

            switch (error.code) {
                case 'auth/email-already-in-use':
                    errorMessage = 'An account with this email already exists';
                    break;
                case 'auth/invalid-email':
                    errorMessage = 'Invalid email address';
                    break;
                case 'auth/weak-password':
                    errorMessage = 'Password should be at least 6 characters';
                    break;
                default:
                    errorMessage = error.message;
            }

            return { success: false, error: errorMessage };
        }
    };

    // Sign in with Google
    const signInWithGoogle = async () => {
        try {
            const provider = new GoogleAuthProvider();
            const result = await signInWithPopup(auth, provider);
            return { success: true, user: result.user };
        } catch (error) {
            console.error('Google sign-in error:', error);
            let errorMessage = 'Google sign-in failed';

            switch (error.code) {
                case 'auth/popup-closed-by-user':
                    errorMessage = 'Sign-in popup was closed';
                    break;
                case 'auth/cancelled-popup-request':
                    errorMessage = 'Sign-in was cancelled';
                    break;
                default:
                    errorMessage = error.message;
            }

            return { success: false, error: errorMessage };
        }
    };

    // Reset password
    const resetPassword = async (email) => {
        try {
            await sendPasswordResetEmail(auth, email);
            return { success: true };
        } catch (error) {
            console.error('Password reset error:', error);
            let errorMessage = 'Password reset failed';

            switch (error.code) {
                case 'auth/user-not-found':
                    errorMessage = 'No user found with this email';
                    break;
                case 'auth/invalid-email':
                    errorMessage = 'Invalid email address';
                    break;
                default:
                    errorMessage = error.message;
            }

            return { success: false, error: errorMessage };
        }
    };

    // Logout
    const logout = async () => {
        try {
            await signOut(auth);
            // Clear any local storage data if needed
            // localStorage.removeItem('lastIrrigationCalendar');
            // localStorage.removeItem('lastCropHealthData');
            // localStorage.removeItem('lastLandCoverData');
        } catch (error) {
            console.error('Logout error:', error);
        }
    };

    // Get ID token for backend authentication
    const getIdToken = async () => {
        try {
            if (auth.currentUser) {
                const token = await auth.currentUser.getIdToken();
                return token;
            }
            return null;
        } catch (error) {
            console.error('Error getting ID token:', error);
            return null;
        }
    };

    const value = {
        user,
        loading,
        login,
        register,
        signInWithGoogle,
        resetPassword,
        logout,
        getIdToken,
        isAuthenticated: !!user,
    };

    return (
        <AuthContext.Provider value={value}>
            {children}
        </AuthContext.Provider>
    );
}

export default AuthContext;
