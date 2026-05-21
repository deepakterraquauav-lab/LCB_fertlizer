// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";
import { getFirestore } from "firebase/firestore";

// TODO: Replace with your Firebase project configuration
// Get these values from Firebase Console > Project Settings > General > Your apps > Web app
const firebaseConfig = {
    apiKey: "AIzaSyCMwVSaJcKeBpLQ2XN05RKvZu6C6xZ6d98",
    authDomain: "lcb-26.firebaseapp.com",
    projectId: "lcb-26",
    storageBucket: "lcb-26.firebasestorage.app",
    messagingSenderId: "519037278027",
    appId: "1:519037278027:web:fd7eebffaaaf98026a7ace",
    measurementId: "G-KLB2GXPE4W"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);

// Initialize Firebase Authentication and get a reference to the service
export const auth = getAuth(app);

// Initialize Cloud Firestore and get a reference to the service
export const db = getFirestore(app);

export default app;
