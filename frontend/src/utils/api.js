// API utility for backend communication
import { auth } from '../config/firebase';

// Use environment variable for backend URL in production, fallback to relative for dev (proxy)
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

/**
 * Get authentication headers with Firebase ID token
 */
export async function getAuthHeaders() {
    const headers = {
        'Content-Type': 'application/json',
    };

    try {
        const user = auth.currentUser;
        if (user) {
            const token = await user.getIdToken();
            headers['Authorization'] = `Bearer ${token}`;
        }
    } catch (error) {
        console.error('Error getting auth token:', error);
    }

    return headers;
}


// Fetch daily data from backend - matches app2.html logic exactly
export async function fetchDailyData(aoi, startDate, endDate, fieldId = null) {
    const headers = await getAuthHeaders();
    const response = await fetch(`${API_BASE_URL}/get_daily_data`, {
        method: 'POST',

        headers,
        body: JSON.stringify({
            aoi: aoi,
            start_date: startDate,
            end_date: endDate,
            field_id: fieldId
        }),
    });

    // Try parse JSON body regardless of res.ok so we can show server error details
    let body = null;
    try {
        body = await response.json();
    } catch (parseErr) {
        // If parsing fails, leave body as null
        body = null;
    }

    // Return both response status and body for caller to handle
    return {
        ok: response.ok,
        status: response.status,
        data: body
    };
}

// Fetch irrigation calendar from backend
export async function fetchIrrigationCalendar(aoi, startDate, endDate, fieldId = null) {
    try {
        const headers = await getAuthHeaders();
        const response = await fetch(`${API_BASE_URL}/get_irrigation_calendar`, {
            method: 'POST',
            headers,
            body: JSON.stringify({
                aoi: aoi,
                start_date: startDate,
                end_date: endDate,
                field_id: fieldId
            }),
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error fetching irrigation calendar:', error);
        throw error;
    }
}

// Fetch available dates with satellite imagery
export async function fetchAvailableDates(aoi, startDate, endDate) {
    try {
        const headers = await getAuthHeaders();
        const response = await fetch(`${API_BASE_URL}/get_available_dates`, {
            method: 'POST',
            headers,
            body: JSON.stringify({
                aoi: aoi,
                start_date: startDate,
                end_date: endDate
            }),
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error fetching available dates:', error);
        throw error;
    }
}

// Fetch land cover analysis from backend
export async function fetchLandCoverAnalysis(aoi, startDate, endDate, timeScale = 'monthly') {
    try {
        const headers = await getAuthHeaders();
        const response = await fetch(`${API_BASE_URL}/get_land_cover_analysis`, {
            method: 'POST',
            headers,
            body: JSON.stringify({
                aoi: aoi,
                start_date: startDate,
                end_date: endDate,
                time_scale: timeScale,
            }),
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error fetching land cover analysis:', error);
        throw error;
    }
}

// Fetch GEE tile URL
export async function fetchGeeTile(aoi, layer, startDate, endDate, specificDate = null, signal = null) {
    try {
        const requestBody = {
            aoi: aoi,
            layer: layer
        };

        // If specific date is provided, use it; otherwise use date range
        if (specificDate) {
            requestBody.date = specificDate;
        } else {
            requestBody.start_date = startDate;
            requestBody.end_date = endDate;
        }

        const response = await fetch(`${API_BASE_URL}/get_gee_tile`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody),
            signal: signal,
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error fetching GEE tile:', error);
        throw error;
    }
}

// Fetch VRA map with Jenks classification
export async function fetchVraMap(aoi, parameter, date, startDate, endDate, signal = null) {
    try {
        const requestBody = {
            aoi: aoi,
            parameter: parameter,
            date: date,
            start_date: startDate,
            end_date: endDate
        };

        const response = await fetch(`${API_BASE_URL}/get_vra_map`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody),
            signal: signal,
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error fetching VRA map:', error);
        throw error;
    }
}

// Generate PDF report
export async function generateReport(reportData) {
    try {
        const response = await fetch(`${API_BASE_URL}/generate_report`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(reportData),
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
        }

        // The response should be a PDF blob
        const blob = await response.blob();
        return blob;
    } catch (error) {
        console.error('Error generating report:', error);
        throw error;
    }
}

// Search location using Nominatim API or exact coordinates
export async function searchLocation(query) {
    try {
        // Regex to check if the query looks like "lat, lon" or "lat lon"
        const coordRegex = /^\s*(-?\d+(\.\d+)?)[,\s]+(-?\d+(\.\d+)?)\s*$/;
        const match = query.match(coordRegex);

        if (match) {
            // It's a coordinate pair! Skip API and return exactly those coordinates.
            const lat = parseFloat(match[1]);
            const lon = parseFloat(match[3]);

            // Basic validation for realistic geographic bounds
            if (lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
                return [{
                    lat: lat.toString(),
                    lon: lon.toString(),
                    display_name: `${lat}, ${lon}`, // Clean display name for exact coords
                    place_id: `coord-${Date.now()}` // Mock ID for React maps
                }];
            }
        }

        const response = await fetch(
            `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}`);


        if (!response.ok) {
            throw new Error('Search failed');
        }

        const results = await response.json();
        return results;
    } catch (error) {
        console.error('Search error:', error);
        throw error;
    }
}

// Reverse geocode
export async function reverseGeocode(lat, lng) {
    try {
        const response = await fetch(
            `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}&zoom=18&addressdetails=1`
        );

        if (!response.ok) {
            throw new Error('Reverse geocoding failed');
        }

        const data = await response.json();
        return data.display_name || 'Unknown location';
    } catch (error) {
        console.error('Reverse geocoding error:', error);
        return 'Unknown location';
    }
}

// ===================================================================
// FIELD MANAGEMENT APIs
// ===================================================================

/**
 * Get all fields for the current user
 */
export async function getFields() {
    try {
        const headers = await getAuthHeaders();
        const response = await fetch(`${API_BASE_URL}/api/get_fields`, { headers });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error fetching fields:', error);
        throw error;
    }
}

/**
 * Save a new field or update existing field
 */
export async function saveField(fieldData) {
    try {
        const headers = await getAuthHeaders();
        const response = await fetch(`${API_BASE_URL}/api/save_field`, {
            method: 'POST',
            headers,
            body: JSON.stringify(fieldData)
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error saving field:', error);
        throw error;
    }
}

/**
 * Update existing field
 */
export async function updateField(fieldId, fieldData) {
    try {
        const headers = await getAuthHeaders();
        const response = await fetch(`${API_BASE_URL}/api/update_field/${fieldId}`, {
            method: 'PUT',
            headers,
            body: JSON.stringify(fieldData)
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error updating field:', error);
        throw error;
    }
}

/**
 * Delete a field
 */
export async function deleteField(fieldId) {
    try {
        const headers = await getAuthHeaders();
        const response = await fetch(`${API_BASE_URL}/api/delete_field/${fieldId}`, {
            method: 'DELETE',
            headers
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error deleting field:', error);
        throw error;
    }
}

/**
 * Get last irrigation calendar
 */
export async function getLastIrrigationCalendar() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/get_last_irrigation_calendar`);

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error fetching last irrigation calendar:', error);
        throw error;
    }
}

// ===================================================================
// Export all API functions
// ===================================================================

export default {
    // Auth
    getAuthHeaders,

    // Data fetching
    fetchDailyData,
    fetchIrrigationCalendar,
    fetchAvailableDates,
    fetchLandCoverAnalysis,
    fetchGeeTile,
    fetchVraMap,

    // Reports
    generateReport,

    // Field management
    getFields,
    saveField,
    updateField,
    deleteField,
    getLastIrrigationCalendar,

    // Location
    searchLocation,
    reverseGeocode,
};
