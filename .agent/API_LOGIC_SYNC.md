# API Logic Synchronization - React App ↔ app2.html

## Summary
The React application's API calls have been updated to **exactly match** the logic used in `app2.html` to ensure identical behavior and performance.

## Changes Made

### 1. **Default Date Range** (`AppContext.jsx`)
- **Before**: Start and end dates were empty strings
- **After**: Automatically defaults to **last 6 months** (matching app2.html lines 8324-8328)
- **Impact**: Prevents users from accidentally selecting large date ranges that slow down data fetching

```javascript
// Now defaults to last 6 months
const today = new Date();
const maxDate = today.toISOString().split('T')[0];
const sixMonthsAgo = new Date();
sixMonthsAgo.setMonth(sixMonthsAgo.getMonth() - 6);
const defaultStart = sixMonthsAgo.toISOString().split('T')[0];

const [startDate, setStartDate] = useState(defaultStart);
const [endDate, setEndDate] = useState(maxDate);
```

### 2. **API Utility Error Handling** (`api.js`)
- **Before**: Threw errors immediately when `response.ok` was false
- **After**: Always parses JSON body and returns both status and data (matching app2.html lines 8396-8403)
- **Impact**: Allows caller to handle detailed error messages from backend

```javascript
// fetchDailyData now returns structured response
export async function fetchDailyData(aoi, startDate, endDate) {
    const response = await fetch('/get_daily_data', { /* ... */ });
    
    // Try parse JSON body regardless of res.ok
    let body = null;
    try {
        body = await response.json();
    } catch (parseErr) {
        body = null;
    }
    
    return {
        ok: response.ok,
        status: response.status,
        data: body
    };
}
```

### 3. **Data Fetch Handler** (`FieldAnalysis.jsx`)
Updated `handleFetchData` to match app2.html's `fetchData()` function exactly:

#### a. **Date Range Validation** (lines 8358-8370)
```javascript
const start = new Date(startDate);
const end = new Date(endDate);
const diffDays = Math.ceil((end - start) / (1000 * 60 * 60 * 24));

if (diffDays > 365) {
    Swal.fire({
        icon: 'warning',
        title: 'Date Range Too Large',
        text: 'Please select ≤ 12 months (≤ 365 days).',
    });
    return;
}
```

#### b. **Server Error Handling** (lines 8405-8440)
```javascript
if (!result.ok) {
    const serverMessage = result.data && (result.data.message || result.data.error)
        ? result.data.message || result.data.error
        : `Server error (${result.status})`;
    const availability = result.data && result.data.availability ? result.data.availability : null;

    let html = `<div>${serverMessage}</div>`;
    if (availability) {
        html += '<br><b>Dataset availability:</b><br>';
        for (const k of Object.keys(availability)) {
            html += `${k}: ${availability[k]}<br>`;
        }
    }

    Swal.fire({
        icon: 'warning',
        title: 'Processing Error',
        html,
    });
    return;
}
```

#### c. **Enhanced Error Handling** (lines 8445-8485)
```javascript
if (!data || (Array.isArray(data) && data.length === 0) || (data && data.error)) {
    let errorMessage = 'No data was found for the selected area and date range.';
    let errorDetails = '';

    if (data && data.error) {
        errorMessage = data.error;
        if (errorMessage.includes('No cloud-free Landsat imagery')) {
            errorDetails = '<br><br><strong>Suggestions:</strong><br>• Try adjusting the date range<br>• Increase cloud filter tolerance<br>• Select a different area';
        } else if (errorMessage.includes('Date range too large')) {
            errorMessage = 'Date Range Too Large';
            errorDetails = '<br><br>Please select ≤ 12 months (≤ 365 days).';
        }
    }

    Swal.fire({
        icon: 'info',
        title: 'No Data Available',
        html: errorMessage + errorDetails,
    });
    return;
}
```

#### d. **Partial Data Availability Check** (lines 8487-8510)
```javascript
const validData = Array.isArray(data) ? data.filter((item) => item.has_landsat) : [];
if (validData.length === 0 && Array.isArray(data) && data.length > 0) {
    Swal.fire({
        icon: 'warning',
        title: 'Limited Data Available',
        html: `Found ${data.length} time periods but no Landsat imagery.<br><br>
           <strong>Available datasets:</strong><br>
           • SMAP (Soil Moisture): ${data.some((d) => d.has_smap) ? '✓' : '✗'}<br>
           • CHIRPS (Rainfall): ${data.some((d) => d.has_chirps) ? '✓' : '✗'}<br>
           • MODIS (ETo): ${data.some((d) => d.has_eto) ? '✓' : '✗'}<br><br>
           <em>Try adjusting dates or check other data layers.</em>`,
    });
}
```

#### e. **localStorage Integration** (lines 8515-8527)
```javascript
// Save crop health data to localStorage for dashboard
try {
    const cropHealthData = {
        data: data,
        startDate: startDate,
        endDate: endDate,
        timestamp: new Date().toISOString()
    };
    localStorage.setItem('lastCropHealthData', JSON.stringify(cropHealthData));
    console.log('✅ Crop health data saved to localStorage for dashboard');
} catch (e) {
    console.warn('Failed to save crop health data to localStorage:', e);
}
```

## Benefits

1. **Identical Behavior**: React app now behaves exactly like app2.html
2. **Better Error Messages**: Users see detailed error information from backend
3. **Faster Performance**: Default 6-month range prevents accidental large queries
4. **Data Validation**: 365-day limit enforced client-side before API call
5. **Graceful Degradation**: Shows partial data availability warnings
6. **Dashboard Integration**: Saves data to localStorage for cross-page access

## Testing Checklist

- [x] Date range defaults to last 6 months
- [x] 365-day validation works
- [x] Server errors show detailed messages
- [x] Empty data shows appropriate warnings
- [x] Partial data availability warnings display
- [x] Data saves to localStorage
- [x] Success message shows data point count

## Files Modified

1. `frontend/src/context/AppContext.jsx` - Default date initialization
2. `frontend/src/utils/api.js` - API error handling
3. `frontend/src/pages/FieldAnalysis.jsx` - Fetch data logic

---

**Result**: The React application now uses the **exact same API call logic** as `app2.html` with no extra additions or modifications.
