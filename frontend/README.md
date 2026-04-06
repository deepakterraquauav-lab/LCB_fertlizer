# KrishiZest React Frontend

This is the React.js version of the KrishiZest Smart Irrigation Dashboard, converted from the original vanilla HTML/CSS/JS implementation.

## Features

- **Interactive Leaflet Map** with drawing tools (polygon, rectangle)
- **Satellite Layer Selection** (NDVI, SAVI, CWSI, Temperature, etc.)
- **Time-series Charts** with Chart.js
- **Analytics Dashboard** with crop health statistics
- **Irrigation Calendar** generation
- **Dark Mode** support
- **Multi-language** support (English & Hindi)
- **Location Search** with autocomplete

## Tech Stack

- **React 18** - UI framework
- **Vite** - Build tool
- **Leaflet & react-leaflet** - Interactive maps
- **Chart.js & react-chartjs-2** - Data visualization
- **SweetAlert2** - Notifications
- **Font Awesome** - Icons

## Project Structure

```
frontend/
├── public/
│   └── static/
│       └── logo.png
├── src/
│   ├── components/
│   │   ├── Header.jsx          # Top navigation with search & dark mode
│   │   ├── Sidebar.jsx         # Left control panel
│   │   ├── MapComponent.jsx    # Leaflet map with drawing tools
│   │   ├── ChartPanel.jsx      # Time-series charts
│   │   ├── AnalyticsSidebar.jsx # Right analytics panel
│   │   └── LoadingOverlay.jsx  # Loading animation
│   ├── context/
│   │   └── AppContext.jsx      # Global state management
│   ├── utils/
│   │   ├── api.js              # Backend API calls
│   │   └── translations.js     # i18n translations
│   ├── App.jsx                 # Main application
│   ├── main.jsx                # Entry point
│   └── index.css               # Global styles
├── index.html
├── vite.config.js
└── package.json
```

## Getting Started

### Prerequisites

- Node.js 18+
- The Flask backend (`app2.py`) running on port 5000

### Installation

```bash
cd frontend
npm install
```

### Development

```bash
# Start the React dev server (runs on port 3000)
npm run dev

# In a separate terminal, start the Flask backend
cd ..
python app2.py
```

### Build for Production

```bash
npm run build
```

The build output will be in the `dist/` folder.

## API Endpoints

The frontend communicates with the Flask backend through these endpoints:

- `POST /get_daily_data` - Fetch satellite data for date range
- `POST /get_gee_tile` - Get map tile layer URLs
- `POST /get_irrigation_calendar` - Generate irrigation schedule
- `POST /get_land_cover_analysis` - Analyze land cover
- `POST /generate_report` - Generate PDF report

## Configuration

The Vite development server proxies API calls to `http://localhost:5000`. Update `vite.config.js` to change the backend URL.

## Migration Notes

This React frontend replaces `templates/app2.html` and provides the same functionality:

- ✅ Same UI design and styling
- ✅ All map/drawing functionality
- ✅ All chart types and parameters
- ✅ Analytics dashboard with tabs
- ✅ Dark mode support
- ✅ Language switching
- ✅ Vector file upload
- ✅ Layer management

The backend (`app2.py`) remains unchanged - no modifications needed.

## Troubleshooting

### Proxy errors
If you see `ECONNREFUSED` errors, make sure the Flask backend is running:
```bash
python app2.py
```

### Map not loading
Ensure Leaflet CSS is imported. Check browser console for errors.

### Styles look wrong
Make sure `index.css` is imported in the main App component.
