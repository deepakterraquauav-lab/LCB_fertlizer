# from flask import Flask, render_template, request, jsonify, session, send_file
# import ee
# import json
# import os
# import rasterio
# from rasterio.mask import mask
# from datetime import timedelta

# # Initialize Earth Engine
# ee.Initialize(project="ee-sambiitk-imageprocessing")

# app = Flask(__name__)
# app.secret_key = 'your-secret-key'  # For session handling
# app.permanent_session_lifetime = timedelta(days=7)

# @app.route('/')
# def index():
#     return render_template('index.html')


# # -------- Existing: Get Daily Data --------
# @app.route('/get_daily_data', methods=['POST'])
# def get_daily_data():
#     try:
#         data = request.get_json()
#         user_aoi = data['aoi']
#         coords = user_aoi['geometry']['coordinates']
#         aoi = ee.Geometry.Polygon(coords)

#         start_date = data['start_date']
#         end_date = data['end_date']

#         days = ee.List.sequence(0, ee.Date(end_date).difference(ee.Date(start_date), 'day').subtract(1))
#         date_list = days.map(lambda d: ee.Date(start_date).advance(d, 'day'))

#         def compute_daily(date):
#             date = ee.Date(date)
#             next_date = date.advance(1, 'day')
#             prev_date = date.advance(-1, 'day')

#             s2 = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED") \
#                 .filterBounds(aoi) \
#                 .filterDate(date, next_date) \
#                 .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 40))

#             s2size = s2.size()

#             def compute_if_available(_):
#                 s2_median = s2.median()
#                 ndvi = s2_median.normalizedDifference(['B8', 'B4']).rename('NDVI')
#                 kc = ndvi.multiply(1.25).subtract(0.2).clamp(0, 1.2).rename('Kc')

#                 eto = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR') \
#                     .filterDate(date, next_date) \
#                     .select('potential_evaporation_sum') \
#                     .mean().multiply(1000).rename('ETo')

#                 rain = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY") \
#                     .filterDate(date, next_date).sum().rename('Rain')
#                 effRain = rain.multiply(0.8).rename('EffRain')

#                 sm_today = ee.ImageCollection("NASA/SMAP/SPL3SMP_E/006") \
#                     .filterDate(date, next_date) \
#                     .select('soil_moisture_am').mean().rename('SoilMoisture')
#                 sm_prev = ee.ImageCollection("NASA/SMAP/SPL3SMP_E/006") \
#                     .filterDate(prev_date, date) \
#                     .select('soil_moisture_am').mean().rename('SoilMoisturePrev')
#                 deltaS = sm_today.subtract(sm_prev).multiply(200).rename('DeltaS')

#                 etc = kc.multiply(eto).rename('ETc')
#                 iwr = etc.subtract(effRain).subtract(deltaS).max(0).rename('IWR')

#                 all = ee.Image.cat([ndvi, kc, eto, effRain, deltaS, etc, iwr])

#                 stats = all.reduceRegion(
#                     reducer=ee.Reducer.mean(),
#                     geometry=aoi,
#                     scale=10,
#                     maxPixels=1e13
#                 )

#                 return ee.Feature(None, stats).set('date', date.format('YYYY-MM-dd'))

#             return ee.Algorithms.If(s2size.gt(0), compute_if_available(None), None)

#         daily_data = ee.FeatureCollection(date_list.map(compute_daily))
#         raw = daily_data.getInfo()['features']
#         result = [{k.lower(): v for k, v in f['properties'].items()} for f in raw if f]
#         return jsonify(result)

#     except Exception as e:
#         return jsonify({'error': str(e)})


# # -------- New: GEE Raster Tile Layer --------
# @app.route('/get_gee_tile', methods=['POST'])
# def get_gee_tile():
#     try:
#         data = request.get_json()
#         coords = data['aoi']['geometry']['coordinates']
#         aoi = ee.Geometry.Polygon(coords)
#         layer_type = data.get("layer", "ndvi")

#         if layer_type == "ndvi":
#             image = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED") \
#                 .filterBounds(aoi).median() \
#                 .normalizedDifference(['B8', 'B4']).rename('NDVI') \
#                 .visualize(min=0, max=1, palette=['white', 'green'])
#         elif layer_type == "etc":
#             image = ee.Image("YOUR_ETC_LAYER").clip(aoi).visualize(min=0, max=10, palette=['white', 'blue'])
#         elif layer_type == "iwr":
#             image = ee.Image("YOUR_IWR_LAYER").clip(aoi).visualize(min=0, max=20, palette=['white', 'red'])
#         else:
#             return jsonify({"error": "Invalid layer type"}), 400

#         map_id = ee.data.getMapId(image)
#         return jsonify(map_id)

#     except Exception as e:
#         return jsonify({'error': str(e)})


# # -------- New: Upload and Clip GeoTIFF --------
# @app.route('/upload_geotiff', methods=['POST'])
# def upload_geotiff():
#     try:
#         file = request.files['file']
#         geojson = json.loads(request.form['aoi'])

#         with rasterio.open(file) as src:
#             out_image, out_transform = mask(src, geojson['features'], crop=True)
#             out_meta = src.meta.copy()
#             out_meta.update({
#                 "height": out_image.shape[1],
#                 "width": out_image.shape[2],
#                 "transform": out_transform
#             })

#         out_path = 'static/clipped.tif'
#         os.makedirs('static', exist_ok=True)

#         with rasterio.open(out_path, "w", **out_meta) as dest:
#             dest.write(out_image)

#         return send_file(out_path, as_attachment=True)

#     except Exception as e:
#         return jsonify({'error': str(e)})


# # -------- New: User Login Placeholder --------
# @app.route('/login', methods=['POST'])
# def login():
#     data = request.get_json()
#     username = data.get('username')
#     password = data.get('password')

#     if username == 'admin' and password == 'admin':
#         session['user'] = username
#         return jsonify({"success": True})
#     return jsonify({"success": False})


# if __name__ == '__main__':
#     app.run(debug=True)


from flask import Flask, render_template, request, jsonify, session, send_file
import ee
import json
import os
import rasterio
from rasterio.mask import mask
from datetime import timedelta

# Initialize Earth Engine
ee.Initialize(project="ee-sambiitk-imageprocessing")

app = Flask(__name__)
app.secret_key = 'your-secret-key'  # For session handling
app.permanent_session_lifetime = timedelta(days=7)

@app.route('/')
def index():
    return render_template('index.html')

# -------- Existing: Get Daily Data --------
@app.route('/get_daily_data', methods=['POST'])
def get_daily_data():
    try:
        data = request.get_json()
        user_aoi = data['aoi']
        coords = user_aoi['geometry']['coordinates']
        aoi = ee.Geometry.Polygon(coords)

        start_date = data['start_date']
        end_date = data['end_date']

        days = ee.List.sequence(0, ee.Date(end_date).difference(ee.Date(start_date), 'day').subtract(1))
        date_list = days.map(lambda d: ee.Date(start_date).advance(d, 'day'))

        def compute_daily(date):
            date = ee.Date(date)
            next_date = date.advance(1, 'day')
            prev_date = date.advance(-1, 'day')

            s2 = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED") \
                .filterBounds(aoi) \
                .filterDate(date, next_date) \
                .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 40))

            s2size = s2.size()

            def compute_if_available(_):
                s2_median = s2.median()
                ndvi = s2_median.normalizedDifference(['B8', 'B4']).rename('NDVI')
                kc = ndvi.multiply(1.25).subtract(0.2).clamp(0, 1.2).rename('Kc')

                eto = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR') \
                    .filterDate(date, next_date) \
                    .select('potential_evaporation_sum') \
                    .mean().multiply(1000).rename('ETo')

                rain = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY") \
                    .filterDate(date, next_date).sum().rename('Rain')
                effRain = rain.multiply(0.8).rename('EffRain')

                sm_today = ee.ImageCollection("NASA/SMAP/SPL3SMP_E/006") \
                    .filterDate(date, next_date) \
                    .select('soil_moisture_am').mean().rename('SoilMoisture')
                sm_prev = ee.ImageCollection("NASA/SMAP/SPL3SMP_E/006") \
                    .filterDate(prev_date, date) \
                    .select('soil_moisture_am').mean().rename('SoilMoisturePrev')
                deltaS = sm_today.subtract(sm_prev).multiply(200).rename('DeltaS')

                etc = kc.multiply(eto).rename('ETc')
                iwr = etc.subtract(effRain).subtract(deltaS).max(0).rename('IWR')

                all = ee.Image.cat([ndvi, kc, eto, effRain, deltaS, etc, iwr])

                stats = all.reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=aoi,
                    scale=10,
                    maxPixels=1e13
                )

                return ee.Feature(None, stats).set('date', date.format('YYYY-MM-dd'))

            return ee.Algorithms.If(s2size.gt(0), compute_if_available(None), None)

        daily_data = ee.FeatureCollection(date_list.map(compute_daily))
        raw = daily_data.getInfo()['features']
        result = [{k.lower(): v for k, v in f['properties'].items()} for f in raw if f]
        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)})

# -------- New: GEE Raster Tile Layer --------
@app.route('/get_gee_tile', methods=['POST'])
def get_gee_tile():
    try:
        data = request.get_json()
        coords = data['aoi']['geometry']['coordinates']
        aoi = ee.Geometry.Polygon(coords)
        layer_type = data.get("layer", "ndvi")

        # Select image and apply visualization
        if layer_type == "ndvi":
            image = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED") \
                .filterBounds(aoi).median() \
                .normalizedDifference(['B8', 'B4']).rename('NDVI') \
                .visualize(min=0, max=1, palette=['white', 'green'])
        elif layer_type == "kc":
            ndvi = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED") \
                .filterBounds(aoi).median() \
                .normalizedDifference(['B8', 'B4'])
            kc = ndvi.multiply(1.25).subtract(0.2).clamp(0, 1.2)
            image = kc.visualize(min=0, max=1.2, palette=['white', 'blue'])
        elif layer_type == "etc":
            eto = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR') \
                .filterBounds(aoi).mean().multiply(1000)
            ndvi = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED") \
                .filterBounds(aoi).median() \
                .normalizedDifference(['B8', 'B4'])
            kc = ndvi.multiply(1.25).subtract(0.2).clamp(0, 1.2)
            etc = kc.multiply(eto)
            image = etc.visualize(min=0, max=10, palette=['white', 'orange'])
        elif layer_type == "iwr":
            eto = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR') \
                .filterBounds(aoi).mean().multiply(1000)
            ndvi = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED") \
                .filterBounds(aoi).median() \
                .normalizedDifference(['B8', 'B4'])
            kc = ndvi.multiply(1.25).subtract(0.2).clamp(0, 1.2)
            etc = kc.multiply(eto)
            rain = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY") \
                .filterBounds(aoi).mean()
            effRain = rain.multiply(0.8)
            deltaS = ee.Image.constant(0)  # Placeholder
            iwr = etc.subtract(effRain).subtract(deltaS).max(0)
            image = iwr.visualize(min=0, max=20, palette=['white', 'red'])
        elif layer_type == "deltas":
            deltaS = ee.Image.constant(0.1)  # Placeholder
            image = deltaS.visualize(min=0, max=1, palette=['white', 'purple'])
        else:
            return jsonify({"error": "Invalid layer type"}), 400

        image = image.clip(aoi)

        # Get map ID dictionary with tile URL
        map_id_dict = ee.data.getMapId({'image': image})
        return jsonify({
            'mapid': map_id_dict['mapid'],
            'urlFormat': map_id_dict['tile_fetcher'].url_format
        })

    except Exception as e:
        return jsonify({'error': str(e)})


# @app.route('/get_gee_tile', methods=['POST'])
# def get_gee_tile():
#     try:
#         data = request.get_json()
#         coords = data['aoi']['geometry']['coordinates']
#         aoi = ee.Geometry.Polygon(coords)
#         layer_type = data.get("layer", "ndvi")

#         if layer_type == "ndvi":
#             image = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED") \
#                 .filterBounds(aoi).median() \
#                 .normalizedDifference(['B8', 'B4']).rename('NDVI') \
#                 .visualize(min=0, max=1, palette=['white', 'green'])
#         elif layer_type == "kc":
#             ndvi = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED") \
#                 .filterBounds(aoi).median() \
#                 .normalizedDifference(['B8', 'B4'])
#             kc = ndvi.multiply(1.25).subtract(0.2).clamp(0, 1.2)
#             image = kc.visualize(min=0, max=1.2, palette=['white', 'blue'])
#         elif layer_type == "etc":
#             eto = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR') \
#                 .filterBounds(aoi).mean().multiply(1000)
#             ndvi = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED") \
#                 .filterBounds(aoi).median() \
#                 .normalizedDifference(['B8', 'B4'])
#             kc = ndvi.multiply(1.25).subtract(0.2).clamp(0, 1.2)
#             etc = kc.multiply(eto)
#             image = etc.visualize(min=0, max=10, palette=['white', 'orange'])
#         elif layer_type == "iwr":
#             eto = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR') \
#                 .filterBounds(aoi).mean().multiply(1000)
#             ndvi = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED") \
#                 .filterBounds(aoi).median() \
#                 .normalizedDifference(['B8', 'B4'])
#             kc = ndvi.multiply(1.25).subtract(0.2).clamp(0, 1.2)
#             etc = kc.multiply(eto)
#             rain = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY") \
#                 .filterBounds(aoi).mean()
#             effRain = rain.multiply(0.8)
#             deltaS = ee.Image.constant(0)  # Placeholder for deltaS visualization
#             iwr = etc.subtract(effRain).subtract(deltaS).max(0)
#             image = iwr.visualize(min=0, max=20, palette=['white', 'red'])
#         elif layer_type == "deltas":
#             deltaS = ee.Image.constant(0.1)  # Placeholder for deltaS visualization
#             image = deltaS.visualize(min=0, max=1, palette=['white', 'purple'])
#         else:
#             return jsonify({"error": "Invalid layer type"}), 400

#         image = image.clip(aoi)
#         map_id = ee.data.getMapId({'image': image})
#         return jsonify(map_id)

#     except Exception as e:
#         return jsonify({'error': str(e)})

# -------- New: Upload and Clip GeoTIFF --------
@app.route('/upload_geotiff', methods=['POST'])
def upload_geotiff():
    try:
        file = request.files['file']
        geojson = json.loads(request.form['aoi'])

        with rasterio.open(file) as src:
            out_image, out_transform = mask(src, geojson['features'], crop=True)
            out_meta = src.meta.copy()
            out_meta.update({
                "height": out_image.shape[1],
                "width": out_image.shape[2],
                "transform": out_transform
            })

        out_path = 'static/clipped.tif'
        os.makedirs('static', exist_ok=True)

        with rasterio.open(out_path, "w", **out_meta) as dest:
            dest.write(out_image)

        return send_file(out_path, as_attachment=True)

    except Exception as e:
        return jsonify({'error': str(e)})

# -------- New: User Login Placeholder --------
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if username == 'admin' and password == 'admin':
        session['user'] = username
        return jsonify({"success": True})
    return jsonify({"success": False})

if __name__ == '__main__':
    app.run(debug=True)
