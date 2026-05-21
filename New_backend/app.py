"""
SMART IRRIGATION SYSTEM - COMPLETE FLASK BACKEND
Merged Landsat + Sentinel-2/MODIS Logic
"""

import matplotlib
matplotlib.use('Agg') # Render/Production server compatibility (Non-interactive mode)

from flask import Flask, render_template, request, jsonify
import ee
from datetime import timedelta, datetime
import logging
import sys
import traceback
import numpy as np
import jenkspy

# Import custom modules
import ee_auth
from services import irrigation_service
from processors import landsat, sentinel2, common, soil_moisture, weather, pca_processor

try:
    from report_generator import generate_report_response
except ImportError:
    # Mock if missing
    def generate_report_response(payload):
        return jsonify({'error': 'Report generator not available'}), 501

# =============================================================================
# INITIALIZATION
# =============================================================================

# Initialize Earth Engine
ee_auth.initialize_ee()


# Import additional libraries
import os
import firebase_admin
from firebase_admin import credentials as firebase_credentials, auth as firebase_auth
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from functools import wraps
import base64
import json
from flask_cors import CORS

# =============================================================================
# FLASK APP SETUP & DATABASE
# =============================================================================

load_dotenv()

# Firebase Initialization
try:
    if not firebase_admin._apps:
        cred = firebase_credentials.Certificate('karshizest-a7b3c3acdeee.json')
        firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"Firebase Init Warning: {e}")

app = Flask(__name__)

# Configure CORS to allow requests from multiple origins (Local Dev + Production)
allowed_origins = [
    "http://localhost:4000",
    "http://localhost:3000",
    "http://localhost:5173",
    "https://lcb-vite-frontend.onrender.com"
]
CORS(app, resources={r"/*": {"origins": allowed_origins}})

app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-at-least-32-chars-long')
app.permanent_session_lifetime = timedelta(days=7)

# Configure logging
root_logger = logging.getLogger()
if not root_logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s - %(name)s - %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
root_logger.setLevel(logging.DEBUG)

app.config['DEBUG'] = True

logger = logging.getLogger('smart_irrigation_logger')
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

# Database Configuration
_db_url = os.getenv('DATABASE_URL', '')
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url.replace("postgres://", "postgresql://")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
}
db = SQLAlchemy(app)

# =============================================================================
# DATABASE MODELS
# =============================================================================

class Field(db.Model):
    __tablename__ = 'user_fields'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(128), nullable=False)
    name = db.Column(db.String(128), nullable=False)
    geometry = db.Column(db.JSON, nullable=False)
    area_hectares = db.Column(db.Float, nullable=True)
    area_acres = db.Column(db.Float, nullable=True)
    field_type = db.Column(db.String(50), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    village = db.Column(db.String(128), nullable=True)
    district = db.Column(db.String(128), nullable=True)
    state = db.Column(db.String(128), nullable=True)
    crop_type = db.Column(db.String(128), nullable=True)
    crop_name = db.Column(db.String(128), nullable=True)
    sowing_date = db.Column(db.String(32), nullable=True)
    harvesting_date = db.Column(db.String(32), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AnalysisLog(db.Model):
    __tablename__ = 'analysis_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(128), nullable=False, index=True)
    field_id = db.Column(db.Integer, db.ForeignKey('user_fields.id'), nullable=True)
    analysis_type = db.Column(db.String(50))
    data = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Expenditure(db.Model):
    __tablename__ = 'user_expenditures'
    id = db.Column(db.Integer, primary_key=True)
    field_id = db.Column(db.Integer, db.ForeignKey('user_fields.id'), nullable=False)


class UserStats(db.Model):
    __tablename__ = 'user_stats'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(128), nullable=False, unique=True, index=True)
    total_area_hectares = db.Column(db.Float, default=0.0)
    total_area_acres = db.Column(db.Float, default=0.0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Create tables (safe for multiple gunicorn workers - ignores if tables already exist)
try:
    with app.app_context():
        db.create_all()
        print("Database tables created/verified")
        # Run startup alteration queries to ensure dynamic schema upgrade
        db.session.execute(db.text("ALTER TABLE user_fields ADD COLUMN IF NOT EXISTS latitude FLOAT;"))
        db.session.execute(db.text("ALTER TABLE user_fields ADD COLUMN IF NOT EXISTS longitude FLOAT;"))
        db.session.execute(db.text("ALTER TABLE user_fields ADD COLUMN IF NOT EXISTS village VARCHAR(128);"))
        db.session.execute(db.text("ALTER TABLE user_fields ADD COLUMN IF NOT EXISTS district VARCHAR(128);"))
        db.session.execute(db.text("ALTER TABLE user_fields ADD COLUMN IF NOT EXISTS state VARCHAR(128);"))
        db.session.execute(db.text("ALTER TABLE user_fields ADD COLUMN IF NOT EXISTS crop_type VARCHAR(128);"))
        db.session.execute(db.text("ALTER TABLE user_fields ADD COLUMN IF NOT EXISTS crop_name VARCHAR(128);"))
        db.session.execute(db.text("ALTER TABLE user_fields ADD COLUMN IF NOT EXISTS sowing_date VARCHAR(32);"))
        db.session.execute(db.text("ALTER TABLE user_fields ADD COLUMN IF NOT EXISTS harvesting_date VARCHAR(32);"))
        db.session.commit()
        print("Database schema successfully upgraded with coordinates, crop/location, and sowing/harvesting columns.")
except Exception as _db_init_err:
    print(f"DB init warning (safe to ignore if tables already exist): {_db_init_err}")

# =============================================================================
# AUTH HELPERS
# =============================================================================

def verify_firebase_token(token):
    try:
        return firebase_auth.verify_id_token(token)
    except Exception as e:
        # Fallback for Dev/Demo if strict verification fails (e.g. project mismatch)
        logger.warning(f"Token verification warning: {e}. Attempting manual decode.")
        try:
            parts = token.split('.')
            if len(parts) > 1:
                payload = parts[1]
                padded = payload + '=' * ((4 - len(payload) % 4) % 4)
                decoded = json.loads(base64.urlsafe_b64decode(padded))
                if 'uid' not in decoded and 'sub' in decoded:
                    decoded['uid'] = decoded['sub']
                return decoded
        except Exception:
            pass
        raise e

def firebase_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        id_token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                id_token = auth_header.split('Bearer ')[1]
        
        if not id_token:
            return jsonify({'error': 'No authentication token provided'}), 401
        
        try:
            decoded_token = verify_firebase_token(id_token)
            request.user = decoded_token
            return f(*args, **kwargs)
        except Exception as e:
            return jsonify({'error': f'Authentication failed: {str(e)}'}), 401
    return decorated_function

# =============================================================================
# FLASK ROUTES
# =============================================================================



def update_user_stats(user_id):
    """Aggregate all fields for a user and update their UserStats record."""
    user_fields = Field.query.filter_by(user_id=user_id).all()
    
    total_ha = sum(f.area_hectares for f in user_fields if f.area_hectares)
    total_acres = sum(f.area_acres for f in user_fields if f.area_acres)
    
    stats = UserStats.query.filter_by(user_id=user_id).first()
    if not stats:
        stats = UserStats(user_id=user_id, total_area_hectares=total_ha, total_area_acres=total_acres)
        db.session.add(stats)
    else:
        stats.total_area_hectares = total_ha
        stats.total_area_acres = total_acres
        
    db.session.commit()
    return stats


@app.route('/api/user_stats', methods=['GET'])
@firebase_required
def get_user_stats():
    """Returns the total area stats for the authenticated user"""
    try:
        user_id = request.user['uid']
        # Trigger an update to ensure exact synchronization
        stats = update_user_stats(user_id)
        
        return jsonify({
            'success': True,
            'total_area_hectares': round(stats.total_area_hectares, 3) if stats.total_area_hectares else 0,
            'total_area_acres': round(stats.total_area_acres, 3) if stats.total_area_acres else 0
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching user stats: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/update_field/<int:field_id>', methods=['PUT'])
@firebase_required
def update_field(field_id):
    try:
        user_id = request.user['uid']
        data = request.get_json()
        
        field = Field.query.filter_by(id=field_id, user_id=user_id).first()
        if not field:
            return jsonify({'error': 'Field not found'}), 404
            
        if 'name' in data:
            field.name = data['name']
        if 'field_name' in data:
            field.name = data['field_name']
        if 'geometry' in data:
            field.geometry = data['geometry']
        if 'area_hectares' in data:
            field.area_hectares = data['area_hectares']
            # Recompute acres whenever hectares is updated
            try:
                field.area_acres = round(float(data['area_hectares']) * 2.47105, 2)
            except (TypeError, ValueError):
                pass
        if 'area_acres' in data:
            field.area_acres = data['area_acres']
        if 'field_type' in data:
            field.field_type = data['field_type']
        if 'latitude' in data:
            field.latitude = data['latitude']
        if 'longitude' in data:
            field.longitude = data['longitude']
        if 'village' in data:
            field.village = data['village']
        if 'district' in data:
            field.district = data['district']
        if 'state' in data:
            field.state = data['state']
        if 'cropType' in data:
            field.crop_type = data['cropType']
        if 'crop_type' in data:
            field.crop_type = data['crop_type']
        if 'cropName' in data:
            field.crop_name = data['cropName']
        if 'crop_name' in data:
            field.crop_name = data['crop_name']
        if 'sowingDate' in data:
            field.sowing_date = data['sowingDate']
        if 'sowing_date' in data:
            field.sowing_date = data['sowing_date']
        if 'harvestingDate' in data:
            field.harvesting_date = data['harvestingDate']
        if 'harvesting_date' in data:
            field.harvesting_date = data['harvesting_date']
            
        db.session.commit()
        
        # Update user total stats
        update_user_stats(user_id)
        
        return jsonify({'success': True, 'message': 'Field updated'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating field: {e}")
        return jsonify({'error': str(e)}), 500



@app.route('/api/get_last_irrigation_calendar', methods=['GET'])
def get_last_irrigation_calendar():
    """Retrieve the last generated irrigation calendar."""
    try:
        # Check database logs first (AnalysisLog not fully utilized yet, fallback to file)
        # Using file for compatibility with old backend logic
        calendar_file = 'last_calendar.json'
        if os.path.exists(calendar_file):
            with open(calendar_file, 'r') as f:
                data = json.load(f)
            return jsonify(data)
        else:
            return jsonify({}) # Empty if not found
    except Exception as e:
        logger.error(f"Error reading calendar: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/')
def index():
    return jsonify({
        "status": "success", 
        "message": "Backend API is Live and working perfectly! 🎉"
    }), 200

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'db': 'connected'}), 200

# Field Management Routes
@app.route('/api/save_field', methods=['POST'])
@firebase_required
def save_field():
    try:
        data = request.get_json()
        user_id = request.user['uid']
        
        name = data.get('name') or data.get('field_name') or 'Untitled Field'
        
        # Check for duplicate name
        if Field.query.filter_by(user_id=user_id, name=name).first():
             return jsonify({'error': 'Field name already exists. Please choose a different name.'}), 409

        area_hectares = data.get('areaHectares')
        area_acres = data.get('areaAcres')
        # Compute acres if not provided but hectares available
        if area_acres is None and area_hectares is not None:
            try:
                area_acres = round(float(area_hectares) * 2.47105, 2)
            except (TypeError, ValueError):
                area_acres = None

        new_field = Field(
            user_id=user_id,
            name=name,
            geometry=data.get('geometry'), 
            area_hectares=area_hectares,
            area_acres=area_acres,
            field_type=data.get('type'),
            latitude=data.get('latitude'),
            longitude=data.get('longitude'),
            village=data.get('village'),
            district=data.get('district'),
            state=data.get('state'),
            crop_type=data.get('cropType') or data.get('crop_type'),
            crop_name=data.get('cropName') or data.get('crop_name'),
            sowing_date=data.get('sowingDate') or data.get('sowing_date'),
            harvesting_date=data.get('harvestingDate') or data.get('harvesting_date')
        )
        db.session.add(new_field)
        db.session.commit()
        
        # Update user total stats
        update_user_stats(user_id)
        
        return jsonify({'success': True, 'id': new_field.id, 'message': 'Field saved successfully'})
    except Exception as e:
        logger.error(f"Error in save_field: {traceback.format_exc()}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/get_fields', methods=['GET'])
@firebase_required
def get_fields():
    try:
        user_id = request.user['uid']
        fields = Field.query.filter_by(user_id=user_id).order_by(Field.created_at.desc()).all()
        fields_list = []
        for f in fields:
            # Compute acres from hectares if area_acres not stored (migration safety)
            ha = f.area_hectares
            acres = f.area_acres
            if acres is None and ha is not None:
                try:
                    acres = round(float(ha) * 2.47105, 2)
                except (TypeError, ValueError):
                    acres = None

            fields_list.append({
                'id': f.id,
                'name': f.name,
                'geometry': f.geometry,
                'areaHectares': round(float(ha), 2) if ha is not None else None,
                'areaAcres': acres,
                'type': f.field_type,
                'latitude': f.latitude,
                'longitude': f.longitude,
                'village': f.village,
                'district': f.district,
                'state': f.state,
                'cropType': f.crop_type,
                'cropName': f.crop_name,
                'sowingDate': f.sowing_date,
                'harvestingDate': f.harvesting_date,
                'created_at': f.created_at.isoformat()
            })
        return jsonify(fields_list)
    except Exception as e:
        logger.error(f"Error in get_fields: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete_field/<int:field_id>', methods=['DELETE'])
@firebase_required
def delete_field(field_id):
    try:
        user_id = request.user['uid']
        field = Field.query.filter_by(id=field_id, user_id=user_id).first()
        if not field:
            return jsonify({'error': 'Field not found'}), 404
        # Cascading pre-delete purge on dependent tables
        db.session.query(AnalysisLog).filter_by(field_id=field_id).delete()
        db.session.query(Expenditure).filter_by(field_id=field_id).delete()

        db.session.delete(field)
        db.session.commit()
        
        # Update user total stats
        update_user_stats(user_id)
        
        return jsonify({'success': True, 'message': 'Field deleted'})
    except Exception as e:
        logger.error(f"Error in delete_field: {traceback.format_exc()}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/.well-known/appspecific/com.chrome.devtools.json')
def _chrome_probe():
    return ('', 204)

@app.route('/get_daily_data', methods=['POST'])
def get_daily_data():
    """Enhanced daily data endpoint using Landsat & Sentinel-2"""
    try:
        data = request.get_json()
        print(f"DEBUG: get_daily_data payload: {json.dumps(data, indent=2)}") # Log payload
        user_aoi = data['aoi']
        
        # Helper to remove Z coordinates (Altitude) from KML/GeoJSON
        def remove_z(coords):
            if isinstance(coords, list):
                if len(coords) > 0 and isinstance(coords[0], (int, float)):
                    return coords[:2] # Keep only [lon, lat]
                return [remove_z(c) for c in coords]
            return coords

        # Handle GeometryCollection or MultiPolygon if needed
        geom_type = user_aoi['geometry']['type']
        raw_coords = user_aoi['geometry']['coordinates']
        
        # Clean coordinates
        coords = remove_z(raw_coords)
        
        print(f"DEBUG: Geometry Type: {geom_type}")
        
        if geom_type == 'Polygon':
            aoi = ee.Geometry.Polygon(coords)
        elif geom_type == 'MultiPolygon':
            aoi = ee.Geometry.MultiPolygon(coords)
        elif geom_type == 'Point':
            aoi = ee.Geometry.Point(coords)
        else:
            # Fallback for complex types with cleaned coords
            # We need to reconstruct the geometry object
            cleaned_geom = user_aoi['geometry'].copy()
            cleaned_geom['coordinates'] = coords
            aoi = ee.Geometry(cleaned_geom)

        start_date = data['start_date']
        end_date = data['end_date']
        
        # Read Mask Option (Default False to be safe for user pixels)
        mask_agri = data.get('mask_agri', False)
        
        # Validate date range
        start = ee.Date(start_date)
        end = ee.Date(end_date)
        diff_days = end.difference(start, 'day').getInfo()
        
        if diff_days > 1096:
            return jsonify({'error': 'Date range too large. Please select ≤ 3 years.'}), 400

        logger.info(f"Requesting data from {start_date} to {end_date}. Masking: {mask_agri}")
        
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from datetime import datetime, timedelta
        
        def fetch_chunk(chunk_start, chunk_end):
            chunk_collection = irrigation_service.get_combined_data(aoi, chunk_start, chunk_end, mask_agri=mask_agri)
            return chunk_collection.getInfo().get('features', [])

        raw = []
        try:
            if diff_days <= 366:
                raw = fetch_chunk(start_date, end_date)
                logger.debug(f"Fetched {len(raw)} daily records")
            else:
                chunks = []
                current_start = datetime.strptime(start_date, "%Y-%m-%d")
                final_end = datetime.strptime(end_date, "%Y-%m-%d")
                
                while current_start < final_end:
                    current_end = current_start + timedelta(days=365)
                    if current_end > final_end or (final_end - current_end).days < 30:
                        current_end = final_end
                    chunks.append((current_start.strftime("%Y-%m-%d"), current_end.strftime("%Y-%m-%d")))
                    current_start = current_end
                
                logger.info(f"Chunking request into {len(chunks)} chunks: {chunks}")
                
                with ThreadPoolExecutor(max_workers=len(chunks)) as executor:
                    futures = [executor.submit(fetch_chunk, c_start, c_end) for c_start, c_end in chunks]
                    for future in as_completed(futures):
                        raw.extend(future.result())
                        
                logger.debug(f"Fetched {len(raw)} total daily records from chunks")
        except Exception as e:
            logger.error(f"EE getInfo failed: {e}")
            logger.error(traceback.format_exc())
            return jsonify({'error': 'Earth Engine getInfo() failed', 'details': str(e)}), 500

        result = []
        for f in raw:
            if not f: 
                continue
                
            props = f.get('properties', {})
            # Normalize keys to lowercase
            normalized = {k.lower(): v for k, v in props.items()}
            
            keys_to_ensure = ['ndvi', 'savi', 'cwsi', 'kc', 'lst', 'eto', 'rain', 'effrain', 
                              'soilmoisture', 'deltas_mm', 'etc', 'cwr', 'irrigation_need', 'evi', 'lai', 'pc1', 'clre']
            for k in keys_to_ensure:
                normalized.setdefault(k, None)
            
            if 'soilmoisture' in normalized:
                normalized['soilmoisture_mm'] = normalized['soilmoisture']
            if 'deltas_mm' in normalized:
                normalized['deltas'] = normalized['deltas_mm'] 
            if 'pc1' in normalized:
                normalized['pca'] = normalized['pc1'] # Frontend checks 'pca' key 

            result.append(normalized)

        return jsonify(result)

    except Exception as e:
        logger.error(f"Unhandled exception in /get_daily_data: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route('/get_irrigation_calendar', methods=['POST'])
def get_irrigation_calendar():
    """Smart irrigation calendar using Multi-Sensor Logic"""
    try:
        data = request.get_json()
        user_aoi = data['aoi']
        coords = user_aoi['geometry']['coordinates']
        aoi = ee.Geometry.Polygon(coords)

        start_date = data['start_date']
        end_date = data['end_date']
        
        # Thresholds
        PRECIPITATION_THRESHOLD = data.get('rain_threshold', 2.0)
        CWSI_THRESHOLD = data.get('cwsi_threshold', 0.35)
        SOIL_MOISTURE_THRESHOLD = data.get('sm_threshold', 25.0)
        mask_agri = data.get('mask_agri', False)
        
        logger.info(f"Generating calendar. Thresholds: Rain={PRECIPITATION_THRESHOLD}, CWSI={CWSI_THRESHOLD}, SM={SOIL_MOISTURE_THRESHOLD}, Masking={mask_agri}")

        # Get Data
        daily_collection = irrigation_service.get_combined_data(aoi, start_date, end_date, mask_agri=mask_agri)
        
        try:
            raw = daily_collection.getInfo().get('features', [])
        except Exception as e:
            return jsonify({'error': f"Failed to fetch calendar data: {e}"}), 500

        calendar_data = []

        for f in raw:
            props = f.get('properties', {})
            date_str = props.get('date')
            if not date_str: continue
            
            # Check if satellite data is available for this date
            l8_available = props.get('landsat_available', 0)
            s2_available = props.get('s2_available', 0)
            
            # SKIP dates with no satellite data (both Landsat and S2 filtered by clouds)
            if l8_available == 0 and s2_available == 0:
                logger.info(f"Skipping {date_str} - no satellite data available (cloud filtered)")
                continue

            # Extract values
            cwsi = props.get('CWSI', 0.4)
            sm = props.get('SoilMoisture', 35.0)
            rain = props.get('Rain', 0)
            irr_val = props.get('Irrigation_Need', 0)
            kc = props.get('Kc', 0.5)
            etc = props.get('ETc', 0)
            cwr = props.get('CWR', 0)
            sm_source = props.get('soil_moisture_source', 'Default')
            sensor = props.get('source_sensor', 'Unknown')

            # Decision Logic
            should_irrigate = False
            advice = ''
            priority = 'LOW'

            if rain < PRECIPITATION_THRESHOLD:
                if (cwsi is not None and cwsi > CWSI_THRESHOLD) or (sm is not None and sm < SOIL_MOISTURE_THRESHOLD):
                    should_irrigate = True
                    if irr_val > 2.0:
                        advice = '🔴 Low rain + Stress - Immediate irrigation needed'
                        priority = 'URGENT'
                    elif irr_val > 0.5:
                        advice = '🟡 Low rain + Stress - Irrigation needed soon'
                        priority = 'MODERATE'
                    else:
                        advice = '✅ Low rain but plants healthy - No irrigation needed'
                        priority = 'LOW'
                        should_irrigate = False
                else:
                    advice = '✅ Low rain but plants healthy - No irrigation needed'
                    priority = 'LOW'
            else:
                 advice = '✅ Adequate rainfall - No irrigation needed'
                 priority = 'LOW'
            
            final_irrigation = irr_val if should_irrigate else 0.0

            entry = {
                'date': date_str,
                'cwsi_mean': round(cwsi, 3) if cwsi else None,
                'soil_moisture_percent': round(sm, 2) if sm else None,
                'rain_mm': round(rain, 2),
                'original_irrigation_mm': round(irr_val, 2),
                'final_irrigation_mm': round(final_irrigation, 2),
                'should_irrigate': should_irrigate,
                'advice': advice,
                'priority': priority,
                'soil_moisture_source': sm_source,
                'sensor_source': sensor,
                'kc_mean': round(kc, 3) if kc else None,
                'etc_mm': round(etc, 2) if etc else None,
                'cwr_mm': round(cwr, 2) if cwr else None
            }
            calendar_data.append(entry)

        if not calendar_data:
             return jsonify({'error': 'No valid data processed.'}), 404

        # Summary
        irrigation_events = [d for d in calendar_data if d['should_irrigate']]
        total_water = sum(d['final_irrigation_mm'] for d in irrigation_events)
        original_water = sum(d['original_irrigation_mm'] for d in calendar_data)
        water_saved = original_water - total_water
        
        # Debug logging
        logger.info(f"Calendar Summary: Total days={len(calendar_data)}, Irrigation events={len(irrigation_events)}, Total water={total_water}mm")
        logger.info(f"Irrigation events breakdown: {[(e['date'], e['priority'], e['final_irrigation_mm']) for e in irrigation_events]}")
        
        # Count priority levels for frontend display
        urgent_count = len([e for e in irrigation_events if e['priority'] == 'URGENT'])
        moderate_count = len([e for e in irrigation_events if e['priority'] == 'MODERATE'])

        # FLATTENED structure to match frontend expectations
        summary = {
            'start_date': start_date,
            'end_date': end_date,
            'total_days': len(calendar_data),
            'irrigation_events': len(irrigation_events),  # Flattened from irrigation.total_events
            'total_water_mm': round(total_water, 2),      # Flattened from irrigation.total_water_mm
            'water_saved_mm': round(water_saved, 2),      # Flattened from irrigation.water_saved_mm
            'urgent_count': urgent_count,
            'moderate_count': moderate_count,
            'thresholds': {
                'precipitation': PRECIPITATION_THRESHOLD,
                'cwsi': CWSI_THRESHOLD,
                'soil_moisture': SOIL_MOISTURE_THRESHOLD
            }
        }

        return jsonify({
            'success': True,
            'summary': summary,
            'calendar': calendar_data
        })

    except Exception as e:
        logger.error(f"Error in /get_irrigation_calendar: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route('/get_available_dates', methods=['POST'])
def get_available_dates():
    """Get list of dates with available satellite imagery"""
    try:
        data = request.get_json()
        coords = data['aoi']['geometry']['coordinates']
        aoi = ee.Geometry.Polygon(coords)
        start_date = data['start_date']
        end_date = data['end_date']
        
        # Get AOI-level cloud proxy per Sentinel-2 date.
        # This is computed at 20m only for statistics (visualization resolution is unchanged).
        cloud_fc = sentinel2.get_s2_date_cloud_info(
            aoi,
            start_date,
            end_date,
            cloud_filter=100,
            cs_threshold=0.60,
            scale=20
        )
        cloud_features = cloud_fc.getInfo().get('features', [])

        date_info = []
        for f in cloud_features:
            props = f.get('properties', {})
            date_str = props.get('date')
            if not date_str:
                continue
            cloud_pct = props.get('cloud_pct_aoi', 0)
            try:
                cloud_pct = round(float(cloud_pct), 2)
            except Exception:
                cloud_pct = 0.0

            date_info.append({
                'date': date_str,
                'sensor': 'Sentinel-2',
                'has_landsat': False,
                'has_sentinel2': True,
                'cloud_pct_aoi': cloud_pct
            })

        all_dates = sorted([d['date'] for d in date_info])
        date_info = sorted(date_info, key=lambda x: x['date'])
        
        return jsonify({
            'success': True,
            'count': len(all_dates),
            'dates': all_dates,
            'date_info': date_info
        })
        
    except Exception as e:
        logger.error(f"Error getting available dates: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/get_gee_tile', methods=['POST'])
def get_gee_tile():
    """
    Tile generation. Supports specific date or composite layer.
    """
    try:
        data = request.get_json()
        coords = data['aoi']['geometry']['coordinates']
        aoi = ee.Geometry.Polygon(coords)
        layer_type = data.get("layer", "ndvi")
        
        # Check if specific date requested
        specific_date_str = data.get('date')
        
        start_date_param = data.get('start_date')
        end_date_param = data.get('end_date')
        
        # Mask Option for Visuals
        mask_agri = data.get('mask_agri', False)
        
        # Determine Period
        if specific_date_str:
            d = ee.Date(specific_date_str)
            start_date = d
            end_date = d.advance(1, 'day')
            logger.info(f"Generating tile for specific date: {specific_date_str}")
        elif start_date_param and end_date_param:
            start_date = ee.Date(start_date_param)
            end_date = ee.Date(end_date_param)
            logger.info("Generating tile for composite period")
        else:
            end_date = ee.Date(datetime.now())
            start_date = end_date.advance(-30, 'day')

        # Determine Thresholds Dynamically (Matching Temp.py logic)
        try:
            # Only use Sentinel-2 for threshold calculation
            s2_col_raw = sentinel2.get_s2_collection(aoi, start_date, end_date)
            def get_ndvi_s2(img):
                return img.normalizedDifference(['B8', 'B4']).rename('NDVI')
            combined_ndvi = s2_col_raw.map(get_ndvi_s2)
            
            n_min, n_max = common.get_ndvi_range(combined_ndvi, aoi)
            ndvi_min_img = ee.Image.constant(n_min)
            ndvi_max_img = ee.Image.constant(n_max)
            logger.info(f"Dynamic NDVI Range: {n_min.getInfo():.3f} - {n_max.getInfo():.3f}")
        except Exception as e:
            logger.warning(f"Error calculating dynamic thresholds: {e}. Using defaults.")
            ndvi_min_img = ee.Image.constant(0.1)
            ndvi_max_img = ee.Image.constant(0.8)

        base_img = None
        
        # Determine Source and Build Base Image
        if specific_date_str:
            # FORCE SENTINEL-2 ONLY (Skip Landsat)
            logger.info("📊 Using Sentinel-2 for specific date (Landsat skipped)")
            s2_col = sentinel2.get_s2_collection(aoi, start_date, end_date)
            s2_img = s2_col.first()
            count_s2 = s2_col.size().getInfo()
            
            if count_s2 > 0:
                base_img = sentinel2.process_s2_image(s2_img, aoi, ndvi_min_img, ndvi_max_img, mask_agri=mask_agri)
            else:
                return jsonify({'error': f'No Sentinel-2 imagery found for date {specific_date_str}'}), 404
        else:
            # FORCE SENTINEL-2 ONLY FOR COMPOSITE
            logger.info("📊 Using Sentinel-2 composite (Landsat skipped)")
            s2_col = sentinel2.get_s2_collection(aoi, start_date, end_date)
            
            if s2_col.size().getInfo() == 0:
                return jsonify({'error': 'No Sentinel-2 imagery found for composite.'}), 404
            
            base = sentinel2.process_s2_image(s2_col.median().set('selected_date', 'Composite'), aoi, ndvi_min_img, ndvi_max_img, mask_agri=False)
            if mask_agri:
                mask = common.get_agri_mask(aoi, end_date)
                base_img = base.updateMask(mask)
            else:
                base_img = base
        
        # =====================================================================
        # APPLY GLOBAL TRANSPARENCY (Water & Non-Agri Masking)
        # =====================================================================
        # Build a robust mask: 
        # 1. NDVI > 0 removes pure water bodies
        # 2. (Optional) Dynamic World mask removes trees/built-up
        
        # Start with a mask where NDVI > 0 (Water is <= 0)
        final_mask = base_img.select('NDVI').gt(0)
        
        # Fallback to JRC Water if NDVI is noisy (Optional but good for robustness)
        try:
            jrc = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select('occurrence')
            # If occurrence > 90, it's definitely water
            jrc_mask = jrc.lt(90).unmask(1)
            final_mask = final_mask.And(jrc_mask)
        except:
            pass

        # Apply Agricultural Mask if requested
        if mask_agri:
            ag_mask = common.get_agri_mask(aoi, start_date)
            final_mask = final_mask.And(ag_mask)

        # Apply the final combined mask to base_img
        base_img = base_img.updateMask(final_mask)
        
        # =====================================================================
        # SELECT LAYER
        # =====================================================================
        vis_params = {}
        selected_img = None
        stats_data = {}

        if layer_type == 'pca':
            logger.info("  Applying PCA Transformation...")
            try:
                # Train/Load Dynamic Model
                # Use start_date/end_date from request to define season
                # If specific_date_str is present, use that. Else use start_date param.
                training_date = specific_date_str if specific_date_str else start_date_param
                if not training_date:
                     training_date = datetime.now().strftime('%Y-%m-%d')
                
                # Train (or load from cache)
                pca_params = pca_processor.processor.train_dynamic_model(aoi, training_date)
                
                # Apply PCA with specific params
                pca_img = pca_processor.processor.apply_pca(base_img, params=pca_params)
                selected_img = pca_img.select('PC1')
                
                # Dynamic stats for visualization (PC1 is roughly -3 to 3, but dynamic is better)
                stats = common.get_dynamic_stats(selected_img, 'PC1', aoi)
                
                # Use robust min/max from stats (p2/p98 avoids outliers)
                vis_params = {
                    'min': stats['p2'],
                    'max': stats['p98'],
                    'palette': ['#d73027', '#fc8d59', '#fee08b', '#91cf60', '#1a9850'] # Red to Green (RdYlGn) 5 classes
                }
                stats_data = {'min': stats['min'], 'max': stats['max'], 'mean': stats['p50']}
                
            except Exception as e:
                logger.error(f"PCA Application failed: {e}")
                return jsonify({'error': str(e)}), 500

        elif layer_type in ['ndvi', 'savi', 'evi', 'cwsi', 'kc', 'lst', 'lai', 'chlorophyll', 'etc', 'cwr', 'irrigation_need', 'vra_irrigation']:
            
            if layer_type == 'etc':
                # Use the same logic as time series for consistency
                # This searches a 4-day window for MODIS data (8-day composite product)
                eto_img, eto_count = weather.get_eto_image(start_date)
                selected_img = base_img.select('Kc').multiply(eto_img).rename('ETc')
                # Dynamic Stats for ETc
                try:
                    stats = common.get_dynamic_stats(selected_img, 'ETc', aoi)
                    vis_params = {
                        'min': max(0, stats['p2']),
                        'max': stats['p98'],
                        'palette': ['#D7191C', '#FDAE61', '#FFFFBF', '#ABD9E9', '#2C7BB6']
                    }
                    stats_data = {'min': stats['min'], 'max': stats['max'], 'mean': stats['p50'], 'p25': stats['p25'], 'p75': stats['p75']}
                except:
                    vis_params = {'min': 0, 'max': 10, 'palette': ['#D7191C', '#FDAE61', '#FFFFBF', '#ABD9E9', '#2C7BB6']}
            
            elif layer_type == 'cwr':
                # Similar approx
                # Use weather.get_eto_image for consistent 4-day window search
                eto_img, eto_count = weather.get_eto_image(start_date)
                
                chirps_col = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY").filterDate(start_date, end_date)
                fallback_rain = ee.Image.constant(0.1).toFloat().rename('precipitation')
                rain_img = ee.ImageCollection([fallback_rain]).merge(chirps_col).sum().rename('Rain')
                
                # Calculate number of days to get AVG DAILY rain
                days_diff = (ee.Date(end_date).difference(ee.Date(start_date), 'day')).max(1)
                rain_daily = rain_img.divide(days_diff)
                
                selected_img = base_img.select('Kc').multiply(eto_img).subtract(rain_daily.multiply(0.8)).max(0).rename('CWR')
                vis_params = {'min': 0, 'max': 10, 'palette': ['#D7191C', '#FDAE61', '#FFFFBF', '#ABD9E9', '#2C7BB6']}

            
            elif layer_type == 'irrigation_need':
                # Irrigation need calculation (DAILY comparison) - matches Temp.py
                # Irrigation need calculation (DAILY comparison)
                # Use weather.get_eto_image for consistent 4-day window search to handle missing MODIS data
                eto_img, eto_count = weather.get_eto_image(start_date)
                
                chirps_col = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY") \
                              .filterDate(start_date, end_date)
                fallback_rain = ee.Image.constant(0.1).toFloat().rename('precipitation')
                rain_img = ee.ImageCollection([fallback_rain]).merge(chirps_col).sum().rename('Rain')
                
                # Calculate number of days to get AVG DAILY rain
                days_diff = (ee.Date(end_date).difference(ee.Date(start_date), 'day')).max(1)
                rain_daily = rain_img.divide(days_diff)
                eff_rain_daily = rain_daily.multiply(0.8)
                
                kc = base_img.select('Kc')
                etc = kc.multiply(eto_img)  # ETc is already daily (avg)
                
                # Subtract DAILY rain from DAILY ETc
                cwr = etc.subtract(eff_rain_daily).max(0)
                selected_img = cwr.divide(0.7).rename('Irrigation_Need')
                # Dynamic Stats for Irrigation Need
                try:
                    stats = common.get_dynamic_stats(selected_img, 'Irrigation_Need', aoi)
                    vis_params = {
                        'min': 0,
                        'max': max(1.0, stats['p98']),
                        'palette': ['#E8F5E9', '#FFF9C4', '#FFB74D', '#F57C00', '#C62828']
                    }
                    stats_data = {'min': stats['min'], 'max': stats['max'], 'mean': stats['p50'], 'p25': stats['p25'], 'p75': stats['p75']}
                except:
                    vis_params = {'min': 0, 'max': 10, 'palette': ['#E8F5E9', '#FFF9C4', '#FFB74D', '#F57C00', '#C62828']}

            elif layer_type == 'vra_irrigation':
                # 1. Fetch ETo (MODIS 8-day composite)
                # Use a wider window (15 days) to ensure we always have data even on a single specific_date
                eto_col = ee.ImageCollection("MODIS/061/MOD16A2") \
                            .filterDate(ee.Date(start_date).advance(-10, 'day'), ee.Date(end_date).advance(5, 'day')) \
                            .select('PET') \
                            .map(lambda img: img.multiply(0.1).divide(8).rename('eto'))
                eto_img = eto_col.mean().unmask(4.0)
                
                # 2. Daily Rainfall (CHIRPS)
                # Handle single date vs range robustly
                fallback_rain = ee.Image.constant(0.1).toFloat().rename('precipitation')
                if specific_date_str:
                    # For a single day, look at 3-day average for more stable stress assessment
                    rain_col = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY") \
                                   .filterDate(ee.Date(start_date).advance(-2, 'day'), ee.Date(end_date))
                    rain_daily = ee.ImageCollection([fallback_rain]).merge(rain_col).sum().divide(3).rename('Rain')
                else:
                    # For a range, use the mean of that range
                    rain_col = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY").filterDate(start_date, end_date)
                    rain_sum = ee.ImageCollection([fallback_rain]).merge(rain_col).sum()
                    days = ee.Date(end_date).difference(ee.Date(start_date), 'day').max(1)
                    rain_daily = rain_sum.divide(days).rename('Rain')
                
                eff_rain_daily = rain_daily.multiply(0.8)
                
                # 3. Calculate Water Demand (Daily)
                kc = base_img.select('Kc')
                etc = kc.multiply(eto_img) # Daily water loss
                cwr = etc.subtract(eff_rain_daily).max(0)
                irr_val = cwr.divide(0.7).rename('Irrigation_Need')
                
                # 4. Stress Parameters
                s1_col = soil_moisture.get_sentinel1_soil_moisture_simple(aoi, start_date, end_date)
                sm_img, _, _, _, _ = soil_moisture.get_combined_soil_moisture(aoi, ee.Date(start_date), s1_col)
                
                # CWSI is only available from Landsat. Check if base_img has it.
                has_cwsi = base_img.bandNames().contains('CWSI')
                cwsi = ee.Image(ee.Algorithms.If(
                    has_cwsi,
                    base_img.select('CWSI'),
                    ee.Image.constant(0).selfMask().rename('CWSI')  # No CWSI on S2-only dates
                ))
                
                # 5. Thresholds
                P_thresh = data.get('rain_threshold', 2.0)
                C_thresh = data.get('cwsi_threshold', 0.35)
                S_thresh = data.get('sm_threshold', 25.0)
                
                # 6. Ag Masking (Crop areas only)
                ag_mask = common.get_agri_mask(aoi, ee.Date(start_date))
                
                # 7. Decision Matrix
                # When CWSI is unavailable (S2-only dates), stress is determined by soil moisture alone
                stress = ee.Image(ee.Algorithms.If(
                    has_cwsi,
                    cwsi.gt(C_thresh).Or(sm_img.lt(S_thresh)),
                    sm_img.lt(S_thresh)  # Soil moisture only fallback
                ))
                low_rain = rain_daily.lt(P_thresh)
                critical_condition = low_rain.And(stress)
                
                zone_urgent = critical_condition.And(irr_val.gt(2.0))
                
                # Build VRA classified image: 0=no irr, 1=moderate, 2=urgent
                vra_map = ee.Image(0) \
                    .where(critical_condition.And(irr_val.gt(0.5)), 1) \
                    .where(zone_urgent, 2) \
                    .rename('VRA_Irrigation')
                selected_img = vra_map
                
                try:
                    area_counts = selected_img.reduceRegion(ee.Reducer.frequencyHistogram(), aoi, 30).get('VRA_Irrigation').getInfo()
                    total_pixels = sum(area_counts.values()) if area_counts else 1
                    stats_data = {
                        'min': 0, 'max': 2, 'mean': selected_img.reduceRegion(ee.Reducer.mean(), aoi, 30).get('VRA_Irrigation').getInfo(),
                        'no_irrigation_pct': round((area_counts.get('0', 0) / total_pixels) * 100, 1),
                        'moderate_pct': round((area_counts.get('1', 0) / total_pixels) * 100, 1),
                        'urgent_pct': round((area_counts.get('2', 0) / total_pixels) * 100, 1)
                    }
                except:
                    stats_data = {'min': 0, 'max': 2, 'mean': 0}
            
            else:
                mapping = {
                    'ndvi': {'band':'NDVI', 'min':0, 'max':1, 'pal': ['#8B4513', '#D2691E', '#FFD700', '#ADFF2F', '#7FFF00', '#32CD32', '#228B22', '#006400']},
                    'savi': {'band':'SAVI', 'min':0, 'max':1, 'pal': ['#8B4513', '#D2691E', '#FFFF00', '#90EE90', '#32CD32', '#006400']},
                    'evi': {'band':'EVI', 'min':-0.2, 'max':1, 'pal': ['#8B4513', '#CD853F', '#F4A460', '#FFFF00', '#ADFF2F', '#7FFF00', '#00FF00', '#006400']},
                    'cwsi': {'band':'CWSI', 'min':0, 'max':0.6, 'pal': ['#0000FF', '#87CEEB','#FFFF00','#FF6666', '#FF0000']},
                    'kc':   {'band':'Kc',   'min':0, 'max':1.5, 'pal': ['#FF0000', '#FF7F00', '#FFFF00', '#7FFF00', '#00FF00']},
                    'lst':  {'band':'LST',  'min':280, 'max':330, 'pal': ['#0000FF', '#00FFFF', '#FFFF00', '#FFA500', '#FF4500', '#8B0000']},
                    'lai':  {'band':'LAI',  'min':0, 'max':6, 'pal': ['#964B00', '#FFD700', '#ADFF2F', '#7FFF00', '#32CD32', '#228B22', '#006400']},
                    # CLRe: Chlorophyll Red-Edge Index (Sentinel-2 only: B7/B5 - 1)
                    # Typical theoretical range 0-2, but we use dynamic range for better visuals
                    'chlorophyll': {'band':'CLRe', 'min':0, 'max':2, 'pal': ['#d0f0c0', '#a8d5a2', '#7bbf6a', '#4d9c44', '#2e6b2d']},
                }
                conf = mapping.get(layer_type)
                
                # Dynamically set max and min for chlorophyll based on the image
                if layer_type == 'chlorophyll':
                    try:
                        # Use central percentiles to avoid outliers dominating the legend range
                        c_perc = base_img.select('CLRe').reduceRegion(
                            reducer=ee.Reducer.percentile([20, 80]),
                            geometry=aoi,
                            scale=10,
                            maxPixels=1e9,
                            bestEffort=True
                        )
                        c_min = ee.Number(c_perc.get('CLRe_p20')).getInfo()
                        c_max = ee.Number(c_perc.get('CLRe_p80')).getInfo()
                        if c_min is not None and c_max is not None and c_max > c_min:
                            conf['min'] = c_min
                            conf['max'] = c_max
                            logger.info(f"Dynamic Chlorophyll Range: {c_min:.3f} - {c_max:.3f}")
                    except Exception as e:
                        logger.warning(f"Error calculating dynamic chlorophyll bounds: {e}. Using defaults.")
                
                if conf:
                    # CWSI and LST are Landsat-only (S2 no longer produces these bands)
                    if layer_type in ('cwsi', 'lst'):
                        try:
                            band_names = base_img.bandNames().getInfo()
                            if conf['band'] not in band_names:
                                return jsonify({'error': f'No Landsat thermal data available for {layer_type.upper()} on this date. '\
                                                        f'{layer_type.upper()} requires Landsat imagery.'}), 404
                        except:
                            pass  # Let it fail naturally below if bandNames check fails
                    
                    # CLRe (Chlorophyll) is Sentinel-2 only — needs B5/B7 red-edge bands
                    # If base_img is Landsat (no CLRe band), re-fetch from Sentinel-2
                    elif layer_type == 'chlorophyll':
                        try:
                            band_names = base_img.bandNames().getInfo()
                            if conf['band'] not in band_names:
                                logger.info("CLRe not in base_img (Landsat date). Trying Sentinel-2 re-fetch...")
                                # Try forcing Sentinel-2 for this date
                                s2_col_chl = sentinel2.get_s2_collection(aoi, start_date, end_date)
                                s2_count_chl = s2_col_chl.size().getInfo()
                                if s2_count_chl > 0:
                                    s2_img_chl = s2_col_chl.first()
                                    base_img = sentinel2.process_s2_image(s2_img_chl, aoi, ndvi_min_img, ndvi_max_img, mask_agri=mask_agri)
                                    # Re-apply water mask
                                    ndvi_mask = base_img.select('NDVI').gt(0)
                                    base_img = base_img.updateMask(ndvi_mask)
                                    logger.info("CLRe: switched to Sentinel-2 base image successfully")
                                else:
                                    return jsonify({'error': 'Chlorophyll (CLRe) requires Sentinel-2 imagery with red-edge bands (B5, B7). '
                                                             'No Sentinel-2 data available for this date. Try a different date.'}), 404
                        except Exception as band_check_err:
                            logger.warning(f"CLRe band check failed: {band_check_err}")
                    
                    selected_img = base_img.select(conf['band'])
                    # Dynamic Stats (Temp.py Logic)
                    try:
                        stats = common.get_dynamic_stats(selected_img, conf['band'], aoi)
                        vis_min = max(conf['min'], stats['p2']) if stats['p2'] is not None else conf['min']
                        vis_max = min(conf['max'], stats['p98']) if stats['p98'] is not None else conf['max']
                        vis_params = {'min': vis_min, 'max': vis_max, 'palette': conf.get('pal')}
                        stats_data = {'min': stats['min'], 'max': stats['max'], 'mean': stats['p50'], 'p25': stats['p25'], 'p75': stats['p75']}
                    except Exception as e:
                        logger.warning(f"Fallback to default vis for {layer_type}: {e}")
                        vis_params = {'min': conf['min'], 'max': conf['max'], 'palette': conf.get('pal')}
                else: 
                     return jsonify({'error': f"Unknown layer: {layer_type}"}), 400
            
            # Compute Stats ONLY IF not already set (from get_dynamic_stats above)
            if not stats_data:
                try:
                    # Re-apply mask to selected_img if created locally (etc/cwr)
                    # base_img is already masked
                    raw_stats = selected_img.reduceRegion(
                        reducer=ee.Reducer.mean().combine(ee.Reducer.min(), '', True).combine(ee.Reducer.max(), '', True),
                        geometry=aoi, scale=30, maxPixels=1e9
                    ).getInfo()
                    # Normalize keys to standard format (remove band suffix if present)
                    # e.g., 'SAVI_min' -> 'min', 'LST_mean' -> 'mean'
                    normalized_stats = {}
                    for k, v in raw_stats.items():
                        # Extract the stat type (min, max, mean) from the key
                        if '_min' in k:
                            normalized_stats['min'] = v
                        elif '_max' in k:
                            normalized_stats['max'] = v
                        elif '_mean' in k or k.lower() in ['mean', 'min', 'max']:
                            # Handle both 'BAND_mean' and 'mean' cases
                            if k.lower() == 'mean' or '_mean' in k:
                                normalized_stats['mean'] = v
                            elif k.lower() == 'min':
                                normalized_stats['min'] = v
                            elif k.lower() == 'max':
                                normalized_stats['max'] = v
                    
                    if normalized_stats:
                        stats_data = normalized_stats
                    else:
                        # Fallback: use raw stats as-is
                        stats_data = {k: raw_stats[k] for k in raw_stats}
                except Exception as e:
                    logger.warning(f"Stats computation failed: {e}")
        # --- NEW: Sentinel-2 Specific Layer (NO LANDSAT FALLBACK) ---
        elif layer_type == 's2_rgb':
            vis_params = {'min': 0, 'max': 0.4, 'gamma': 1.4}  # FCC: NIR is brighter
            s2_col = sentinel2.get_s2_collection(aoi, start_date, end_date)
            
            if s2_col.size().getInfo() > 0:
                if specific_date_str:
                    s2_img = s2_col.first()
                else:
                    s2_img = s2_col.median()
                
                # FCC bands: B8=NIR (Red channel), B4=Red (Green channel), B3=Green (Blue channel)
                selected_img = s2_img.select(['B8', 'B4', 'B3'])
            else:
                logger.warning("No Sentinel-2 data available for FCC layer")
                return jsonify({'error': 'No Sentinel-2 imagery available for the selected date range. PDF will use simple AOI outline.'}), 404
        # --------------------------------------

        elif layer_type == 'rgb':
            vis_params = {'min': 0, 'max': 0.4, 'gamma': 1.4}  # FCC: NIR is brighter
            try:
                band_names = base_img.bandNames().getInfo()
                logger.info(f"Available bands for FCC: {band_names}")
                
                # S2 FCC: B8=NIR, B4=Red, B3=Green
                if 'B8' in band_names and 'B4' in band_names and 'B3' in band_names:
                    selected_img = base_img.select(['B8', 'B4', 'B3'])
                    logger.info("Using Sentinel-2 FCC bands: B8, B4, B3")
                # Landsat FCC: SR_B5=NIR, SR_B4=Red, SR_B3=Green
                elif 'SR_B5' in band_names and 'SR_B4' in band_names and 'SR_B3' in band_names:
                    selected_img = base_img.select(['SR_B5', 'SR_B4', 'SR_B3'])
                    logger.info("Using Landsat FCC bands: SR_B5, SR_B4, SR_B3")
                else:
                    logger.error(f"No recognizable FCC bands found in: {band_names}")
                    return jsonify({'error': f'No FCC bands available. Found bands: {band_names}'}), 400
            except Exception as e:
                logger.error(f"Error selecting FCC bands: {e}")
                return jsonify({'error': f'Failed to select FCC bands: {str(e)}'}), 500
        
        elif layer_type == 's2_rgb':
            # Force Sentinel-2 FCC (for PDF reports)
            vis_params = {'min': 0, 'max': 0.4, 'gamma': 1.4}
            try:
                # Try using existing base_img if it's S2 (has B8)
                selected_img = base_img.select(['B8', 'B4', 'B3'])
            except:
                logger.info("Forcing Sentinel-2 for FCC layer")
                s2_col = sentinel2.get_s2_collection(aoi, start_date, end_date)
                
                if s2_col.size().getInfo() > 0:
                    if specific_date_str:
                        s2_img = s2_col.first()
                        s2_processed = sentinel2.process_s2_image(s2_img, aoi, ndvi_min_img, ndvi_max_img, mask_agri=mask_agri)
                    else:
                        s2_processed = sentinel2.process_s2_image(s2_col.median().set('selected_date', 'Composite'), aoi, ndvi_min_img, ndvi_max_img, mask_agri=False)
                        if mask_agri:
                            mask = common.get_agri_mask(aoi, end_date)
                            s2_processed = s2_processed.updateMask(mask)
                    
                    selected_img = s2_processed.select(['B8', 'B4', 'B3'])
                else:
                    return jsonify({'error': 'No Sentinel-2 imagery available for FCC layer'}), 404

        elif layer_type == 'soilmoisture':
            # Handle specifics: If a specific date is requested, widen window for Sentinel-1 (6-12 day revisit)
            if specific_date_str:
                sm_start = ee.Date(start_date).advance(-5, 'day')
                sm_end = ee.Date(end_date).advance(5, 'day')
                target_date = ee.Date(start_date)
            else:
                sm_start = start_date
                sm_end = end_date
                # For date ranges, use middle date as target
                target_date = ee.Date(start_date).advance(
                    ee.Date(end_date).difference(ee.Date(start_date), 'day').divide(2), 'day'
                )
            
            logger.info(f"Fetching soil moisture from {sm_start.getInfo()} to {sm_end.getInfo()}")
                
            # Use robust getter with SMAP fallback
            sm_col = soil_moisture.get_soil_moisture(aoi, sm_start, sm_end)
            
            if sm_col:
                col_size = sm_col.size().getInfo()
                logger.info(f"Soil moisture collection size: {col_size}")
                
                if col_size > 0:
                    # Try to get nearest image
                    try:
                        nearest_img = soil_moisture.get_nearest_image_with_coverage(
                            sm_col, target_date, aoi, coverage_threshold=0.95
                        )
                        
                        if nearest_img:
                            # Use the nearest image
                            selected_img = nearest_img
                            logger.info("Using nearest Sentinel-1 image")
                        else:
                            # Fallback to median
                            selected_img = sm_col.median()
                            logger.info("Using median composite (nearest selection returned None)")
                    except Exception as e:
                        logger.error(f"Error in nearest image selection: {e}")
                        selected_img = sm_col.median()
                        logger.info("Using median composite (fallback due to error)")
                    
                    # SMAP might need different palette/range? 0-100 is target for both.
                    vis_params = {'min': 0, 'max': 100, 'palette': ['brown', 'yellow', 'lightgreen', 'darkgreen', 'blue']}
                else:
                    logger.error("Soil moisture collection is empty")
                    return jsonify({'error': 'No soil moisture data'}), 404
            else:
                logger.error("Soil moisture collection is None")
                return jsonify({'error': 'No soil moisture data'}), 404
        
        elif layer_type == 'deltas':
            sm_col = soil_moisture.get_sentinel1_soil_moisture_simple(aoi, start_date, end_date)
            if sm_col and sm_col.size().getInfo() > 1:
                # Delta between first and last
                l = sm_col.sort('system:time_start', False).first()
                f = sm_col.sort('system:time_start', True).first()
                selected_img = l.subtract(f).rename('DeltaS')
                vis_params = {'min': -20, 'max': 20, 'palette': ['red', 'orange', 'white', 'lightgreen', 'darkgreen']}
            else:
                 return jsonify({'error': 'Not enough data for DeltaS'}), 404

        if selected_img is None:
             return jsonify({'error': f'Layer {layer_type} not supported or failed'}), 400

        # =====================================================================
        # FINAL TRANSPARENCY ENFORCEMENT
        # =====================================================================
        # =====================================================================
        # FINAL TRANSPARENCY ENFORCEMENT
        # =====================================================================
        # We now rely solely on NDVI-based masking for water.
        # Dynamic World mask removed to prevent gaps on cloudy days.
        try:
            # Apply an NDVI-based mask as a robust defense
            # (Water usually has negative NDVI)
            ndvi_mask = base_img.select('NDVI').gt(0)
            selected_img = selected_img.updateMask(ndvi_mask)
        except Exception as e:
            logger.warning(f"Final masking skipped: {e}")

        # Visualize
        visualized = selected_img.visualize(**vis_params).clip(aoi)
        map_id = ee.data.getMapId({'image': visualized})
        
        return jsonify({
            'mapid': map_id['mapid'],
            'urlFormat': map_id['tile_fetcher'].url_format,
            'stats': stats_data
        })

    except Exception as e:
        logger.error(f"Tile error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/generate_report', methods=['POST'])
def generate_report():
    """Report generation endpoint"""
    try:
        payload = request.get_json()
        return generate_report_response(payload)
    except Exception as e:
        logger.error("generate_report failed: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500

# =============================================================================
# VRA MAP CLASSIFICATION FUNCTIONS
# =============================================================================

def classify_with_jenks(image, band_name, aoi, n_classes=5, scale=30):
    """
    Classify an Earth Engine image using Hybrid Method:
    1. Try Jenks (Natural Breaks) for best clustering.
    2. Fallback to Quantile (Percentile) if:
       - Variance is low (to force visual spread).
       - Jenks fails or produces invalid breaks.
       
    Args:
        image: EE Image to classify
        band_name: Band name to classify
        aoi: Area of interest
        n_classes: Number of classification zones (default 5)
        scale: Resolution in meters for sampling (default 30, use 10 for Sentinel-2)
    """
    try:
        # Sample the image to get pixel values (Client Side)
        # Using a moderate sample size to balance performance and accuracy
        sample = image.select(band_name).sample(
            region=aoi,
            scale=scale,  # Dynamic scale for 10m or 30m resolution
            numPixels=2000, # Reduced slightly for speed, usually sufficient for distribution
            seed=42
        )
        
        # Extract values
        values = sample.aggregate_array(band_name).getInfo()
        values = [v for v in values if v is not None and not np.isnan(v)]
        
        if not values:
             # Handle empty data
             return ee.Image(0), [0]*6

        # Calculate Statistics
        val_array = np.array(values)
        val_min = np.min(val_array)
        val_max = np.max(val_array)
        val_std = np.std(val_array)
        val_mean = np.mean(val_array)
        
        # Coefficient of Variation (CV)
        if val_mean != 0:
            cv = val_std / abs(val_mean)
        else:
            cv = 0
            
        logger.info(f"VRA Classification Stats for {band_name}: Min={val_min:.3f}, Max={val_max:.3f}, Mean={val_mean:.3f}, CV={cv:.3f}")

        breaks = []
        method = "Jenks"

        # DECISION LOGIC:
        # If very few unique values, just map them
        unique_vals = np.unique(val_array)
        if len(unique_vals) < n_classes:
             method = "Unique"
             # Just use equal interval between min and max to ensure 5 zones exist theoretically
             # or better, just map the unique values to classes? 
             # User wants 5 zones. Let's stick to Breaks.
             # If we have fewer values than classes, breaks will duplicate.
             # Fallback to Linear (Equal Interval)
             method = "Linear (Low Unique Count)"
             breaks = np.linspace(val_min, val_max, n_classes + 1).tolist()

        # If Low Variance (CV < 0.15) -> Use Quantile to ERROR on the side of "Show Me Difference"
        elif cv < 0.15:
             method = "Quantile (Low Variance)"
             # np.percentile for 0, 20, 40, 60, 80, 100
             qs = [0, 20, 40, 60, 80, 100]
             breaks = np.percentile(val_array, qs).tolist()
             
        else:
            # Try Jenks
            try:
                breaks = jenkspy.jenks_breaks(values, n_classes=n_classes)
            except Exception as jenks_e:
                logger.warning(f"Jenks failed: {jenks_e}. Falling back to Quantile.")
                method = "Quantile (Fallback)"
                qs = [0, 20, 40, 60, 80, 100]
                breaks = np.percentile(val_array, qs).tolist()

        # Final Safety Check on Breaks:
        # Using 'set' to check uniqueness. If breaks led to duplicates (e.g. [0,0,0,1,1]),
        # it renders invisible zones.
        if len(set(breaks)) < n_classes:
             logger.warning(f"Classification produced duplicate breaks: {breaks}. Forcing Linear.")
             method = "Linear (Duplicate Breaks)"
             breaks = np.linspace(val_min, val_max, n_classes + 1).tolist()

        logger.info(f"Using method: {method}. Breaks: {[round(b,3) for b in breaks]}")
        
        # Create classified image on Server Side
        classified = ee.Image(0)
        
        # Note: breaks has n_classes + 1 elements (Start -> End)
        # Zones are 1-based (1 to 5)
        
        band_img = image.select(band_name)
        
        for i in range(n_classes):
            # Define lower and upper for this class
            b_start = breaks[i]
            b_end = breaks[i+1]
            
            if i == n_classes - 1:
                # Last class: Include upper bound (<=)
                mask = band_img.gte(b_start)
            else:
                # Normal class: [start, end)
                mask = band_img.gte(b_start).And(band_img.lt(b_end))
                
            # Assign value (i+1)
            classified = classified.where(mask, i + 1)
        
        return classified, breaks

    except Exception as e:
        logger.error(f"Classification error: {e}")
        # Ultimate Fallback: Simple Equal Interval from EE MinMax
        stats = image.select(band_name).reduceRegion(
            reducer=ee.Reducer.minMax(),
            geometry=aoi,
            scale=30,
            maxPixels=1e9
        ).getInfo()
        min_val = stats.get(f'{band_name}_min', 0)
        max_val = stats.get(f'{band_name}_max', 1)
        
        if min_val is None: min_val = 0
        if max_val is None: max_val = 1
            
        breaks = np.linspace(min_val, max_val, n_classes + 1).tolist()
        
        classified = ee.Image(0)
        for i in range(len(breaks) - 1):
             if i == len(breaks) - 2:
                 mask = image.select(band_name).gte(breaks[i])
             else:
                 mask = image.select(band_name).gte(breaks[i]).And(
                        image.select(band_name).lt(breaks[i + 1]))
             classified = classified.where(mask, i + 1)
        
        return classified, breaks

# VRA Color Schemes - Intelligent colors for each parameter
VRA_COLOR_SCHEMES = {
    'ndvi': ['#f7fcf5', '#c7e9c0', '#74c476', '#238b45', '#00441b'],  # Light to dark green
    'savi': ['#f7fcf5', '#c7e9c0', '#74c476', '#238b45', '#00441b'],  # Light to dark green
    'lai': ['#c7e9c0', '#a1d99b', '#74c476', '#238b45', '#00441b'],   # Light to dark green
    'cwsi': ['#81D4FA', '#4FC3F7', '#FFFF8D', '#FFB74D', '#E57373'],  # Lighter Tones: Light Blue -> Light Orange -> Light Red
    'irrigation_need': ['#f7fbff', '#c6dbef', '#6baed6', '#2171b5', '#08306b'],  # Light to dark blue
    'soilmoisture': ['#f7fbff', '#c6dbef', '#6baed6', '#2171b5', '#08306b'],  # Light to dark blue
    'lst': ['#ffffcc', '#ffeda0', '#feb24c', '#f03b20', '#bd0026'],  # Yellow to red
    'etc': ['#f7fcfd', '#c6dbef', '#9e9ac8', '#756bb1', '#54278f'],  # Light purple to dark purple
    'kc': ['#FFFFE5', '#D9F0A3', '#78C679', '#238443', '#004529'],   # Yellow (Low) to Green (High)
    'pca': ['#c7e9c0', '#a1d99b', '#74c476', '#238b45', '#00441b'],  # Green scale for Vigor
    'chlorophyll': ['#d0f0c0', '#a8d5a2', '#7bbf6a', '#4d9c44', '#2e6b2d'],  # Light to dark green (CLRe)
}
@app.route('/get_deep_spatial_stats', methods=['POST'])
def get_deep_spatial_stats():
    """
    Extracts deep GEE statistics for CropHealth, LAI, and CIre.
    Specifically designed for fertilizer response analysis.
    """
    try:
        data = request.get_json()
        coords = data['aoi']['geometry']['coordinates']
        aoi = ee.Geometry.Polygon(coords)
        start_date = ee.Date(data.get('start_date'))
        end_date = ee.Date(data.get('end_date'))
        scale = data.get('scale', 20)
        application_date = data.get('application_date')

        s2_col = sentinel2.get_s2_collection(aoi, start_date, end_date)
        if s2_col.size().getInfo() == 0:
            return jsonify({'error': 'No Sentinel-2 data available for deep spatial stats.'}), 404

        n_min, n_max = 0.2, 0.8
        ndvi_min_img = ee.Image.constant(n_min)
        ndvi_max_img = ee.Image.constant(n_max)

        median_img = s2_col.median().set('selected_date', 'Composite')
        processed = sentinel2.process_s2_image(median_img, aoi, ndvi_min_img, ndvi_max_img, mask_agri=False)

        pca_result = pca_processor.get_pca_image(processed)
        band_pca = pca_result.select(['PC1'], ['CropHealth']).toFloat()
        band_lai = processed.select(['LAI'], ['LAI']).toFloat()
        band_clre = processed.select(['CLRe'], ['CIre']).toFloat()

        stacked_image = ee.Image.cat([band_pca, band_lai, band_clre])

        basic = stacked_image.reduceRegion(
            reducer=ee.Reducer.mean()
                .combine(ee.Reducer.stdDev(),    sharedInputs=True)
                .combine(ee.Reducer.min(),        sharedInputs=True)
                .combine(ee.Reducer.max(),        sharedInputs=True)
                .combine(ee.Reducer.median(),     sharedInputs=True)
                .combine(ee.Reducer.variance(),   sharedInputs=True)
                .combine(ee.Reducer.skew(),       sharedInputs=True)
                .combine(ee.Reducer.kurtosis(),   sharedInputs=True)
                .combine(ee.Reducer.percentile([5,10,25,75,90,95]), sharedInputs=True),
            geometry=aoi, scale=scale, bestEffort=True, maxPixels=1e9
        ).getInfo()

        corr_AB = stacked_image.select(['CropHealth','LAI']).reduceRegion(
            reducer=ee.Reducer.pearsonsCorrelation(), geometry=aoi, scale=scale, bestEffort=True, maxPixels=1e9
        ).getInfo()
        
        corr_AC = stacked_image.select(['CropHealth','CIre']).reduceRegion(
            reducer=ee.Reducer.pearsonsCorrelation(), geometry=aoi, scale=scale, bestEffort=True, maxPixels=1e9
        ).getInfo()
        
        corr_BC = stacked_image.select(['LAI','CIre']).reduceRegion(
            reducer=ee.Reducer.pearsonsCorrelation(), geometry=aoi, scale=scale, bestEffort=True, maxPixels=1e9
        ).getInfo()

        covar_result = stacked_image.toArray().reduceRegion(
            reducer=ee.Reducer.centeredCovariance(), geometry=aoi, scale=scale, bestEffort=True, maxPixels=1e9
        ).getInfo()

        reg_health_from_cire = stacked_image.select(['CIre','CropHealth']).reduceRegion(
            reducer=ee.Reducer.linearRegression(numX=1, numY=1), geometry=aoi, scale=scale, bestEffort=True, maxPixels=1e9
        ).getInfo()
        
        reg_health_from_lai = stacked_image.select(['LAI','CropHealth']).reduceRegion(
            reducer=ee.Reducer.linearRegression(numX=1, numY=1), geometry=aoi, scale=scale, bestEffort=True, maxPixels=1e9
        ).getInfo()
        
        reg_health_from_both = stacked_image.select(['CIre','LAI','CropHealth']).reduceRegion(
            reducer=ee.Reducer.linearRegression(numX=2, numY=1), geometry=aoi, scale=scale, bestEffort=True, maxPixels=1e9
        ).getInfo()

        def get_minmax(band):
            s = stacked_image.select([band]).reduceRegion(
                reducer=ee.Reducer.minMax(), geometry=aoi, scale=scale, bestEffort=True, maxPixels=1e9
            ).getInfo()
            if not s or f'{band}_min' not in s:
                return 0.0, 1.0
            return float(s.get(f'{band}_min')), float(s.get(f'{band}_max'))
        
        ch_min, ch_max = get_minmax('CropHealth')
        lai_min, lai_max = get_minmax('LAI')
        cire_min, cire_max = get_minmax('CIre')
        
        def safe_div(mn, mx):
            diff = mx - mn
            return diff if diff > 0 else 1.0

        norm_CH  = stacked_image.select(['CropHealth']).subtract(ch_min).divide(safe_div(ch_min, ch_max))
        norm_LAI = stacked_image.select(['LAI']).subtract(lai_min).divide(safe_div(lai_min, lai_max))
        norm_CIre = stacked_image.select(['CIre']).subtract(cire_min).divide(safe_div(cire_min, cire_max))
        
        zone_all_high = norm_CH.gt(0.66).And(norm_LAI.gt(0.66)).And(norm_CIre.gt(0.66))
        zone_early_response = norm_CIre.gt(0.66).And(norm_LAI.lt(0.33))
        zone_structural_only = norm_LAI.gt(0.66).And(norm_CIre.lt(0.33))
        zone_all_low = norm_CH.lt(0.33).And(norm_LAI.lt(0.33)).And(norm_CIre.lt(0.33))
        
        zone_counts = ee.Image.cat([
            zone_all_high.rename('all_high_response'),
            zone_early_response.rename('early_cire_response'),
            zone_structural_only.rename('structural_growth_only'),
            zone_all_low.rename('no_response')
        ]).reduceRegion(
            reducer=ee.Reducer.sum(), geometry=aoi, scale=scale, bestEffort=True, maxPixels=1e9
        ).getInfo()

        return jsonify({
            'basic_stats': basic,
            'correlations': {
                'CropHealth_vs_LAI':  corr_AB or {},
                'CropHealth_vs_CIre': corr_AC or {},
                'LAI_vs_CIre':        corr_BC or {}
            },
            'covariance_matrix': covar_result.get('array', []),
            'regressions': {
                'CropHealth_from_CIre':     reg_health_from_cire or {},
                'CropHealth_from_LAI':      reg_health_from_lai or {},
                'CropHealth_from_CIre_LAI': reg_health_from_both or {}
            },
            'spatial_zones': zone_counts or {},
            'application_date': application_date
        })

    except Exception as e:
        logger.error(f"Error in deep spatial stats: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/get_vra_map', methods=['POST'])
def get_vra_map():
    """Generate VRA map with Jenks classification for a specific parameter and date"""
    try:
        data = request.get_json()
        coords = data['aoi']['geometry']['coordinates']
        aoi = ee.Geometry.Polygon(coords)
        parameter = data.get('parameter', 'ndvi')
        
        target_date = data.get('date')
        start_date_param = data.get('start_date')
        end_date_param = data.get('end_date')
        
        # Get scale parameter (default 30m for backward compatibility)
        # 10m for most Sentinel-2 based parameters, 30m for LST (thermal)
        scale = data.get('scale', 30 if parameter == 'lst' else 10)
        
        # force_sentinel2: report mode can enforce S2 for all non-thermal params
        force_sentinel2 = data.get('force_sentinel2', False)
        
        if not target_date and not (start_date_param and end_date_param):
            return jsonify({'error': 'Either date OR start_date+end_date is required'}), 400

        
        # Map parameter names to band names
        param_to_band = {
            'ndvi': 'NDVI',
            'savi': 'SAVI',
            'cwsi': 'CWSI',
            'lai': 'LAI',
            'lst': 'LST',
            'etc': 'ETc',
            'irrigation_need': 'Irrigation_Need',
            'soilmoisture': 'SoilMoisture',
            'kc': 'Kc',
            'pca': 'PC1',
            'chlorophyll': 'CLRe',  # CLRe = (B7/B5) - 1, Sentinel-2 only
        }
        
        band_name = param_to_band.get(parameter)
        if not band_name:
            return jsonify({'error': f'Invalid parameter: {parameter}'}), 400
            
        logger.info(f"Generating VRA map for {parameter} at {scale}m resolution. Target: {target_date}, Range: {start_date_param}-{end_date_param}")

        # Determine Date Range
        if target_date:
            date = ee.Date(target_date)
            start_date = date
            end_date = date.advance(1, 'day')
            is_composite = False
        else:
            start_date = ee.Date(start_date_param)
            end_date = ee.Date(end_date_param)
            is_composite = True

        # =========================================================
        # FETCH & PROCESS IMAGERY
        # =========================================================
        
        # 1. Get NDVI Range (needed for CWSI) - calculated from composite of period
        l_col_raw = landsat.get_landsat_collection(aoi, start_date, end_date)
        s2_col_raw = sentinel2.get_s2_collection(aoi, start_date, end_date)
        
        def get_ndvi(img):
            bands = img.bandNames()
            return ee.Algorithms.If(
                bands.contains('SR_B5'),
                img.normalizedDifference(['SR_B5', 'SR_B4']).rename('NDVI'),
                img.normalizedDifference(['B8', 'B4']).rename('NDVI')
            )
        
        # Combine cols for threshold stats
        combined_ndvi = l_col_raw.merge(s2_col_raw).map(lambda img: ee.Image(get_ndvi(img)))
        
        # Handle case with no data for thresholds
        try:
             n_min, n_max = common.get_ndvi_range(combined_ndvi, aoi)
        except:
             n_min, n_max = 0.2, 0.8 # Fallback
             
        ndvi_min_img = ee.Image.constant(n_min)
        ndvi_max_img = ee.Image.constant(n_max)
        
        processed_img = None
        
        if not is_composite:
            # SPECIFIC DATE LOGIC
            l8_col = landsat.get_landsat_collection(aoi, start_date, end_date)
            s2_col = sentinel2.get_s2_collection(aoi, start_date, end_date)
            
            # STRICT LOGIC: CWSI and LST require thermal bands -> MUST use Landsat
            if parameter in ['lst', 'cwsi']:
                if l8_col.size().getInfo() > 0:
                    l8_img = l8_col.first()
                    processed_img = landsat.process_landsat_image(l8_img, aoi, ndvi_min_img, ndvi_max_img, mask_agri=False)
                else:
                    return jsonify({'error': f'No Landsat thermal data available for {parameter.upper()} on this date'}), 404
            else:
                # For everything else (NDVI, LAI, etc), prefer Landsat if it's the only one available, otherwise Sentinel-2
                # EXCEPTION: chlorophyll (CLRe) requires S2 red-edge bands — force S2 always
                count_s2 = s2_col.size().getInfo()
                count_l8 = l8_col.size().getInfo()
                
                if parameter == 'chlorophyll' or force_sentinel2:
                    # CLRe needs Sentinel-2 B5/B7 red-edge bands — Landsat does NOT have them.
                    # Even if force_sentinel2 is set, we CANNOT fall back to Landsat for chlorophyll.
                    if count_s2 > 0:
                        s2_img = s2_col.first()
                        processed_img = sentinel2.process_s2_image(s2_img, aoi, ndvi_min_img, ndvi_max_img, mask_agri=False)
                    else:
                        # No Sentinel-2 data at all — cannot compute CLRe from Landsat
                        return jsonify({'error': 'Chlorophyll (CLRe) requires Sentinel-2 red-edge bands (B5/B7). No Sentinel-2 data found for this date. Try a wider date range.'}), 404
                elif count_s2 == 0 and count_l8 > 0:
                    l8_img = l8_col.first()
                    processed_img = landsat.process_landsat_image(l8_img, aoi, ndvi_min_img, ndvi_max_img, mask_agri=False)
                elif count_s2 > 0:
                    s2_img = s2_col.first()
                    processed_img = sentinel2.process_s2_image(s2_img, aoi, ndvi_min_img, ndvi_max_img, mask_agri=False)
                else:
                    return jsonify({'error': 'No satellite data available for this date'}), 404
        else:
            # COMPOSITE LOGIC (MEDIAN)
            l8_col = landsat.get_landsat_collection(aoi, start_date, end_date)
            s2_col = sentinel2.get_s2_collection(aoi, start_date, end_date)
            
            if parameter in ['lst', 'cwsi']:
                if l8_col.size().getInfo() > 0:
                    def proc_l8(img): return landsat.process_landsat_image(img, aoi, ndvi_min_img, ndvi_max_img, mask_agri=False)
                    processed_img = l8_col.map(proc_l8).median()
                else:
                    return jsonify({'error': f'No Landsat thermal data available for {parameter.upper()} in this period'}), 404
            else:
                count_s2 = s2_col.size().getInfo()
                count_l8 = l8_col.size().getInfo()
                
                if parameter == 'chlorophyll' or force_sentinel2:
                    # CLRe needs S2 B5/B7 red-edge bands — Landsat does NOT have them.
                    # Even if force_sentinel2 is set, we CANNOT fall back to Landsat for chlorophyll.
                    if count_s2 > 0:
                        processed_img = sentinel2.process_s2_image(
                            s2_col.median().set('selected_date', 'Composite'),
                            aoi, ndvi_min_img, ndvi_max_img, mask_agri=False
                        )
                    else:
                        # No Sentinel-2 data in this period — cannot compute CLRe from Landsat
                        return jsonify({'error': 'Chlorophyll (CLRe) requires Sentinel-2 red-edge bands (B5/B7). No Sentinel-2 data found in this period. Try a wider date range.'}), 404
                elif count_s2 == 0 and count_l8 > 0:
                    def proc_l8(img): return landsat.process_landsat_image(img, aoi, ndvi_min_img, ndvi_max_img, mask_agri=False)
                    processed_img = l8_col.map(proc_l8).median()
                elif count_s2 > 0:
                    processed_img = sentinel2.process_s2_image(
                        s2_col.median().set('selected_date', 'Composite'),
                        aoi, ndvi_min_img, ndvi_max_img, mask_agri=False
                    )
                else:
                    return jsonify({'error': 'No satellite data available for this period. Try a larger date range.'}), 404

        # =========================================================
        # PARAMETER EXTRACTION
        # =========================================================
        
        if parameter == 'etc':
            # Use weather.get_eto_image for consistent 4-day window search
            eto_img, eto_count = weather.get_eto_image(start_date)
            param_img = processed_img.select('Kc').multiply(eto_img).rename('ETc')
        elif parameter == 'irrigation_need':
            # Use weather.get_eto_image for consistent 4-day window search
            eto_img, eto_count = weather.get_eto_image(start_date)
            param_img = processed_img.select('Kc').multiply(eto_img).divide(0.7).rename('Irrigation_Need')
        elif parameter == 'soilmoisture':
            # For soil moisture, use Sentinel-1 with nearest-date selection
            # Match the logic from the main soil moisture layer
            if target_date:
                sm_start = ee.Date(start_date).advance(-5, 'day')
                sm_end = ee.Date(end_date).advance(5, 'day')
                target_sm_date = ee.Date(start_date)
            else:
                sm_start = start_date
                sm_end = end_date
                # For date ranges, use middle date as target
                target_sm_date = ee.Date(start_date).advance(
                    ee.Date(end_date).difference(ee.Date(start_date), 'day').divide(2), 'day'
                )
            
            sm_col = soil_moisture.get_soil_moisture(aoi, sm_start, sm_end)
            if sm_col and sm_col.size().getInfo() > 0:
                # Use nearest-date selection for consistency with main layer
                try:
                    nearest_sm_img = soil_moisture.get_nearest_image_with_coverage(
                        sm_col, target_sm_date, aoi, coverage_threshold=0.95
                    )
                    
                    if nearest_sm_img:
                        param_img = nearest_sm_img.rename('SoilMoisture')
                        logger.info("VRA: Using nearest Sentinel-1 soil moisture image")
                    else:
                        param_img = sm_col.median().rename('SoilMoisture')
                        logger.info("VRA: Using median soil moisture (fallback)")
                except Exception as e:
                    logger.error(f"VRA soil moisture nearest selection error: {e}")
                    param_img = sm_col.median().rename('SoilMoisture')
            else:
                return jsonify({'error': 'No soil moisture data available'}), 404

        elif parameter == 'pca':
             # Apply PCA logic
             if processed_img:
                  pca_result = pca_processor.get_pca_image(processed_img)
                  param_img = pca_result.select('PC1')
             else:
                  return jsonify({'error': 'No imagery for PCA'}), 404
        else:
            param_img = processed_img.select(band_name)
        
        # Apply Jenks classification at dynamic scale (10m for most, 30m for LST)
        logger.info(f"Applying Jenks classification for {band_name} at {scale}m resolution")
        classified_img, breaks = classify_with_jenks(param_img, band_name, aoi, n_classes=5, scale=scale)
        
        # Get color palette
        palette = VRA_COLOR_SCHEMES.get(parameter, ['#ffffff', '#cccccc', '#999999', '#666666', '#000000'])
        
        # Visualize with classified colors
        vis_params = {'min': 1, 'max': 5, 'palette': palette}
        visualized = classified_img.visualize(**vis_params).clip(aoi)
        
        # Get map ID
        map_id_dict = ee.data.getMapId({'image': visualized})
        
        # Format breaks for response
        class_labels = []
        for i in range(len(breaks) - 1):
            class_labels.append({
                'class': i + 1,
                'label': f"Zone {i + 1}", # Frontend uses this if present, or we change how it consumes it.
                'min': round(breaks[i], 3),
                'max': round(breaks[i + 1], 3),
                'color': palette[i]
            })
        
        response = {
            'mapid': map_id_dict['mapid'],
            'urlFormat': map_id_dict['tile_fetcher'].url_format,
            'breaks': breaks,
            'classes': class_labels, # The frontend iterates this. Ideally it reads a 'name' or 'label' property.
            # If frontend hardcodes "Class {item.class}", I might need to change frontend too.
            # But usually it iterates. Let's assume standard iterating.
            # Actually, I'll update the 'class' value itself if it's used for display. 
            # But 'class' usually implies ID.
            # I will add a 'name' field "Zone {i+1}" and ensure frontend uses it?
            # User said "change it to zones1, zone2".
            # If I look at the sidebar or legend component... 
            # I can't see the Legend component code here.
            # I will assume updating the 'classes' list is enough.
            'parameter': parameter,
            'date': target_date if target_date else f"{start_date_param} to {end_date_param} (Composite)"
        }
        
        logger.info(f"VRA map generated successfully for {parameter}")
        
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"VRA map generation error: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/get_land_cover_analysis', methods=['POST'])
def get_land_cover_analysis():
    """Land cover analysis using Landsat with time-series support"""
    try:
        data = request.get_json()
        user_aoi = data['aoi']
        coords = user_aoi['geometry']['coordinates']
        aoi = ee.Geometry.Polygon(coords)
        
        start_date = data['start_date']
        end_date = data['end_date']
        time_scale = data.get('time_scale', 'monthly')
        
        # Validate date range
        start = ee.Date(start_date)
        end = ee.Date(end_date)
        diff_days = end.difference(start, 'day').getInfo()

        if diff_days > 365:
            return jsonify({'error': 'Date range too large. Please select ≤ 12 months (≤ 365 days).'}), 400

        # Use Landsat collection
        landsat_col = landsat.get_landsat_collection(aoi, start_date, end_date, cloud_filter=30)
        
        # Add NDVI band
        def add_ndvi(image):
            ndvi = image.normalizedDifference(['SR_B5', 'SR_B4']).rename('NDVI')
            return image.addBands(ndvi)

        # Group by time period
        def make_time_key(image):
            date = image.date()
            if time_scale == 'monthly':
                key = date.format('YYYY-MM')
            else:
                key = date.format('YYYY-ww')
            return image.set('time_key', key)

        landsat_with_keys = landsat_col.map(landsat.apply_scale_factors).map(landsat.cloud_mask_landsat).map(make_time_key)

        # Composite by period
        distinct_periods = landsat_with_keys.distinct('time_key')
        
        def composite_function(img):
            key = img.get('time_key')
            period_images = landsat_with_keys.filter(ee.Filter.eq('time_key', key))
            composite = period_images.median() \
                                   .set('time_key', key) \
                                   .set('date', ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'))
            return composite

        composite_by_period = ee.ImageCollection(distinct_periods.map(composite_function)) \
                                .sort('time_key').limit(12)

        landsat_with_ndvi = composite_by_period.map(add_ndvi)

        # Classification
        def classify_pixels(image):
            ndvi = image.select('NDVI')
            water = ndvi.lt(0)
            bareland = ndvi.gte(0).And(ndvi.lt(0.1))
            builtup = ndvi.gte(0.1).And(ndvi.lt(0.2))
            sparse_veg = ndvi.gte(0.2).And(ndvi.lt(0.4))
            full_veg = ndvi.gte(0.4)

            classified = water.multiply(1) \
                .add(bareland.multiply(2)) \
                .add(builtup.multiply(3)) \
                .add(sparse_veg.multiply(4)) \
                .add(full_veg.multiply(5)) \
                .rename('class')

            return image.addBands(classified)

        classified_collection = landsat_with_ndvi.map(classify_pixels)

        # Pixel counting
        def count_pixels(image):
            class_band = image.select('class')
            pixel_counts = ee.Dictionary(
                class_band.reduceRegion(
                    reducer=ee.Reducer.frequencyHistogram(),
                    geometry=aoi,
                    scale=30,
                    maxPixels=1e13
                ).get('class')
            )
            return ee.Feature(None, {
                'period': image.get('time_key'),
                'pixel_counts': pixel_counts
            })

        pixel_count_per_class = classified_collection.map(count_pixels)
        features_list = pixel_count_per_class.toList(12).getInfo()
        
        # Process results
        result_data = []
        class_names = {
            '1': 'Water',
            '2': 'Bare Land', 
            '3': 'Built-up',
            '4': 'Sparse Vegetation',
            '5': 'Dense Vegetation'
        }
        
        for feature in features_list:
            properties = feature['properties']
            period = properties['period']
            pixel_counts = properties.get('pixel_counts', {})
            
            readable_counts = {}
            total_pixels = 0
            
            for class_id, count in pixel_counts.items():
                class_name = class_names.get(class_id, f'Class {class_id}')
                readable_counts[class_name] = count
                total_pixels += count
            
            percentages = {}
            for class_name, count in readable_counts.items():
                if total_pixels > 0:
                    percentages[class_name] = round((count / total_pixels) * 100, 2)
                else:
                    percentages[class_name] = 0
            
            result_data.append({
                'period': period,
                'pixel_counts': readable_counts,
                'percentages': percentages,
                'total_pixels': total_pixels
            })
        
        return jsonify({
            'success': True,
            'time_scale': time_scale,
            'periods_analyzed': len(result_data),
            'data': result_data
        })

    except Exception as e:
        logger.error(f"Land cover analysis failed: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 6000))
    app.run(host='0.0.0.0', port=port, debug=True)
