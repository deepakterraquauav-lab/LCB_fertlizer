// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";
import { getFirestore } from "firebase/firestore";

// TODO: Replace with your Firebase project configuration
// Get these values from Firebase Console > Project Settings > General > Your apps > Web app
const firebaseConfig = {
    apiKey: "AIzaSyCmCgN0boRho5qx-FJ3CR0t6xduv1gemME",
    authDomain: "mapzest-459c9.firebaseapp.com",
    projectId: "mapzest-459c9",
    storageBucket: "mapzest-459c9.firebasestorage.app",
    messagingSenderId: "590069245844",
    appId: "1:590069245844:web:14df26efde1a6d3a931181",
    measurementId: "G-7NVXEXEPLX"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);

// Initialize Firebase Authentication and get a reference to the service
export const auth = getAuth(app);

// Initialize Cloud Firestore and get a reference to the service
export const db = getFirestore(app);

export default app;
