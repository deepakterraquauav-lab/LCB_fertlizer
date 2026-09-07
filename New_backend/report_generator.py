from datetime import datetime, timedelta
import io
import logging
import os
import math

from flask import send_file
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from geopy.geocoders import Nominatim
import matplotlib

# Use a non-interactive backend for servers without display support
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.patches as mpatches  # noqa: E402
import pandas as pd  # noqa: E402
from PIL import Image as PILImage  # noqa: E402
from PIL import ImageChops  # noqa: E402
from PIL import ImageDraw  # noqa: E402
from PIL import ImageFont  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Flowable,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    SimpleDocTemplate,
    Frame,
)
import requests
from io import BytesIO
import numpy as np
import traceback
from typing import Optional
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import google.generativeai as genai  # noqa: E402
from shapely.geometry import shape
from shapely.ops import transform
import pyproj
from pyproj import Geod, CRS, Transformer  # Geodesic and CRS utilities


logger = logging.getLogger(__name__)


def filter_series_to_15day_gap(series: list, min_gap_days: int = 15) -> list:
    """
    Filters a time-series list so that consecutive selected images are at least
    `min_gap_days` apart. Uses a greedy rolling approach anchored on the date
    field of each series item (Sentinel-2 dates are the natural anchor).

    If two clear images fall within the minimum gap window, only the FIRST one
    is kept and the clock resets from that date.  The result preserves the
    original dict structure of every selected item.

    Args:
        series        : list of dicts, each with a 'date' / 'day' / 'year_month' key.
        min_gap_days  : minimum number of days required between consecutive picks.

    Returns:
        Filtered list, maintaining the original dict structure.
    """
    if not series:
        return series

    def _parse_date(item: dict):
        raw = item.get('date') or item.get('day') or item.get('year_month') or ''
        try:
            return datetime.strptime(str(raw)[:10], '%Y-%m-%d')
        except Exception:
            return None

    # Sort chronologically; items with unparseable dates are dropped.
    dated = [(item, _parse_date(item)) for item in series]
    dated = [(item, d) for item, d in dated if d is not None]
    dated.sort(key=lambda x: x[1])

    selected = []
    last_date = None

    for item, item_date in dated:
        if last_date is None or (item_date - last_date).days >= min_gap_days:
            selected.append(item)
            last_date = item_date

    logger.info(
        f"[15-day filter] {len(series)} series items → {len(selected)} selected "
        f"(min gap = {min_gap_days} days)"
    )
    return selected


def extract_s2_dates_from_series(series: list) -> list:
    """
    Pulls out the date strings (YYYY-MM-DD) from a filtered series list.
    Only dates that are parseable as YYYY-MM-DD are included.
    Used to pass the selected Sentinel-2 anchor dates to the deep-stats endpoint.
    """
    dates = []
    for item in series:
        raw = item.get('date') or item.get('day') or item.get('year_month') or ''
        date_str = str(raw)[:10]
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
            dates.append(date_str)
        except Exception:
            logger.debug(f"Could not parse date: {raw!r}")
            pass
    logger.info(f"Extracted {len(dates)} S2 dates from {len(series)} series items")    
    return dates

# Professional branding constants
FOOTER_TEXT = "MapZest | Powered by TerrAqua UAV Solutions"

REPORT_SUBTITLE = "Precision Agriculture Report"


def add_scale_bar(ax, crs_epsg: int = 3857) -> None:
    """
    Adds a dynamic scale bar to a matplotlib axes object.
    Works with any projected or geographic CRS.
    
    Parameters:
        ax       : matplotlib Axes with map data
        crs_epsg : EPSG code of the map's CRS (e.g. 3857, 4326, 32644)
    """
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    cx = (xmin + xmax) / 2
    cy = (ymin + ymax) / 2

    crs = CRS.from_epsg(crs_epsg)

    # --- Determine map width in metres regardless of CRS ---
    if crs.is_geographic:
        # Units are degrees — convert a horizontal segment at map centre to metres
        transformer = Transformer.from_crs(
            f"EPSG:{crs_epsg}", "EPSG:4326", always_xy=True
        )
        lon1, lat1 = transformer.transform(xmin, cy)
        lon2, lat2 = transformer.transform(xmax, cy)
        # Haversine distance
        R = 6_371_000  # Earth radius in metres
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
             * math.sin(dlon / 2) ** 2)
        map_width_m = 2 * R * math.asin(math.sqrt(a))
    else:
        # Units are metres (EPSG:3857, UTM, etc.) — check axis unit scale factor
        unit_factor = crs.axis_info[0].unit_conversion_factor  # metres per unit
        map_width_m = (xmax - xmin) * unit_factor

    # --- Pick a "nice" round scale bar length (~20% of map width) ---
    raw_target = map_width_m * 0.20
    magnitude = 10 ** math.floor(math.log10(max(raw_target, 1)))
    target_m = magnitude  # fallback
    best_diff = float("inf")
    for nice in [
        1,
        2,
        5,
        10,
        20,
        25,
        50,
        100,
        200,
        250,
        500,
        1000,
        2000,
        5000,
        10_000,
        20_000,
        50_000,
        100_000,
    ]:
        candidate = nice * magnitude
        diff = abs(candidate - raw_target)
        if diff < best_diff:
            best_diff = candidate
            target_m = candidate

    # --- Convert target_m back to axis units for drawing ---
    if crs.is_geographic:
        # Approximate: degrees longitude at map centre latitude
        transformer = Transformer.from_crs(
            f"EPSG:{crs_epsg}", "EPSG:4326", always_xy=True
        )
        _, lat_c = transformer.transform(cx, cy)
        R = 6_371_000
        metres_per_deg_lon = (math.pi / 180) * R * math.cos(math.radians(lat_c))
        bar_width_units = target_m / metres_per_deg_lon
    else:
        bar_width_units = target_m / unit_factor

    # --- Draw scale bar ---
    bx0 = xmin + 0.03 * (xmax - xmin)
    bx1 = bx0 + bar_width_units
    by = ymin + 0.06 * (ymax - ymin)
    tick_h = 0.006 * (ymax - ymin)

    ax.plot([bx0, bx1], [by, by], "-", color="white", lw=3)
    for bx in [bx0, bx1]:
        ax.plot([bx, bx], [by - tick_h, by + tick_h], "-", color="white", lw=2)

    # --- Label ---
    if target_m >= 1000:
        label = f"{target_m / 1000:g} km"
    else:
        label = f"{int(target_m)} m"

    ax.text(
        (bx0 + bx1) / 2,
        by + 0.014 * (ymax - ymin),
        label,
        ha="center",
        fontsize=8,
        color="white",
        fontweight="bold",
    )

def crop_to_content(img: PILImage.Image, padding: int = 30) -> PILImage.Image:
    """
    Crops the image to the non-transparent content with adequate padding.
    This ensures the field appears properly without being clipped.
    Increased padding to prevent over-aggressive cropping.
    """
    try:
        # Ensure we are working with alpha channel
        img = img.convert("RGBA")
        alpha = img.split()[3]
        
        # Get bounding box of non-transparent pixels
        bbox = alpha.getbbox()
        
        # If no alpha bbox found, try finding difference from white/black
        if not bbox:
            bg = PILImage.new(img.mode, img.size, img.getpixel((0,0)))
            diff = ImageChops.difference(img, bg)
            diff = ImageChops.add(diff, diff, 2.0, -100)
            bbox = diff.getbbox()

        if bbox:
            left, upper, right, lower = bbox
            width, height = img.size
            
            # Add padding without going out of bounds
            left = max(0, left - padding)
            upper = max(0, upper - padding)
            right = min(width, right + padding)
            lower = min(height, lower + padding)
            
            return img.crop((left, upper, right, lower))
            
        return img
    except Exception as e:
        logger.warning(f"Cropping failed: {e}")
        return img




def process_map_image(image_buffer: BytesIO, target_width: int = 1600) -> BytesIO:
    """
    Standardizes map images: 
    1. Crops to content (removes empty space).
    2. Adds White Background (removes black box).
    3. Resizes for high-quality print.
    """
    try:
        image_buffer.seek(0)
        img = PILImage.open(image_buffer)
        
        # 1. Crop to the actual field
        img = crop_to_content(img)
        
        # 2. Handle Transparency -> Composite on White
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            background = PILImage.new("RGB", img.size, (255, 255, 255))
            # Paste using alpha channel as mask
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[3])
            img = background
        else:
            img = img.convert("RGB")

        # 3. Resize (High Quality)
        w_percent = (target_width / float(img.size[0]))
        h_size = int((float(img.size[1]) * float(w_percent)))
        
        # Don't upscale if it's already smaller than target to avoid blur, 
        # unless it's tiny (less than 300px)
        if img.size[0] > target_width or img.size[0] < 300:
             img = img.resize((target_width, h_size), PILImage.LANCZOS)

        # 4. Save
        out_buffer = BytesIO()
        img.save(out_buffer, format='PNG', optimize=True)
        out_buffer.seek(0)
        return out_buffer

    except Exception as e:
        logger.error(f"Error processing map image: {e}")
        return image_buffer


class HR(Flowable):
    """Helper flowable used for drawing horizontal rules."""

    def __init__(self, thickness: int = 1):
        super().__init__()
        self.thickness = thickness

    def draw(self) -> None:
        width = self.canv._pagesize[0] - 40 * mm  # type: ignore[attr-defined]
        self.canv.setLineWidth(self.thickness)
        self.canv.line(20 * mm, 0, 20 * mm + width, 0)


def draw_footer(canvas, doc) -> None:
    """Draw footer with page number and branding on each page."""

    canvas.saveState()

    # Border
    canvas.setStrokeColor(colors.HexColor("#2E7D32"))  # Green border
    canvas.setLineWidth(0.8)
    margin = 10 * mm
    canvas.rect(
        margin,
        margin,
        doc.pagesize[0] - 2 * margin,
        doc.pagesize[1] - 2 * margin,
        stroke=1,
        fill=0,
    )

    # Footer branding (left side)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.grey)
    canvas.drawString(15 * mm, 12 * mm, FOOTER_TEXT)
    
    # Page number (right side)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.setFillColor(colors.HexColor("#2E7D32"))
    page_num_text = f"Page {doc.page}"
    canvas.drawRightString(doc.pagesize[0] - 15 * mm, 12 * mm, page_num_text)

    canvas.restoreState()



def create_high_quality_tile_mosaic(aoi, start_date, end_date, layer_type, 
                                   backend_url="http://localhost:6000", 
                                   zoom=15, grid_size=3, final_size=2400, draw_aoi_outline=False):
    """
    Create a HIGH-QUALITY tile mosaic with DYNAMIC SCALING:
    - Calculates AOI area to determine optimal zoom and resolution
    - Higher zoom level (16-18) for small AOIs, moderate (14-15) for large
    - Dynamically adjusted resolution based on AOI size
    - Enhanced DPI settings for clarity
    - Minimal compression for sharp images
    """
    try:
        logger.info(f"Creating HIGH-QUALITY {layer_type} tile mosaic...")
        
        # Get tile URL template from backend
        # Force Sentinel-2 only for report generation (skip Landsat)
        response = requests.post(
            f"{backend_url}/get_gee_tile",
            json={
                'aoi': aoi,
                'start_date': start_date,
                'end_date': end_date,
                'layer': layer_type,
                'force_sentinel2': True  # Only use Sentinel-2 for reports
            },
            timeout=60
        )
        
        if response.status_code != 200:
            logger.warning(f"Failed to get {layer_type} tile template")
            return None, None
        
        data = response.json()
        tile_url_template = data.get('urlFormat')
        stats = data.get('stats')
        
        if not tile_url_template:
            return None, None

        # --- Dynamic Tile Grid Calculation with AOI Size Detection ---
        # 1. Get AOI bounds and calculate area
        try:
            coords = aoi['geometry']['coordinates'][0] 
            # Handle possible nested list structure (MultiPolygon vs Polygon)
            if isinstance(coords[0][0], list):
                 coords = coords[0]
            
            lons = [p[0] for p in coords]
            lats = [p[1] for p in coords]
            min_lon, max_lon = min(lons), max(lons)
            min_lat, max_lat = min(lats), max(lats)
            
            # Calculate approximate AOI area in degrees (rough estimate)
            lon_span = max_lon - min_lon
            lat_span = max_lat - min_lat
            aoi_area_degrees = lon_span * lat_span
            
            # Calculate approximate area in square kilometers using Haversine approximation
            # At equator: 1 degree ≈ 111 km
            # Adjust for latitude
            avg_lat = (min_lat + max_lat) / 2
            lat_correction = math.cos(math.radians(avg_lat))
            aoi_area_km2 = (lon_span * 111 * lat_correction) * (lat_span * 111)
            
            logger.info(f"📐 AOI Size: ~{aoi_area_km2:.2f} km² ({lon_span:.4f}° x {lat_span:.4f}°)")
            
        except Exception as e:
             logger.error(f"Error parsing AOI coordinates: {e}")
             return None, None

        # 2. Determine optimal zoom level and resolution based on AOI size
        # Small AOI: Higher zoom, higher resolution for better detail
        # Large AOI: Lower zoom, standard resolution for better overview
        
        if aoi_area_km2 < 0.1:  # Very small AOI (< 0.1 km² ≈ 10 hectares)
            initial_zoom = 18
            max_tiles = 25  # 5x5 grid
            dynamic_final_size = 3200  # Higher resolution
            dpi_setting = (600, 600)  # High DPI
            logger.info("🔍 Very Small AOI detected - Using HIGH zoom (18) and HIGH resolution (3200px, 600 DPI)")
            
        elif aoi_area_km2 < 0.5:  # Small AOI (0.1-0.5 km² ≈ 10-50 hectares)
            initial_zoom = 17
            max_tiles = 25
            dynamic_final_size = 2800
            dpi_setting = (500, 500)
            logger.info("🔍 Small AOI detected - Using HIGH zoom (17) and HIGH resolution (2800px, 500 DPI)")
            
        elif aoi_area_km2 < 2.0:  # Medium AOI (0.5-2 km² ≈ 50-200 hectares)
            initial_zoom = 16
            max_tiles = 20
            dynamic_final_size = 2600
            dpi_setting = (450, 450)
            logger.info("📊 Medium AOI detected - Using MODERATE zoom (16) and resolution (2600px, 450 DPI)")
            
        elif aoi_area_km2 < 10.0:  # Large AOI (2-10 km² ≈ 200-1000 hectares)
            initial_zoom = 15
            max_tiles = 16
            dynamic_final_size = 2400
            dpi_setting = (350, 350)
            logger.info("📊 Large AOI detected - Using STANDARD zoom (15) and resolution (2400px, 350 DPI)")
            
        else:  # Very large AOI (> 10 km²)
            initial_zoom = 14
            max_tiles = 16
            dynamic_final_size = 2200
            dpi_setting = (300, 300)
            logger.info("🗺️ Very Large AOI detected - Using LOWER zoom (14) and resolution (2200px, 300 DPI)")
        
        current_zoom = initial_zoom
        tile_min_x, tile_min_y, tile_max_x, tile_max_y = 0, 0, 0, 0
        
        # Adjust zoom if too many tiles are needed
        while current_zoom >= 10:
             tile_min_x, tile_min_y = lonlat_to_tile_xy(min_lon, max_lat, current_zoom)
             tile_max_x, tile_max_y = lonlat_to_tile_xy(max_lon, min_lat, current_zoom)
             
             # Convert to integer tile indices AND ADD BUFFER
             tile_min_x = int(tile_min_x) - 1  
             tile_min_y = int(tile_min_y) - 1
             tile_max_x = int(tile_max_x) + 1
             tile_max_y = int(tile_max_y) + 1
             width_tiles = tile_max_x - tile_min_x + 1
             height_tiles = tile_max_y - tile_min_y + 1
             total_tiles = width_tiles * height_tiles
             
             if total_tiles <= max_tiles:
                 break # This zoom level is good
             
             current_zoom -= 1
        
        logger.info(f"✅ Final zoom: {current_zoom} for AOI (Grid: {width_tiles}x{height_tiles}, {total_tiles} tiles)")
        
        # 3. Fetch tiles
        tile_size = 256
        tiles = {}
        successful = 0
        
        for tx in range(tile_min_x, tile_max_x + 1):
            for ty in range(tile_min_y, tile_max_y + 1):
                try:
                    tile_url = tile_url_template.replace('{x}', str(tx)).replace('{y}', str(ty)).replace('{z}', str(current_zoom))
                    if '{s}' in tile_url:
                        tile_url = tile_url.replace('{s}', 'a')
                    
                    tile_response = requests.get(tile_url, timeout=15)
                    
                    if tile_response.status_code == 200:
                        tile_img = PILImage.open(BytesIO(tile_response.content)).convert('RGBA')
                        tiles[(tx, ty)] = tile_img
                        successful += 1
                except Exception as e:
                    logger.debug(f"Failed to fetch tile ({tx}, {ty}): {e}")
                    continue

        if not tiles:
            logger.warning(f"No tiles fetched for {layer_type}")
            return None, None
        
        logger.info(f"📦 Successfully fetched {successful}/{total_tiles} tiles")
        
        # 4. Stitch Mosaic
        mosaic_width = width_tiles * tile_size
        mosaic_height = height_tiles * tile_size
        mosaic = PILImage.new('RGBA', (mosaic_width, mosaic_height), (255, 255, 255, 0))
        
        for (tx, ty), tile_img in tiles.items():
            # Calculate pixel position relative to top-left tile
            x_pos = (tx - tile_min_x) * tile_size
            y_pos = (ty - tile_min_y) * tile_size
            mosaic.paste(tile_img, (x_pos, y_pos))
        
        # Draw AOI Outline if requested
        if draw_aoi_outline and aoi:
            try:
                draw = ImageDraw.Draw(mosaic)
                polygons = _extract_aoi_outer_rings(aoi)
                for poly_coords in polygons:
                    pixel_points = []
                    for pt in poly_coords:
                        if isinstance(pt, list) and len(pt) >= 2:
                            lon, lat = pt[0], pt[1]
                            # Calculate pixel position
                            tx, ty = lonlat_to_tile_xy(lon, lat, current_zoom)
                            px = (tx - tile_min_x) * tile_size
                            py = (ty - tile_min_y) * tile_size
                            pixel_points.append((px, py))
                    
                    if len(pixel_points) >= 2:
                        # Ensure polygon ring is closed for complete AOI boundary.
                        if pixel_points[0] != pixel_points[-1]:
                            pixel_points.append(pixel_points[0])

                        # Double-stroke outline improves visibility over any basemap tone.
                        outer_w = max(4, current_zoom - 11)
                        inner_w = max(2, outer_w - 2)
                        draw.line(pixel_points, fill='white', width=outer_w)
                        draw.line(pixel_points, fill='black', width=inner_w)
            except Exception as e:
                logger.warning(f"Failed to draw AOI outline: {e}")
        
        # 5. Crop and Finish
        mosaic = crop_to_content(mosaic, padding=30)  # Slightly more padding
        
        if mosaic.mode == 'RGBA':
            background = PILImage.new('RGB', mosaic.size, (255, 255, 255))
            background.paste(mosaic, mask=mosaic.split()[3])
            mosaic = background
        
        # Dynamic resizing based on aspect ratio using the dynamic final size
        aspect_ratio = mosaic.size[0] / mosaic.size[1]
        
        # Use dynamic_final_size as the dimension for the larger side
        if aspect_ratio > 1:
            target_w = dynamic_final_size
            target_h = int(dynamic_final_size / aspect_ratio)
        else:
            target_h = dynamic_final_size
            target_w = int(dynamic_final_size * aspect_ratio)
        
        # Use high-quality LANCZOS resampling
        mosaic = mosaic.resize((target_w, target_h), PILImage.LANCZOS)
        
        # Save high quality buffer with minimal compression
        buffer = BytesIO()
        # Use PNG with minimal compression for maximum quality
        mosaic.save(buffer, format='PNG', optimize=False, compress_level=0, dpi=dpi_setting)
        buffer.seek(0)
        
        logger.info(f"✅ Created high-quality {layer_type} mosaic: {target_w}x{target_h}px (Zoom {current_zoom}, DPI {dpi_setting[0]})")
        return buffer, stats
        
    except Exception as e:
        logger.error(f"Error creating high-quality tile mosaic: {e}")
        traceback.print_exc()
        return None, None

def create_high_quality_vra_mosaic(aoi, start_date, end_date, parameter, 
                                   backend_url="http://localhost:6000", 
                                   zoom=15, final_size=2400, draw_aoi_outline=False,
                                   force_sentinel2=False, selected_dates=None):
    """
    Create a HIGH-QUALITY VRA (Variable Rate Application) tile mosaic with Jenks classification.
    Uses /get_vra_map endpoint for 5-zone classified maps.
    
    Uses 10m resolution for most parameters (Sentinel-2 native), 30m for LST (thermal).
    
    Args:
        aoi: Area of interest GeoJSON
        start_date: Start date for composite
        end_date: End date for composite  
        parameter: Parameter name (ndvi, savi, lai, lst, etc, cwsi, kc, irrigation_need, soilmoisture)
        backend_url: Backend server URL
        zoom: Initial zoom level
        final_size: Target image size
        draw_aoi_outline: Whether to draw AOI boundary
        force_sentinel2: Force Sentinel-2 usage
        selected_dates: List of specific date strings to use for the composite
        
    Returns:
        tuple: (image_buffer, vra_data) where vra_data contains breaks, stats, zoneCounts
    """
    try:
        logger.info(f"Creating VRA mosaic for {parameter}...")
        
        # Determine scale based on parameter
        # LST uses 30m (thermal limitation), others use 10m (Sentinel-2 native)
        scale = 30 if parameter == 'lst' else 10
        
        # Get VRA tile URL template from backend
        payload = {
            'aoi': aoi,
            'parameter': parameter,
            'start_date': start_date,
            'end_date': end_date,
            'scale': scale,
            'force_sentinel2': force_sentinel2
        }
        if selected_dates:
            payload['selected_dates'] = selected_dates
            
        response = requests.post(
            f"{backend_url}/get_vra_map",
            json=payload,
            timeout=420
        )
        
        if response.status_code != 200:
            logger.warning(f"Failed to get VRA map for {parameter}: {response.text}")
            return None, None
            
        data = response.json()
        tile_url_template = data.get('urlFormat')
        vra_data = {
            'breaks': data.get('breaks', []),
            'stats': data.get('stats', {}),
            'zoneCounts': data.get('zoneCounts', {})
        }
        
        if not tile_url_template:
            logger.warning(f"No VRA tile URL for {parameter}")
            return None, None

        # --- Dynamic Tile Grid Calculation (same as regular mosaic) ---
        try:
            coords = aoi['geometry']['coordinates'][0] 
            if isinstance(coords[0][0], list):
                 coords = coords[0]
            
            lons = [p[0] for p in coords]
            lats = [p[1] for p in coords]
            min_lon, max_lon = min(lons), max(lons)
            min_lat, max_lat = min(lats), max(lats)
            
            # Calculate AOI area
            avg_lat = (min_lat + max_lat) / 2
            lat_correction = math.cos(math.radians(avg_lat))
            lon_span = max_lon - min_lon
            lat_span = max_lat - min_lat
            aoi_area_km2 = (lon_span * 111 * lat_correction) * (lat_span * 111)
            
            logger.info(f"📐 VRA AOI Size: ~{aoi_area_km2:.2f} km²")
            
        except Exception as e:
             logger.error(f"Error parsing AOI coordinates: {e}")
             return None, None

        # Determine optimal zoom based on AOI size
        if aoi_area_km2 < 0.1:
            initial_zoom = 18
            max_tiles = 25
            dynamic_final_size = 3200
            dpi_setting = (600, 600)
        elif aoi_area_km2 < 0.5:
            initial_zoom = 17
            max_tiles = 25
            dynamic_final_size = 2800
            dpi_setting = (500, 500)
        elif aoi_area_km2 < 2.0:
            initial_zoom = 16
            max_tiles = 20
            dynamic_final_size = 2600
            dpi_setting = (450, 450)
        elif aoi_area_km2 < 10.0:
            initial_zoom = 15
            max_tiles = 16
            dynamic_final_size = 2400
            dpi_setting = (350, 350)
        else:
            initial_zoom = 14
            max_tiles = 16
            dynamic_final_size = 2200
            dpi_setting = (300, 300)
        
        current_zoom = initial_zoom
        
        # Adjust zoom if too many tiles
        while current_zoom >= 10:
             tile_min_x, tile_min_y = lonlat_to_tile_xy(min_lon, max_lat, current_zoom)
             tile_max_x, tile_max_y = lonlat_to_tile_xy(max_lon, min_lat, current_zoom)
             
             tile_min_x = int(tile_min_x) - 1  
             tile_min_y = int(tile_min_y) - 1
             tile_max_x = int(tile_max_x) + 1
             tile_max_y = int(tile_max_y) + 1
             width_tiles = tile_max_x - tile_min_x + 1
             height_tiles = tile_max_y - tile_min_y + 1
             total_tiles = width_tiles * height_tiles
             
             if total_tiles <= max_tiles:
                 break
             
             current_zoom -= 1
        
        logger.info(f"✅ VRA zoom: {current_zoom} (Grid: {width_tiles}x{height_tiles}, {total_tiles} tiles)")
        
        # Fetch tiles
        tile_size = 256
        tiles = {}
        successful = 0
        
        for tx in range(tile_min_x, tile_max_x + 1):
            for ty in range(tile_min_y, tile_max_y + 1):
                try:
                    tile_url = tile_url_template.replace('{x}', str(tx)).replace('{y}', str(ty)).replace('{z}', str(current_zoom))
                    if '{s}' in tile_url:
                        tile_url = tile_url.replace('{s}', 'a')
                    
                    tile_response = requests.get(tile_url, timeout=60)
                    
                    if tile_response.status_code == 200:
                        tile_img = PILImage.open(BytesIO(tile_response.content)).convert('RGBA')
                        tiles[(tx, ty)] = tile_img
                        successful += 1
                except Exception as e:
                    logger.debug(f"Failed to fetch VRA tile ({tx}, {ty}): {e}")
                    continue

        if not tiles:
            logger.warning(f"No VRA tiles fetched for {parameter}")
            return None, None
        
        logger.info(f"📦 Fetched {successful}/{total_tiles} VRA tiles")
        
        # Stitch Mosaic
        mosaic_width = width_tiles * tile_size
        mosaic_height = height_tiles * tile_size
        mosaic = PILImage.new('RGBA', (mosaic_width, mosaic_height), (255, 255, 255, 0))
        
        for (tx, ty), tile_img in tiles.items():
            x_pos = (tx - tile_min_x) * tile_size
            y_pos = (ty - tile_min_y) * tile_size
            mosaic.paste(tile_img, (x_pos, y_pos))
        
        # Draw AOI Outline if requested
        if draw_aoi_outline and aoi:
            try:
                draw = ImageDraw.Draw(mosaic)
                polygons = _extract_aoi_outer_rings(aoi)
                for poly_coords in polygons:
                    pixel_points = []
                    for pt in poly_coords:
                        if isinstance(pt, list) and len(pt) >= 2:
                            lon, lat = pt[0], pt[1]
                            tx, ty = lonlat_to_tile_xy(lon, lat, current_zoom)
                            px = (tx - tile_min_x) * tile_size
                            py = (ty - tile_min_y) * tile_size
                            pixel_points.append((px, py))
                    
                    if len(pixel_points) >= 2:
                        if pixel_points[0] != pixel_points[-1]:
                            pixel_points.append(pixel_points[0])
                        border_width = max(4, current_zoom - 11)
                        # Double stroke keeps AOI visible on both bright and dark imagery.
                        draw.line(pixel_points, fill='white', width=border_width + 1)
                        draw.line(pixel_points, fill='#FF0000', width=border_width)
            except Exception as e:
                logger.warning(f"Failed to draw VRA AOI outline: {e}")
        
        # Crop and Finish
        mosaic = crop_to_content(mosaic, padding=30)
        
        if mosaic.mode == 'RGBA':
            background = PILImage.new('RGB', mosaic.size, (255, 255, 255))
            background.paste(mosaic, mask=mosaic.split()[3])
            mosaic = background
        
        # Dynamic resizing
        aspect_ratio = mosaic.size[0] / mosaic.size[1]
        
        if aspect_ratio > 1:
            target_w = dynamic_final_size
            target_h = int(dynamic_final_size / aspect_ratio)
        else:
            target_h = dynamic_final_size
            target_w = int(dynamic_final_size * aspect_ratio)
        
        mosaic = mosaic.resize((target_w, target_h), PILImage.LANCZOS)
        
        # Save high quality buffer
        buffer = BytesIO()
        mosaic.save(buffer, format='PNG', optimize=False, compress_level=0, dpi=dpi_setting)
        buffer.seek(0)
        
        
        logger.info(f"✅ Created VRA mosaic for {parameter}: {target_w}x{target_h}px")
        return buffer, vra_data, current_zoom
        
    except Exception as e:
        logger.error(f"Error creating VRA tile mosaic: {e}")
        traceback.print_exc()
        return None, None

def lonlat_to_tile_xy(lon, lat, zoom):
    """Convert longitude/latitude to tile coordinates."""
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n
    
    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n
    
    return x, y


def _extract_aoi_outer_rings(aoi):
    """
    Return a list of outer rings from GeoJSON Feature/Geometry.
    Supports Polygon and MultiPolygon robustly.
    """
    if not aoi:
        return []

    geom = aoi.get("geometry", aoi)
    if not isinstance(geom, dict):
        return []

    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if not coords:
        return []

    if gtype == "Polygon":
        return [coords[0]] if len(coords) > 0 else []

    if gtype == "MultiPolygon":
        return [poly[0] for poly in coords if poly and len(poly) > 0]

    # Backward-compatible fallback for malformed structures:
    # try to infer by depth-like nesting.
    try:
        if isinstance(coords[0][0][0], (int, float)):
            return [coords[0]]
        if isinstance(coords[0][0][0], list):
            return [poly[0] for poly in coords if poly and len(poly) > 0]
    except Exception:
        pass

    return []


def calculate_map_scale(aoi, zoom_level, map_width_pixels=2400):
    """
    Calculate a "nice" real‑world scale length for the map scale bar.

    This mirrors the geographic logic used in add_scale_bar:
    - Compute the true horizontal ground distance across the AOI
    - Pick a rounded length ~20% of that width
    """
    try:
        # Extract AOI bounds
        coords = aoi["geometry"]["coordinates"][0]
        if isinstance(coords[0][0], list):
            coords = coords[0]

        lons = [p[0] for p in coords]
        lats = [p[1] for p in coords]
        if not lons or not lats:
            raise ValueError("Empty AOI coordinates")

        min_lon, max_lon = min(lons), max(lons)
        avg_lat = sum(lats) / len(lats)

        # True horizontal distance (in metres) across AOI using WGS84 ellipsoid
        geod = Geod(ellps="WGS84")
        _, _, map_width_m = geod.inv(min_lon, avg_lat, max_lon, avg_lat)

        # Target scale bar length ~20% of map width
        raw_target = map_width_m * 0.20
        magnitude = 10 ** math.floor(math.log10(max(raw_target, 1)))
        target_m = magnitude
        best_diff = float("inf")

        for nice in [
            1,
            2,
            5,
            10,
            20,
            25,
            50,
            100,
            200,
            250,
            500,
            1000,
            2000,
            5000,
            10_000,
            20_000,
            50_000,
            100_000,
        ]:
            candidate = nice * magnitude
            diff = abs(candidate - raw_target)
            if diff < best_diff:
                best_diff = candidate
                target_m = candidate

        # Format label
        if target_m >= 1000:
            label = f"{target_m / 1000:g}km"
        else:
            label = f"{int(target_m)}m"

        logger.info(
            f"📏 Calculated map scale: {label} (map width: {map_width_m:.0f} m, "
            f"zoom {zoom_level}, {map_width_pixels} px)"
        )
        return target_m, label

    except Exception as e:
        logger.warning(f"Could not calculate map scale: {e}")
        return 500.0, "500m"  # Fallback


def _build_location_inset(aoi: dict, region_name: str = "Field location") -> PILImage.Image:
    """
    Build a simple location inset using only Pillow.
    Shows the field centroid as a red dot inside a grey box,
    giving QGIS-style context without external basemap dependencies.
    """
    try:
        coords = aoi.get('geometry', {}).get('coordinates')
        if not coords:
            raise ValueError("No coordinates in AOI")

        # Handle Polygon / MultiPolygon nesting
        def _flatten_coords(c):
            if isinstance(c[0][0], (float, int)):
                return c
            if isinstance(c[0][0], list):
                return _flatten_coords(c[0])
            return c

        flat = _flatten_coords(coords)
        lons = [p[0] for p in flat if isinstance(p, (list, tuple)) and len(p) >= 2]
        lats = [p[1] for p in flat if isinstance(p, (list, tuple)) and len(p) >= 2]
        if not lons or not lats:
            raise ValueError("Empty coordinate list")

        lon_c = (min(lons) + max(lons)) / 2.0
        lat_c = (min(lats) + max(lats)) / 2.0

        size = 260
        inset = PILImage.new("RGB", (size, size), (232, 232, 232))
        d = ImageDraw.Draw(inset)

        # Outer border
        d.rectangle([0, 0, size - 1, size - 1], outline=(0, 0, 0), width=3)

        # Simple crosshair background
        d.line([size // 2, 10, size // 2, size - 10], fill=(200, 200, 200), width=2)
        d.line([10, size // 2, size - 10, size // 2], fill=(200, 200, 200), width=2)

        # Field point in the centre (we do not distort the AOI, just show presence)
        r = 8
        cx, cy = size // 2, size // 2
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(220, 0, 0), outline=(0, 0, 0), width=2)

        # Optional small title at top
        try:
            font = ImageFont.truetype("arial.ttf", 18)
        except Exception:
            font = ImageFont.load_default()
        title = region_name
        if hasattr(d, "textbbox"):
            bbox = d.textbbox((0, 0), title, font=font)
            tw = bbox[2] - bbox[0]
        else:
            tw = len(title) * 8
        d.text(((size - tw) // 2, 6), title, fill=(0, 0, 0), font=font)

        return inset
    except Exception as e:
        logger.warning(f"Could not build location inset: {e}")
        # Fallback very small grey box
        return PILImage.new("RGB", (200, 200), (232, 232, 232))


def add_colormap_legend(mosaic_pil: PILImage.Image, layer_type: str, title: Optional[str] = None, stats: Optional[dict] = None) -> PILImage.Image:
    """
    Add a professional colormap legend with statistics, scale bar, and north arrow.
    Enhanced to display min/max/mean values, scale bar, and north direction.
    """
    try:
        # Define colormaps and ranges for each layer type with units
        colormap_specs = {
            'ndvi': {
                'title': title or 'NDVI (Vegetation Health)',
                'subtitle': 'Normalized Difference Vegetation Index',
                'min': 0.0,
                'max': 1.0,
                'unit': '',
                'colors': ['#8B4513', '#D2691E', '#FFD700', '#ADFF2F', '#7FFF00', '#32CD32', '#228B22', '#006400'],
                'labels': ['0.0', '0.3', '0.6', '1.0']
            },
            'soilmoisture': {
                'title': title or 'Soil Moisture',
                'subtitle': 'Soil Moisture Content',
                'min': 0,
                'max': 100,
                'unit': '%',
                'colors': ['#8B4513', '#CD853F', '#DEB887', '#F0E68C', '#90EE90', '#3CB371', '#4682B4'],
                'labels': ['0%', '25%', '50%', '75%', '100%']
            },
            'cwr': {
                'title': title or 'Crop Water Requirement',
                'subtitle': 'Crop Water Requirement',
                'min': 0,
                'max': 10,
                'unit': 'mm',
                'colors': ['#FFFFCC', '#A1DAB4', '#41B6C4', '#2C7FB8', '#253494'],
                'labels': ['0 mm', '2.5', '5', '7.5', '10 mm']
            },
            'lst': {
                'title': title or 'Land Surface Temperature',
                'subtitle': 'Land Surface Temperature',
                'min': 0,
                'max': 50,
                'unit': '°C',
                'colors': ['#0000FF', '#00FFFF', '#FFFF00', '#FFA500', '#FF4500', '#8B0000'],       
                'labels': ['0°C', '15°C', '30°C', '50°C']
            },
            'etc': {
                'title': title or 'Crop Evapotranspiration',
                'subtitle': '',
                'min': 0,
                'max': 10,
                'unit': 'mm/day',
                'colors': ['#D7191C', '#FDAE61', '#FFFFBF', '#ABD9E9', '#2C7BB6'],
                'labels': ['0', '2.5', '5', '7.5', '10']
            },
            'cwsi': {
                'title': title or 'Crop Water Stress',
                'subtitle': 'Water Stress Level',
                'min': 0.0,
                'max': 0.6,
                'unit': '',
                'colors': ['#0000FF', '#FFFF00', '#FF0000'],
                'labels': ['0.0', '0.3', '0.6']
            },
            'pca': {
                'title': title or 'Crop Health (PCA)',
                'subtitle': 'Vegetation Vigor',
                'min': 0.0,
                'max': 100.0,
                'unit': '',
                'colors': ['#8B0000', '#FF0000', '#FFA500', '#FFFF00', '#008000', '#006400'],
                'labels': ['Very Low', 'Low', 'Mod', 'High', 'V. High']
            },
            'kc': {
                'title': title or 'Crop Coefficient',
                'subtitle': 'Crop Coefficient (Kc)',
                'min': 0.0,
                'max': 1.5,
                'unit': '',
                'colors': ['#FF0000', '#FF7F00', '#FFFF00', '#7FFF00', '#00FF00'],
                'labels': ['0.0', '0.5', '1.0', '1.5']
            },
            'irrigation_need': {
                'title': title or 'Irrigation Need',
                'subtitle': 'Daily Irrigation Requirement',
                'min': 0.0,
                'max': 10.0,
                'unit': 'mm/day',
                'colors': ['#808080', '#FFCC00', '#FF9900', '#FF3300', '#990000'],
                'labels': ['0', '3', '5', '10']
            },
            'evi': {
                'title': title or 'Enhanced Vegetation Index',
                'subtitle': 'Enhanced Vegetation Index (EVI)',
                'min': -0.2,
                'max': 1.0,
                'unit': '',
                'colors': ['#8B4513', '#CD853F', '#F4A460', '#FFFF00', '#ADFF2F', '#7FFF00', '#00FF00', '#006400'],
                'labels': ['-0.2', '0.2', '0.6', '1.0']
            },
            'deltas': {
                'title': title or 'Soil Moisture Change',
                'subtitle': 'ΔS - Soil Moisture Change',
                'min': -20,
                'max': 20,
                'unit': '%',
                'colors': ['#D73027', '#FC8D59', '#FEE08B', '#FFFFFF', '#D9EF8B', '#91CF60', '#1A9850'],
                'labels': ['-20%', '0%', '+20%']
            },
            'ndwi': {
                'title': title or 'NDWI',
                'subtitle': 'Normalized Difference Water Index',
                'min': -1.0,
                'max': 1.0,
                'unit': '',
                'colors': ['#8B4513', '#DEB887', '#F0E68C', '#FFFFFF', '#87CEEB', '#4682B4', '#000080'],
                'labels': ['-1.0', '-0.5', '0.0', '0.5', '1.0']
            }
        }
        
        spec = colormap_specs.get(layer_type, colormap_specs['ndvi'])
        
        # Create new image with space for legend, statistics, AND left-side stats box
        mosaic_w, mosaic_h = mosaic_pil.size
        title_h = 0         # No space for title
        subtitle_h = 0      # No space for subtitle
        has_stats = bool(stats)
        legend_h = 400      # EXTRA LARGE space for bigger legend + statistics + scale bar
        padding = 40        # Large padding around content for better spacing
        
        # ADD EXTRA WIDTH for stats box on the left side
        stats_box_width = 970 if has_stats else 300  # Stats box + small margin
        left_stats_area = stats_box_width  # Reserve space on left for stats
        
        new_w = left_stats_area + mosaic_w + padding * 2  # WIDER canvas with stats area
        new_h = mosaic_h + title_h + subtitle_h + legend_h + padding * 2
        
        # Create white background
        new_img = PILImage.new('RGB', (new_w, new_h), color=(255, 255, 255))
        draw = ImageDraw.Draw(new_img)
        
        # Paste original mosaic - SHIFTED RIGHT to make room for stats box
        paste_x = left_stats_area + padding  # Start AFTER the stats area
        paste_y = title_h + subtitle_h + padding
        new_img.paste(mosaic_pil, (paste_x, paste_y))

        # Optional location inset in map area (bottom‑right corner of map)
        try:
            if aoi:
                inset = _build_location_inset(aoi)
                iw, ih = inset.size
                margin = 40
                inset_x = paste_x + mosaic_w - iw - margin
                inset_y = paste_y + mosaic_h - ih - margin
                new_img.paste(inset, (inset_x, inset_y))
        except Exception as e:
            logger.warning(f"Could not draw location inset: {e}")
        
        # --- IMPROVED FONT LOADING ---
        font_paths = [
            "arial.ttf",
            "Arial.ttf",
            "arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf"
        ]
        
        # --- MUCH LARGER FONT SIZES FOR MAXIMUM READABILITY ---
        title_size = 32
        subtitle_size = 24
        label_size = 160  # Legend labels - MASSIVE for visibility
        stats_size = 130  # Statistics text - MASSIVE for visibility
        
        title_font = None
        subtitle_font = None
        label_font = None
        stats_font = None

        # Loop through paths until we find a working font
        for fpath in font_paths:
            try:
                if not title_font: title_font = ImageFont.truetype(fpath, title_size)
                if not subtitle_font: subtitle_font = ImageFont.truetype(fpath, subtitle_size)
                if not label_font: label_font = ImageFont.truetype(fpath, label_size)
                if not stats_font: stats_font = ImageFont.truetype(fpath, stats_size)
                if title_font and label_font and stats_font:
                    break
            except:
                continue
        
        # Fallback if no fonts found
        if not title_font: title_font = ImageFont.load_default()
        if not subtitle_font: subtitle_font = ImageFont.load_default()
        if not label_font: label_font = ImageFont.load_default()
        if not stats_font: stats_font = ImageFont.load_default()
        
        # --- DRAW NORTH ARROW (TOP RIGHT OF FRAME) - LARGE AND VISIBLE ---
        try:
            arrow_size = 100  # Much larger for visibility
            # Position at TOP RIGHT corner of the FRAME, not the map
            arrow_x = new_w - arrow_size - 60  # Right edge of frame
            arrow_y = padding + 20  # Top edge of frame
            
            # Draw north arrow triangle
            arrow_points = [
                (arrow_x + arrow_size // 2, arrow_y),  # Top point
                (arrow_x, arrow_y + arrow_size),  # Bottom left
                (arrow_x + arrow_size, arrow_y + arrow_size)  # Bottom right
            ]
            draw.polygon(arrow_points, fill=(0, 0, 0), outline=(255, 255, 255))
            
            # Draw 'N' label - LARGE AND BOLD
            n_font_size = 70  # Very large for visibility
            try:
                n_font = ImageFont.truetype(font_paths[0], n_font_size)
            except:
                n_font = stats_font
            
            n_text = "N"
            if hasattr(n_font, 'getbbox'):
                n_bbox = draw.textbbox((0, 0), n_text, font=n_font)
                n_width = n_bbox[2] - n_bbox[0]
                n_height = n_bbox[3] - n_bbox[1]
            else:
                n_width, n_height = 35, 50
            
            n_x = arrow_x + (arrow_size - n_width) // 2
            n_y = arrow_y + arrow_size + 10  # More space below arrow
            draw.text((n_x, n_y), n_text, fill=(0, 0, 0), font=n_font)
        except Exception as e:
            logger.warning(f"Could not draw north arrow: {e}")
        
        # --- DRAW SCALE BAR (Bottom Left) - MAXIMUM SIZE ---
        try:
            scale_bar_width = 500  # MAXIMUM WIDTH for visibility
            scale_bar_height = 30  # VERY TALL
            scale_x = paste_x + 60
            scale_y = paste_y + mosaic_h - 140  # More space from bottom
            
            # Draw scale bar background with VERY THICK border
            draw.rectangle(
                [scale_x, scale_y, scale_x + scale_bar_width, scale_y + scale_bar_height],
                fill=(255, 255, 255),
                outline=(0, 0, 0),
                width=5  # Maximum thickness
            )
            
            # Draw alternating black/white segments
            segment_width = scale_bar_width // 4
            for i in range(4):
                seg_x = scale_x + i * segment_width
                fill_color = (0, 0, 0) if i % 2 == 0 else (255, 255, 255)
                draw.rectangle(
                    [seg_x, scale_y, seg_x + segment_width, scale_y + scale_bar_height],
                    fill=fill_color,
                    outline=(0, 0, 0),
                    width=3  # Thicker segment borders
                )
            
            # Add scale text - MAXIMUM FONT SIZE
            # Fix: Draw 0 and Max value separately for correct alignment
            if aoi:
                # calculate_map_scale now returns (value, "X km" or "Y m")
                _, scale_max_text = calculate_map_scale(aoi, zoom_level, mosaic_w)
            else:
                 scale_max_text = "500m"
            
            scale_font_size = 85  # MAXIMUM size for visibility
            try:
                scale_font = ImageFont.truetype(font_paths[0], scale_font_size)
            except:
                scale_font = stats_font
            
            # Draw "0" at start
            draw.text(
                (scale_x, scale_y + scale_bar_height + 8),
                "0",
                fill=(0, 0, 0),
                font=scale_font
            )

            # Draw Max Text at end (Right Aligned)
            max_bbox = draw.textbbox((0, 0), scale_max_text, font=scale_font)
            max_width = max_bbox[2] - max_bbox[0]
            max_x = scale_x + scale_bar_width - max_width
            
            draw.text(
                (max_x, scale_y + scale_bar_height + 8),
                scale_max_text,
                fill=(0, 0, 0),
                font=scale_font
            )
        except Exception as e:
            logger.warning(f"Could not draw scale bar: {e}")
        
        # --- DRAW STATISTICS BOX - EXTREME LEFT EDGE OF CANVAS (NO OVERLAP) ---
        if stats:
            try:
                # Position at EXTREME LEFT edge of the canvas
                stats_x = 2  # Just 5px from absolute left edge
                stats_y = padding + 20  # Top edge of frame
                
                # Extract and format statistics
                min_val = stats.get('min', 0)
                max_val = stats.get('max', 0)
                mean_val = stats.get('mean', 0)
                unit = spec.get('unit', '')
                
                # Format with 2 decimal places
                min_str = f"{min_val:.2f}{unit}"
                max_str = f"{max_val:.2f}{unit}"
                mean_str = f"{mean_val:.2f}{unit}"
                
                # Create semi-transparent background for stats - VERY WIDE for units
                stats_bg_width = 950  # Extra wide to fit "mm/day" and other long units
                stats_bg_height = 480  # Very tall for comfort
                
                # Create a semi-transparent overlay
                overlay = PILImage.new('RGBA', (stats_bg_width, stats_bg_height), (255, 255, 255, 230))
                overlay_draw = ImageDraw.Draw(overlay)
                
                # Draw border - VERY THICK
                overlay_draw.rectangle(
                    [0, 0, stats_bg_width - 1, stats_bg_height - 1],
                    outline=(0, 0, 0),
                    width=6  # Very thick border
                )
                
                # Add text to overlay with MAXIMUM spacing for larger fonts
                text_x_padding = 60  # Large padding for larger text
                text_y = 55          # More vertical spacing from top
                line_spacing = 130   # LARGE space between lines
                
                overlay_draw.text((text_x_padding, text_y), f"Min: {min_str}", fill=(0, 0, 0), font=stats_font)
                text_y += line_spacing
                overlay_draw.text((text_x_padding, text_y), f"Max: {max_str}", fill=(0, 0, 0), font=stats_font)
                text_y += line_spacing
                overlay_draw.text((text_x_padding, text_y), f"Mean: {mean_str}", fill=(0, 0, 0), font=stats_font)
                
                # Paste overlay onto main image
                new_img_rgba = new_img.convert('RGBA')
                new_img_rgba.paste(overlay, (stats_x, stats_y), overlay)
                new_img = new_img_rgba.convert('RGB')
                draw = ImageDraw.Draw(new_img)  # Recreate draw object
                
            except Exception as e:
                logger.warning(f"Could not draw statistics box: {e}")
        
        # --- DRAW LEGEND BAR - MAXIMUM SIZE ---
        legend_y = paste_y + mosaic_h + 50  # MUCH MORE spacing between map and legend
        
        # Use 80% of the total width for maximum visibility
        legend_width = int(mosaic_w * 0.80) 
        
        legend_x_start = (new_w - legend_width) // 2
        legend_bar_h = 100  # VERY TALL - maximum prominence
        
        # Draw gradient bar with THICKER border
        num_colors = len(spec['colors'])
        block_w = legend_width // num_colors
        
        for i, color_hex in enumerate(spec['colors']):
            color_rgb = tuple(int(color_hex.lstrip('#')[j:j+2], 16) for j in (0, 2, 4))
            x0 = legend_x_start + i * block_w
            y0 = legend_y
            x1 = x0 + block_w
            y1 = y0 + legend_bar_h
            # MAXIMUM THICKNESS border
            draw.rectangle([x0, y0, x1, y1], fill=color_rgb, outline=(0, 0, 0), width=8)
        
        # Add value labels below legend with MAXIMUM spacing
        label_y = legend_y + legend_bar_h + 50  # Much more spacing for larger text
        labels = spec['labels']
        
        for i, label in enumerate(labels):
            if len(labels) > 1:
                # Distribute labels evenly
                pct = i / (len(labels) - 1)
                label_x = legend_x_start + int(pct * (num_colors * block_w))
            else:
                label_x = legend_x_start + legend_width // 2
            
            # Center the label text
            if hasattr(label_font, 'getbbox'):
                bbox = draw.textbbox((0, 0), label, font=label_font)
                label_text_width = bbox[2] - bbox[0]
            else:
                label_text_width = len(label) * 15  # Adjusted for bigger font
                
            label_x -= label_text_width // 2
            
            # Draw label with BIGGER font
            draw.text((label_x, label_y), str(label), fill=(0, 0, 0), font=label_font)
        
        logger.info(f"✅ Added enhanced colormap legend with statistics to {layer_type} mosaic")
        return new_img
        
    except Exception as e:
        logger.warning(f"Could not add colormap legend: {e}")
        return mosaic_pil

def add_vra_legend(mosaic_pil: PILImage.Image, parameter: str, vra_data: Optional[dict] = None, title: Optional[str] = None, 
                   aoi: Optional[dict] = None, zoom_level: int = 15) -> PILImage.Image:
    """
    Add a VRA-specific legend with 5 discrete zones matching the React Frontend.
    """
    try:
        # EXACT COLORS FROM REACT CODE (High to Low)
        VRA_COLOR_SCHEMES = {
            'ndvi': ['#00441b', '#238b45', '#74c476', '#c7e9c0', '#f7fcf5'],
            'pca': ['#00441b', '#238b45', '#74c476', '#a1d99b', '#c7e9c0'],
            'cwsi': ['#E57373', '#FFB74D', '#FFFF8D', '#4FC3F7', '#81D4FA'],
            'irrigation_need': ['#08306b', '#2171b5', '#6baed6', '#c6dbef', '#f7fbff'],
            'kc': ['#004529', '#238443', '#78C679', '#D9F0A3', '#FFFFE5'],
            'soilmoisture': ['#08306b', '#2171b5', '#6baed6', '#c6dbef', '#f7fbff'],
            'lst': ['#bd0026', '#f03b20', '#feb24c', '#ffeda0', '#ffffcc'],
            'etc': ['#54278f', '#756bb1', '#9e9ac8', '#c6dbef', '#f7fcfd'],
            'chlorophyll': ['#2e6b2d', '#4d9c44', '#7bbf6a', '#a8d5a2', '#d0f0c0'],
            'lai': ['#00441b', '#238b45', '#74c476', '#a1d99b', '#c7e9c0']
        }
        
        # EXACT LABELS FROM REACT CODE (High to Low)
        VRA_LABELS = {
            'ndvi': ['Highest', 'High', 'Moderate', 'Low', 'Lowest'],
            'pca': ['Highest', 'High', 'Moderate', 'Low', 'Lowest'],
            'cwsi': ['Severe Stress', 'High Stress', 'Moderate', 'Low Stress', 'No Stress'],
            'irrigation_need': ['Highest Need', 'High Need', 'Moderate', 'Low Need', 'Minimal'],
            'kc': ['Highest', 'High', 'Moderate', 'Low', 'Lowest'],
            'soilmoisture': ['Highest', 'High', 'Moderate', 'Low', 'Lowest'],
            'lst': ['Hottest', 'Hot', 'Moderate', 'Cool', 'Coolest'],
            'etc': ['Highest', 'High', 'Moderate', 'Low', 'Lowest'],
            'chlorophyll': ['Highest', 'High', 'Moderate', 'Low', 'Lowest'],
            'lai': ['Highest', 'High', 'Moderate', 'Low', 'Lowest']
        }
        
        # VRA titles
        VRA_TITLES = {
            'ndvi': 'Vegetation Health Zones (NDVI)',
            'pca': 'Crop Health Zones (Vigor)',
            'cwsi': 'Crop Water Stress Zones (CWSI)',
            'lst': 'Temperature Zones (LST)',
            'etc': 'Evapotranspiration Zones (ETc)',
            'kc': 'Crop Coefficient Zones (Kc)',
            'irrigation_need': 'Irrigation Need Zones',
            'soilmoisture': 'Soil Moisture Zones',
            'chlorophyll': 'Chlorophyll Zones (CLRe)',
            'lai': 'Leaf Area Density Zones (LAI)'
        }
        
        # Determine colors and labels based on parameter requested
        colors = VRA_COLOR_SCHEMES.get(parameter, ['#252525', '#636363', '#969696', '#bdbdbd', '#f0f0f0'])
        ZONE_LABELS = VRA_LABELS.get(parameter, ['Zone 5', 'Zone 4', 'Zone 3', 'Zone 2', 'Zone 1'])
        map_title = title or VRA_TITLES.get(parameter, f'{parameter.upper()} Zones')
        
        # Get stats from VRA data
        stats = vra_data.get('stats', {}) if vra_data else {}
        
        # Image dimensions and layout calculations
        mosaic_w, mosaic_h = mosaic_pil.size
        has_stats = bool(stats)
        legend_h = 400
        padding = 40
        stats_box_width = 970 if has_stats else 300
        left_stats_area = stats_box_width
        
        new_w = left_stats_area + mosaic_w + padding * 2
        new_h = mosaic_h + legend_h + padding * 2
        
        new_img = PILImage.new('RGB', (new_w, new_h), color=(255, 255, 255))
        draw = ImageDraw.Draw(new_img)
        
        # Paste the map mosaic onto the white background
        paste_x = left_stats_area + padding
        paste_y = padding
        new_img.paste(mosaic_pil, (paste_x, paste_y))
        
        # Load fonts
        font_paths = [
            "arial.ttf", "Arial.ttf", "arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "C:\\Windows\\Fonts\\arial.ttf", "C:\\Windows\\Fonts\\arialbd.ttf"
        ]
        
        label_size = 100
        stats_size = 100
        title_size = 80
        
        label_font, stats_font, title_font = None, None, None
        
        for fpath in font_paths:
            try:
                if not label_font: label_font = ImageFont.truetype(fpath, label_size)
                if not stats_font: stats_font = ImageFont.truetype(fpath, stats_size)
                if not title_font: title_font = ImageFont.truetype(fpath, title_size)
                if label_font and stats_font and title_font:
                    break
            except:
                continue
        
        if not label_font: label_font = ImageFont.load_default()
        if not stats_font: stats_font = ImageFont.load_default()
        if not title_font: title_font = ImageFont.load_default()
        
        # Draw North Arrow (larger and shifted to the left of the map)
        try:
            arrow_size = 200
            # Place arrow slightly to the left of the map mosaic
            arrow_x = max(20, paste_x - arrow_size - 40)
            arrow_y = padding + 20
            
            arrow_points = [
                (arrow_x + arrow_size // 2, arrow_y), 
                (arrow_x, arrow_y + arrow_size),  
                (arrow_x + arrow_size, arrow_y + arrow_size)  
            ]
            draw.polygon(arrow_points, fill=(0, 0, 0), outline=(255, 255, 255))
            
            n_font_size = 110
            try:
                n_font = ImageFont.truetype(font_paths[0], n_font_size)
            except:
                n_font = stats_font
            
            n_text = "N"
            if hasattr(n_font, 'getbbox'):
                n_bbox = draw.textbbox((0, 0), n_text, font=n_font)
                n_width = n_bbox[2] - n_bbox[0]
            else:
                n_width = 35
            
            n_x = arrow_x + (arrow_size - n_width) // 2
            n_y = arrow_y + arrow_size + 10
            draw.text((n_x, n_y), n_text, fill=(0, 0, 0), font=n_font)
        except Exception as e:
            logger.warning(f"Could not draw north arrow: {e}")
        
        # Draw Scale Bar (simple solid bar, using accurate length from calculate_map_scale)
        try:
            scale_bar_width = 500
            scale_bar_height = 60
            scale_x = paste_x + 60
            scale_y = paste_y + mosaic_h - 140
            
            if aoi:
                # calculate_map_scale already assumes a 500‑px bar; keep width=500 so distance stays correct
                _, scale_max_text = calculate_map_scale(aoi, zoom_level, mosaic_w)
            else:
                scale_max_text = "500m" 

            # Draw a simple solid bar
            draw.rectangle(
                [scale_x, scale_y, scale_x + scale_bar_width, scale_y + scale_bar_height],
                fill=(0, 0, 0),
                outline=(0, 0, 0),
                width=3
            )
            
            scale_font_size = 85
            try:
                scale_font = ImageFont.truetype(font_paths[0], scale_font_size)
            except:
                scale_font = stats_font
            
            draw.text((scale_x, scale_y + scale_bar_height + 8), "0", fill=(0, 0, 0), font=scale_font)

            max_bbox = draw.textbbox((0, 0), scale_max_text, font=scale_font)
            max_width = max_bbox[2] - max_bbox[0]
            max_x = scale_x + scale_bar_width - max_width
            draw.text((max_x, scale_y + scale_bar_height + 8), scale_max_text, fill=(0, 0, 0), font=scale_font)
        except Exception as e:
            logger.warning(f"Could not draw scale bar: {e}")
        
        # Draw Statistics Box
        if stats:
            try:
                stats_x = 2
                stats_y = padding + 20
                min_val = stats.get('min', 0)
                max_val = stats.get('max', 0)
                mean_val = stats.get('mean', 0)
                
                min_str = f"{min_val:.2f}"
                max_str = f"{max_val:.2f}"
                mean_str = f"{mean_val:.2f}"
                
                stats_bg_width = 950
                stats_bg_height = 480
                
                overlay = PILImage.new('RGBA', (stats_bg_width, stats_bg_height), (255, 255, 255, 230))
                overlay_draw = ImageDraw.Draw(overlay)
                overlay_draw.rectangle([0, 0, stats_bg_width - 1, stats_bg_height - 1], outline=(0, 0, 0), width=6)
                
                text_x_padding = 60
                text_y = 55
                line_spacing = 130
                
                overlay_draw.text((text_x_padding, text_y), f"Min: {min_str}", fill=(0, 0, 0), font=stats_font)
                text_y += line_spacing
                overlay_draw.text((text_x_padding, text_y), f"Max: {max_str}", fill=(0, 0, 0), font=stats_font)
                text_y += line_spacing
                overlay_draw.text((text_x_padding, text_y), f"Mean: {mean_str}", fill=(0, 0, 0), font=stats_font)
                
                new_img_rgba = new_img.convert('RGBA')
                new_img_rgba.paste(overlay, (stats_x, stats_y), overlay)
                new_img = new_img_rgba.convert('RGB')
                draw = ImageDraw.Draw(new_img)
            except Exception as e:
                logger.warning(f"Could not draw VRA statistics box: {e}")
        
        # --- DRAW ZONAL LEGEND BLOCKS ---
        title_y = paste_y + mosaic_h + 40
        
        if hasattr(title_font, 'getbbox'):
            title_bbox = draw.textbbox((0, 0), map_title, font=title_font)
            title_width = title_bbox[2] - title_bbox[0]
            title_height = title_bbox[3] - title_bbox[1]
        else:
            title_width = len(map_title) * 30
            title_height = 80
        
        title_x = (new_w - title_width) // 2
        draw.text((title_x, title_y), map_title, fill=(0, 0, 0), font=title_font)

        legend_y = title_y + title_height + 50
        legend_width = int(mosaic_w * 0.80)
        legend_x_start = (new_w - legend_width) // 2
        legend_bar_h = 100
        
        num_zones = len(colors)
        zone_w = legend_width // num_zones
        
        # Draw the 5 color blocks
        for i, color_hex in enumerate(colors):
            color_rgb = tuple(int(color_hex.lstrip('#')[j:j+2], 16) for j in (0, 2, 4))
            x0 = legend_x_start + i * zone_w
            y0 = legend_y
            x1 = x0 + zone_w
            y1 = y0 + legend_bar_h
            draw.rectangle([x0, y0, x1, y1], fill=color_rgb, outline=(0, 0, 0), width=5)
        
        # Draw exact labels below each color block
        label_y = legend_y + legend_bar_h + 30
        
        for i, label in enumerate(ZONE_LABELS):
            label_x = legend_x_start + i * zone_w + zone_w // 2
            
            if hasattr(label_font, 'getbbox'):
                bbox = draw.textbbox((0, 0), label, font=label_font)
                label_text_width = bbox[2] - bbox[0]
            else:
                label_text_width = len(label) * 20
            
            label_x -= label_text_width // 2
            draw.text((label_x, label_y), label, fill=(0, 0, 0), font=label_font)
        
        logger.info(f"✅ Added Zonal VRA legend for {parameter}")
        return new_img
        
    except Exception as e:
        logger.warning(f"Could not add VRA legend: {e}")
        return mosaic_pil

def make_draw_header(location_text: Optional[str], aoi_label: str, left_title: Optional[str] = None, crop_name: str = "Crop", report_date: Optional[str] = None):
    """Return a header drawing function capturing the location text and metadata."""
    
    if left_title is None:
        left_title = "MapZest"  # Default title

    def draw_header(canvas, doc) -> None:
        canvas.saveState()

        # Main title (left) - Larger and bolder
        canvas.setFont("Helvetica-Bold", 14)
        canvas.setFillColor(colors.HexColor("#2E7D32"))
        canvas.drawString(22 * mm, doc.pagesize[1] - 16 * mm, left_title)
        
        # Subtitle below title
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#558B2F"))
        canvas.drawString(22 * mm, doc.pagesize[1] - 20 * mm, REPORT_SUBTITLE)

        # Right side: Location and Crop Info
        canvas.setFont("Helvetica-Bold", 9)
        canvas.setFillColor(colors.black)
        
        # Location
        canvas.drawRightString(
            doc.pagesize[0] - 22 * mm,
            doc.pagesize[1] - 16 * mm,
            f"{aoi_label}: {location_text or 'Not specified'}",
        )
        
        # Header line (green)
        canvas.setLineWidth(1.5)
        canvas.setStrokeColor(colors.HexColor("#2E7D32"))
        canvas.line(20 * mm, doc.pagesize[1] - 23 * mm, doc.pagesize[0] - 20 * mm, doc.pagesize[1] - 23 * mm)

        canvas.restoreState()

    return draw_header


def download_image(url: str) -> Optional[io.BytesIO]:
    if not url: return None
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        return io.BytesIO(response.content)
    except Exception as e:
        logger.error(f"Error downloading image {url}: {e}")
        return None


def _px_to_points(px: int, dpi: float) -> float:
    if not dpi or dpi <= 0: dpi = 96.0
    return px * 72.0 / dpi


def make_reportlab_image(buf: io.BytesIO, max_width_pt: float, max_height_pt: float) -> Image:
    """Create a ReportLab Image Flowable that fits into max_width_pt x max_height_pt."""
    try:
        buf.seek(0)
        pil = PILImage.open(buf)
        px_w, px_h = pil.size
        dpi = pil.info.get('dpi', (96, 96))[0] if isinstance(pil.info.get('dpi', None), tuple) else (pil.info.get('dpi', 96) or 96)
        img_w_pt = _px_to_points(px_w, dpi)
        img_h_pt = _px_to_points(px_h, dpi)

        scale = min(1.0, max_width_pt / img_w_pt if img_w_pt > 0 else 1.0, max_height_pt / img_h_pt if img_h_pt > 0 else 1.0)
        draw_w = img_w_pt * scale
        draw_h = img_h_pt * scale

        out_buf = io.BytesIO()
        pil.save(out_buf, format='PNG')
        out_buf.seek(0)
        rl_img = Image(out_buf, width=draw_w, height=draw_h)
        return rl_img
    except Exception:
        try:
            buf.seek(0)
            rl_img = Image(buf)
            rl_img._restrictSize(max_width_pt, max_height_pt)
            return rl_img
        except Exception:
            placeholder = PILImage.new('RGB', (800, 480), color=(240, 240, 240))
            pbuf = io.BytesIO()
            placeholder.save(pbuf, format='PNG')
            pbuf.seek(0)
            return Image(pbuf, width=max_width_pt, height=max_height_pt)


def get_logo_path(provided_path: str | None = None) -> str | None:
    """Resolve the logo path using several fallbacks."""
    if provided_path and os.path.exists(provided_path):
        return provided_path

    candidate_paths = [
        provided_path,
        "static/mapzest_logo.png",
        "mapzest_logo.png",
        "../static/mapzest_logo.png",
        "./static/mapzest_logo.png",
        os.path.join(os.path.dirname(__file__), "static", "mapzest_logo.png"),
        os.path.join(os.path.dirname(__file__), "mapzest_logo.png"),
    ]

    for path in candidate_paths:
        if path and os.path.exists(path):
            return path

    return None


def _render_ndvi_chart(series, outbuf: io.BytesIO, title: str = "NDVI time series", na_text: str = "NDVI not available") -> None:
    dates, vals = [], []
    for item in series:
        date_val = item.get("date") or item.get("day") or item.get("year_month")
        ndvi_val = item.get("ndvi") or item.get("NDVI") or item.get("ndvi_mean")
        try:
            if date_val and ndvi_val is not None:
                dates.append(pd.to_datetime(date_val))
                vals.append(float(ndvi_val))
        except Exception:
            continue

    if not vals:
        fig = plt.figure(figsize=(8, 2.5))
        plt.text(0.5, 0.5, na_text, ha="center", va="center")
        plt.axis("off")
        fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
        plt.close(fig)
        outbuf.seek(0)
        return

    fig, ax = plt.subplots(figsize=(8, 2.5))
    ax.plot(dates, vals, marker="o", linewidth=1.5, markersize=4)
    ax.set_title(title, fontsize=10, fontweight='bold')
    ax.set_ylabel("NDVI")
    ax.set_ylim(0, 1)
    ax.grid(alpha=0.25, linestyle='--')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    fig.autofmt_xdate(rotation=30)
    fig.tight_layout()
    fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
    plt.close(fig)
    outbuf.seek(0)


def _render_pie_chart(landcover_dict, outbuf: io.BytesIO, title: str = "Vegetation vs Bare Land", no_data_label: str = "No data") -> None:
    labels = list(landcover_dict.keys()) if landcover_dict else [no_data_label]
    sizes = [float(v) for v in landcover_dict.values()] if landcover_dict else [1]
    total = sum(sizes)
    if total == 0:
        labels, sizes = [no_data_label], [1]

    fig, ax = plt.subplots(figsize=(5, 4))
    ax.pie(sizes, labels=labels, autopct="%1.1f%%", textprops={"fontsize": 8})
    ax.set_title(title, fontsize=10)
    ax.axis("equal")
    fig.tight_layout()
    fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
    plt.close(fig)
    outbuf.seek(0)


def _render_aoi_map(aoi_coords, outbuf: io.BytesIO, title: str = "AOI Map", na_text: str = "AOI not available") -> None:
    try: 
        polygon = aoi_coords[0] if isinstance(aoi_coords[0][0], (list, tuple)) else aoi_coords
        lons = [p[0] for p in polygon]
        lats = [p[1] for p in polygon]

        fig, ax = plt.subplots(figsize=(7.4, 4.5))
        ax.fill(lons, lats, facecolor="#98FB98", edgecolor="darkgreen", alpha=0.6)
        ax.plot(lons + [lons[0]], lats + [lats[0]], color="darkgreen")
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.grid(alpha=0.2)
        ax.set_xlim(min(lons) - 0.001, max(lons) + 0.001)
        ax.set_ylim(min(lats) - 0.001, max(lats) + 0.001)

        # Add dynamic scale bar based on geographic CRS (EPSG:4326 for lon/lat)
        try:
            add_scale_bar(ax, crs_epsg=4326)
        except Exception as e:
            logger.warning(f"Could not add AOI map scale bar: {e}")

        fig.tight_layout()
        fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
        plt.close(fig)
        outbuf.seek(0)
    except Exception:
        img = PILImage.new("RGB", (800, 480), color=(240, 240, 240))
        draw = ImageDraw.Draw(img)
        draw.text((200, 220), na_text, fill=(0, 0, 0))
        img.save(outbuf, format="PNG")
        outbuf.seek(0)


def _render_irrigation_timeline(calendar_data, outbuf: io.BytesIO, title: str = "Irrigation Timeline") -> None:
    """Render irrigation timeline chart with amounts and priorities."""
    try:
        if not calendar_data:
            fig = plt.figure(figsize=(8, 3))
            plt.text(0.5, 0.5, "No irrigation data available", ha="center", va="center")
            plt.axis("off")
            fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
            plt.close(fig)
            outbuf.seek(0)
            return

        dates, amounts, priorities, rains = [], [], [], []
        for entry in calendar_data:
            try:
                date_val = entry.get("date")
                if date_val:
                    dates.append(pd.to_datetime(date_val))
                    amounts.append(float(entry.get("final_irrigation_mm", 0)))
                    priorities.append(entry.get("priority", "LOW"))
                    rains.append(float(entry.get("rain_mm", 0)))
            except Exception:
                continue

        if not dates:
            fig = plt.figure(figsize=(8, 3))
            plt.text(0.0, 0.5, "No valid irrigation dates", ha="center", va="center")
            plt.axis("off")
            fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
            plt.close(fig)
            outbuf.seek(0)
            return

        color_map = {"URGENT": "#d32f2f", "HIGH": "#f57c00", "MEDIUM": "#fbc02d", "LOW": "#388e3c"}
        colors_list = [color_map.get(p, "#cccccc") for p in priorities]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 4), sharex=True, gridspec_kw={'height_ratios': [3, 1]})
        
        ax1.bar(dates, amounts, color=colors_list, alpha=0.8, edgecolor='black', linewidth=0.5)
        ax1.set_ylabel("Irrigation (mm)")
        ax1.set_title(title, fontsize=11, fontweight='bold')
        ax1.grid(axis='y', alpha=0.3)
        
        legend_elements = [mpatches.Patch(facecolor=color_map[p], label=p, edgecolor='black') 
                          for p in ["URGENT", "HIGH", "MEDIUM", "LOW"]]
        ax1.legend(handles=legend_elements, loc='upper right', fontsize=8)

        ax2.bar(dates, rains, color='#1976d2', alpha=0.6, edgecolor='black', linewidth=0.5)
        ax2.set_ylabel("Rain (mm)", fontsize=9)
        ax2.set_xlabel("Date")
        ax2.grid(axis='y', alpha=0.3)
        
        fig.autofmt_xdate(rotation=45)
        fig.tight_layout()
        fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
        plt.close(fig)
        outbuf.seek(0)

    except Exception as e:
        logger.error(f"Error rendering irrigation timeline: {e}")
        fig = plt.figure(figsize=(8, 3))
        plt.text(0.5, 0.5, "Error rendering chart", ha="center", va="center")
        plt.axis("off")
        fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
        plt.close(fig)
        outbuf.seek(0)


def _render_priority_distribution(calendar_data, outbuf: io.BytesIO, title: str = "Irrigation Priority Distribution") -> None:
    """Render pie chart showing distribution of irrigation priorities."""
    try:
        if not calendar_data:
            fig = plt.figure(figsize=(5, 4))
            plt.text(0.5, 0.5, "No irrigation data", ha="center", va="center")
            plt.axis("off")
            fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
            plt.close(fig)
            outbuf.seek(0)
            return

        priority_counts = {"URGENT": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for entry in calendar_data:
            if entry.get("should_irrigate"):
                priority = entry.get("priority", "LOW")
                if priority in priority_counts:
                    priority_counts[priority] += 1

        labels = [k for k, v in priority_counts.items() if v > 0]
        sizes = [v for v in priority_counts.values() if v > 0]

        if not sizes:
            fig = plt.figure(figsize=(5, 4))
            plt.text(0.5, 0.5, "No irrigation events", ha="center", va="center")
            plt.axis("off")
            fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
            plt.close(fig)
            outbuf.seek(0)
            return

        color_map = {"URGENT": "#d32f2f", "HIGH": "#f57c00", "MEDIUM": "#fbc02d", "LOW": "#388e3c"}
        colors_list = [color_map.get(label, "#cccccc") for label in labels]

        fig, ax = plt.subplots(figsize=(5, 4))
        ax.pie(sizes, labels=labels, autopct="%1.1f%%", colors=colors_list, 
               textprops={"fontsize": 9, "weight": "bold"}, startangle=90)
        ax.set_title(title, fontsize=10, fontweight='bold')
        ax.axis("equal")
        fig.tight_layout()
        fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
        plt.close(fig)
        outbuf.seek(0)

    except Exception as e:
        logger.error(f"Error rendering priority distribution: {e}")
        fig = plt.figure(figsize=(5, 4))
        plt.text(0.5, 0.5, "Error rendering chart", ha="center", va="center")
        plt.axis("off")
        fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
        plt.close(fig)
        outbuf.seek(0)


def _render_water_comparison(calendar_data, outbuf: io.BytesIO, title: str = "Water Need vs Rainfall") -> None:
    """Render comparison chart of irrigation need vs rainfall."""
    try:
        if not calendar_data:
            fig = plt.figure(figsize=(8, 3))
            plt.text(0.5, 0.5, "No data available", ha="center", va="center")
            plt.axis("off")
            fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
            plt.close(fig)
            outbuf.seek(0)
            return

        dates, irrigation, rainfall = [], [], []
        for entry in calendar_data:
            try:
                date_val = entry.get("date")
                if date_val:
                    dates.append(pd.to_datetime(date_val))
                    irrigation.append(float(entry.get("final_irrigation_mm", 0)))
                    rainfall.append(float(entry.get("rain_mm", 0)))
            except Exception:
                continue

        if not dates:
            fig = plt.figure(figsize=(8, 3))
            plt.text(0.5, 0.5, "No valid data", ha="center", va="center")
            plt.axis("off")
            fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
            plt.close(fig)
            outbuf.seek(0)
            return

        fig, ax = plt.subplots(figsize=(8, 3.5))
        
        width = 0.35
        x = range(len(dates))
        
        ax.bar([i - width/2 for i in x], irrigation, width, label='Irrigation Need', 
               color='#ff6b6b', alpha=0.8, edgecolor='black', linewidth=0.5)
        ax.bar([i + width/2 for i in x], rainfall, width, label='Rainfall', 
               color='#4ecdc4', alpha=0.8, edgecolor='black', linewidth=0.5)
        
        ax.set_ylabel("Water (mm)")
        ax.set_title(title, fontsize=11, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels([d.strftime('%m/%d') for d in dates], rotation=45, ha='right', fontsize=8)
        ax.legend(loc='upper right')
        ax.grid(axis='y', alpha=0.3)
        
        fig.tight_layout()
        fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
        plt.close(fig)
        outbuf.seek(0)

    except Exception as e:
        logger.error(f"Error rendering water comparison: {e}")
        fig = plt.figure(figsize=(8, 3))
        plt.text(0.5, 0.5, "Error rendering chart", ha="center", va="center")
        plt.axis("off")
        fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
        plt.close(fig)
        outbuf.seek(0)


def _render_generic_timeline(series, metric_key: str, outbuf: io.BytesIO, 
                             title: str = "Timeline", ylabel: str = "Value", 
                             color: str = '#2E7D32', na_text: str = "No data available") -> None:
    """Render a generic timeline chart for any metric."""
    try:
        # Extract data based on metric_key
        key_variants = {
            'ndvi': ['ndvi', 'NDVI', 'ndvi_mean'],
            'pca': ['pca', 'PC1', 'pc1', 'pca_mean'],
            'lst': ['lst_c', 'lst'],
            'etc': ['etc_mm', 'etc'],
            'cwr': ['cwr_mm', 'cwr'],
            'irrigation_need': ['irrigation_need', 'irrigation'],
            'soilmoisture': ['soilmoisture_mm', 'soilmoisture', 'soil_moisture'],
        }
        
        keys_to_try = key_variants.get(metric_key, [metric_key])
        
        dates, vals = [], []
        for item in series:
            date_val = item.get("date") or item.get("day") or item.get("year_month")
            value = None
            
            # Try to find the value
            for key in keys_to_try:
                if item.get(key) is not None:
                    value = item.get(key)
                    break
            
            try:
                if date_val and value is not None:
                    val_float = float(value)
                    # Auto-convert Kelvin to Celsius for LST chart
                    # Auto-convert Kelvin to Celsius for LST chart
                    if metric_key == 'lst' and val_float > 200:
                        val_float = val_float - 273.15
                    
                    dates.append(pd.to_datetime(date_val))
                    vals.append(val_float)
            except Exception:
                continue
        
        if not vals:
            fig = plt.figure(figsize=(8, 2.5))
            plt.text(0.5, 0.5, na_text, ha="center", va="center", fontsize=10)
            plt.axis("off")
            fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
            plt.close(fig)
            outbuf.seek(0)
            return

        fig, ax = plt.subplots(figsize=(8, 2.5))
        ax.plot(dates, vals, marker="o", linewidth=1.5, markersize=4, color=color)
        ax.set_title(title, fontsize=10, fontweight='bold')

        ax.set_ylabel(ylabel, fontsize=9)
        if metric_key == 'pca':
            ax.set_ylabel("Crop Health Score", fontsize=9)
            # ax.set_ylim(0, 105) # Let it auto-scale to show actual variation
        ax.grid(alpha=0.25, linestyle='--')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        fig.autofmt_xdate(rotation=30)
        fig.tight_layout()
        fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
        plt.close(fig)
        outbuf.seek(0)
        
    except Exception as e:
        logger.error(f"Error rendering timeline for {metric_key}: {e}")
        fig = plt.figure(figsize=(8, 2.5))
        plt.text(0.5, 0.5, "Error rendering chart", ha="center", va="center")
        plt.axis("off")
        fig.savefig(outbuf, format="png", bbox_inches="tight", dpi=150)
        plt.close(fig)
        outbuf.seek(0)


def _extract_series_data(series, title_key: str):
    """Extracts series data based on a normalized key (e.g., 'ndvi', 'cwr')."""
    key_map = {
        "ndvi": ["ndvi", "NDVI", "ndvi_mean"],
        "pca": ["pca", "PC1", "pc1", "pca_mean"],
        "cwr": ["cwr_mm", "cwr"],
        "kc": ["kc"],
        "lst": ["lst_c", "lst"],
        "etc": ["etc_mm", "etc"],
        "deltas": ["deltas_mm", "deltas"],
        "soilmoisture": ["soilmoisture_mm", "soilmoisture", "soil_moisture"],
    }

    keys_to_try = key_map.get(title_key, [])

    values = []
    for item in series:
        value = None
        for key in keys_to_try:
            if item.get(key) is not None:
                value = item.get(key)
                break
        try:
            if value is not None:
                val_float = float(value)
                # Auto-convert Kelvin to Celsius for LST
                if "lst" in title_key.lower() and val_float > 200:
                    val_float = val_float - 273.15
                values.append(val_float)
        except Exception:
            continue
    return values


def calculate_statistics_with_confidence(values: list, metric_name: str = "Value") -> dict:
    """
    Calculate min, max, mean, and confidence level for a list of values.
    Returns a dictionary with statistics and a confidence indicator.
    """
    if not values or len(values) == 0:
        return {
            "min": None,
            "max": None,
            "mean": None,
            "count": 0,
            "confidence": "No Data",
            "display": f"{metric_name}: No data available"
        }
    
    values = [v for v in values if v is not None and not math.isnan(v)]
    
    if len(values) == 0:
        return {
            "min": None,
            "max": None,
            "mean": None,
            "count": 0,
            "confidence": "No Data",
            "display": f"{metric_name}: No valid data"
        }
    
    min_val = min(values)
    max_val = max(values)
    mean_val = sum(values) / len(values)
    count = len(values)
    
    # Confidence based on data count and variance
    if count >= 10:
        variance = sum((x - mean_val) ** 2 for x in values) / count
        std_dev = math.sqrt(variance) if variance > 0 else 0
        cv = (std_dev / mean_val * 100) if mean_val != 0 else 0
        
        if cv < 15:
            confidence = "High"
        elif cv < 30:
            confidence = "Medium"
        else:
            confidence = "Low"
    elif count >= 5:
        confidence = "Medium"
    else:
        confidence = "Low"
    
    return {
        "min": round(min_val, 2),
        "max": round(max_val, 2),
        "mean": round(mean_val, 2),
        "count": count,
        "confidence": confidence,
        "display": f"{metric_name}: Min={min_val:.2f}, Max={max_val:.2f}, Avg={mean_val:.2f} (Confidence: {confidence})"
    }


def generate_executive_summary_content(metrics: dict, irrigation_summary: dict, series: list, crop_name: str = "Crop") -> dict:
    """
    Generate executive summary content with key findings, risks, and recommendations.
    """
    summary = {
        "crop_status": "Unknown",
        "key_risks": [],
        "priority_actions": [],
        "water_saved_percent": 0,
        "confidence_level": "Medium",
        "health_score": 0
    }
    
    # Analyze NDVI for crop status
    ndvi_metric = metrics.get("ndvi", {})
    ndvi_mean = ndvi_metric.get("mean")
    
    if ndvi_mean is not None:
        if ndvi_mean > 0.7:
            summary["crop_status"] = "Excellent - Healthy vegetation with good canopy coverage"
            summary["health_score"] = 90
        elif ndvi_mean > 0.5:
            summary["crop_status"] = "Good - Moderate vegetation health, minor improvements possible"
            summary["health_score"] = 75
        elif ndvi_mean > 0.3:
            summary["crop_status"] = "Fair - Vegetation shows stress, intervention recommended"
            summary["health_score"] = 55
            summary["key_risks"].append("Moderate vegetation stress detected")
        else:
            summary["crop_status"] = "Poor - Significant vegetation stress, immediate action needed"
            summary["health_score"] = 30
            summary["key_risks"].append("Critical vegetation stress - urgent intervention required")
    
    # Analyze temperature stress
    lst_metric = metrics.get("lst_c") or metrics.get("lst", {})
    lst_mean = lst_metric.get("mean")
    
    if lst_mean is not None:
        if lst_mean > 35:
            summary["key_risks"].append(f"High Land Surface Temperature ({lst_mean:.1f}°C) - heat stress risk")
            summary["priority_actions"].append("Increase irrigation frequency to mitigate heat stress")
        elif lst_mean < 10:
            summary["key_risks"].append(f"Low Land Surface Temperature ({lst_mean:.1f}°C) - cold stress risk")
    
    # Analyze water management
    water_saved_percent = irrigation_summary.get("savings_percent", 0)
    summary["water_saved_percent"] = round(water_saved_percent, 1)
    
    if water_saved_percent > 20:
        summary["priority_actions"].append(f"Excellent water efficiency - maintain current practices ({water_saved_percent:.1f}% savings)")
    elif water_saved_percent > 10:
        summary["priority_actions"].append(f"Good water management - continue smart irrigation ({water_saved_percent:.1f}% savings)")
    
    # Check irrigation urgency
    total_events = irrigation_summary.get("total_events", 0)
    if total_events > 0:
        summary["priority_actions"].append(f"Schedule {total_events} irrigation events as per recommendations")
    
    # Confidence level based on data availability
    data_count = sum(1 for m in metrics.values() if m.get("mean") is not None)
    if data_count >= 5:
        summary["confidence_level"] = "High"
    elif data_count >= 3:
        summary["confidence_level"] = "Medium"
    else:
        summary["confidence_level"] = "Low"
    
    # Default priority actions if none found
    if not summary["priority_actions"]:
        summary["priority_actions"].append("Monitor crop health regularly using satellite data")
        summary["priority_actions"].append("Follow irrigation schedule based on crop water requirements")
    
    if not summary["key_risks"]:
        summary["key_risks"].append("No significant risks detected - continue monitoring")
    
    return summary



def get_translations(lang: str = "en") -> dict:
    """
    Returns a dictionary of translated strings for the report.
    """
    translations = {
        "en": {
            "report_title": "Crop Health Report",
            "logo_alt": "MapZest Agricultural Intelligence",
            "crop": "Crop",
            "period": "Period",
            "location": "Location",
            "not_specified": "Not specified",
            "aoi_title": "Area of Interest (AOI)",
            "aoi_label": "AOI",
            "aoi_map_title": "AOI (user-drawn)",
            "aoi_na": "AOI not provided",
            "aoi_area": "AOI Area (ha)",
            "time_period": "Time Period",
            "cloud_cover": "Cloud Cover",
            "report_generated": "Report Generated",
            "ndvi_title": "Vegetation (NDVI)",
            "pca_title": "Crop Health",
            "ndvi_chart_title_suffix": "Health over time",
            "ndvi_na": "NDVI time series not available",
            "cwr_title": "Crop Water Requirement",
            "kc_title": "crop Coefficient",
            "lst_title": "Field Temperature",
            "etc_title": "Total Water Loss",
            "sm_title": "Soil Moisture Change",
            "soilmoisture_title": "Soil Moisture (%)",
            "soilmoisture_avg": "<b>Average Soil Moisture: {mean:.2f}%</b>",
            "soilmoisture_trend": "<b>Soil Moisture Trend:</b> {trend}",
            "analytics_title": "Overall Crop Analytics (summary)",
            "analytics_health_na": "Crop Health data not available",
            "analytics_cwr_na": "Water Requirement not available",
            "analytics_health": "Current canopy health (NDVI mean): <b>{mean:.2f}</b>",
            "analytics_cwr": "Approx. water need (mean CWR): <b>{mean:.2f} mm/day</b>",
            "analytics_temp": "Mean field temperature: <b>{mean:.2f} °C</b>",
            "analytics_sm": "Avg. Soil Moisture: <b>{mean:.2f}%</b>",
            "analytics_rec": "Recommendation: Walk the field to confirm these findings and take action.",
            "pie_title": "Field Cover: Vegetation vs Bare Land",
            "pie_interp": "Interpretation: Higher vegetation percentage indicates good canopy cover or dense weeds. Lower percentage indicates exposed soil, sparse vegetation, or very early crop stages.",
            "pie_no_data": "No data",
            "landcover_veg": "Vegetation",
            "landcover_bare": "Bare Land",
            "thanks": "Thank you",
            "contact": "For any queries, contact: contact@terraquauav.com",
            "analysis_title": "<b>{title} — Detailed Analysis:</b>",
            "analysis_no_data": "Data not available to compute a robust summary for this parameter.",
            "analysis_trend_stable": "The readings have been <b>stable</b>, starting at {start:.2f} and ending near {end:.2f}.",
            "analysis_trend_positive": "A <b>positive trend</b> was observed, starting at {start:.2f} and rising to {end:.2f}.",
            "analysis_trend_downward": "A <b>downward trend</b> was observed, starting at {start:.2f} and falling to {end:.2f}.",
            "analysis_recent_stable": "The most recent readings show <b>stability</b>.",
            "analysis_recent_improve": "The most recent readings show a <b>recent improvement</b>.",
            "analysis_recent_decline": "The most recent readings show a <b>recent decline</b>.",
            "analysis_note": "<b>Note:</b> These recommendations should be adapted based on local conditions, soil type, and specific crop requirements.",
            "ndvi_avg": "<b>Average Crop Health Index: {mean:.3f}</b>",
            "ndvi_vlow": "• <b>Very Low Health:</b> Indicates bare soil, stressed vegetation, or crop failure",
            "ndvi_low": "• <b>Low to Moderate Health:</b> Shows early stress signs or sparse vegetation",
            "ndvi_mod": "• <b>Moderate Health:</b> Average crop condition with room for improvement",
            "ndvi_good": "• <b>Good Health:</b> Healthy vegetation with strong photosynthetic activity",
            "ndvi_exc": "• <b>Excellent Health:</b> Optimal crop condition with dense, vigorous vegetation",
            "ndvi_trend": "<b>Historical Trend:</b> {trend}",
            "ndvi_recent": "<b>Recent Pattern:</b> {trend}",
            "cwr_avg": "<b>Average Daily Water Need: {mean:.2f} mm/day</b>",
            "cwr_trend": "<b>Water Need Trend:</b> {trend}",
            "kc_avg": "<b>Average Crop Coefficient (Kc): {mean:.2f}</b>",
            "kc_trend": "<b>Growth Stage Trend:</b> {trend}",
            "lst_avg": "<b>Average Field Temperature: {mean:.1f}°C</b>",
            "lst_trend": "<b>Temperature Trend:</b> {trend}",
            "etc_avg": "<b>Average Total Water Loss: {mean:.2f} mm/day</b>",
            "etc_trend": "<b>Water Loss Trend:</b> {trend}",
            "sm_avg": "<b>Average Daily Soil Moisture: {mean:.2f}%</b>",
            "sm_trend": "<b>Soil Moisture Trend:</b> {trend}",
            "default_avg": "<b>Average value: {mean:.2f}.</b>",
            "default_trend": "<b>Trend Analysis:</b> {trend}",
            "irrigation_title": "Smart Irrigation Schedule",
            "irrigation_summary_title": "Irrigation Summary",
            "irrigation_timeline_title": "Irrigation Timeline",
            "irrigation_priority_title": "Priority Distribution",
            "irrigation_comparison_title": "Water Need vs Rainfall Comparison",
            "irrigation_calendar_title": "Irrigation Calendar",
            "irrigation_total_events": "Total Irrigation Events",
            "irrigation_total_water": "Total Water Required",
            "irrigation_water_saved": "Water Saved (Smart Scheduling)",
            "irrigation_savings_percent": "Water Savings",
            "irrigation_urgent": "Urgent Events",
            "irrigation_high": "High Priority Events",
            "irrigation_medium": "Medium Priority Events",
            "irrigation_date": "Date",
            "irrigation_amount": "Amount (mm)",
            "irrigation_priority": "Priority",
            "irrigation_advice": "Advice",
            "irrigation_no_data": "No irrigation data available",
            "field_intel_title": "Field Intelligence Analysis",
            "health_scale_title": "Overall Crop Health Scale (0–10)",
            "health_weak": "0 – 3<br/><i>Weak</i>",
            "health_moderate": "4 – 7<br/><i>Moderate</i>",
            "health_strong": "8 – 10<br/><i>Strong</i>",
            "aoi_map_main_title": "Area of Interest Map",
            "aoi_map_subtitle": "Geographically aligned view showing the field boundary.",
            "param_analysis_title": "Detailed Parameter Analysis",
            "map_unavailable": "Map unavailable",
            "chlorophyll_na_msg": "<b>Chlorophyll (CLRe) map not available.</b><br/>This layer requires Sentinel-2 red-edge bands (B5/B7).<br/>No Sentinel-2 imagery was found for the selected date range.<br/><i>Try a wider date range to include a cloud-free image.</i>",
            "chlorophyll_short_na": "<b>Chlorophyll map unavailable</b><br/><i>Sentinel-2 data not found for selected period.</i>",
        },
        "hi": {
            "report_title": "सटीक कृषि विश्लेषण रिपोर्ट",
            "logo_alt": "MapZest कृषि बुद्धिमत्ता",
            "crop": "फसल",
            "period": "अवधि",
            "location": "स्थान",
            "not_specified": "निर्दिष्ट नहीं",
            "aoi_title": "रुचि का क्षेत्र (AOI)",
            "aoi_label": "AOI",
            "aoi_map_title": "AOI (उपयोगकर्ता द्वारा खींचा गया)",
            "aoi_na": "AOI प्रदान नहीं किया गया",
            "aoi_area": "AOI क्षेत्रफल (हेक्टेयर)",
            "time_period": "समय अवधि",
            "cloud_cover": "बादल आच्छादन",
            "report_generated": "रिपोर्ट तैयार की गई",
            "ndvi_title": "वनस्पति (NDVI)",
            "pca_title": "फसल स्वास्थ्य",
            "ndvi_chart_title_suffix": "समय के साथ स्वास्थ्य",
            "ndvi_na": "NDVI समय शृंखला उपलब्ध नहीं है",
            "cwr_title": "फसल जल आवश्यकता",
            "kc_title": "फसल गुणांक",
            "lst_title": "खेत का तापमान",
            "etc_title": "कुल जल हानि",
            "sm_title": "मिट्टी में नमी का बदलाव",
            "soilmoisture_title": "मिट्टी की नमी (%)",
            "soilmoisture_avg": "<b>औसत मिट्टी की नमी: {mean:.2f}%</b>",
            "soilmoisture_trend": "<b>मिट्टी की नमी का रुझान:</b> {trend}",
            "analytics_title": "समग्र फसल विश्लेषिकी (सारांश)",
            "analytics_health_na": "फसल स्वास्थ्य डेटा उपलब्ध नहीं है",
            "analytics_cwr_na": "जल आवश्यकता डेटा उपलब्ध नहीं है",
            "analytics_health": "वर्तमान चंदवा स्वास्थ्य (NDVI औसत): <b>{mean:.2f}</b>",
            "analytics_cwr": "अनुमानित जल की आवश्यकता (औसत CWR): <b>{mean:.2f} मिमी/दिन</b>",
            "analytics_temp": "खेत का औसत तापमान: <b>{mean:.2f} °C</b>",
            "analytics_sm": "औसत मिट्टी की नमी: <b>{mean:.2f}%</b>",
            "analytics_rec": "सिफारिश: इन निष्कर्षों की पुष्टि करने के लिए खेत का निरीक्षण करें और उचित कार्रवाई करें।",
            "pie_title": "खेत का आवरण: वनस्पति बनाम बंजर भूमि",
            "pie_interp": "व्याख्या: अधिक वनस्पति प्रतिशत अच्छे चंदवा आवरण या घने खरपतवार को इंगित करता है। कम प्रतिशत स्पष्ट मिट्टी, विरल वनस्पति या बहुत प्रारंभिक फसल अवस्था को दर्शाता है।",
            "pie_no_data": "कोई डेटा नहीं",
            "landcover_veg": "वनस्पति",
            "landcover_bare": "बंजर भूमि",
            "thanks": "धन्यवाद",
            "contact": "किसी भी पूछताछ के लिए, संपर्क करें: contact@terraquauav.com",
            "analysis_title": "<b>{title} — विस्तृत विश्लेषण:</b>",
            "analysis_no_data": "इस पैरामीटर के लिए एक मजबूत सारांश की गणना करने के लिए डेटा उपलब्ध नहीं है।",
            "analysis_trend_stable": "रीडिंग <b>स्थिर</b> रही है, {start:.2f} से शुरू होकर {end:.2f} के करीब समाप्त हुई है।",
            "analysis_trend_positive": "एक <b>सकारात्मक रुझान</b> देखा गया, जो {start:.2f} से बढ़कर {end:.2f} हो गया।",
            "analysis_trend_downward": "एक <b>नीचे की ओर रुझान</b> देखा गया, जो {start:.2f} से गिरकर {end:.2f} हो गया।",
            "analysis_recent_stable": "सबसे हाल की रीडिंग <b>स्थिरता</b> दिखाती है।",
            "analysis_recent_improve": "सबसे हाल की रीडिंग में <b>हालिया सुधार</b> दिखाती है।",
            "analysis_recent_decline": "सबसे हाल की रीडिंग <b>हालिया गिरावट</b> दिखाती है।",
            "analysis_note": "<b>नोट:</b> इन सिफारिशों को स्थानीय परिस्थितियों, मिट्टी के प्रकार और विशिष्ट फसल की आवश्यकताओं के आधार पर अनुकूलित किया जाना चाहिए।",
            "ndvi_avg": "<b>औसत फसल स्वास्थ्य सूचकांक: {mean:.3f}</b>",
            "ndvi_vlow": "• <b>बहुत कम स्वास्थ्य:</b> बंजर मिट्टी, तनावग्रस्त वनस्पति या फसल विफलता को दर्शाता है",
            "ndvi_low": "• <b>कम से मध्यम स्वास्थ्य:</b> शुरुआती तनाव के लक्षण या विरल वनस्पति को दर्शाता है",
            "ndvi_mod": "• <b>मध्यम स्वास्थ्य:</b> सुधार की गुंजाइश के साथ औसत फसल की स्थिति",
            "ndvi_good": "• <b>अच्छा स्वास्थ्य:</b> मजबूत प्रकाश संश्लेषक गतिविधि के साथ स्वस्थ वनस्पति",
            "ndvi_exc": "• <b>उत्कृष्ट स्वास्थ्य:</b> घनी, जोरदार वनस्पति के साथ इष्टतम फसल की स्थिति",
            "ndvi_trend": "<b>ऐतिहासिक रुझान:</b> {trend}",
            "ndvi_recent": "<b>हालिया पैटर्न:</b> {trend}",
            "cwr_avg": "<b>दैनिक जल की औसत आवश्यकता: {mean:.2f} मिमी/दिन</b>",
            "cwr_trend": "<b>जल की आवश्यकता का रुझान:</b> {trend}",
            "kc_avg": "<b>औसत फसल गुणांक (Kc): {mean:.2f}</b>",
            "kc_trend": "<b>विकास चरण का रुझान:</b> {trend}",
            "lst_avg": "<b>खेत का औसत तापमान: {mean:.1f}°C</b>",
            "lst_trend": "<b>तापमान रुझान:</b> {trend}",
            "etc_avg": "<b>औसत कुल जल हानि: {mean:.2f} मिमी/दिन</b>",
            "etc_trend": "<b>जल हानि का रुझान:</b> {trend}",
            "sm_avg": "<b>औसत दैनिक मिट्टी की नमी: {mean:.2f}%</b>",
            "sm_trend": "<b>मिट्टी की नमी का रुझान:</b> {trend}",
            "default_avg": "<b>औसत मान: {mean:.2f}.</b>",
            "default_trend": "<b>प्रवृत्ति विश्लेषण:</b> {trend}",
            "irrigation_title": "स्मार्ट सिंचाई अनुसूची",
            "irrigation_summary_title": "सिंचाई सारांश",
            "irrigation_timeline_title": "सिंचाई की समयरेखा",
            "irrigation_priority_title": "प्राथमिकता वितरण",
            "irrigation_comparison_title": "जल की आवश्यकता बनाम वर्षा की तुलना",
            "irrigation_calendar_title": "सिंचाई कैलेंडर",
            "irrigation_total_events": "कुल सिंचाई घटनाएँ",
            "irrigation_total_water": "कुल आवश्यक जल",
            "irrigation_water_saved": "जल की बचत (स्मार्ट शेड्यूलिंग)",
            "irrigation_savings_percent": "जल की बचतें",
            "irrigation_urgent": "अत्यावश्यक कार्यक्रम",
            "irrigation_high": "उच्च प्राथमिकता वाले कार्यक्रम",
            "irrigation_medium": "मध्यम प्राथमिकता वाले कार्यक्रम",
            "irrigation_date": "दिनांक",
            "irrigation_amount": "मात्रा (मिमी)",
            "irrigation_priority": "प्राथमिकता",
            "irrigation_advice": "सलाह",
            "irrigation_no_data": "कोई सिंचाई डेटा उपलब्ध नहीं है",
            "field_intel_title": "खेत बुद्धि विश्लेषण",
            "health_scale_title": "समग्र फसल स्वास्थ्य पैमाना (0-10)",
            "health_weak": "0 – 3<br/><i>कमजोर</i>",
            "health_moderate": "4 – 7<br/><i>मध्यम</i>",
            "health_strong": "8 – 10<br/><i>मजबूत</i>",
            "aoi_map_main_title": "रुचि का क्षेत्र मानचित्र",
            "aoi_map_subtitle": "खेत की सीमा दर्शाने वाला भौगोलिक संरेखित दृश्य।",
            "param_analysis_title": "विस्तृत पैरामीटर विश्लेषण",
            "map_unavailable": "मानचित्र उपलब्ध नहीं",
            "chlorophyll_na_msg": "<b>क्लोरोफिल (CLRe) मानचित्र उपलब्ध नहीं है।</b><br/>इस परत के लिए सेंटिनल-2 रेड-एज बैंड (B5/B7) की आवश्यकता है।<br/>चुनी गई समय सीमा के लिए कोई सेंटिनल-2 डेटा नहीं मिला।<br/><i>बादल रहित छवि के लिए विस्तृत समय सीमा का प्रयास करें।</i>",
            "chlorophyll_short_na": "<b>क्लोरोफिल मानचित्र अनुपलब्ध</b><br/><i>सेंटिनल-2 डेटा नहीं मिला।</i>",
        },
    }
    return translations.get(lang, translations["en"])


def generate_plain_language_explanation(
    title_key: str,
    title_text: str,
    metric: dict,
    series: list,
    lang_strings: dict,
    max_chars: int = 4500,
) -> str:
    """Generates the rule-based explanation in the selected language."""

    parts: list[str] = []
    mean = None
    try:
        if metric and isinstance(metric, dict):
            mean = metric.get("mean")
    except Exception:
        mean = None

    series_vals = _extract_series_data(series, title_key)
    trend_desc = ""
    recent_trend = ""
    if len(series_vals) >= 2:
        change = series_vals[-1] - series_vals[0]
        if abs(change) < 0.02:
            trend_desc = lang_strings["analysis_trend_stable"].format(start=series_vals[0], end=series_vals[-1])
        elif change > 0:
            trend_desc = lang_strings["analysis_trend_positive"].format(start=series_vals[0], end=series_vals[-1])
        else:
            trend_desc = lang_strings["analysis_trend_downward"].format(start=series_vals[0], end=series_vals[-1])

        if len(series_vals) >= 3:
            recent_change = series_vals[-1] - series_vals[-3]
            if abs(recent_change) < 0.01:
                recent_trend = lang_strings["analysis_recent_stable"]
            elif recent_change > 0:
                recent_trend = lang_strings["analysis_recent_improve"]
            else:
                recent_trend = lang_strings["analysis_recent_decline"]

    # Removed redundant sub-heading to avoid duplicate "Analysis" headers in PDF
    # parts.append(lang_strings["analysis_title"].format(title=title_text))

    if mean is None:
        parts.append(lang_strings["analysis_no_data"])
    else:
        if title_key == "ndvi":
            parts.append(lang_strings["ndvi_avg"].format(mean=mean))
            if mean < 0.2:
                parts.append(lang_strings["ndvi_vlow"])
            elif mean < 0.4:
                parts.append(lang_strings["ndvi_low"])
            elif mean < 0.6:
                parts.append(lang_strings["ndvi_mod"])
            elif mean < 0.8:
                parts.append(lang_strings["ndvi_good"])
            else:
                parts.append(lang_strings["ndvi_exc"])
            if trend_desc:
                parts.append(lang_strings["ndvi_trend"].format(trend=trend_desc))
            if recent_trend:
                parts.append(lang_strings["ndvi_recent"].format(trend=recent_trend))
        elif title_key == "cwr":
            parts.append(lang_strings["cwr_avg"].format(mean=mean))
            if trend_desc:
                parts.append(lang_strings["cwr_trend"].format(trend=trend_desc))
        elif title_key == "kc":
            parts.append(lang_strings["kc_avg"].format(mean=mean))
            if trend_desc:
                parts.append(lang_strings["kc_trend"].format(trend=trend_desc))
        elif title_key == "lst":
            parts.append(lang_strings["lst_avg"].format(mean=mean))
            if trend_desc:
                parts.append(lang_strings["lst_trend"].format(trend=trend_desc))
        elif title_key == "etc":
            parts.append(lang_strings["etc_avg"].format(mean=mean))
            if trend_desc:
                parts.append(lang_strings["etc_trend"].format(trend=trend_desc))
        elif title_key == "deltas":
            parts.append(lang_strings["sm_avg"].format(mean=mean))
            if trend_desc:
                parts.append(lang_strings["sm_trend"].format(trend=trend_desc))
        elif title_key == "soilmoisture":
            parts.append(lang_strings["soilmoisture_avg"].format(mean=mean))
            if trend_desc:
                parts.append(lang_strings["soilmoisture_trend"].format(trend=trend_desc))        
        else:
            parts.append(lang_strings["default_avg"].format(mean=mean))
            if trend_desc:
                parts.append(lang_strings["default_trend"].format(trend=trend_desc))

    parts.append(lang_strings["analysis_note"])

    result = "\n\n".join(parts)
    if len(result) > max_chars:
        result = result[: max_chars - 200] + "\n\n[Explanation trimmed due to length]"
    return result


def generate_ai_explanation(
    title_text: str,
    metric: dict,
    series: list,
    language: str,
    crop_name: str,
    metric_key: str = None, 
) -> str:
    """
    Generates an explanation using an AI model (e.g., Gemini).
    """
    logger.info(f"Generating AI explanation for '{title_text}' (key={metric_key}) in '{language}'...")

    # Key mapping (consistent with _extract_series_data)
    key_map = {
        "ndvi": ["ndvi", "NDVI", "ndvi_mean"],
        "pca": ["pca", "PC1", "pc1", "pca_mean"],
        "cwr": ["cwr_mm", "cwr"],
        "kc": ["kc"],
        "lst": ["lst_c", "lst"],
        "etc": ["etc_mm", "etc"],
        "deltas": ["deltas_mm", "deltas"],
        "soilmoisture": ["soilmoisture_mm", "soilmoisture", "soil_moisture"],
    }

    keys_to_try = key_map.get(metric_key, []) if metric_key else []

    data_summary_parts = []
    if metric and metric.get("mean") is not None:
        data_summary_parts.append(f"Average value (mean): {metric.get('mean'):.3f}")
    if series:
        data_summary_parts.append(f"Time series data points (date, value):")
        
        # Smart Sampling: Take ~12 evenly spaced points to show full trend
        total_points = len(series)
        check_points = []
        if total_points <= 12:
            check_points = series
        else:
            # Pick start, end, and 10 in between
            indices = [int(i) for i in list(range(0, total_points, max(1, total_points // 11)))]
            # Ensure last point is included
            if (total_points - 1) not in indices:
                indices[-1] = total_points - 1
            
            check_points = [series[i] for i in sorted(list(set(indices)))]

        for item in check_points:
            date_val = item.get("date") or item.get("day") or item.get("year_month")
            
            val = None
            if keys_to_try:
                # Use specific keys if provided
                for k in keys_to_try:
                    if item.get(k) is not None:
                        val = item.get(k)
                        break
            else:
                # Fallback (old buggy behavior, minimized)
                val = (item.get("ndvi") or item.get("NDVI") 
                       or item.get("lst_c") or item.get("lst"))

            if date_val and val is not None:
                try:
                    val_float = float(val)
                    # LST Conversion logic
                    if metric_key == "lst" and val_float > 200:
                        val_float = val_float - 273.15
                    
                    data_summary_parts.append(f"- {date_val}: {val_float:.2f}")
                except:
                    data_summary_parts.append(f"- {date_val}: {val}")
        if len(series) > 12:
             data_summary_parts.append("...and more data points.")

    data_summary = "\n".join(data_summary_parts)
    if not data_summary:
        data_summary = "No data available."

    lang_name = "English"

    prompt = f"""
    You are an expert agronomist analyzing a report for a farmer.
    Your task is to provide a brief, insightful analysis of the provided data in {lang_name}.

    The analysis is for the "{title_text}" metric for a {crop_name} crop.

    Here is the data:
    ---
    {data_summary}
    ---

    Please provide your analysis in simple HTML format (using <b>, <br>, <ul>, <li>).
    Your response should include:
   
    2. A 3-4 sentence summary of the key finding from the data.
    3. A bulleted list (<ul>) with 5-6 key observations (e.g., "The trend is positive," "The average is low," etc.).
    4. A short, actionable recommendation for the farmer.

    Keep the entire response concise and easy to understand for a non-expert.
    Keep the entire response concise and easy to understand for a non-expert.
    Respond ONLY in {lang_name}.
    IMPORTANT: Do NOT include a heading like "Analysis:", "Crop Health Analysis:", or "**Analysis**" at the beginning. Start directly with the summary sentence.
    """

    try:
        api_key = ""
        
        if not api_key or api_key == "YOUR_NEW_GEMINI_API_KEY_HERE":
            api_key = os.environ.get("GEMINI_API_KEY")
            if api_key:
                logger.info("Using API key from GEMINI_API_KEY environment variable.")
            else:
                raise ValueError("GEMINI_API_KEY not set. Please update the hardcoded key in the code or set GEMINI_API_KEY environment variable.")
        else:
            logger.info("Using hardcoded API key from code.")

        logger.info(f"Configuring Gemini API with key: {api_key[:10]}...")
        genai.configure(api_key=api_key)
        
        
        available_models = []
        try:
            models_list = list(genai.list_models())
            available_models = [m.name for m in models_list if 'generateContent' in m.supported_generation_methods]
            if available_models:
                logger.info(f"Found {len(available_models)} available models with generateContent support")
                for m in available_models[:3]:
                    logger.info(f"  - {m}")
        except Exception as list_error:
            logger.warning(f"Could not list models (this is okay): {list_error}")
        
        model_names_to_try = []
        
        if available_models:
            flash_models = [m for m in available_models if 'flash' in m.lower()]
            pro_models = [m for m in available_models if 'pro' in m.lower() and m not in flash_models]
            other_models = [m for m in available_models if m not in flash_models and m not in pro_models]
            model_names_to_try = flash_models + pro_models + other_models
        
        if not model_names_to_try:
            model_names_to_try = [
                'gemini-1.5-flash-latest',
                'gemini-1.5-pro-latest', 
                'gemini-pro',
                'models/gemini-pro',
                'gemini-1.5-flash',
                'gemini-1.5-pro'
            ]
        
        response = None
        last_error = None
        
        for model_name in model_names_to_try:
            try:
                logger.info(f"Trying model: {model_name}")
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt, safety_settings=None)
                logger.info(f"Successfully used model: {model_name}")
                break
            except Exception as model_error:
                logger.debug(f"Model {model_name} failed: {model_error}")
                last_error = model_error
                continue
        
        if response is None:
            error_msg = f"No working Gemini model found. Tried: {', '.join(model_names_to_try[:3])}. "
            if available_models:
                error_msg += f"Your API key has access to: {', '.join(available_models[:3])}. "
            error_msg += f"Last error: {last_error}. "
            error_msg += "Please ensure your API key has the Generative Language API enabled in Google Cloud Console."
            raise ValueError(error_msg)
        
        if hasattr(response, 'text'):
            ai_response_raw = response.text
        elif hasattr(response, 'candidates') and response.candidates:
            ai_response_raw = response.candidates[0].content.parts[0].text if response.candidates[0].content.parts else ""
        else:
            ai_response_raw = str(response)
        
        if not ai_response_raw:
            raise ValueError("Empty response from Gemini API")

        ai_response = ai_response_raw.replace("```html", "").replace("```", "").strip()

        if not ai_response:
            raise ValueError("No meaningful content in AI response")

        # Strip out "Analysis:" or "Crop Health Analysis" if AI added it as a heading
        # This prevents duplicate headings since the report already adds one.
        prefixes_to_remove = [
            "**Smart Irrigation Analysis**", 
            "**Crop Health Analysis**", 
            "**Analysis:**", 
            "Analysis:", 
            "Detailed Analysis:",
            "<b>Smart Irrigation Analysis</b>",
            "<b>Crop Health Analysis</b>",
            "<b>Analysis:</b>",
            "<b>Analysis</b>", # Handle case without colon
            "Analysis"       # Handle plain text
        ]
        
        # Loop to remove all potential prefixes (handling multiple newlines or stacked headings)
        cleaning = True
        while cleaning:
            cleaning = False
            ai_response = ai_response.lstrip()
            for prefix in prefixes_to_remove:
                if ai_response.lower().startswith(prefix.lower()):
                    # Remove prefix (case insensitive match, but exact length removal)
                    ai_response = ai_response[len(prefix):]
                    cleaning = True
                    break
            
        ai_response = ai_response.strip()

        logger.info("Successfully received AI-generated analysis.")
        return ai_response

    except Exception as e:
        logger.error(f"AI generation failed for '{title_text}': {e}", exc_info=True)
        logger.info(f"Falling back to rule-based explanation for '{title_text}'")
        return None


def generate_ai_irrigation_analysis(
    calendar_data: list,
    summary: dict,
    crop_name: str,
) -> str:
    """
    Generates AI-powered irrigation analysis using Gemini.
    """
    logger.info("Generating AI-powered irrigation analysis...")

    data_summary_parts = []
    
    if summary:
        data_summary_parts.append("Irrigation Summary:")
        if summary.get("irrigation"):
            irr = summary["irrigation"]
            data_summary_parts.append(f"- Total Events: {irr.get('total_events', 0)}")
            data_summary_parts.append(f"- Total Water: {irr.get('total_water_mm', 0):.2f} mm")
            data_summary_parts.append(f"- Water Saved: {irr.get('water_saved_mm', 0):.2f} mm ({irr.get('savings_percent', 0):.1f}%)")
        
        if summary.get("urgency"):
            urg = summary["urgency"]
            data_summary_parts.append(f"\nUrgency Breakdown:")
            data_summary_parts.append(f"- URGENT: {urg.get('urgent', 0)} events")
            data_summary_parts.append(f"- HIGH: {urg.get('high', 0)} events")
            data_summary_parts.append(f"- MEDIUM: {urg.get('medium', 0)} events")
    
    if calendar_data:
        data_summary_parts.append("\nSample Irrigation Events:")
        for entry in calendar_data[:5]:
            if entry.get("should_irrigate"):
                data_summary_parts.append(
                    f"- {entry.get('date')}: {entry.get('final_irrigation_mm', 0):.1f}mm "
                    f"({entry.get('priority', 'LOW')}) - {entry.get('advice', 'No advice')}"
                )
    
    data_summary = "\n".join(data_summary_parts)
    if not data_summary:
        data_summary = "No irrigation data available."

    prompt = f"""
    You are an expert irrigation agronomist analyzing a smart irrigation schedule for a farmer.
    Your task is to provide actionable insights about the irrigation plan in English.

    The analysis is for a {crop_name} crop.

    Here is the irrigation data:
    ---
    {data_summary}
    ---

    Please provide your analysis in simple HTML format (using <b>, <br>, <ul>, <li>).
    Your response should include:
    1. A bolded title: "<b>Smart Irrigation Analysis</b>"
    2. A 3-4 sentence overview of the irrigation schedule and water savings
    3. A bulleted list with 5-7 key insights, such as:
       - Critical irrigation dates and their urgency
       - Water savings compared to traditional methods
       - Recommendations for monitoring soil moisture
       - Suggestions for adjusting irrigation based on weather
       - Best practices for efficient water use
    4. A short, actionable recommendation for the farmer

    Keep the response concise and farmer-friendly.
    Respond ONLY in English.
    """

    try:
        api_key = "AIzaSyCJDuNiytOFccf0V3MXCEgMKnByye8HiKY"
        
        if not api_key or api_key == "YOUR_NEW_GEMINI_API_KEY_HERE":
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY not set")
        
        genai.configure(api_key=api_key)
        
        model_names_to_try = [
            'gemini-1.5-flash-latest',
            'gemini-1.5-pro-latest', 
            'gemini-pro',
        ]
        
        response = None
        for model_name in model_names_to_try:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt, safety_settings=None)
                break
            except Exception:
                continue
        
        if response is None:
            return None
        
        if hasattr(response, 'text'):
            ai_response_raw = response.text
        elif hasattr(response, 'candidates') and response.candidates:
            ai_response_raw = response.candidates[0].content.parts[0].text if response.candidates[0].content.parts else ""
        else:
            ai_response_raw = str(response)
        
        if not ai_response_raw:
            return None

        ai_response = ai_response_raw.replace("```html", "").replace("```", "").strip()
        
        if not ai_response:
            return None

        logger.info("Successfully generated AI irrigation analysis.")
        return ai_response

    except Exception as e:
        logger.error(f"AI irrigation analysis failed: {e}", exc_info=True)
        return None


def sanitize_html_for_reportlab(html: str) -> str:
    """
    ReportLab Paragraph requires strictly well-formed XML with limited tag support.
    This function uses a stack-based parser to ensure proper tag nesting.
    """
    if not html:
        return ""
    
    import re
    
    text = html
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    
    # Remove full HTML document structure
    text = re.sub(r"<!DOCTYPE[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*html[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*html\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*head[^>]*>.*?</\s*head\s*>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<\s*title[^>]*>.*?</\s*title\s*>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<\s*meta[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*body[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*body\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*style[^>]*>.*?</\s*style\s*>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<\s*script[^>]*>.*?</\s*script\s*>", "", text, flags=re.IGNORECASE | re.DOTALL)
    
    # Remove unsupported structural tags
    text = re.sub(r"<\s*para[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*para\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*div[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*div\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*span[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*span\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*section[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*section\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*article[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*article\s*>", "", text, flags=re.IGNORECASE)
    
    # Convert lists to bullets
    text = re.sub(r"<\s*ul[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*ul\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*ol[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*ol\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*li[^>]*>(.*?)</\s*li\s*>", r"• \1<br/>", text, flags=re.IGNORECASE | re.DOTALL)
    
    # Convert headings to bold
    text = re.sub(r"<\s*h[1-6][^>]*>", "<b>", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*h[1-6]\s*>", "</b><br/>", text, flags=re.IGNORECASE)
    
    # Convert paragraphs to line breaks
    text = re.sub(r"<\s*p[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*p\s*>", "<br/>", text, flags=re.IGNORECASE)
    
    # Normalize br tags
    text = re.sub(r"<\s*br\s*>", "<br/>", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*br\s*/\s*>", "<br/>", text, flags=re.IGNORECASE)
    
    # Remove markdown
    text = text.replace("**", "").replace("__", "")
    
    # Stack-based tag balancer for inline tags
    allowed_tags = {'b', 'i', 'u', 'strong', 'em'}
    tag_pattern = re.compile(r'<(/?)(\w+)([^>]*)>')
    
    output = []
    stack = []
    last_pos = 0
    
    for match in tag_pattern.finditer(text):
        # Add text before tag
        output.append(text[last_pos:match.start()])
        
        is_closing = match.group(1) == '/'
        tag_name = match.group(2).lower()
        attrs = match.group(3)
        
        # Map strong/em to b/i
        if tag_name == 'strong':
            tag_name = 'b'
        elif tag_name == 'em':
            tag_name = 'i'
        
        # Handle br specially (self-closing)
        if tag_name == 'br':
            output.append('<br/>')
            last_pos = match.end()
            continue
        
        # Skip unsupported tags
        if tag_name not in allowed_tags:
            last_pos = match.end()
            continue
        
        if is_closing:
            # Closing tag - only add if it matches stack top
            if stack and stack[-1] == tag_name:
                stack.pop()
                output.append(f'</{tag_name}>')
            # Otherwise ignore orphan closing tag
        else:
            # Opening tag
            if attrs.strip().endswith('/'):
                # Self-closing (unusual for b/i but handle it)
                pass
            else:
                stack.append(tag_name)
                output.append(f'<{tag_name}>')
        
        last_pos = match.end()
    
    # Add remaining text
    output.append(text[last_pos:])
    
    # Close any unclosed tags
    while stack:
        tag = stack.pop()
        output.append(f'</{tag}>')
    
    result = ''.join(output)
    
    # Clean up whitespace and excessive breaks
    result = re.sub(r'(<br/>){3,}', '<br/><br/>', result)
    result = re.sub(r'\n\s*\n', '<br/>', result)
    result = re.sub(r'\s+', ' ', result)
    
    return result.strip()


def get_location_name(lat: float, lon: float) -> str | None:
    try:
        geolocator = Nominatim(user_agent="mapzest_report_app_v1")
        location = geolocator.reverse((lat, lon), exactly_one=True, timeout=5, language="en")
        if location and location.raw.get("address"):
            address = location.raw["address"]
            city = address.get("city") or address.get("town") or address.get("village")
            state = address.get("state")
            country = address.get("country")
            parts = [p for p in (city, state) if p]
            if not parts and country:
                parts.append(country)
            return ", ".join(parts) if parts else None
    except (GeocoderTimedOut, GeocoderUnavailable):
        logger.warning("Reverse geocoding service timed out or is unavailable.")
    except Exception as exc:
        logger.warning("Reverse geocoding error: %s", exc)
    return None


def make_reportlab_image_high_quality(buf: io.BytesIO, max_width_pt: float, max_height_pt: float) -> Image:
    """
    Create a HIGH-QUALITY ReportLab Image with proper DPI settings and aspect ratio preservation.
    Ensures images fit properly without clipping, regardless of AOI size.
    """
    try:
        buf.seek(0)
        pil_img = PILImage.open(buf)
        
        # Get original dimensions
        px_w, px_h = pil_img.size
        
        # Set high DPI for print quality
        target_dpi = 300
        
        # Calculate dimensions in points (1 inch = 72 points)
        img_w_pt = (px_w / target_dpi) * 72
        img_h_pt = (px_h / target_dpi) * 72
        
        # Calculate aspect ratio
        aspect_ratio = px_w / px_h
        
        # Scale to fit within max dimensions while maintaining aspect ratio
        # This ensures no clipping regardless of AOI shape/size
        if img_w_pt <= 0 or img_h_pt <= 0:
            # Fallback for invalid dimensions
            scale = 1.0
        else:
            width_scale = max_width_pt / img_w_pt
            height_scale = max_height_pt / img_h_pt
            # Use the smaller scale to ensure it fits in both dimensions
            scale = min(width_scale, height_scale, 1.0)
        
        draw_w = img_w_pt * scale
        draw_h = img_h_pt * scale
        
        # Additional safety check to ensure we don't exceed bounds
        if draw_w > max_width_pt:
            draw_w = max_width_pt
            draw_h = draw_w / aspect_ratio
        if draw_h > max_height_pt:
            draw_h = max_height_pt
            draw_w = draw_h * aspect_ratio
        
        # Save with high quality
        out_buf = io.BytesIO()
        pil_img.save(out_buf, format='PNG', optimize=False, compress_level=1, dpi=(target_dpi, target_dpi))
        out_buf.seek(0)
        
        # Create ReportLab image with calculated dimensions
        rl_img = Image(out_buf, width=draw_w, height=draw_h)
        
        logger.debug(f"Image sized: {px_w}x{px_h}px -> {draw_w:.1f}x{draw_h:.1f}pt (max: {max_width_pt}x{max_height_pt}pt)")
        
        return rl_img
        
    except Exception as e:
        logger.error(f"Error creating high-quality image: {e}")
        # Fallback: use original buffer with max dimensions
        try:
            buf.seek(0)
            pil_img = PILImage.open(buf)
            px_w, px_h = pil_img.size
            aspect_ratio = px_w / px_h if px_h > 0 else 1.0
            
            # Fit within bounds
            if max_width_pt / aspect_ratio <= max_height_pt:
                width = max_width_pt
                height = max_width_pt / aspect_ratio
            else:
                height = max_height_pt
                width = max_height_pt * aspect_ratio
            
            buf.seek(0)
            return Image(buf, width=width, height=height)
        except:
            buf.seek(0)
            return Image(buf, width=max_width_pt, height=max_height_pt)



def _render_single_param_chart(series: list, outbuf, param_key: str, title: str, color: str = '#2E7D32'):
    """
    Plots a single parameter (e.g. PCA, LAI, CLRe, or Soil Moisture) over time.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from datetime import datetime as _dt
    import numpy as np

    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=140)
    ax.set_facecolor('#FAFAFA')
    fig.patch.set_facecolor('white')

    dates, vals = [], []
    for row in series:
        v = row.get(param_key) or row.get(param_key + '_mm')
        if v is None:
            continue
        try:
            d = _dt.strptime(row['date'], '%Y-%m-%d')
            dates.append(d)
            vals.append(float(v))
        except Exception:
            continue

    if len(vals) == 0:
        ax.text(0.5, 0.5, 'No data available', ha='center', va='center',
                transform=ax.transAxes, fontsize=10, color='grey')
    else:
        ax.plot(dates, vals, color=color, linestyle='-', linewidth=2.0, marker='o', markersize=4)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=5))
        fig.autofmt_xdate(rotation=30, ha='right')
        # ax.set_ylabel('Index Value', fontsize=8)
        ax.grid(True, alpha=0.3, linewidth=0.8)

    ax.set_title(title + ' Trend', fontsize=18, fontweight='bold', pad=6)
    plt.tight_layout(pad=0.8)
    fig.savefig(outbuf, format='png', bbox_inches='tight', dpi=140)
    plt.close(fig)

  

def generate_field_intelligence_summary(deep_stats: dict, start_date: str, end_date: str, crop_name: str, aoi_name: str = "Field", language: str = "en") -> str:
    """
    Generates an expert agricultural summary using either Claude or Gemini API based on environment variables.
    """
    
    if not deep_stats or deep_stats.get('error') or deep_stats.get('basic_stats') is None:
        return f"<b>Field Intelligence Summary ({start_date} to {end_date})</b><br/>Adequate satellite data was not available to compute deep spatial statistics for this period."

    s = deep_stats.get('basic_stats', {})
    c = deep_stats.get('correlations', {})
    r = deep_stats.get('regressions', {})
    z = deep_stats.get('spatial_zones', {}) or {}
    application_date = deep_stats.get('application_date', None)
    temporal_stats = deep_stats.get('temporal_stats', [])  # Per-image 15-day stats

    def g(key, decimals=4):
        val = s.get(key)
        if val is None: return 'N/A'
        return round(val, decimals)

    def get_reg(reg_result, coef_idx):
        try: return round(reg_result['coefficients'][coef_idx][0], 4)
        except: return 'N/A'

    def get_corr(corr_result):
        try: return round(corr_result.get('correlation', 0), 4)
        except: return 'N/A'

    def get_pval(corr_result):
        try:
            pval = corr_result.get('p-value', 1)
            if pval < 0.001: return '< 0.001 (highly significant)'
            elif pval < 0.05: return f'{pval:.4f} (significant)'
            else: return f'{pval:.4f} (not significant)'
        except: return 'N/A'

    total_pixels = max(
        1,
        int(
            (z.get('all_high_response', 0) or 0)
            + (z.get('early_cire_response', 0) or 0)
            + (z.get('structural_growth_only', 0) or 0)
            + (z.get('no_response', 0) or 0)
        )
    )

    def pct(count_key):
        try:
            return round(100.0 * float(z.get(count_key, 0) or 0) / float(total_pixels), 1)
        except Exception:
            return 0.0

    p_full   = pct('all_high_response')
    p_early  = pct('early_cire_response')
    p_struct = pct('structural_growth_only')
    p_low    = pct('no_response')

    # Build temporal trend text from per-image 15-day stats
    temporal_trend_text = ""
    if temporal_stats:
        lines = []
        for ts in temporal_stats:
            date = ts.get('date', 'N/A')
            st   = ts.get('stats', {})
            ch   = st.get('CropHealth_mean')
            lai  = st.get('LAI_mean')
            cl   = st.get('CIre_mean')
            ch_s = f"{ch:.3f}" if ch is not None else 'N/A'
            lai_s = f"{lai:.2f}" if lai is not None else 'N/A'
            cl_s  = f"{cl:.3f}" if cl is not None else 'N/A'
            lines.append(f"  {date}: CropHealth={ch_s}, LeafArea={lai_s}, Greenness={cl_s}")
        temporal_trend_text = "\n".join(lines)

    # Build a simple, non‑technical HTML summary prompt
    ai_prompt = f"""
You are an agronomy advisor. Write in very simple, farmer‑friendly language.
Avoid technical words like "regression", "skew", "correlation", "LAI", "CIre" or "PCA".
Do not mention statistics, equations or pixel counts. Talk only about crop condition and area in percent.
Use short sentences and no bullet points. Output must be HTML using <b>, <br/>, and <i>.
IMPORTANT: Do NOT use colloquial Hindi terms of address or greetings such as "Bhai Sahab" (भाई साहब), "Bhaiya" (भैया), or "किसान भाई" (Kisan Bhai). Do NOT address the farmer as "Bhai Sahab" or similar informal terms. Keep the language polite, professional, and address the farmer in a neutral/standard respectful manner without informal titles.

FIELD CONTEXT:
- Location: {aoi_name}
- Analysis period: {start_date} to {end_date}
- Fertilizer application date: {application_date or 'Not specified'}

SUMMARY NUMBERS (FOR YOUR REFERENCE ONLY, DO NOT REPEAT AS RAW STATS):
- Overall crop health average (0–10 style score): {g('CropHealth_mean')}
- Share of area with strong response (health, leaves and greenness all high): {p_full}% of the field
- Share of area with early greenness but leaf growth still catching up: {p_early}% of the field
- Share of area with more leaf growth but weaker greenness response: {p_struct}% of the field
- Share of area with weak or no visible response yet: {p_low}% of the field
{f'''
TEMPORAL EVOLUTION (one observation every ~15 days — use this to describe how the crop changed over time):
{temporal_trend_text}
Higher CropHealth = better overall condition. Higher LeafArea = more canopy growth. Higher Greenness = stronger chlorophyll.
''' if temporal_trend_text else ''}
Please write a 5–7 sentence continuous summary that:
1) Explains in plain words how well the field has responded to fertilizer overall.
2) Describes how much of the field is doing very well, doing okay, and still weak, using percentages of area (for example "around one‑third of the field").
3) If temporal data is available, describes how the crop condition changed over time (e.g. improved after a certain date, dipped, peaked).
4) Clearly points out if the response is uniform or patchy across the field.
5) Ends with one or two direct, practical suggestions for the farmer.
"""

    if language == "hi":
        ai_prompt += "\nIMPORTANT: You must write your ENTIRE final response strictly in the Hindi language. Translate all information to Hindi."

    ai_text = ""
    # Try Claude first if available
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        try:
            import requests as _req
            response = _req.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01"
                },
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 1000,
                    "messages": [{"role": "user", "content": ai_prompt}]
                },
                timeout=30
            )
            if response.status_code == 200:
                ai_text = response.json()['content'][0]['text']
        except Exception as e:
            logger.warning(f"Claude failed: {e}")

    # Fallback to Gemini (direct REST API — SDK model names are deprecated)
    if not ai_text:
        try:
            from dotenv import load_dotenv as _ldenv
            _ldenv()  # Reload .env in case Flask didn't pick it up
        except Exception:
            pass
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if gemini_key and gemini_key != "YOUR_GEMINI_API_KEY_HERE":
            import requests as _req
            for _model in ['gemini-2.5-flash-lite', 'gemini-2.5-flash-preview-05-20', 'gemini-2.5-flash']:
                try:
                    _url = f"https://generativelanguage.googleapis.com/v1beta/models/{_model}:generateContent?key={gemini_key}"
                    _body = {
                        "contents": [{"parts": [{"text": ai_prompt}]}],
                        "generationConfig": {"maxOutputTokens": 1200, "temperature": 0.6}
                    }
                    _r = _req.post(_url, json=_body, timeout=40)
                    if _r.status_code == 200:
                        ai_text = _r.json()['candidates'][0]['content']['parts'][0]['text']
                        if ai_text:
                            logger.info(f"Gemini AI success with {_model}")
                            break
                    else:
                        logger.warning(f"Gemini {_model} HTTP {_r.status_code}: {_r.text[:120]}")
                except Exception as _e:
                    logger.warning(f"Gemini {_model} failed: {_e}")

    if ai_text:
        clean_html = ai_text.replace('```html', '').replace('```', '').strip()
        # Clean up colloquial Hindi addressings like "Bhai Sahab", "bhai sahab", "भाई साहब", "भैया", "bhaiya", "किसान भाई", "किसान भाई साहब"
        for phrase in [
            "Bhai Sahab,", "bhai sahab,", "Bhai Sahab", "bhai sahab",
            "भाई साहब,", "भाई साहब", "भैया,", "भैया", "bhaiya,", "bhaiya",
            "किसान भाई,", "किसान भाई", "किसान भाई साहब,", "किसान भाई साहब"
        ]:
            clean_html = clean_html.replace(phrase, "")
        
        # Clean up spaces/punctuation leftovers
        clean_html = clean_html.replace(" ,", ",").replace(",,", ",").strip()
        if clean_html.startswith(","):
            clean_html = clean_html[1:].strip()
        clean_html = clean_html.strip()
        
        # Ensure the summary is wrapped with a clear title if the model did not add one
        if "Field Intelligence Summary" not in clean_html:
            clean_html = f"<b>Field Intelligence Summary ({start_date} to {end_date})</b><br/>" + clean_html
        return clean_html

    fallback_corr = get_corr(c.get('LAI_vs_CIre', {}))
    return f"<b>Field Intelligence Summary ({start_date} to {end_date})</b><br/>Fertilizer response analysis complete. Correlation between canopy density (LAI) and chlorophyll (CIre) is {fallback_corr}. Please configure an API key for full AI synthesis."

def create_perfect_context_map(aoi, zoom=18, padding=150):
    """
    Generate a 100% mathematically accurate context map directly on the backend using Satellite maps.
    """
    try:
        # 1. Extract coordinates and find bounding box
        coords_list = []
        geom_type = aoi.get('geometry', {}).get('type')
        coords = aoi.get('geometry', {}).get('coordinates', [])
        
        if geom_type == 'Polygon':
            for ring in coords:
                coords_list.extend(ring)
        elif geom_type == 'MultiPolygon':
            for poly in coords:
                for ring in poly:
                    coords_list.extend(ring)
        else:
            return None # Fallback if unknown
            
        if not coords_list:
            return None
            
        lons = [pt[0] for pt in coords_list]
        lats = [pt[1] for pt in coords_list]
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)
        
        # 2. Determine required XYZ tiles
        min_x, min_y = lonlat_to_tile_xy(min_lon, max_lat, zoom)
        max_x, max_y = lonlat_to_tile_xy(max_lon, min_lat, zoom)
        
        tile_min_x = int(math.floor(min_x)) - 1
        tile_max_x = int(math.floor(max_x)) + 1
        tile_min_y = int(math.floor(min_y)) - 1
        tile_max_y = int(math.floor(max_y)) + 1
        
        # Calculate canvas size
        cols = tile_max_x - tile_min_x + 1
        rows = tile_max_y - tile_min_y + 1
        
        canvas_w = cols * 256
        canvas_h = rows * 256
        
        # Stitch canvas
        canvas = PILImage.new('RGB', (canvas_w, canvas_h), (255, 255, 255))
        
        headers = {'User-Agent': 'MapZest-ReportGenerator/1.0'}
        for tx in range(tile_min_x, tile_max_x + 1):
            for ty in range(tile_min_y, tile_max_y + 1):
                url = f"https://mt1.google.com/vt/lyrs=s&x={tx}&y={ty}&z={zoom}"
                try:
                    r = requests.get(url, headers=headers, timeout=10)
                    if r.status_code == 200:
                        tile_img = PILImage.open(io.BytesIO(r.content)).convert('RGB')
                        px = (tx - tile_min_x) * 256
                        py = (ty - tile_min_y) * 256
                        canvas.paste(tile_img, (px, py))
                except Exception as e:
                    logger.warning(f"Failed to fetch tile {url}: {e}")
                    
        # 3. Draw Polygons
        draw = ImageDraw.Draw(canvas)
        
        all_px_x = []
        all_px_y = []
        
        def process_ring(ring):
            px_pts = []
            for pt in ring:
                tx_pt, ty_pt = lonlat_to_tile_xy(pt[0], pt[1], zoom)
                px = int((tx_pt - tile_min_x) * 256)
                py = int((ty_pt - tile_min_y) * 256)
                px_pts.append((px, py))
                all_px_x.append(px)
                all_px_y.append(py)
            return px_pts
            
        def draw_ring(ring):
            px_pts = process_ring(ring)
            if px_pts:
                pts = px_pts + [px_pts[0]] # Close the ring
                draw.line(pts, fill='#006400', width=8) # Dark Green thick
                draw.line(pts, fill='#90EE90', width=4) # Light Green thin center

        if geom_type == 'Polygon':
            for ring in coords:
                draw_ring(ring)
        elif geom_type == 'MultiPolygon':
            for poly in coords:
                for ring in poly:
                    draw_ring(ring)

        # Crop tightly
        if all_px_x and all_px_y:
            c_min_x = max(0, min(all_px_x) - padding)
            c_min_y = max(0, min(all_px_y) - padding)
            c_max_x = min(canvas_w, max(all_px_x) + padding)
            c_max_y = min(canvas_h, max(all_px_y) + padding)
            canvas = canvas.crop((c_min_x, c_min_y, c_max_x, c_max_y))
            
        buf = io.BytesIO()
        canvas.save(buf, format='PNG')
        buf.seek(0)
        return buf
    except Exception as e:
        logger.error(f"Error creating perfect context map: {e}", exc_info=True)
        return None

def generate_report_response(payload: dict):
    """Build and return the 2-page PDF report as a Flask response."""

    if not payload:
        raise ValueError("No JSON payload received")

    language = payload.get("language", "en").lower()
    if language not in ["en", "hi"]:
        language = "en"
    lang_strings = get_translations(language)

    crop_name   = payload.get("crop_name", "Crop")
    aoi         = payload.get("aoi")
    aoi_coords  = None
    center_lat  = payload.get("centroid_lat")
    center_lon  = payload.get("centroid_lon")
    area_ha     = payload.get("area_ha") or 0
    try:
        aoi_coords = aoi["geometry"]["coordinates"]
    except Exception:
        pass

    # Derive centroid from AOI if frontend didn't send it
    if (center_lat is None or center_lon is None) and aoi_coords:
        try:
            polygon = aoi_coords[0] if isinstance(aoi_coords[0][0], (list, tuple)) else aoi_coords
            center_lon = sum(p[0] for p in polygon) / len(polygon)
            center_lat = sum(p[1] for p in polygon) / len(polygon)
        except Exception:
            pass

    location_text = payload.get("location")
    if not location_text and center_lat is not None and center_lon is not None:
        try:
            location_text = get_location_name(center_lat, center_lon) or f"{round(center_lat,5)}, {round(center_lon,5)}"
        except Exception:
            location_text = None

    start_date      = payload.get("start_date", "")
    end_date        = payload.get("end_date", "")
    metrics         = payload.get("metrics") or {}
    series          = payload.get("series") or []

    # ── 15-day gap filtering ───────────────────────────────────────────────
    # Apply rolling minimum-gap filter so that consecutive images used in the
    # report are at least 15 days apart (greedy, Sentinel-2 anchored).
    series = filter_series_to_15day_gap(series, min_gap_days=15)
    # Extract the selected dates to pass to the deep-stats endpoint so it can
    # build its composite and per-image stats from the same set of images.
    selected_s2_dates = extract_s2_dates_from_series(series)
    logger.info(f"Selected S2 dates for report ({len(selected_s2_dates)}): {selected_s2_dates}")
    # ──────────────────────────────────────────────────────────────────────
    backend_url     = payload.get("backend_url") or os.environ.get("BACKEND_URL") or "http://localhost:6000"
    logo_path       = get_logo_path(payload.get("logo_path"))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=8 * mm,
        bottomMargin=10 * mm,
    )


    pdf_font_name = "Helvetica"
    pdf_font_bold = "Helvetica-Bold"
    pdf_font_italic = "Helvetica-Oblique"

    # Hindi font setup (inside generate_report_response)
    if language == "hi":
        try:
            # Try to find and load a Devanagari font
            hindi_font_path = get_hindi_font_path()

            if hindi_font_path and os.path.exists(hindi_font_path):
                # Register with shapable=True for complex script support
                pdfmetrics.registerFont(TTFont("HindiFont", hindi_font_path, shapable=True))
                pdf_font_name = "HindiFont"
                pdf_font_bold = "HindiFont"
                pdf_font_italic = "HindiFont"

                # Also register bold/italic variants if available
                bold_path = hindi_font_path.replace("Regular", "Bold")
                if os.path.exists(bold_path):
                    pdfmetrics.registerFont(TTFont("HindiFont-Bold", bold_path, shapable=True))
                    pdf_font_bold = "HindiFont-Bold"

                logger.info(f"Successfully loaded Hindi font from: {hindi_font_path}")
            else:
                # Fallback to Arial Unicode MS which has some Devanagari support
                fallback_paths = [
                    "C:/Windows/Fonts/ARIALUNI.TTF",
                    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
                ]
                for fb_path in fallback_paths:
                    if os.path.exists(fb_path):
                        pdfmetrics.registerFont(TTFont("HindiFont", fb_path))
                        pdf_font_name = "HindiFont"
                        pdf_font_bold = "HindiFont"
                        pdf_font_italic = "HindiFont"
                        logger.warning(f"Using fallback font for Hindi: {fb_path}")
                        break
                else:
                    logger.warning("No Hindi font found. Text may not render correctly.")
        except Exception as e:
            logger.error(f"Failed to load Hindi font: {e}")
            traceback.print_exc()

    styles  = getSampleStyleSheet()
    W       = doc.width            # usable width
    
    # Tighten spacing for Hindi to ensure content fits on 2 pages
    is_hi = (language == "hi")
    line_leading = 12.5 if is_hi else 14.5
    para_space = 3 if is_hi else 5
    
    normal  = ParagraphStyle(
        "Normal2",
        parent=styles["Normal"],
        fontName=pdf_font_name,
        fontSize=9.5,
        leading=line_leading,
        spaceAfter=para_space,
        wordSelectMethod='shaping' if is_hi else 'default'
    )
    caption = ParagraphStyle("Caption", fontName=pdf_font_italic,
                              fontSize=8, leading=10, alignment=1, textColor=colors.grey,
                              wordSelectMethod='shaping' if is_hi else 'default')
    maplab  = ParagraphStyle("MapLabel", fontName=pdf_font_bold,
                              fontSize=8.5, leading=11, alignment=1,
                              wordSelectMethod='shaping' if is_hi else 'default')

    story = []

    # ══════════════════════════════════════════════════════════════════
    # PAGE 1 ‑ Header + AI Deep Summary
    # ══════════════════════════════════════════════════════════════════

    # ── Header table
    logo_img = None
    if logo_path and os.path.exists(logo_path):
        try:
            pil_logo = PILImage.open(logo_path)
            pil_logo.thumbnail((160, 60), PILImage.LANCZOS)
            logo_buf = io.BytesIO()
            pil_logo.save(logo_buf, format="PNG")
            logo_buf.seek(0)
            logo_img = Image(logo_buf, width=pil_logo.width * 0.72, height=pil_logo.height * 0.72)
        except Exception:
            pass

    header_left = logo_img or Paragraph("<b>KrishiZest</b>", ParagraphStyle("Logo", fontSize=14, fontName=pdf_font_bold, textColor=colors.HexColor("#2E7D32")))
    period_str   = f"{start_date}  →  {end_date}"
    loc_str      = location_text or "—"
    header_right = Paragraph(
        f"<b>{lang_strings.get('report_title', 'Precision Agriculture Report')}</b><br/>"
        f"<font size='8'>{crop_name}  |  {period_str}  |  {loc_str}</font>",
        ParagraphStyle("HdrRight", fontName=pdf_font_name, fontSize=10.5, leading=14, alignment=2, textColor=colors.HexColor("#212121"))
    )

    hdr_table = Table([[header_left, header_right]], colWidths=[W*0.35, W*0.65])
    hdr_table.setStyle(TableStyle([
        ('VALIGN',  (0,0), (-1,-1), 'MIDDLE'), ('ALIGN',   (1,0), (1,0),   'RIGHT'),
        ('LINEBELOW', (0,0), (-1,0), 1.2, colors.HexColor("#2E7D32")), ('BOTTOMPADDING', (0,0), (-1,0), 6),
    ]))
    story.append(hdr_table)
    story.append(Spacer(1, 2 if is_hi else 3))

    # ── Area & Location info bar ──────────────────────────────────────
    info_style = ParagraphStyle(
        "InfoCell",
        fontName=pdf_font_name,
        fontSize=8.5,
        leading=12,
        alignment=1,
        textColor=colors.HexColor("#1B5E20"),
    )
    info_label_style = ParagraphStyle(
        "InfoLabel",
        fontName=pdf_font_bold,
        fontSize=7,
        leading=10,
        alignment=1,
        textColor=colors.HexColor("#4CAF50"),
    )

    loc_display   = location_text or u"\u2014"
    area_display  = f"{area_ha:.4f} ha" if area_ha else u"\u2014"
    if center_lat is not None and center_lon is not None:
        latdir = "N" if center_lat >= 0 else "S"
        londir = "E" if center_lon >= 0 else "W"
        coord_display = f"{abs(center_lat):.5f}\u00b0{latdir},  {abs(center_lon):.5f}\u00b0{londir}"
    else:
        coord_display = u"\u2014"

    info_data = [[
        Paragraph("LOCATION",   info_label_style),
        Paragraph("AREA",       info_label_style),
        Paragraph("COORDINATES", info_label_style),
    ], [
        Paragraph(loc_display,   info_style),
        Paragraph(area_display,  info_style),
        Paragraph(coord_display, info_style),
    ]]

    info_table = Table(info_data, colWidths=[W * 0.45, W * 0.2, W * 0.35])
    info_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#F1F8E9")),
        ("BOX",           (0, 0), (-1, -1), 0.8, colors.HexColor("#4CAF50")),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, colors.HexColor("#A5D6A7")),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 2 if is_hi else 5))
    # ─────────────────────────────────────────────────────────────────

    sum_title = lang_strings.get("field_intel_title", "Field Intelligence Analysis")
    story.append(Paragraph(sum_title, ParagraphStyle("SumTitle", fontName=pdf_font_bold, fontSize=13, textColor=colors.HexColor("#2E7D32"), spaceAfter=3 if is_hi else 6, wordSelectMethod='shaping' if is_hi else 'default')))

    # Fetch deep stats
    deep_stats = {}
    if aoi:
        try:
            resp = requests.post(f"{backend_url}/get_deep_spatial_stats", json={
                'aoi': aoi,
                'start_date': start_date,
                'end_date': end_date,
                'scale': 10,
                'selected_dates': selected_s2_dates,   # 15-day-gap selected images
            }, timeout=180)
            if resp.status_code == 200:
                deep_stats = resp.json()
                logger.info(f"Deep stats keys: {list(deep_stats.keys())}")
                logger.info(f"basic_stats: {deep_stats.get('basic_stats')}")
            else:
                logger.error(f"Deep stats endpoint returned {resp.status_code}: {resp.text[:300]}")
        except Exception as e:
            logger.warning(f"Failed to fetch deep stats: {e}")

    # Determine if deep stats are truly available (used to decide whether to show the 0–10 scale)
    has_deep_stats = bool(deep_stats) and not deep_stats.get('error') and bool(deep_stats.get('basic_stats'))

    ai_summary = generate_field_intelligence_summary(deep_stats, start_date, end_date, crop_name, location_text or "Field", language)
    ai_blocks = [b for b in ai_summary.split("\n\n") if b.strip()][:10]
    ai_paragraphs = [Paragraph(sanitize_html_for_reportlab(b), normal) for b in ai_blocks]

    # ── Build AOI map buffer ──────────────────────────────────────────────
    map_col_content = Paragraph("<i>Field map not available</i>", caption)
    if aoi:
        try:
            map_buf = create_perfect_context_map(aoi, zoom=18, padding=150)
            if map_buf:
                pil_shot = PILImage.open(map_buf)
                iw, ih = pil_shot.size
                MAP_COL_W = W * 0.40           # 40% of page width for map column
                TEXT_COL_W = W * 0.57          # 57% for text column (3% gutter)
                max_map_h = 90 * mm            # generous vertical budget
                mscale = min(MAP_COL_W / iw, max_map_h / ih)
                map_buf.seek(0)
                map_col_content = Image(map_buf, width=iw * mscale, height=ih * mscale)
        except Exception as e:
            logger.warning(f"AOI map failed: {e}")
    else:
        MAP_COL_W  = W * 0.40
        TEXT_COL_W = W * 0.57

    MAP_COL_W  = W * 0.40
    TEXT_COL_W = W * 0.57

    # ── Health scale widget (compact, fits in text column) ────────────────
    health_scale_rows = None
    if has_deep_stats:
        weak_color     = colors.HexColor("#FFCDD2")
        moderate_color = colors.HexColor("#FFF9C4")
        strong_color   = colors.HexColor("#C8E6C9")
        weak_high      = colors.HexColor("#EF9A9A")
        moderate_high  = colors.HexColor("#FFF59D")
        strong_high    = colors.HexColor("#A5D6A7")

        legend_rows = [
            [
                Paragraph(lang_strings.get("health_weak",     "0–3<br/><i>Weak</i>"),     ParagraphStyle("LL", parent=normal, alignment=1, fontSize=8)),
                Paragraph(lang_strings.get("health_moderate", "4–7<br/><i>Moderate</i>"), ParagraphStyle("LM", parent=normal, alignment=1, fontSize=8)),
                Paragraph(lang_strings.get("health_strong",   "8–10<br/><i>Strong</i>"),  ParagraphStyle("LH", parent=normal, alignment=1, fontSize=8)),
            ],
            ["", "", ""],
        ]
        overall_score = None
        try:
            bs = deep_stats.get('basic_stats', {}) if deep_stats else {}
            ch_mean = bs.get('CropHealth_mean')
            if isinstance(ch_mean, (int, float)):
                overall_score = max(0.0, min(10.0, round(float(ch_mean) * 10.0, 1)))
        except Exception:
            pass

        marker_col = None
        if overall_score is not None:
            score_int = int(round(overall_score))
            marker_col = 0 if score_int <= 3 else (1 if score_int <= 7 else 2)
            legend_rows[1][marker_col] = Paragraph(str(score_int), ParagraphStyle("SI", parent=normal, alignment=1, fontSize=10))

        col_w3 = TEXT_COL_W / 3.0
        legend_table = Table(legend_rows, colWidths=[col_w3, col_w3, col_w3], rowHeights=[9*mm, 4*mm])
        legend_cmds = [
            ('BACKGROUND', (0,0),(0,0), weak_color),
            ('BACKGROUND', (1,0),(1,0), moderate_color),
            ('BACKGROUND', (2,0),(2,0), strong_color),
            ('VALIGN',     (0,0),(-1,-1), 'MIDDLE'),
            ('ALIGN',      (0,0),(-1,-1), 'CENTER'),
            ('BOX',        (0,0),(-1,-1), 0.5, colors.grey),
            ('INNERGRID',  (0,0),(-1,-1), 0.3, colors.grey),
        ]
        if marker_col is not None:
            hi_colors = [weak_high, moderate_high, strong_high]
            legend_cmds.append(('BACKGROUND', (marker_col,0),(marker_col,0), hi_colors[marker_col]))
            legend_cmds.append(('BOX', (marker_col,0),(marker_col,1), 1.0, colors.black))
        legend_table.setStyle(TableStyle(legend_cmds))
        health_scale_rows = legend_table

    # ── Assemble text column ──────────────────────────────────────────────
    from reportlab.platypus import KeepInFrame

    scale_title_p = Paragraph(
        lang_strings.get("health_scale_title", "Overall Crop Health Scale (0–10)"),
        ParagraphStyle("ScTitle", fontName=pdf_font_name, fontSize=8, leading=10,
                       textColor=colors.HexColor("#2E7D32"), spaceAfter=2)
    ) if has_deep_stats else None

    map_title_p = Paragraph(
        lang_strings.get("aoi_map_main_title", "Area of Interest Map"),
        ParagraphStyle("MapTitleInner", fontName=pdf_font_bold, fontSize=9,
                       textColor=colors.HexColor("#2E7D32"), alignment=1, spaceAfter=2)
    )
    map_subtitle_p = Paragraph(
        lang_strings.get("aoi_map_subtitle", "Field boundary shown on satellite imagery."),
        ParagraphStyle("MapSubInner", fontName=pdf_font_italic, fontSize=7,
                       textColor=colors.grey, alignment=1, spaceAfter=4)
    )

    text_col_items = ai_paragraphs[:]
    if has_deep_stats and scale_title_p:
        text_col_items.append(Spacer(1, 3))
        text_col_items.append(scale_title_p)
        text_col_items.append(health_scale_rows)
    text_col_items.append(Spacer(1, 4))

    # Wrap text column in KeepInFrame so it never overflows
    text_frame = KeepInFrame(
        maxWidth=TEXT_COL_W,
        maxHeight=105 * mm,
        content=text_col_items,
        mode='shrink',
    )

    map_frame_items = [map_title_p, map_subtitle_p, map_col_content]
    map_frame = KeepInFrame(
        maxWidth=MAP_COL_W,
        maxHeight=105 * mm,
        content=map_frame_items,
        mode='shrink',
    )

    # ── 2-column table: [text | map] ──────────────────────────────────────
    side_by_side = Table(
        [[text_frame, map_frame]],
        colWidths=[TEXT_COL_W, MAP_COL_W],
    )
    side_by_side.setStyle(TableStyle([
        ('VALIGN',       (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING',  (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING',   (0,0), (-1,-1), 0),
        ('BOTTOMPADDING',(0,0), (-1,-1), 0),
        ('LINEAFTER',    (0,0), (0,0), 0.5, colors.HexColor("#A5D6A7")),  # subtle divider
    ]))
    story.append(side_by_side)
    story.append(Spacer(1, 4))

    # ══════════════════════════════════════════════════════════════════
    # Parameter Analysis Setup & Layout
    # ══════════════════════════════════════════════════════════════════
    ROW_H_P1   = 118 * mm  # Single row fills remaining Page 1 space (available ~124mm)
    ROW_H_P2   = 78 * mm   # 3 rows × 78mm = 234mm, fills Page 2 (~240mm usable after title)
    col_map_w = W * 0.48
    col_chart_w = W * 0.52

    MAP_PARAMS = [
        ('pca',         'Crop Health',       'pca',          '#2E7D32', True),
        ('chlorophyll', 'Chlorophyll',       'clre',         '#558B2F', True),
        ('lai',         'Leaf Area Index',   'lai',          '#1565C0', True),
        ('soilmoisture','Soil Moisture',     'soilmoisture', '#6A1B9A', False),
    ]

    import concurrent.futures

    def _fetch_vra(args):
        param, label, s2_force = args
        try:
            result = create_high_quality_vra_mosaic(
                aoi, start_date, end_date, param,
                backend_url=backend_url, final_size=1200,
                force_sentinel2=s2_force
            )
            return param, result
        except Exception as e:
            logger.warning(f"Parallel VRA fetch failed for {param}: {e}")
            return param, None

    # Fetch all 4 VRA maps in PARALLEL to avoid sequential blocking
    vra_results_map = {}
    if aoi:
        logger.info("⚡ Launching parallel VRA map fetches...")
        fetch_args = [(param, label, s2_force) for (param, label, chart_key, color, s2_force) in MAP_PARAMS]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_fetch_vra, arg): arg[0] for arg in fetch_args}
            for future in concurrent.futures.as_completed(futures):
                param_key, vra_res = future.result()
                vra_results_map[param_key] = vra_res
        logger.info("✅ All parallel VRA fetches complete.")

    def _build_param_row(idx, param, label, chart_key, color, ROW_H):
        """Build a single parameter row: [nested_table] with fixed height."""
        map_u_str = lang_strings.get("map_unavailable", "Map unavailable")
        map_cell  = Paragraph(f"<i>{map_u_str}</i>",
                        ParagraphStyle("NoMap", fontSize=7, alignment=1, textColor=colors.grey))
        if aoi:
            try:
                vra_result = vra_results_map.get(param)
                tile_buf = vra_result[0] if vra_result and len(vra_result) >= 3 else None
                vra_data = vra_result[1] if vra_result and len(vra_result) >= 3 else None
                zoom = vra_result[2] if vra_result and len(vra_result) >= 3 else 15
                if tile_buf:
                    pil = PILImage.open(tile_buf)
                    styled = add_vra_legend(pil, param, vra_data, label, aoi=aoi, zoom_level=zoom)
                    sbuf = BytesIO()
                    styled.save(sbuf, format='PNG', optimize=True)
                    sbuf.seek(0)
                    iw, ih = styled.size
                    avail_w = col_map_w - 2 * mm
                    avail_h = ROW_H - 10 * mm   # 10mm for label row (6mm) + padding
                    scale = min(avail_w / iw, avail_h / ih)
                    map_cell = Image(sbuf, width=iw * scale, height=ih * scale)
                else:
                    # No map returned — build a parameter-specific informative message
                    if param == 'chlorophyll':
                        info_msg = lang_strings.get("chlorophyll_na_msg") or "Chlorophyll map unavailable"
                    else:
                        info_msg = f"<i>{label} {map_u_str}</i>"
                    
                    map_cell = Paragraph(info_msg,
                        ParagraphStyle("NoMapInfo", fontSize=7.5, alignment=1,
                                       textColor=colors.HexColor("#555555"), leading=11, spaceAfter=4,
                                       wordSelectMethod='shaping' if is_hi else 'default'))
            except Exception as e:
                logger.warning(f"Map failed for {param}: {e}")
                if param == 'chlorophyll':
                    map_cell = Paragraph(
                        lang_strings.get("chlorophyll_short_na") or "Chlorophyll map unavailable",
                        ParagraphStyle("NoMapInfo", fontSize=7.5, alignment=1,
                                       textColor=colors.HexColor("#555555"), leading=11,
                                       wordSelectMethod='shaping' if is_hi else 'default'))

        # 2. Chart Image
        chart_buf = io.BytesIO()
        _render_single_param_chart(series, chart_buf, chart_key, label, color)
        chart_buf.seek(0)

        # Read actual chart pixel size and fit to cell
        chart_pil = PILImage.open(chart_buf)
        cw, ch = chart_pil.size
        avail_w = col_chart_w - 4 * mm
        avail_h = ROW_H - 12 * mm
        cscale  = min(avail_w / cw, avail_h / ch)
        chart_buf.seek(0)
        chart_cell = Image(chart_buf, width=cw * cscale, height=ch * cscale)

        # ── Label row + content row ───────────────────────────────────────
        label_para = Paragraph(
            f"<b>{label}</b>",
            ParagraphStyle("ParamLbl", fontName="Helvetica-Bold", fontSize=8,
                           alignment=0, textColor=colors.HexColor("#1B5E20"))
        )
        # Each parameter = 2 sub-rows: [label spanning both cols] + [map | chart]
        # Encode as single row with nested table for precise sizing
        inner = Table(
            [[label_para, ""], [map_cell, chart_cell]],
            colWidths=[col_map_w, col_chart_w],
            rowHeights=[6 * mm, ROW_H - 6 * mm],
        )
        inner.setStyle(TableStyle([
            ('SPAN',          (0, 0), (1, 0)),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING',    (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        return inner

    # ══════════════════════════════════════════════════════════════════════
    # PAGE 1 TAIL — "Detailed Parameter Analysis" title + first param row
    # ══════════════════════════════════════════════════════════════════════
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Detailed Parameter Analysis",
        ParagraphStyle("P1ParamTitle", fontName="Helvetica-Bold", fontSize=11,
                       textColor=colors.HexColor("#2E7D32"), spaceAfter=3, alignment=1)
    ))

    # Build first parameter row (Crop Health) with Page-1 row height
    first_row = _build_param_row(0, *MAP_PARAMS[0][:4], ROW_H_P1)
    p1_table = Table([[first_row]], colWidths=[W], rowHeights=[ROW_H_P1])
    p1_table.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING',    (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 0),
    ]))
    story.append(p1_table)

    # ══════════════════════════════════════════════════════════════════════
    # PAGE 2 — Remaining 3 parameter rows
    # ══════════════════════════════════════════════════════════════════════
    story.append(PageBreak())

    # story.append(Paragraph(
    #     "Detailed Parameter Analysis (continued)",
    #     ParagraphStyle("P2Title", fontName="Helvetica-Bold", fontSize=12,
    #                    textColor=colors.HexColor("#2E7D32"), spaceAfter=4, alignment=1)
    # ))

    remaining_params = MAP_PARAMS[1:]
    table_data  = []
    row_heights = []
    for idx, (param, label, chart_key, color, s2_force) in enumerate(remaining_params, start=1):
        row = _build_param_row(idx, param, label, chart_key, color, ROW_H_P2)
        table_data.append([row])
        row_heights.append(ROW_H_P2)

    outer = Table(table_data, colWidths=[W], rowHeights=row_heights)
    outer.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING',    (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 0),
        ('LINEBELOW', (0,0), (-1, len(remaining_params)-2), 0.5, colors.HexColor("#C8E6C9")),
    ]))
    story.append(outer)


    # ── Build PDF ─────────────────────────────────────────────────────
    location_text_safe = location_text or "Field"
    draw_header = make_draw_header(location_text_safe, location_text_safe,
                                   left_title=lang_strings.get('report_title'),
                                   crop_name=crop_name,
                                   report_date=datetime.utcnow().strftime("%Y-%m-%d"))

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/pdf",         
        as_attachment=True,
        download_name=f"KrishiZest_Report_{start_date}_{end_date}.pdf",
    )

