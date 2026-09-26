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


def filter_series_to_15day_gap(series: list, start_date_str: str = None) -> list:
    """
    Filters a time-series list based on 15-day sequential windows.
    Starting from start_date_str, selects the observation in each 15-day window
    that has valid parameter data. If no data exists in the window, it falls back
    to any available observation in that window.
    """
    if not series:
        return series

    def _parse_date(item: dict):
        raw = item.get('date') or item.get('day') or item.get('year_month') or ''
        try:
            return datetime.strptime(str(raw)[:10], '%Y-%m-%d')
        except Exception:
            return None

    def _has_valid_data(item: dict) -> bool:
        # Check if any of the actual parameter keys have a valid (non-None, non-NaN) value.
        # These are the exact keys used in the series data for this project.
        PARAM_KEYS = ['pca', 'clre', 'lai', 'soilmoisture', 'soilmoisture_mm']
        for k in PARAM_KEYS:
            v = item.get(k)
            if v is not None:
                try:
                    f = float(v)
                    if f == f:  # NaN check (NaN != NaN)
                        return True
                except (TypeError, ValueError):
                    pass
        return False

    dated = [(item, _parse_date(item)) for item in series]
    dated = [(item, d) for item, d in dated if d is not None]
    dated.sort(key=lambda x: x[1])

    if not dated:
        return []

    if start_date_str:
        try:
            anchor_date = datetime.strptime(str(start_date_str)[:10], '%Y-%m-%d')
        except Exception:
            anchor_date = dated[0][1]
    else:
        anchor_date = dated[0][1]

    if anchor_date > dated[-1][1]:
        anchor_date = dated[0][1]
        
    end_date = dated[-1][1]
    selected = []
    
    current_window_start = anchor_date
    while current_window_start <= end_date:
        current_window_end = current_window_start + timedelta(days=14)
        
        pts_in_window = [
            (item, d) for item, d in dated 
            if current_window_start <= d <= current_window_end
        ]
        
        if pts_in_window:
            # Try to find one with valid data first
            valid_pts = [p for p in pts_in_window if _has_valid_data(p[0])]
            
            if valid_pts:
                # Of those with valid data, pick the one closest to window end
                valid_pts.sort(key=lambda x: abs((x[1] - current_window_end).days))
                selected.append(valid_pts[0][0])
            else:
                # Fallback to any in window, closest to window end
                pts_in_window.sort(key=lambda x: abs((x[1] - current_window_end).days))
                selected.append(pts_in_window[0][0])
            
        current_window_start = current_window_start + timedelta(days=15)

    logger.info(
        f"[15-day Window Filter] {len(series)} items → {len(selected)} selected "
        f"(Start anchor = {anchor_date.strftime('%Y-%m-%d')})"
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

REPORT_SUBTITLE = "CropHealth Report"


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
            
            logger.info(f"ðŸ“ AOI Size: ~{aoi_area_km2:.2f} km² ({lon_span:.4f}Â° x {lat_span:.4f}Â°)")
            
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
            logger.info("ðŸ” Very Small AOI detected - Using HIGH zoom (18) and HIGH resolution (3200px, 600 DPI)")
            
        elif aoi_area_km2 < 0.5:  # Small AOI (0.1-0.5 km² ≈ 10-50 hectares)
            initial_zoom = 17
            max_tiles = 25
            dynamic_final_size = 2800
            dpi_setting = (500, 500)
            logger.info("ðŸ” Small AOI detected - Using HIGH zoom (17) and HIGH resolution (2800px, 500 DPI)")
            
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
            logger.info("ðŸ—ºï¸ Very Large AOI detected - Using LOWER zoom (14) and resolution (2200px, 300 DPI)")
        
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

                        # High-contrast black outer + yellow inner — visible on all imagery.
                        outer_w = max(8, current_zoom - 8)
                        inner_w = max(4, outer_w - 4)
                        draw.line(pixel_points, fill='black', width=outer_w + 2)
                        draw.line(pixel_points, fill='#FFFF00', width=inner_w)
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
            
            logger.info(f"ðŸ“ VRA AOI Size: ~{aoi_area_km2:.2f} km²")
            
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
        
        # --- Fetch Satellite Background Template ---
        # Using Google Satellite directly to perfectly match the main context map and guarantee it loads!
        sat_tile_url_template = "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
        
        # Fetch tiles
        tile_size = 256
        tiles = {}
        sat_tiles = {}
        successful = 0
        
        for tx in range(tile_min_x, tile_max_x + 1):
            for ty in range(tile_min_y, tile_max_y + 1):
                try:
                    # 1. Fetch VRA Tile
                    tile_url = tile_url_template.replace('{x}', str(tx)).replace('{y}', str(ty)).replace('{z}', str(current_zoom))
                    if '{s}' in tile_url: tile_url = tile_url.replace('{s}', 'a')
                    tile_response = requests.get(tile_url, timeout=60)
                    if tile_response.status_code == 200:
                        tiles[(tx, ty)] = PILImage.open(BytesIO(tile_response.content)).convert('RGBA')
                        successful += 1
                        
                    # 2. Fetch SAT Tile
                    if sat_tile_url_template:
                        sat_url = sat_tile_url_template.replace('{x}', str(tx)).replace('{y}', str(ty)).replace('{z}', str(current_zoom))
                        if '{s}' in sat_url: sat_url = sat_url.replace('{s}', 'a')
                        
                        sat_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                        for attempt in range(3):
                            try:
                                sat_response = requests.get(sat_url, headers=sat_headers, timeout=10)
                                if sat_response.status_code == 200:
                                    sat_tiles[(tx, ty)] = PILImage.open(BytesIO(sat_response.content)).convert('RGBA')
                                    break
                            except Exception as e:
                                if attempt == 2:
                                    logger.warning(f"Failed to fetch SAT tile ({tx}, {ty}) after 3 attempts: {e}")
                except Exception as e:
                    logger.debug(f"Failed to fetch VRA/SAT tile ({tx}, {ty}): {e}")
                    continue

        if not tiles:
            logger.warning(f"No VRA tiles fetched for {parameter}")
            return None, None
        
        logger.info(f"📦 Fetched {successful}/{total_tiles} VRA tiles (and {len(sat_tiles)} SAT tiles)")
        
        # Stitch both mosaics
        mosaic_width = width_tiles * tile_size
        mosaic_height = height_tiles * tile_size
        vra_mosaic = PILImage.new('RGB', (mosaic_width, mosaic_height), (0, 0, 0))
        sat_mosaic = PILImage.new('RGB', (mosaic_width, mosaic_height), (255, 255, 255))  # White fallback so it blends into PDF
        
        for (tx, ty), tile_img in tiles.items():
            x_pos = (tx - tile_min_x) * tile_size
            y_pos = (ty - tile_min_y) * tile_size
            vra_mosaic.paste(tile_img.convert('RGB'), (x_pos, y_pos))
            if (tx, ty) in sat_tiles:
                sat_mosaic.paste(sat_tiles[(tx, ty)].convert('RGB'), (x_pos, y_pos))

        # --- Build AOI polygon mask (white inside field, black outside) ---
        # This is the KEY fix: we clip VRA colors to the exact field boundary
        aoi_mask = PILImage.new('L', (mosaic_width, mosaic_height), 0)  # black = outside
        mask_draw = ImageDraw.Draw(aoi_mask)
        try:
            polygons = _extract_aoi_outer_rings(aoi)
            for poly_coords in polygons:
                pixel_points = []
                for pt in poly_coords:
                    if isinstance(pt, list) and len(pt) >= 2:
                        lon, lat = pt[0], pt[1]
                        tx_f, ty_f = lonlat_to_tile_xy(lon, lat, current_zoom)
                        px = (tx_f - tile_min_x) * tile_size
                        py = (ty_f - tile_min_y) * tile_size
                        pixel_points.append((px, py))
                if len(pixel_points) >= 3:
                    mask_draw.polygon(pixel_points, fill=255)  # white = inside field
        except Exception as e:
            logger.warning(f"Failed to build AOI mask: {e}")

        # Composite: satellite base, then paste VRA only inside the AOI polygon
        composite = sat_mosaic.copy()
        composite.paste(vra_mosaic, mask=aoi_mask)
        mosaic = composite

        # Draw AOI boundary outline (white line for contrast over satellite)
        if draw_aoi_outline and aoi:
            try:
                draw = ImageDraw.Draw(mosaic)
                polygons = _extract_aoi_outer_rings(aoi)
                for poly_coords in polygons:
                    pixel_points = []
                    for pt in poly_coords:
                        if isinstance(pt, list) and len(pt) >= 2:
                            lon, lat = pt[0], pt[1]
                            tx_f, ty_f = lonlat_to_tile_xy(lon, lat, current_zoom)
                            px = (tx_f - tile_min_x) * tile_size
                            py = (ty_f - tile_min_y) * tile_size
                            pixel_points.append((px, py))
                    if len(pixel_points) >= 2:
                        if pixel_points[0] != pixel_points[-1]:
                            pixel_points.append(pixel_points[0])
                        draw.line(pixel_points, fill='white', width=2)
            except Exception as e:
                logger.warning(f"Failed to draw VRA AOI outline: {e}")

        # Crop tightly around the AOI bounding box (using mask bbox)
        bbox = aoi_mask.getbbox()
        if bbox:
            left, upper, right, lower = bbox
            pad = 60
            left = max(0, left - pad)
            upper = max(0, upper - pad)
            right = min(mosaic.width, right + pad)
            lower = min(mosaic.height, lower + pad)
            mosaic = mosaic.crop((left, upper, right, lower))
        
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
            f"ðŸ“ Calculated map scale: {label} (map width: {map_width_m:.0f} m, "
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
        label_size = 26   # Legend label font size
        stats_size = 22   # Statistics text font size
        
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
            n_font_size = 120  # Very large for visibility
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
            'soilmoisture': ['#54278f', '#756bb1', '#9e9ac8', '#bcbddc', '#dadaeb'],
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
        
        # Load fonts - dynamic label size so labels don't collide under zone blocks
        font_paths = [
            "arial.ttf", "Arial.ttf", "arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "C:\\Windows\\Fonts\\arial.ttf", "C:\\Windows\\Fonts\\arialbd.ttf"
        ]
        
        legend_width = int(mosaic_w * 0.80)
        num_zones = len(colors)
        zone_w = legend_width // num_zones
        label_size = max(55, min(90, int(zone_w * 0.44)))
        stats_size = 22
        title_size = 26
        
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

        # -- Draw Premium North Arrow --
        try:
            arrow_size = 250
            # Place arrow slightly to the left of the map mosaic
            arrow_x = max(20, paste_x - arrow_size - 40)
            arrow_y = padding + 20
            
            # Use the same style as the context map (black/gray compass triangle)
            draw.polygon([
                (arrow_x + arrow_size // 2, arrow_y), 
                (arrow_x, arrow_y + arrow_size), 
                (arrow_x + arrow_size, arrow_y + arrow_size)
            ], fill='black', outline='red')

            
            draw.polygon([
                (arrow_x + arrow_size // 2, arrow_y), 
                (arrow_x, arrow_y + arrow_size), 
                (arrow_x + arrow_size // 2, arrow_y + arrow_size // 2)
            ], fill='gray')
            
            n_font_size = 120

            try:
                n_font = ImageFont.truetype(font_paths[2], n_font_size) # bold Arial
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
            
            draw.text((n_x, n_y), n_text, fill='black', font=n_font,
                      stroke_width=2, stroke_fill='white')
        except Exception as e:
            logger.warning(f"Could not draw north arrow: {e}")
        
        # Draw Scale Bar (simple solid bar, using accurate length from calculate_map_scale)
        try:
            scale_bar_width = 500
            scale_bar_height = 60
            scale_x = paste_x + 60
            scale_y = paste_y + mosaic_h - 240  # Moved 100px UP so text doesn't overflow the bottom edge!
            
            if aoi:
                # calculate_map_scale already assumes a 500‑px bar; keep width=500 so distance stays correct
                _, scale_max_text = calculate_map_scale(aoi, zoom_level, mosaic_w)
            else:
                scale_max_text = "500m" 

            # Draw a simple solid bar (White with Black Outline for high visibility)
            draw.rectangle(
                [scale_x, scale_y, scale_x + scale_bar_width, scale_y + scale_bar_height],
                fill=(255, 255, 255),
                outline=(0, 0, 0),
                width=3
            )
            
            scale_font_size = 120  # Increased size
            try:
                scale_font = ImageFont.truetype(font_paths[2], scale_font_size)  # font_paths[2] is BOLD Arial
            except:
                scale_font = stats_font
            
            # Draw text as White with a Black stroke so it's visible anywhere
            draw.text((scale_x, scale_y + scale_bar_height + 8), "0", fill=(255, 255, 255), font=scale_font, stroke_width=3, stroke_fill='black')

            max_bbox = draw.textbbox((0, 0), scale_max_text, font=scale_font)
            max_width = max_bbox[2] - max_bbox[0]
            max_x = scale_x + scale_bar_width - max_width
            draw.text((max_x, scale_y + scale_bar_height + 8), scale_max_text, fill=(255, 255, 255), font=scale_font, stroke_width=3, stroke_fill='black')
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
        legend_y = paste_y + mosaic_h + 30
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
            "logo_alt": "MapZest Agricultural Intelligence",
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
            "param_analysis_title": "Detailed Analysis",
            "map_unavailable": "Map unavailable",
            "chlorophyll_na_msg": "<b>Chlorophyll (CLRe) map not available.</b><br/>This layer requires Sentinel-2 red-edge bands (B5/B7).<br/>No Sentinel-2 imagery was found for the selected date range.<br/><i>Try a wider date range to include a cloud-free image.</i>",
            "chlorophyll_short_na": "<b>Chlorophyll map unavailable</b><br/><i>Sentinel-2 data not found for selected period.</i>",
        },
        "hi": {
            "logo_alt": "MapZest कृषि बुद्धिमत्ता",
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



def _render_single_param_chart(series: list, outbuf, param_key: str, title: str,
                                color: str = '#2E7D32', application_date: str = None,
                                start_date: str = None, end_date: str = None):
    """
    Plots a single parameter over time with enhanced visualization:
    - Shaded fill under the trend line
    - Mean reference line (dashed)
    - Fertilizer application date vertical marker (red dotted)
    - Stats annotation box (min / max / mean / trend)
    - Unit label on Y-axis
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from datetime import datetime as _dt

    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=140)
    ax.set_facecolor('#F8FAFB')
    fig.patch.set_facecolor('white')

    # Unit labels for Y-axis
    _UNITS = {
        'pca':            'Crop Health (0–1)',
        'clre':           'CIre Index',
        'lai':            'm² leaf / m² ground',
        'soilmoisture':   '%',
        'soilmoisture_mm':'%',
        'ndvi':           'NDVI (0–1)',
        'cwsi':           'Stress Index (0–1)',
        'lst':            '°C',
        'lst_c':          '°C',
        'etc':            'mm / day',
        'cwr':            'mm / day',
        'kc':             'Kc',
    }
    unit_label = _UNITS.get(param_key, 'Value')

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
        ax.text(0.5, 0.5,
                'No data available for this period.\nTry a wider date range.',
                ha='center', va='center', transform=ax.transAxes,
                fontsize=9, color='#888888',
                bbox=dict(boxstyle='round,pad=0.5', facecolor='#F5F5F5', alpha=0.9))
    else:
        # â”€â”€ Main trend line â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        ax.plot(dates, vals, color=color, linestyle='-', linewidth=2.2,
                marker='o', markersize=5, zorder=5)

        # â”€â”€ Shaded area fill under line â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        ax.fill_between(dates, vals, alpha=0.13, color=color, zorder=2)

        # â”€â”€ Mean / Threshold reference line â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        mean_val = sum(vals) / len(vals)

        # â”€â”€ Fertilizer application date marker â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if application_date:
            try:
                app_dt = _dt.strptime(str(application_date)[:10], '%Y-%m-%d')
                if dates[0] <= app_dt <= dates[-1]:
                    ax.axvline(app_dt, color='#C62828', linestyle=':', linewidth=2.0,
                               alpha=0.85, zorder=6, label='Fertilizer Applied')
                    ylims = ax.get_ylim()
                    ax.text(app_dt, ylims[0] + (ylims[1] - ylims[0]) * 0.96,
                            '  â†“ Fert.', color='#C62828', fontsize=7,
                            va='top', ha='left', fontweight='bold')
            except Exception:
                pass

        # â”€â”€ Y-axis + X-axis formatting â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if start_date and end_date:
            try:
                sd = _dt.strptime(str(start_date)[:10], '%Y-%m-%d')
                ed = _dt.strptime(str(end_date)[:10], '%Y-%m-%d')
                ax.set_xlim(sd, ed)
            except Exception:
                pass

        ax.set_ylabel(unit_label, fontsize=8, color='#444444')
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=6))
        fig.autofmt_xdate(rotation=45, ha='right')
        ax.grid(True, alpha=0.15, linewidth=0.6, color='#AAAAAA')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#DDDDDD')
        ax.spines['bottom'].set_color('#DDDDDD')

        # â”€â”€ Legend â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if application_date:
            ax.legend(fontsize=7, loc='lower left', framealpha=0.88,
                      edgecolor='#CCCCCC', ncol=2)
        else:
            ax.legend(fontsize=7, loc='lower left', framealpha=0.88,
                      edgecolor='#CCCCCC')

    ax.set_title(title + ' Trend', fontsize=14, fontweight='bold', pad=7, color='#1A1A1A')
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
Please write exactly 4 short, concise lines (separated by <br/>). DO NOT use bullet point symbols (like • or -).
Use the "%" symbol for percentages (e.g., "45%"). Do NOT write the word "percent". Include the specific percentage details provided above.
Format each line to start with a short bold title, followed by a very concise statement:
<b>Overall Response:</b> [1 brief sentence on how well the field responded overall].<br/>
<b>Field Breakdown:</b> [1 brief sentence listing the exact percentages (%) of area that are strong, moderate, or weak].<br/>
<b>Timeline Trend:</b> [1 brief sentence describing how the crop condition changed over the period].<br/>
<b>Action Item:</b> [1 direct, practical suggestion for the farmer].
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
        # Do NOT prepend the 'Field Intelligence Summary' heading — the section title already shows it
        return clean_html

    fallback_corr = get_corr(c.get('LAI_vs_CIre', {}))
    return f"<b>Field Intelligence Summary ({start_date} to {end_date})</b><br/>Fertilizer response analysis complete. Correlation between canopy density (LAI) and chlorophyll (CIre) is {fallback_corr}. Please configure an API key for full AI synthesis."


def generate_farmer_report_sections(deep_stats: dict, series: list, start_date: str, end_date: str,
                                     crop_name: str, field_name: str = "Field",
                                     language: str = "en") -> dict:
    """
    Generates structured farmer-friendly report content for the new 2-page layout.
    Returns a dict with: status, status_color, season_summary, what_happened,
    key_findings, action_plan, map_descriptions.
    Uses Claude (primary) → Gemini (fallback) APIs.
    """

    # ── 1. Compute data-driven values ──────────────────────────────────────
    s = (deep_stats or {}).get('basic_stats', {}) or {}
    z = (deep_stats or {}).get('spatial_zones', {}) or {}
    temporal_stats = (deep_stats or {}).get('temporal_stats', []) or []

    total_px = max(1, int(
        (z.get('all_high_response', 0) or 0)
        + (z.get('early_cire_response', 0) or 0)
        + (z.get('structural_growth_only', 0) or 0)
        + (z.get('no_response', 0) or 0)
    ))
    def _pct(k):
        try:
            return round(100.0 * float(z.get(k, 0) or 0) / float(total_px), 1)
        except Exception:
            return 0.0

    p_full   = _pct('all_high_response')
    p_early  = _pct('early_cire_response')
    p_struct = _pct('structural_growth_only')
    p_low    = _pct('no_response')

    # Overall status from CropHealth score
    ch_mean = s.get('CropHealth_mean')
    if ch_mean is not None:
        score_10 = max(0.0, min(10.0, float(ch_mean) * 10.0))
    else:
        score_10 = None

    if score_10 is None:
        status        = "Needs attention"
        status_color  = "#B0BEC5"   # grey — no data
    elif score_10 < 3.3:
        status        = "Needs attention"
        status_color  = "#D32F2F"   # red
    elif score_10 <= 6.7:
        status        = "Average performance"
        status_color  = "#F57C00"   # orange
    else:
        status        = "Good performance"
        status_color  = "#2E7D32"   # green

    # Build temporal summary for AI
    # Build stage-specific temporal breakdown for AI
    temporal_lines = []
    if series and len(series) >= 3:
        n = len(series)
        early_slice = series[:max(1, n // 3)]
        mid_slice   = series[max(1, n // 3) : max(2, 2 * n // 3)]
        end_slice   = series[max(2, 2 * n // 3):]

        def _slice_summary(slc, stage_name, phase_desc):
            dates = [r.get('date', '') for r in slc if r.get('date')]
            d_str = f"({dates[0]} to {dates[-1]})" if len(dates) >= 2 else (f"({dates[0]})" if dates else "")
            ndvis = [float(r.get('ndvi') or 0) for r in slc if r.get('ndvi') is not None]
            avg_ndvi = sum(ndvis) / len(ndvis) if ndvis else None
            lais = [float(r.get('lai') or 0) for r in slc if r.get('lai') is not None]
            avg_lai = sum(lais) / len(lais) if lais else None
            c_desc = 'healthy early vigor' if avg_ndvi and avg_ndvi > 0.5 else 'slow initial emergence'
            if 'mid' in stage_name.lower():
                c_desc = 'peak vegetative vigor' if avg_ndvi and avg_ndvi > 0.55 else 'moderate canopy vigor with uneven spots'
            elif 'end' in stage_name.lower():
                c_desc = 'maturation and grain filling' if avg_ndvi and avg_ndvi > 0.45 else 'late-season senescence and dry-down'
            cov_desc = 'dense canopy' if avg_lai and avg_lai > 2.2 else 'moderate canopy' if avg_lai and avg_lai > 1.2 else 'sparse/thin cover'
            return f"  - {stage_name} {d_str} [{phase_desc}]: Crop Condition was {c_desc}, Plant Cover was {cov_desc}."

        temporal_lines.append(_slice_summary(early_slice, "Early season", "Germination & Emergence"))
        temporal_lines.append(_slice_summary(mid_slice, "Middle of season", "Peak Vegetative Growth & Canopy Spread"))
        temporal_lines.append(_slice_summary(end_slice, "End of season", "Maturation, Grain-Filling & Senescence"))
    elif temporal_stats:
        n = len(temporal_stats)
        idx_early, idx_mid, idx_end = 0, n // 2, n - 1
        t_e, t_m, t_end = temporal_stats[idx_early], temporal_stats[idx_mid], temporal_stats[idx_end]
        temporal_lines.append(f"  - Early season ({t_e.get('date', 'Early')}): Initial seedling emergence and establishment after sowing.")
        temporal_lines.append(f"  - Middle of season ({t_m.get('date', 'Mid')}): Active vegetative growth and peak canopy spread across the field.")
        temporal_lines.append(f"  - End of season ({t_end.get('date', 'End')}): Maturation, grain filling, and harvest readiness.")
    else:
        temporal_lines.append("  - Early season: Sowing, germination, and early seedling emergence.")
        temporal_lines.append("  - Middle of season: Vegetative growth, branching/tillering, and canopy expansion.")
        temporal_lines.append("  - End of season: Maturation, grain filling, and natural leaf dry-down.")
    temporal_summary = "\n".join(temporal_lines)

    # Compute average soil moisture for data-driven summary
    sm_list = []
    for r in (series or []):
        v = r.get('soilmoisture') or r.get('soilmoisture_mm')
        if v is not None:
            try:
                sm_list.append(float(v))
            except Exception:
                pass
    sm_avg = round(sum(sm_list) / len(sm_list), 2) if sm_list else None
    sm_summary = f"average {sm_avg} m³/m³" if sm_avg is not None else "observed seasonal levels"

    # ── 2. Build AI prompt ──────────────────────────────────────────────────
    lang_instr = (
        "\nIMPORTANT: Write your ENTIRE response in simple Hindi language. "
        "Use farmer-friendly Hindi only.\n"
    ) if language == "hi" else ""

    ai_prompt = f"""You are KrishiZest, an agricultural assistant. Write a seasonal field performance report.
Your audience is non-technical farmers and FPO staff. Use simple, clear English.
{lang_instr}
IMPORTANT RULES:
1. Do NOT use any of these technical words: NDVI, LAI, CIre, PCA, CropHealth, regression, correlation, pixel, index value, average, minimum, maximum, formula.
2. Instead use these farmer-friendly terms only:
   - "Overall Crop Condition" instead of Crop Health / NDVI
   - "Leaf Greenness" instead of Chlorophyll / CIre
   - "Plant Cover and Crop Density" instead of LAI
   - "Available Soil Moisture" instead of Soil Moisture index
3. Use cautious language: "Satellite observations suggest...", "This may indicate...", "A field visit is recommended to confirm."
4. Do NOT prescribe specific fertiliser doses, pesticide names, or irrigation quantities.
5. Keep all text short and practical.
6. MAP LEGEND & COLOR SPECIFICATIONS (CRITICAL):
   All 4 maps display a 5-step relative legend bar labeled: "Highest", "High", "Moderate", "Low", "Lowest".
   - Overall Crop Condition, Leaf Greenness, and Plant Cover maps are strictly shades of GREEN (Dark green = Highest/High, Medium green = Moderate, Pale/Light green = Low/Lowest).
   - Available Soil Moisture map is strictly shades of PURPLE/VIOLET (Dark purple = Highest/High, Pale lavender = Low/Lowest).
   - ABSOLUTELY NEVER mention red, yellow, orange, or blue. These colors are NOT in the maps.
   - Describe what the maps show by referencing the legend bar ("Highest" down to "Lowest") and the color tones.
   - The action in "What to do" (MAP_*_DO) must directly reference the lagging zones from "What this map shows" (MAP_*_SHOWS) — e.g. ground inspection of 'Low' or 'Lowest' zones on the legend bar to verify soil, nutrient, or water issues.
7. WHAT_HAPPENED RULES (CRITICAL - NO REPETITION):
   - Early season row MUST describe seedling emergence and initial ground cover establishment after sowing.
   - Middle of season row MUST describe active vegetative growth, peak canopy spread, flowering, and any mid-season stress or uneven growth.
   - End of season row MUST describe crop maturation, grain filling, natural drying-down (senescence) of leaves, and harvest readiness.
   - STRICT PROHIBITION: DO NOT repeat the same sentence or same phrase across the 3 rows. Each of the 3 rows MUST describe a completely different life cycle phase!

FIELD DATA (reference only — do NOT repeat raw numbers):
- Crop: {crop_name}
- Field: {field_name}
- Period: {start_date} to {end_date}
- Overall Crop Condition: {p_full}% strong response, {p_low}% weak/lagging response
- Leaf Greenness (Chlorophyll): {p_early}% moderate-to-high active response
- Plant Cover & Crop Density: {p_struct}% moderate canopy coverage
- Available Soil Moisture: {sm_summary} across root zone
- Overall seasonal status: {status}
- Crop Life Cycle Stages:
{temporal_summary}

OUTPUT FORMAT — follow EXACTLY, including section headers with colons:

SEASON_SUMMARY:
[Write 50–70 words. Plain language. Explain how the crop performed during this season. Use "Satellite observations suggest..." style. Do not use technical terms.]

WHAT_HAPPENED:
Early season | [1 short sentence on seedling emergence & early ground cover] | [1 simple interpretation of early establishment]
Middle of season | [1 short sentence on mid-season canopy growth & peak vigor] | [1 simple interpretation of mid-season development]
End of season | [1 short sentence on crop maturation & pre-harvest condition] | [1 simple interpretation of harvest readiness]

KEY_FINDINGS:
[Overall crop condition finding — 1 sentence]
[Leaf greenness finding — 1 sentence]
[Plant cover and crop density finding — 1 sentence]
[Available soil moisture finding — 1 sentence]
[Uneven field performance observation — 1 sentence, mention if some areas are better/worse]

ACTION_PLAN:
High | [urgent practical action — max 10–12 words, crisp and direct] | [timing — e.g. "Before next sowing"]
High | [another urgent action — max 10–12 words] | [timing]
Medium | [moderate priority action — max 10–12 words] | [timing]
Medium | [another medium action — max 10–12 words] | [timing]
Low | [low priority action — max 10–12 words] | [timing]

MAP_CROP_HEALTH_SHOWS: [20–35 words describing what the Overall Crop Condition map shows using the legend bar ("Highest" to "Lowest") and green tones. Dark green = 'Highest'/'High', pale green = 'Low'/'Lowest'. Do NOT mention red or yellow.]
MAP_CROP_HEALTH_DO: [15–25 words describing one practical action directly targeting the 'Low' and 'Lowest' zones identified on the map — e.g. inspect roots and soil in 'Low' and 'Lowest' zones.]
MAP_LEAF_GREENNESS_SHOWS: [20–35 words describing Leaf Greenness using the legend bar and green tones. Dark green = 'Highest' greenness, pale green = 'Low'/'Lowest'. Do NOT mention red or yellow.]
MAP_LEAF_GREENNESS_DO: [15–25 words describing one practical action targeting the 'Low' greenness zones — e.g. inspect 'Low' greenness zones for nutrient stress.]
MAP_PLANT_COVER_SHOWS: [20–35 words describing Plant Cover and Crop Density using the legend bar. Dark green = 'Highest' canopy cover, light green = 'Low'/'Lowest' density. Do NOT mention red or yellow.]
MAP_PLANT_COVER_DO: [15–25 words describing one practical action targeting 'Low' density zones — e.g. check sparse/Low density areas for plant spacing or seed emergence.]
MAP_SOIL_MOISTURE_SHOWS: [20–35 words describing Available Soil Moisture using the legend bar and purple tones. Dark purple = 'Highest' moisture, pale lavender = 'Low'/'Lowest' moisture. Do NOT mention blue, red, or yellow.]
MAP_SOIL_MOISTURE_DO: [15–25 words describing one practical action targeting 'Low' moisture zones — e.g. inspect 'Low' moisture zones for irrigation reach and drainage uniformity.]
"""

    # ── 3. Call AI (Claude → Gemini fallback) ──────────────────────────────────
    import requests as _req
    raw_text = ""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        try:
            _r = _req.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01"
                },
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 1800,
                    "messages": [{"role": "user", "content": ai_prompt}]
                },
                timeout=45
            )
            if _r.status_code == 200:
                raw_text = _r.json()['content'][0]['text']
                logger.info("Farmer report sections: Claude success")
        except Exception as e:
            logger.warning(f"Claude failed for farmer sections: {e}")

    if not raw_text:
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if not gemini_key or gemini_key == "YOUR_GEMINI_API_KEY_HERE":
            if os.path.exists(".env"):
                try:
                    with open(".env", "r") as _ef:
                        for _line in _ef:
                            if _line.startswith("GEMINI_API_KEY"):
                                gemini_key = _line.split("=")[1].strip().strip('"').strip("'")
                                break
                except Exception:
                    pass

        if gemini_key and gemini_key != "YOUR_GEMINI_API_KEY_HERE":
            for _model in ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash']:
                try:
                    _url = f"https://generativelanguage.googleapis.com/v1beta/models/{_model}:generateContent?key={gemini_key}"
                    gen_config = {
                        "maxOutputTokens": 4096,
                        "temperature": 0.3,
                    }
                    if '2.5' in _model:
                        gen_config["thinkingConfig"] = {"thinkingBudget": 0}
                    _r = _req.post(_url, json={
                        "contents": [{"parts": [{"text": ai_prompt}]}],
                        "generationConfig": gen_config
                    }, timeout=45)
                    if _r.status_code == 200:
                        raw_text = _r.json()['candidates'][0]['content']['parts'][0]['text']
                        logger.info(f"Farmer report sections: Gemini {_model} success (length {len(raw_text)})")
                        break
                    else:
                        logger.warning(f"Gemini {_model} status {_r.status_code}: {_r.text[:200]}")
                except Exception as e:
                    logger.warning(f"Gemini {_model} failed: {e}")

    # ── 4. Parse AI output ──────────────────────────────────────────────────
    import re as _re
    def _extract_block(text, marker):
        """Extract lines after 'MARKER:' until next ALL-CAPS marker."""
        lines = text.split('\n')
        in_block = False
        result = []
        for line in lines:
            stripped = line.strip()
            cleaned = stripped.lstrip('*#_ ').rstrip('*_ ')
            if cleaned.upper().startswith(marker.upper() + ':'):
                in_block = True
                rest = cleaned[len(marker)+1:].strip().strip('*_').strip()
                if rest:
                    result.append(rest)
                continue
            if in_block:
                if cleaned and ':' in cleaned:
                    key = cleaned.split(':')[0].strip().replace('*', '').replace('#', '').replace('_', '')
                    if (key.isupper() and len(key) > 3) or key in [
                        'WHATHAPPENED', 'KEYFINDINGS', 'ACTIONPLAN',
                        'SEASONSUMMARY', 'MAPCROPHEALTHSHOWS', 'MAPCROPHEALTHDO',
                        'MAPLEAFGREENNESSSHOWS', 'MAPLEAFGREENNESSDO',
                        'MAPPLANTCOVERSHOWS', 'MAPPLANTCOVERDO',
                        'MAPSOILMOISTURESHOWS', 'MAPSOILMOISTUREDO'
                    ]:
                        break
                result.append(stripped.strip('*_'))
        return [r for r in result if r]

    def _extract_inline(text, marker):
        """Extract value from 'MARKER: value' on one line."""
        for line in text.split('\n'):
            cleaned = line.strip().lstrip('*#_ ').rstrip('*_ ')
            if cleaned.upper().startswith(marker.upper() + ':'):
                return cleaned[len(marker)+1:].strip().strip('*_').strip()
            m = _re.match(rf'^\**#*\s*{_re.escape(marker)}\**\s*:\s*(.*)$', line.strip(), _re.IGNORECASE)
            if m:
                return m.group(1).strip().strip('*_').strip()
        return ""

    # Parse each section
    season_summary = " ".join(_extract_block(raw_text, 'SEASON_SUMMARY'))

    what_happened_raw = _extract_block(raw_text, 'WHAT_HAPPENED')
    what_happened = []
    for row in what_happened_raw:
        parts = [p.strip() for p in row.split('|')]
        if len(parts) >= 3:
            what_happened.append(parts[:3])
    if not what_happened:
        what_happened = [
            ["Early season",      "Crop established after sowing with initial seedling emergence.", "Satellite observations suggest initial early growth and ground cover."],
            ["Middle of season",  "Field developed towards peak vegetative canopy with variable vigor.", "Some field zones maintained good growth while others showed slower coverage."],
            ["End of season",     "Crop reached maturity and grain-filling stage as harvest approached.", "Natural late-season maturation and dry-down reflected earlier growth differences."],
        ]
    elif len(what_happened) >= 3:
        # Check if rows are identical or near-identical copies
        c0 = what_happened[0][1].strip().lower()
        c1 = what_happened[1][1].strip().lower()
        c2 = what_happened[2][1].strip().lower()
        if c0 == c1 or c1 == c2 or c0 == c2:
            if language == "hi":
                what_happened[0] = ["Early season", "बुवाई के बाद फसल का प्रारंभिक अंकुरण और जमाव शुरू हुआ।", "शुरुआती चरण में पौधों की स्थापना और पत्तों का हरापन देखा गया।"]
                what_happened[1] = ["Middle of season", "वानस्पतिक वृद्धि के दौरान फसल का फैलाव हुआ लेकिन विभिन्न क्षेत्रों में असमानता दिखी।", "सक्रिय विकास के समय कुछ हिस्सों में अच्छी वृद्धि रही जबकि कमजोर हिस्सों में तनाव रहा।"]
                what_happened[2] = ["End of season", "फसल परिपक्वता और दाना भरने की अवस्था में पहुंची और कटाई के लिए तैयार हुई।", "अंतिम अवस्था में पत्तों का स्वाभाविक पीलापन और पकाई देखी गई।"]
            else:
                what_happened[0] = ["Early season", "Initial seedling emergence and early ground coverage began after sowing.", "Early vegetative establishment showed healthy initial leaf development."]
                what_happened[1] = ["Middle of season", "Canopy expanded towards peak growth, with noticeable variation across field zones.", "Stronger zones maintained active vigor while lagging areas showed limited coverage."]
                what_happened[2] = ["End of season", "Crop reached maturity and grain-filling stage as harvest approached.", "Natural leaf senescence and maturation reflected earlier seasonal growth patterns."]

    key_findings_raw = _extract_block(raw_text, 'KEY_FINDINGS')
    key_findings = [f.lstrip('•-').strip() for f in key_findings_raw if f.strip() and not f.strip().startswith('KEY_FINDINGS')]
    if not key_findings:
        key_findings = [
            f"Overall crop condition was {status.lower()} during the review period.",
            "Leaf greenness varied across different parts of the field.",
            "Plant cover and crop density showed uneven distribution.",
            "Available soil moisture levels fluctuated during the season.",
            "Some field zones performed better than others — a field inspection is recommended.",
        ]

    action_plan_raw = _extract_block(raw_text, 'ACTION_PLAN')
    action_plan = []
    for row in action_plan_raw:
        parts = [p.strip() for p in row.split('|')]
        if len(parts) >= 3:
            action_plan.append(parts[:3])
    if not action_plan:
        action_plan = [
            ["High",   "Conduct soil sampling from stronger and weaker zones of the field.", "Before next sowing"],
            ["High",   "Inspect low-performing areas for germination, pest, or waterlogging signs.", "After next sowing"],
            ["Medium", "Review irrigation reach and drainage across the field.", "Before next sowing"],
            ["Medium", "Take field photographs at regular intervals during next season.", "Every 15 days"],
            ["Low",    "Compare next season's performance with this report.", "End of next season"],
        ]

    def _clean_map_text(text: str, is_soil: bool = False) -> str:
        """Sanitize any accidental references to red, yellow, orange, or blue."""
        if not text:
            return ""
        t = text
        t = _re.sub(r'\b(red and yellow|yellow and red|red or yellow|yellow or red)\b', "Low and Lowest", t, flags=_re.IGNORECASE)
        t = _re.sub(r'\b(red|yellow|orange)\s+areas\b', "zones marked as Low or Lowest on the legend bar", t, flags=_re.IGNORECASE)
        t = _re.sub(r'\b(red|yellow|orange)\s+zones\b', "Low or Lowest zones on the legend", t, flags=_re.IGNORECASE)
        t = _re.sub(r'\b(red|yellow|orange)\b', "lower-performing", t, flags=_re.IGNORECASE)
        if not is_soil:
            t = _re.sub(r'\bblue\b', "dark green", t, flags=_re.IGNORECASE)
        else:
            t = _re.sub(r'\bblue\b', "dark purple", t, flags=_re.IGNORECASE)
        t = _re.sub(r'लाल और पीले|पीले और लाल|लाल या पीले', "कम और सबसे कम (Low/Lowest)", t)
        t = _re.sub(r'लाल|पीले|पीला', "कम (Low)", t)
        return t.strip()

    if language == "hi":
        fb_shows_ch = f"लीजेंड बार के अनुसार गहरे हरे क्षेत्र 'Highest' और 'High' फसल स्थिति दर्शाते हैं। हल्के हरे क्षेत्र 'Low' और 'Lowest' स्थिति ({p_low}% क्षेत्र) दर्शाते हैं जहां फसल की वृद्धि कमजोर है।"
        fb_do_ch    = "लीजेंड पर 'Low' और 'Lowest' दर्शाए गए क्षेत्रों का स्थलीय निरीक्षण करें और फसल की जड़ों व मिट्टी की स्थिति की जांच करें।"
        fb_shows_cl = f"लीजेंड बार पर गहरे हरे रंग वाले क्षेत्र 'Highest' पत्तियों का हरापन दर्शाते हैं। हल्के हरे क्षेत्र 'Low' और 'Lowest' स्तर दिखाते हैं ({100.0 - p_early:.1f}% क्षेत्र में कम सक्रियता)।"
        fb_do_cl    = "'Low' और 'Lowest' हरेपन वाले क्षेत्रों में पोषक तत्वों (विशेषकर नाइट्रोजन) की कमी या पत्तियों के तनाव की जांच करें।"
        fb_shows_la = f"गहरे हरे क्षेत्र लीजेंड के अनुसार 'Highest' फसल घनत्व और घने फैलाव को दर्शाते हैं। हल्के हरे क्षेत्र 'Low' विरल आवरण दिखाते हैं ({100.0 - p_struct:.1f}% क्षेत्र)।"
        fb_do_la    = "'Low' घनत्व वाले क्षेत्रों में अंकुरण, पौधों की दूरी और कीट या रोग के प्रभाव की जांच करें।"
        fb_shows_sm = f"गहरे बैंगनी क्षेत्र लीजेंड बार पर 'Highest' नमी दर्शाते हैं। हल्के बैंगनी (लैवेंडर) क्षेत्र 'Low' और 'Lowest' नमी स्तर दर्शाते हैं (औसत नमी: {sm_summary})।"
        fb_do_sm    = "'Low' नमी वाले क्षेत्रों में सिंचाई की पहुंच, ढलान और मिट्टी की जलधारण क्षमता की जांच करें।"
    else:
        fb_shows_ch = f"Dark green areas show 'Highest' to 'High' crop condition on the legend bar. Lighter pale green areas indicate 'Low' to 'Lowest' performance ({p_low}% of field) where vigor is lagging."
        fb_do_ch    = "Prioritize ground visits to areas marked as 'Low' or 'Lowest' on the legend to check root health and soil conditions."
        fb_shows_cl = f"Dark green zones represent 'Highest' leaf greenness and active photosynthesis on the legend bar. Pale green areas indicate 'Low' or 'Lowest' greenness ({100.0 - p_early:.1f}% of field showing lower activity)."
        fb_do_cl    = "Inspect 'Low' and 'Lowest' greenness areas for signs of nutrient deficiency, especially nitrogen, or foliage stress."
        fb_shows_la = f"Dark green areas indicate 'Highest' canopy cover and dense crop growth on the legend. Lighter green areas show 'Low' to 'Lowest' plant density ({100.0 - p_struct:.1f}% sparse canopy)."
        fb_do_la    = "Check 'Low' density zones for poor emergence, uneven seed germination, or localized pest damage."
        fb_shows_sm = f"Dark purple areas indicate 'Highest' available soil moisture on the legend bar. Light lavender areas represent 'Low' to 'Lowest' moisture retention (field average: {sm_summary})."
        fb_do_sm    = "Review irrigation reach, drainage uniformity, and soil compaction in zones showing 'Low' moisture."

    raw_ch_shows = _clean_map_text(_extract_inline(raw_text, 'MAP_CROP_HEALTH_SHOWS'), False)
    raw_ch_do    = _clean_map_text(_extract_inline(raw_text, 'MAP_CROP_HEALTH_DO'), False)
    raw_cl_shows = _clean_map_text(_extract_inline(raw_text, 'MAP_LEAF_GREENNESS_SHOWS'), False)
    raw_cl_do    = _clean_map_text(_extract_inline(raw_text, 'MAP_LEAF_GREENNESS_DO'), False)
    raw_la_shows = _clean_map_text(_extract_inline(raw_text, 'MAP_PLANT_COVER_SHOWS'), False)
    raw_la_do    = _clean_map_text(_extract_inline(raw_text, 'MAP_PLANT_COVER_DO'), False)
    raw_sm_shows = _clean_map_text(_extract_inline(raw_text, 'MAP_SOIL_MOISTURE_SHOWS'), True)
    raw_sm_do    = _clean_map_text(_extract_inline(raw_text, 'MAP_SOIL_MOISTURE_DO'), True)

    map_descriptions = {
        'crop_health': {
            'what_shows': raw_ch_shows if raw_ch_shows else fb_shows_ch,
            'what_to_do': raw_ch_do if raw_ch_do else fb_do_ch,
        },
        'leaf_greenness': {
            'what_shows': raw_cl_shows if raw_cl_shows else fb_shows_cl,
            'what_to_do': raw_cl_do if raw_cl_do else fb_do_cl,
        },
        'plant_cover': {
            'what_shows': raw_la_shows if raw_la_shows else fb_shows_la,
            'what_to_do': raw_la_do if raw_la_do else fb_do_la,
        },
        'soil_moisture': {
            'what_shows': raw_sm_shows if raw_sm_shows else fb_shows_sm,
            'what_to_do': raw_sm_do if raw_sm_do else fb_do_sm,
        },
    }

    if not season_summary:
        season_summary = (
            f"Satellite observations suggest that the {crop_name} crop at {field_name} showed "
            f"{status.lower()} during the period {start_date} to {end_date}. "
            f"Approximately {p_full}% of the field area showed a strong response, while {p_low}% "
            f"showed weak or no visible response. A field visit is recommended to confirm these observations."
        )

    return {
        'status':           status,
        'status_color':     status_color,
        'score_10':         score_10,
        'season_summary':   season_summary,
        'what_happened':    what_happened,
        'key_findings':     key_findings,
        'action_plan':      action_plan,
        'map_descriptions': map_descriptions,
    }

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
                    r = requests.get(url, headers=headers, timeout=20)
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
                draw.line(pts, fill='#FFFF00', width=4)    # Single clean yellow border for context map

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
            
        # â”€â”€ Cartographic Overlays: North Arrow + Scale Bar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            _ov_draw = ImageDraw.Draw(canvas)
            _cw, _ch = canvas.size

            # North Arrow (top-right corner)
            _as = max(60, int(min(_cw, _ch) * 0.12))
            _ax = _cw - _as - 18
            _ay = 18
            # Black outer triangle
            _ov_draw.polygon([
                (_ax + _as // 2, _ay), (_ax, _ay + _as), (_ax + _as, _ay + _as)
            ], fill='black', outline='gray')
            # Gray left half for compass appearance
            _ov_draw.polygon([
                (_ax + _as // 2, _ay), (_ax, _ay + _as), (_ax + _as // 2, _ay + _as // 2)
            ], fill='gray')
            try:
                _nf = ImageFont.truetype("C:\\Windows\\Fonts\\arialbd.ttf", max(14, _as // 3))
            except Exception:
                _nf = ImageFont.load_default()
            _nb = _ov_draw.textbbox((0, 0), "N", font=_nf)
            _nw = _nb[2] - _nb[0]
            _ov_draw.text((_ax + (_as - _nw) // 2, _ay + _as + 5), "N",
                          fill='white', font=_nf, stroke_width=2, stroke_fill='black')

            # Scale Bar (bottom-left corner)
            _blen = int(_cw * 0.22)
            _bx, _by = 18, _ch - 48
            _seg = _blen // 4
            for _si in range(4):
                _fc = 'black' if _si % 2 == 0 else 'white'
                _ov_draw.rectangle(
                    [_bx + _si * _seg, _by, _bx + (_si + 1) * _seg, _by + 10],
                    fill=_fc, outline='black'
                )
            
            # Use calculate_map_scale to get the exact distance
            try:
                _, scale_max_text = calculate_map_scale(aoi, zoom, _cw)
            except Exception:
                scale_max_text = "500m"

            try:
                _sf = ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", 12)
            except Exception:
                _sf = ImageFont.load_default()
            _ov_draw.text((_bx, _by - 18), "0", fill='white', font=_sf,
                          stroke_width=1, stroke_fill='black')
            _ov_draw.text((_bx + _blen + 4, _by - 18), scale_max_text, fill='white', font=_sf,
                          stroke_width=1, stroke_fill='black')
        except Exception as _ov_err:
            logger.debug(f"Map overlays: {_ov_err}")

        buf = io.BytesIO()
        canvas.save(buf, format='PNG')
        buf.seek(0)
        return buf
    except Exception as e:
        logger.error(f"Error creating perfect context map: {e}", exc_info=True)
        return None

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Per-parameter metadata: descriptions, units, and interpretation shown under each chart
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
_PARAM_META = {
    'pca': {
        'full_name': 'Crop Health',
        'unit': 'Score (0 to 1)',
        'what': 'Crop showed healthy early growth before experiencing steady decline and persistent stress towards season end.',
        'good_range': 'Good field: above 0.6',
    },
    'chlorophyll': {
        'full_name': 'Crop Greenness (Chlorophyll)',
        'unit': 'Greenness Level',
        'what': 'Leaf greenness peaked during vegetative phase then steadily decreased as the crop matured.',
        'good_range': 'Healthy active crop: 1.0 to 4.0',
    },
    'lai': {
        'full_name': 'Leaf Cover (Canopy Density)',
        'unit': 'Cover Level',
        'what': 'Canopy density expanded strongly early on before thinning rapidly towards the end of the period.',
        'good_range': 'Good crop cover: 2.0 to 6.0',
    },
    'soilmoisture': {
        'full_name': 'Soil Water Level (Moisture)',
        'unit': '% Water in Soil',
        'what': 'Soil moisture was adequate initially but dropped significantly, resulting in late-season dry conditions and stress.',
        'good_range': 'Best range for most crops: 30% to 65%',
    },
}


def generate_all_parameter_interpretations(series, vra_results_map, start_date, end_date, crop_name, language='en'):
    """
    Generate farmer-friendly conclusions for all 4 parameters:
    Crop Health (pca), Chlorophyll, Leaf Area Index (lai), Soil Moisture.
    Adheres strictly to the prompt:
    'Act as an agricultural scientist interpreting a farmerâ€™s field. Combine the whole-period composite map
    with the complete time series to understand how the crop behaved throughout the period. Summarize the fieldâ€™s
    overall condition, major changes, improvement or decline, and stability in simple farmer-friendly language.
    Mention stress or recovery only when supported by the observed pattern. Do not explain the index, map,
    statistics, technical terms, or methodology. Do not guess causes. Return only one natural conclusion of
    maximum 20 words for each parameter.'
    """
    import json

    param_keys = [
        ('pca', 'Crop Health', 'pca'),
        ('chlorophyll', 'Crop Greenness', 'clre'),
        ('lai', 'Leaf Cover / Canopy Density', 'lai'),
        ('soilmoisture', 'Soil Moisture', 'soilmoisture')
    ]

    def _clean_conclusion(text):
        if not text:
            return ""
        text = text.strip().strip('"\'*`')
        words = text.split()
        if len(words) > 20:
            text = " ".join(words[:20]).rstrip(".,;:-") + "."
        return text

    # Extract time-series values & summary for each parameter
    param_stats = {}
    param_obs_text = {}

    for param, label, chart_key in param_keys:
        vals = []
        for row in (series or []):
            v = row.get(chart_key) or row.get(chart_key + '_mm')
            d = row.get('date') or row.get('start_date')
            if v is not None:
                try:
                    vals.append((str(d), float(v)))
                except Exception:
                    pass
        
        # Whole-period composite map stats & spatial zone counts
        map_context_str = ""
        vra_res = vra_results_map.get(param) if vra_results_map else None
        vra_data = vra_res[1] if vra_res and len(vra_res) >= 3 else None
        if vra_data:
            zc = vra_data.get('zoneCounts', {})
            total_px = sum(zc.values()) if zc else 0
            if total_px > 0:
                low_pct = round(100.0 * (zc.get('lowest', 0) + zc.get('low', 0)) / total_px, 1)
                mod_pct = round(100.0 * zc.get('moderate', 0) / total_px, 1)
                high_pct = round(100.0 * (zc.get('highest', 0) + zc.get('high', 0)) / total_px, 1)
                map_context_str = f"Composite map coverage: {low_pct}% low/stressed, {mod_pct}% moderate, {high_pct}% strong/healthy condition across the field."

        if vals:
            first_d, first_v = vals[0]
            last_d, last_v = vals[-1]
            min_entry = min(vals, key=lambda x: x[1])
            max_entry = max(vals, key=lambda x: x[1])
            avg_v = sum(v for _, v in vals) / len(vals)
            trend = "stable"
            chg = last_v - first_v
            thr = max(abs(avg_v) * 0.05, 0.01)
            if chg > thr:
                trend = "improving"
            elif chg < -thr:
                trend = "declining"

            peaked_then_dropped = False
            max_idx = [i for i, item in enumerate(vals) if item == max_entry][0]
            if 0 < max_idx < len(vals) - 1:
                if (max_entry[1] - first_v) > thr and (max_entry[1] - last_v) > thr:
                    peaked_then_dropped = True

            param_stats[param] = {
                'vals': vals,
                'first': first_v,
                'last': last_v,
                'min': min_entry[1],
                'max': max_entry[1],
                'max_date': max_entry[0],
                'avg': avg_v,
                'trend': trend,
                'peaked_then_dropped': peaked_then_dropped
            }
            
            # Format chronological timeline of all satellite observations
            timeline_str = ", ".join(f"{d}: {v:.2f}" for d, v in vals)
            obs_lines = [
                f"- Complete Time Series Points: [{timeline_str}]",
                f"- Calculated Statistics: Average={avg_v:.3f}, Minimum={min_entry[1]:.3f} (on {min_entry[0]}), Maximum={max_entry[1]:.3f} (on {max_entry[0]}), Start={first_v:.3f}, End={last_v:.3f}",
                f"- Observed Trajectory: Overall trend is {trend}." + (" Peaked mid-season then sharply declined towards end." if peaked_then_dropped else "")
            ]
            if map_context_str:
                obs_lines.append(f"- Whole-Period Composite Map: {map_context_str}")
            
            param_obs_text[param] = "\n".join(obs_lines)
        else:
            param_stats[param] = None
            param_obs_text[param] = "No time series data available."

    # Try Gemini AI generation with strict instruction
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        try:
            from dotenv import load_dotenv as _ldenv
            _ldenv()
            gemini_key = os.environ.get("GEMINI_API_KEY", "")
        except Exception:
            pass
    conclusions = {}

    if gemini_key and gemini_key != "YOUR_GEMINI_API_KEY_HERE":
        try:
            prompt = f"""Act as an agricultural scientist interpreting a farmerâ€™s field. Combine the whole-period composite map with the complete time series to understand how the crop behaved throughout the period. Summarize the fieldâ€™s overall condition, major changes, improvement or decline, and stability in simple farmer-friendly language. Mention stress or recovery only when supported by the observed pattern. Do not explain the index, map, statistics, technical terms, or methodology. Do not guess causes. Return only one natural conclusion of maximum 20 words for each parameter.

Field Context:

Parameter Observations:
1. pca (Crop Health):
{param_obs_text.get('pca')}

2. chlorophyll (Crop Greenness / Chlorophyll):
{param_obs_text.get('chlorophyll')}

3. lai (Leaf Cover / Canopy Density):
{param_obs_text.get('lai')}

4. soilmoisture (Soil Moisture / Water Level):
{param_obs_text.get('soilmoisture')}

Strictly return a valid JSON object mapping each key ("pca", "chlorophyll", "lai", "soilmoisture") to its natural conclusion string (maximum 20 words)."""

            if language == "hi":
                prompt += "\nReturn each conclusion in simple, farmer-friendly Hindi (maximum 20 words)."

            body = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "maxOutputTokens": 2000,
                    "temperature": 0.2
                }
            }
            import time
            import requests as _req
            for model_name in ['gemini-3.5-flash', 'gemini-2.5-flash']:
                for attempt in range(2):
                    try:
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
                        resp = _req.post(url, json=body, timeout=25)
                        if resp.status_code == 200:
                            raw_json = resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()
                            if raw_json.startswith("```"):
                                raw_json = raw_json.strip("` \n").removeprefix("json").strip()
                            parsed = json.loads(raw_json)
                            for p, _, _ in param_keys:
                                if p in parsed and parsed[p]:
                                    conclusions[p] = _clean_conclusion(parsed[p])
                            if len(conclusions) == 4:
                                logger.info(f"✅ Generated 4 parameter conclusions with Gemini ({model_name})")
                                return conclusions
                        elif resp.status_code in [503, 429]:
                            time.sleep(2)
                            continue
                        else:
                            break  # Bad request or not found, try next model
                    except Exception as _ge:
                        logger.debug(f"Gemini {model_name} failed for param conclusions: {_ge}")
                        break
        except Exception as e:
            logger.warning(f"Error calling Gemini for parameter conclusions: {e}")

    # Fallback rule-based agricultural scientist interpretation (always guaranteed <= 20 words)
    fallback_conclusions = {
        'en': {
            'pca': {
                'peaked_drop': "Crop showed strong early vigor but later declined, indicating onset of stress.",
                'declining': "Crop conditions steadily declined over the period, suggesting persistent field-level stress.",
                'improving': "Crop health consistently improved, reflecting robust plant development and resilience.",
                'stable': "Crop conditions remained relatively stable and normal throughout the observed period.",
                'low': "Crop vigor remained persistently low throughout the period, suggesting underlying stress conditions."
            },
            'chlorophyll': {
                'peaked_drop': "Leaf greenness was strong initially but faded steadily as the crop matured.",
                'declining': "Crop greenness steadily dropped, suggesting possible nutrient deficiency or onset of senescence.",
                'improving': "Crop greenness increased steadily, indicating good nutrition and healthy development.",
                'stable': "Crop greenness remained stable and normal throughout the observed period.",
                'low': "Leaf greenness stayed persistently low, indicating suboptimal photosynthetic activity."
            },
            'lai': {
                'peaked_drop': "Crop canopy expansion was excellent initially but dropped off sharply later.",
                'declining': "Leaf area and canopy expansion declined steadily, leading to a progressively thinning crop.",
                'improving': "Canopy expansion steadily increased, resulting in good vegetation density across the field.",
                'stable': "Crop canopy coverage in the field remained consistent and stable throughout the period.",
                'low': "Canopy expansion was consistently low, leaving the field with sparse vegetation throughout."
            },
            'soilmoisture': {
                'peaked_drop': "Soil moisture was adequate initially but dropped significantly, resulting in late-season dry conditions and stress.",
                'declining': "Soil moisture levels declined steadily throughout the period, resulting in prolonged moisture stress across the field.",
                'improving': "Soil moisture levels improved and remained well-replenished, providing favorable moisture conditions for crop development.",
                'stable': "Soil moisture remained stable and adequate, supporting steady crop water requirements throughout the period.",
                'low': "Soil moisture stayed critically low throughout the period, indicating severe and continuous water stress."
            }
        },
        'hi': {
            'pca': {
                'peaked_drop': "फसल में शुरुआत में अच्छी वृद्धि दिखी, लेकिन बाद में गिरावट और तनाव दर्ज किया गया।",
                'declining': "पूरे समय फसल की स्थिति में लगातार गिरावट देखी गई, जिससे खेत में तनाव का पता चलता है।",
                'improving': "फसल के स्वास्थ्य में निरंतर सुधार हुआ और पौधे मजबूत व स्वस्थ बने रहे।",
                'stable': "पूरी अवधि के दौरान फसल की स्थिति स्थिर और सामान्य बनी रही।",
                'low': "पूरी अवधि में फसल की स्थिति कमजोर और तनावग्रस्त बनी रही।"
            },
            'chlorophyll': {
                'peaked_drop': "शुरुआत में पत्तियों का हरापन अच्छा रहा, जो फसल पकने के साथ धीरे-धीरे कम हुआ।",
                'declining': "फसल के हरेपन में लगातार कमी आई, जिससे पोषक तत्वों की कमी का संकेत मिलता है।",
                'improving': "फसल में हरापन लगातार बढ़ा, जो अच्छे पोषण और स्वस्थ विकास को दर्शाता है।",
                'stable': "फसल का हरापन पूरी अवधि में स्थिर और सामान्य बना रहा।",
                'low': "पत्तियों में हरापन लगातार कम रहा, जिससे सामान्य से कम वानस्पतिक गतिविधि दिखी।"
            },
            'lai': {
                'peaked_drop': "शुरुआत में फसल का फैलाव बहुत अच्छा रहा, जो बाद में तेजी से कम हुआ।",
                'declining': "पत्तियों के फैलाव में लगातार कमी आई और फसल धीरे-धीरे हल्की होती गई।",
                'improving': "फसल का फैलाव लगातार बढ़ा और पूरे खेत में अच्छी सघनता बनी।",
                'stable': "खेत में फसल का फैलाव पूरी अवधि में एक समान और स्थिर बना रहा।",
                'low': "पूरे समय फसल का फैलाव कम और खेत में हरियाली हल्की बनी रही।"
            },
            'soilmoisture': {
                'peaked_drop': "शुरुआत में मिट्टी में नमी पर्याप्त थी, लेकिन बाद में भारी गिरावट से सूखा तनाव बना।",
                'declining': "मिट्टी की नमी में लगातार कमी आई, जिससे खेत में सूखे की स्थिति बनी।",
                'improving': "मिट्टी में नमी का स्तर सुधरा और फसल के लिए अनुकूल बना रहा।",
                'stable': "मिट्टी में पानी की मात्रा संतुलित और फसल के लिए पर्याप्त बनी रही।",
                'low': "मिट्टी में नमी की भारी कमी रही, जिससे फसल को लगातार पानी का तनाव झेलना पड़ा।"
            }
        }
    }

    lang_key = 'hi' if language == 'hi' else 'en'
    fb = fallback_conclusions.get(lang_key, fallback_conclusions['en'])

    for p, _, _ in param_keys:
        if p not in conclusions or not conclusions[p]:
            st = param_stats.get(p)
            if not st:
                conclusions[p] = fb[p]['stable']
            elif st.get('peaked_then_dropped'):
                conclusions[p] = fb[p]['peaked_drop']
            elif st.get('trend') == 'declining':
                conclusions[p] = fb[p]['declining']
            elif st.get('trend') == 'improving':
                conclusions[p] = fb[p]['improving']
            elif st.get('avg', 0) < (0.3 if p == 'pca' else 1.0 if p == 'chlorophyll' else 1.5 if p == 'lai' else 25.0):
                conclusions[p] = fb[p]['low']
            else:
                conclusions[p] = fb[p]['stable']
            conclusions[p] = _clean_conclusion(conclusions[p])

    return conclusions


def generate_report_response(payload: dict):
    """Build and return the 2-page PDF report as a Flask response."""

    if not payload:
        raise ValueError("No JSON payload received")

    language = payload.get("language", "en").lower()
    if language not in ["en", "hi"]:
        language = "en"
    lang_strings = get_translations(language)

    crop_name   = payload.get("crop_name", "Crop").split("/")[0].strip()
    aoi         = payload.get("aoi")
    aoi_coords  = None
    center_lat  = payload.get("centroid_lat")
    center_lon  = payload.get("centroid_lon")
    area_ha     = payload.get("area_ha") or 0
    # Field details filled by user when saving the AOI
    farmer_name   = payload.get("farmer_name") or payload.get("owner_name") or ""
    field_name    = payload.get("field_name") or payload.get("aoi_name") or payload.get("name") or ""
    village       = payload.get("village") or ""
    taluka        = payload.get("taluka") or ""
    district      = payload.get("district") or ""
    state         = payload.get("state") or ""
    crop_type     = payload.get("crop_type", "").split("/")[0].strip()
    harvest_date  = payload.get("harvest_date") or ""
    sowing_date   = payload.get("sowing_date") or ""
    soil_type     = payload.get("soil_type") or ""
    irrigation_type = payload.get("irrigation_type") or ""
    field_notes   = payload.get("notes") or payload.get("remarks") or ""
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

    # â”€â”€ 15-day sequential window filtering â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Uses report start_date as the anchor. Creates 15-day fixed windows (e.g. Jan 1-15, Jan 16-30).
    # Selects the best valid observation within each window, naturally matching the 15-day client requirement.
    series = filter_series_to_15day_gap(series, start_date_str=start_date)
    # Extract the selected dates to pass to the deep-stats endpoint so it can
    # build its composite and per-image stats from the same set of images.
    selected_s2_dates = extract_s2_dates_from_series(series)
    logger.info(f"Selected S2 dates for report ({len(selected_s2_dates)}): {selected_s2_dates}")
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # ── Header + AI Deep Summary ──────────────────────────────────────────

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

    header_left = logo_img or Paragraph("<b>KrishiZest</b>", ParagraphStyle("Logo", fontSize=16, fontName=pdf_font_bold, textColor=colors.HexColor("#2E7D32")))
    period_str   = f"{start_date}  →  {end_date}"
    state_str    = state if state else "State not recorded"
    
    header_right = Paragraph(
        f"<b>{period_str}</b><br/>"
        f"<font size='10'>{state_str}</font>",
        ParagraphStyle("HdrRight", fontName=pdf_font_name, fontSize=11, leading=14, alignment=2, textColor=colors.HexColor("#212121"))
    )

    hdr_table = Table([[header_left, header_right]], colWidths=[W*0.35, W*0.65])
    hdr_table.setStyle(TableStyle([
        ('VALIGN',  (0,0), (-1,-1), 'MIDDLE'), ('ALIGN',   (1,0), (1,0),   'RIGHT'),
        ('LINEBELOW', (0,0), (-1,0), 1.2, colors.HexColor("#2E7D32")), ('BOTTOMPADDING', (0,0), (-1,0), 6),
    ]))
    story.append(hdr_table)
    story.append(Spacer(1, 3))
    _fi_hdr_s = ParagraphStyle("FIHdr", fontName=pdf_font_bold, fontSize=8, leading=10, textColor=colors.white)
    _fi_lbl_s = ParagraphStyle("FILbl", fontName=pdf_font_name, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#212121"))
    _fi_val_s = ParagraphStyle("FIVal", fontName=pdf_font_name, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#212121"))

    field_name_disp = field_name if field_name else "Not recorded"
    village_disp    = village if village else "Not recorded"
    district_disp   = f"District: {district}" if district else "District: Not recorded"
    state_disp      = state if state else "Not recorded"

    if crop_type and crop_name:
        crop_disp = f"Crop: {crop_name} ({crop_type})"
    elif crop_name:
        crop_disp = f"Crop: {crop_name}"
    else:
        crop_disp = "Crop: Not recorded"

    if area_ha:
        try:
            area_flt = float(area_ha)
            acre_flt = area_flt * 2.47105
            area_disp = f"Area: {area_flt:.4f} ha (~{acre_flt:.2f} acre)"
        except Exception:
            area_disp = f"Area: {area_ha} ha"
    else:
        area_disp = "Area: Not recorded"

    if center_lat is not None and center_lon is not None:
        latdir = "N" if center_lat >= 0 else "S"
        londir = "E" if center_lon >= 0 else "W"
        coord_disp = f"{abs(center_lat):.5f}° {latdir}, {abs(center_lon):.5f}° {londir}"
    else:
        coord_disp = "Not recorded"

    sowing_disp = f"Sowing Date: {sowing_date}" if sowing_date else "Sowing Date: Unclear"

    finfo_data = [
        [
            Paragraph("<b>FIELD INFORMATION</b>", _fi_hdr_s),
            "",
            ""
        ],
        [
            Paragraph("Field Name", _fi_lbl_s),
            Paragraph(field_name_disp, _fi_val_s),
            Paragraph(area_disp, _fi_val_s)
        ],
        [
            Paragraph("Village", _fi_lbl_s),
            Paragraph(village_disp, _fi_val_s),
            Paragraph(district_disp, _fi_val_s)
        ],
        [
            Paragraph("State", _fi_lbl_s),
            Paragraph(state_disp, _fi_val_s),
            Paragraph(crop_disp, _fi_val_s)
        ],
        [
            Paragraph("Coordinates", _fi_lbl_s),
            Paragraph(coord_disp, _fi_val_s),
            Paragraph(sowing_disp, _fi_val_s)
        ]
    ]

    finfo_table = Table(finfo_data, colWidths=[W * 0.25, W * 0.38, W * 0.37])
    finfo_table.setStyle(TableStyle([
        ('SPAN',          (0, 0), (2, 0)),
        ('BACKGROUND',    (0, 0), (-1, 0), colors.HexColor("#2E7D32")),
        ('BOX',           (0, 0), (-1, -1), 0.8, colors.HexColor("#2E7D32")),
        ('INNERGRID',     (0, 0), (-1, -1), 0.5, colors.HexColor("#2E7D32")),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 3.2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.2),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
        ('BACKGROUND',    (0, 1), (-1, -1), colors.HexColor("#FFFFFF")),
    ]))
    story.append(finfo_table)
    story.append(Spacer(1, 10))
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    # â”€â”€ 1. Fetch deep stats â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    deep_stats = {}
    if aoi:
        try:
            resp = requests.post(f"{backend_url}/get_deep_spatial_stats", json={
                'aoi': aoi,
                'start_date': start_date,
                'end_date': end_date,
                'scale': 10,
                'selected_dates': selected_s2_dates,
            }, timeout=180)
            if resp.status_code == 200:
                deep_stats = resp.json()
                logger.info(f"Deep stats keys: {list(deep_stats.keys())}")
            else:
                logger.error(f"Deep stats endpoint returned {resp.status_code}: {resp.text[:300]}")
        except Exception as e:
            logger.warning(f"Failed to fetch deep stats: {e}")

    # 2. Generate structured farmer report sections via AI 
    report_sections = generate_farmer_report_sections(
        deep_stats=deep_stats,
        series=series,
        start_date=start_date,
        end_date=end_date,
        crop_name=crop_name,
        field_name=field_name or location_text or "Field",
        language=language,
    )

    r_status        = report_sections['status']
    r_status_color  = report_sections['status_color']
    r_summary       = report_sections['season_summary']
    r_what_happened = report_sections['what_happened']
    r_key_findings  = report_sections['key_findings']
    r_action_plan   = report_sections['action_plan']
    r_map_desc      = report_sections['map_descriptions']

    # 3. Fetch all 4 VRA maps in PARALLEL 
    MAP_PARAMS = [  
        ('pca',         'Overall Crop Condition',       True),
        ('chlorophyll', 'Leaf Greenness',               True),
        ('lai',         'Plant Cover and Crop Density', True),
        ('soilmoisture','Available Soil Moisture',      False),
    ]

    import concurrent.futures

    def _fetch_vra(args):
        param, label, s2_force = args
        try:
            result = create_high_quality_vra_mosaic(
                aoi, start_date, end_date, param,
                backend_url=backend_url, final_size=1200,
                force_sentinel2=s2_force,
                draw_aoi_outline=True
            )
            return param, result
        except Exception as e:
            logger.warning(f"Parallel VRA fetch failed for {param}: {e}")
            return param, None

    vra_results_map = {}
    if aoi:
        logger.info("âš¡ Launching parallel VRA map fetches...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_fetch_vra, arg): arg[0] for arg in MAP_PARAMS}
            for future in concurrent.futures.as_completed(futures):
                param_key, vra_res = future.result()
                vra_results_map[param_key] = vra_res
        logger.info("✅ All parallel VRA fetches complete.")

    # â”€â”€ 4. Build AOI context map â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    map_col_content = Paragraph("<i>Field map not available</i>", caption)
    MAP_COL_W  = W * 0.40
    TEXT_COL_W = W * 0.57
    if aoi:
        try:
            map_buf = create_perfect_context_map(aoi, zoom=18, padding=150)
            if map_buf:
                pil_shot = PILImage.open(map_buf)
                iw, ih = pil_shot.size
                max_map_h = 70 * mm
                mscale = min(MAP_COL_W / iw, max_map_h / ih)
                map_buf.seek(0)
                map_col_content = Image(map_buf, width=iw * mscale, height=ih * mscale)
        except Exception as e:
            logger.warning(f"AOI map failed: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # PAGE 1 — SEASONAL FIELD SUMMARY
    # ──────────────────────────────────────────────────────────────────────────

    # ── Style helpers ─────────────────────────────────────────────────────────
    _sec_title  = ParagraphStyle("SecTitle",  fontName=pdf_font_bold,  fontSize=9.8,  leading=12.2,
                                  textColor=colors.HexColor("#2E7D32"), spaceBefore=6, spaceAfter=3)
    _body_small = ParagraphStyle("BodySmall", fontName=pdf_font_name,  fontSize=8.2, leading=11,
                                  textColor=colors.HexColor("#212121"), spaceAfter=2,
                                  wordSelectMethod='shaping' if is_hi else 'default')
    _tbl_hdr    = ParagraphStyle("TblHdr",    fontName=pdf_font_bold,  fontSize=8.2,   leading=10.5,
                                  textColor=colors.white)
    _tbl_cell   = ParagraphStyle("TblCell",   fontName=pdf_font_name,  fontSize=8.0, leading=10.8,
                                  textColor=colors.HexColor("#212121"),
                                  wordSelectMethod='shaping' if is_hi else 'default')
    _bullet_s   = ParagraphStyle("BulletS",   fontName=pdf_font_name,  fontSize=8.2, leading=11.0,
                                  leftIndent=10, firstLineIndent=-8, spaceAfter=3.5,
                                  wordSelectMethod='shaping' if is_hi else 'default')

    GREEN_DARK  = colors.HexColor("#2E7D32")
    GREEN_LIGHT = colors.HexColor("#E8F5E9")
    GREEN_MID   = colors.HexColor("#A5D6A7")
    GREY_BG     = colors.HexColor("#F5F5F5")
    BORDER_COL  = colors.HexColor("#C8E6C9")

    # ── 4a. Status box + AOI map side by side ─────────────────────────────────
    status_bg   = colors.HexColor(r_status_color)
    status_para = Paragraph(
        f"<b>{r_status}</b>",
        ParagraphStyle("StatusLbl", fontName=pdf_font_bold, fontSize=14, leading=17,
                       textColor=colors.white, alignment=1)
    )

    summary_para = Paragraph(
        r_summary,
        ParagraphStyle("Summary", fontName=pdf_font_name, fontSize=8.8, leading=12.5,
                       textColor=colors.HexColor("#212121"), spaceAfter=4,
                       wordSelectMethod='shaping' if is_hi else 'default')
    )

    # Status box: colored box (top) + summary text (below)
    status_box_data = [
        [status_para],
        [summary_para],
    ]
    status_box = Table(status_box_data, colWidths=[TEXT_COL_W])
    status_box.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (0,0), status_bg),
        ('BACKGROUND',    (0,1), (0,1), GREEN_LIGHT),
        ('TOPPADDING',    (0,0), (0,0), 7),
        ('BOTTOMPADDING', (0,0), (0,0), 7),
        ('TOPPADDING',    (0,1), (0,1), 6),
        ('BOTTOMPADDING', (0,1), (0,1), 6),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ('RIGHTPADDING',  (0,0), (-1,-1), 8),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('BOX',           (0,0), (-1,-1), 1.0, status_bg),
    ]))

    # ── Crop Health Score (0-10 Scale) ────────────────────────────────────────
    overall_score = report_sections.get('score_10')
    if overall_score is None:
        try:
            bs = deep_stats.get('basic_stats', {}) if deep_stats else {}
            ch_mean = bs.get('CropHealth_mean')
            if ch_mean is not None and isinstance(ch_mean, (int, float)):
                overall_score = round(float(ch_mean) * 10.0, 1) if float(ch_mean) <= 1.0 else round(float(ch_mean), 1)
            elif metrics and isinstance(metrics, dict) and 'pca' in metrics:
                pca_mean = metrics['pca'].get('mean')
                if pca_mean is not None and isinstance(pca_mean, (int, float)):
                    overall_score = round(float(pca_mean) * 10.0, 1) if float(pca_mean) <= 1.0 else round(float(pca_mean), 1)
            elif series:
                valid_pcas = [s.get('pca') for s in series if s.get('pca') is not None and isinstance(s.get('pca'), (int, float))]
                if valid_pcas:
                    avg_pca = sum(valid_pcas) / len(valid_pcas)
                    overall_score = round(avg_pca * 10.0, 1) if avg_pca <= 1.0 else round(avg_pca, 1)
        except Exception as e:
            logger.warning(f"Error calculating overall_score: {e}")
            overall_score = None

    if overall_score is None:
        status_l = r_status.lower()
        if "attention" in status_l or "alert" in status_l:
            overall_score = 2.4
        elif "fair" in status_l or "moderate" in status_l or "average" in status_l:
            overall_score = 5.0
        else:
            overall_score = 8.0
    else:
        overall_score = max(0.0, min(10.0, float(overall_score)))

    # Synchronized exactly with status banner thresholds (< 3.3, 3.3–6.7, > 6.7)
    if overall_score < 3.3:
        marker_col = 0
        score_status_color = "#D32F2F"
    elif overall_score <= 6.7:
        marker_col = 1
        score_status_color = "#F57C00"
    else:
        marker_col = 2
        score_status_color = "#2E7D32"

    class GaugeNeedle(Flowable):
        def __init__(self, score, width, color='#D32F2F', font_name='Helvetica-Bold'):
            super().__init__()
            self.score = max(0.0, min(10.0, float(score)))
            self.width = width
            self.height = 14
            self.color = colors.HexColor(color)
            self.font_name = font_name

        def draw(self):
            c = self.canv
            pct = self.score / 10.0
            x = pct * self.width
            x = max(10, min(self.width - 10, x))

            # Upward pointer triangle
            p = c.beginPath()
            p.moveTo(x, 12)
            p.lineTo(x - 3.5, 6)
            p.lineTo(x + 3.5, 6)
            p.close()
            c.setFillColor(self.color)
            c.setStrokeColor(self.color)
            c.drawPath(p, fill=1, stroke=0)

            # Numeric score text under triangle
            c.setFont(self.font_name, 7.5)
            c.drawCentredString(x, -2, f"{self.score:.1f}")

    scale_title_text = (
        f"<b>Overall Crop Health Gauge (0–10):</b> &nbsp; Score <b><font color='{score_status_color}'>{overall_score:.1f} / 10</font></b>"
        if not is_hi else
        f"<b>समग्र फसल स्वास्थ्य गेज (0–10):</b> &nbsp; स्कोर <b><font color='{score_status_color}'>{overall_score:.1f} / 10</font></b>"
    )
    scale_title_p = Paragraph(scale_title_text, ParagraphStyle(
        "ScaleTitle", fontName=pdf_font_name, fontSize=7.8, leading=10.0,
        textColor=GREEN_DARK, spaceAfter=2.5,
        wordSelectMethod='shaping' if is_hi else 'default'
    ))

    w_needs = "<b>Needs Attention</b><br/><font size=5.5 color='#555555'>0 – 3.3</font>" if not is_hi else "<b>ध्यान देने योग्य</b><br/><font size=5.5 color='#555555'>0 – 3.3</font>"
    w_avg   = "<b>Average</b><br/><font size=5.5 color='#555555'>3.3 – 6.7</font>" if not is_hi else "<b>औसत</b><br/><font size=5.5 color='#555555'>3.3 – 6.7</font>"
    w_good  = "<b>Good</b><br/><font size=5.5 color='#555555'>6.7 – 10</font>" if not is_hi else "<b>अच्छा</b><br/><font size=5.5 color='#555555'>6.7 – 10</font>"

    leg_cell_s = ParagraphStyle("LegCell", fontName=pdf_font_name, fontSize=7.0, leading=8.6, alignment=1,
                                textColor=colors.HexColor("#424242"),
                                wordSelectMethod='shaping' if is_hi else 'default')
    leg_cell_act = ParagraphStyle("LegCellAct", fontName=pdf_font_bold, fontSize=7.2, leading=8.8, alignment=1,
                                  textColor=colors.HexColor(score_status_color),
                                  wordSelectMethod='shaping' if is_hi else 'default')

    row1_cells = [
        Paragraph(w_needs, leg_cell_act if marker_col == 0 else leg_cell_s),
        Paragraph(w_avg,   leg_cell_act if marker_col == 1 else leg_cell_s),
        Paragraph(w_good,  leg_cell_act if marker_col == 2 else leg_cell_s),
    ]

    # Perfectly symmetrical widths: exactly 3 equal parts (33.33% each)
    w_third = TEXT_COL_W / 3.0
    scale_table = Table([row1_cells], colWidths=[w_third, w_third, w_third])
    scale_cmds = [
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor("#FFCDD2")),
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor("#FFE082")),
        ('BACKGROUND', (2, 0), (2, 0), colors.HexColor("#C8E6C9")),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('BOX',        (0, 0), (-1, -1), 0.7, colors.HexColor("#B0BEC5")),
        ('INNERGRID',  (0, 0), (-1, -1), 0.5, colors.white),
    ]
    if marker_col == 0:
        scale_cmds.append(('BACKGROUND', (0, 0), (0, 0), colors.HexColor("#EF9A9A")))
        scale_cmds.append(('BOX', (0, 0), (0, 0), 1.2, colors.HexColor("#C62828")))
    elif marker_col == 1:
        scale_cmds.append(('BACKGROUND', (1, 0), (1, 0), colors.HexColor("#FFD54F")))
        scale_cmds.append(('BOX', (1, 0), (1, 0), 1.2, colors.HexColor("#F57F17")))
    else:
        scale_cmds.append(('BACKGROUND', (2, 0), (2, 0), colors.HexColor("#A5D6A7")))
        scale_cmds.append(('BOX', (2, 0), (2, 0), 1.2, colors.HexColor("#2E7D32")))

    scale_table.setStyle(TableStyle(scale_cmds))
    needle_flowable = GaugeNeedle(overall_score, TEXT_COL_W, color=score_status_color, font_name=pdf_font_bold)

    sec1_title = Paragraph("1. SEASON SUMMARY" if not is_hi else "1. मौसमी सारांश", _sec_title)

    # AOI map column
    map_title_p = Paragraph(
        "Area of Interest Map" if not is_hi else "खेत का उपग्रह नक्शा",
        ParagraphStyle("MapTitleP", fontName=pdf_font_bold, fontSize=10,
                       textColor=GREEN_DARK, alignment=1, spaceAfter=3)
    )

    from reportlab.platypus import KeepInFrame
    text_col_items = [sec1_title, Spacer(1, 3), status_box, Spacer(1, 6), scale_title_p, scale_table, needle_flowable]
    text_frame = KeepInFrame(maxWidth=TEXT_COL_W, maxHeight=78 * mm,
                              content=text_col_items, mode='shrink')
    map_frame_items = [map_title_p, Spacer(1, 3), map_col_content]
    map_frame = KeepInFrame(maxWidth=MAP_COL_W, maxHeight=78 * mm,
                             content=map_frame_items, mode='shrink')

    summary_row = Table([[text_frame, map_frame]], colWidths=[TEXT_COL_W, MAP_COL_W])
    summary_row.setStyle(TableStyle([
        ('VALIGN',       (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING',  (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (0,0),   8),
        ('RIGHTPADDING', (1,0), (1,0),   0),
        ('TOPPADDING',   (0,0), (-1,-1), 0),
        ('BOTTOMPADDING',(0,0), (-1,-1), 0),
    ]))
    story.append(summary_row)
    story.append(Spacer(1, 5))

    # ── 4b. What Happened During the Season table ─────────────────────────────
    story.append(Paragraph("2. WHAT HAPPENED DURING THE SEASON" if not is_hi else "2. सीजन के दौरान क्या हुआ", _sec_title))

    wh_header = [
        Paragraph("Season Stage" if not is_hi else "सीजन चरण",        _tbl_hdr),
        Paragraph("Field Condition" if not is_hi else "खेत की स्थिति",     _tbl_hdr),
        Paragraph("Simple Interpretation" if not is_hi else "सरल व्याख्या", _tbl_hdr),
    ]
    wh_data = [wh_header]
    for row in r_what_happened:
        stage, condition, interpretation = (row + ["", "", ""])[:3]
        wh_data.append([
            Paragraph(stage,          _tbl_cell),
            Paragraph(condition,      _tbl_cell),
            Paragraph(interpretation, _tbl_cell),
        ])

    wh_col_w = [W * 0.22, W * 0.39, W * 0.39]
    wh_table = Table(wh_data, colWidths=wh_col_w)
    wh_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  GREEN_DARK),
        ('BACKGROUND',    (0,1), (-1,-1), GREEN_LIGHT),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [GREEN_LIGHT, colors.white]),
        ('INNERGRID',     (0,0), (-1,-1), 0.4, BORDER_COL),
        ('BOX',           (0,0), (-1,-1), 0.8, GREEN_DARK),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0), (-1,-1), 3.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3.5),
        ('LEFTPADDING',   (0,0), (-1,-1), 6),
        ('RIGHTPADDING',  (0,0), (-1,-1), 6),
    ]))
    story.append(wh_table)
    story.append(Spacer(1, 5))

    # ── 4c. Key Seasonal Findings bullets ─────────────────────────────────────
    story.append(Paragraph("3. KEY SEASONAL FINDINGS", _sec_title))
    for finding in r_key_findings[:5]:
        story.append(Paragraph(f"• {finding}", _bullet_s))
    story.append(Spacer(1, 5))

    # ── 4d. Next Season Action Plan table ─────────────────────────────────────
    story.append(Paragraph("4. NEXT SEASON ACTION PLAN", _sec_title))

    ap_header = [
        Paragraph("Priority", _tbl_hdr),
        Paragraph("Action",   _tbl_hdr),
        Paragraph("When to do it", _tbl_hdr),
    ]
    ap_data = [ap_header]

    _priority_colors = {
        "High":   colors.HexColor("#FFEBEE"),
        "Medium": colors.HexColor("#FFF8E1"),
        "Low":    colors.HexColor("#E8F5E9"),
    }
    _priority_text_colors = {
        "High":   colors.HexColor("#B71C1C"),
        "Medium": colors.HexColor("#E65100"),
        "Low":    colors.HexColor("#1B5E20"),
    }

    for row in r_action_plan[:6]:
        priority, action, when = (row + ["", "", ""])[:3]
        tc = _priority_text_colors.get(priority, colors.HexColor("#212121"))
        ap_data.append([
            Paragraph(f"<b>{priority}</b>",
                      ParagraphStyle("PriorityCell", fontName=pdf_font_bold, fontSize=8.0,
                                     leading=10.0, textColor=tc, alignment=1)),
            Paragraph(action, _tbl_cell),
            Paragraph(when,   _tbl_cell),
        ])

    ap_col_w = [W * 0.13, W * 0.65, W * 0.22]
    ap_table = Table(ap_data, colWidths=ap_col_w)

    ap_cmds = [
        ('BACKGROUND',    (0,0), (-1,0),  GREEN_DARK),
        ('INNERGRID',     (0,0), (-1,-1), 0.4, BORDER_COL),
        ('BOX',           (0,0), (-1,-1), 0.8, GREEN_DARK),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0), (-1,-1), 3.2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3.2),
        ('LEFTPADDING',   (0,0), (-1,-1), 6),
        ('RIGHTPADDING',  (0,0), (-1,-1), 6),
        ('ALIGN',         (0,1), (0,-1),  'CENTER'),
    ]
    # Row-wise background colors
    for row_idx, row in enumerate(r_action_plan[:6], start=1):
        priority = (row + ["", "", ""])[:3][0]
        row_bg = _priority_colors.get(priority, colors.white)
        ap_cmds.append(('BACKGROUND', (0, row_idx), (-1, row_idx), row_bg))

    ap_table.setStyle(TableStyle(ap_cmds))
    story.append(ap_table)

    # â”€â”€ PAGE BREAK â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    story.append(PageBreak())

    # PAGE 2 — FIELD CONDITION MAPS (2Ã—2 grid) + FPO + Disclaimer
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    story.append(Paragraph(
        "Field Condition Maps",
        ParagraphStyle("MapPageTitle", fontName=pdf_font_bold, fontSize=12,
                       textColor=GREEN_DARK, alignment=1, spaceAfter=4)
    ))
    story.append(Paragraph(
        "These maps show relative variation within the field during the season. "
        "Use them to decide where the field should receive more attention.",
        ParagraphStyle("MapPageSubtitle", fontName=pdf_font_name, fontSize=8,
                       leading=11, textColor=colors.HexColor("#555555"), alignment=1, spaceAfter=6)
    ))

    # Map metadata
    _map_meta = [
        {
            'param':       'pca',
            'legend_param': 'pca',
            'label':       'Overall Crop Condition',
            'key':         'crop_health',
        },
        {
            'param':       'chlorophyll',
            'legend_param': 'chlorophyll',
            'label':       'Leaf Greenness',
            'key':         'leaf_greenness',
        },
        {
            'param':       'lai',
            'legend_param': 'lai',
            'label':       'Plant Cover and Crop Density',
            'key':         'plant_cover',
        },
        {
            'param':       'soilmoisture',
            'legend_param': 'soilmoisture',
            'label':       'Available Soil Moisture',
            'key':         'soil_moisture',
        },
    ]

    CELL_W   = W / 2.0 - 3 * mm   # two columns with small gutter
    IMG_H    = 67 * mm              # max image height per cell
    DESC_H   = 22 * mm              # description text height per cell

    _map_title_s = ParagraphStyle("MapCellTitle", fontName=pdf_font_bold, fontSize=8.8,
                                   leading=11.0, textColor=GREEN_DARK, alignment=1, spaceAfter=2)
    _map_desc_s  = ParagraphStyle("MapCellDesc",  fontName=pdf_font_name, fontSize=7.4,
                                   leading=9.6, textColor=colors.HexColor("#333333"), spaceAfter=1,
                                   wordSelectMethod='shaping' if is_hi else 'default')
    _map_do_s    = ParagraphStyle("MapCellDo",    fontName=pdf_font_bold, fontSize=7.4,
                                   leading=9.6, textColor=colors.HexColor("#1B5E20"),
                                   wordSelectMethod='shaping' if is_hi else 'default')

    def _build_map_cell(meta):
        """Build a single map cell for the 2x2 grid."""
        param        = meta['param']
        legend_param = meta['legend_param']
        label        = meta['label']
        desc_key     = meta['key']

        # Map image
        map_img = Paragraph(f"<i>{label} map not available</i>",
                             ParagraphStyle("NoMapCell", fontSize=7, alignment=1, textColor=colors.grey))
        has_map = False
        if aoi:
            try:
                vra_result = vra_results_map.get(param)
                tile_buf   = vra_result[0] if vra_result and len(vra_result) >= 3 else None
                vra_data   = vra_result[1] if vra_result and len(vra_result) >= 3 else None
                zoom_lvl   = vra_result[2] if vra_result and len(vra_result) >= 3 else 15
                if tile_buf:
                    pil = PILImage.open(tile_buf)
                    styled = add_vra_legend(pil, legend_param, vra_data, label, aoi=aoi, zoom_level=zoom_lvl)
                    sbuf = BytesIO()
                    styled.save(sbuf, format='PNG', optimize=True)
                    sbuf.seek(0)
                    iw, ih = styled.size
                    avail_w = CELL_W - 4 * mm
                    scale = min(avail_w / iw, IMG_H / ih)
                    map_img = Image(sbuf, width=iw * scale, height=ih * scale)
                    has_map = True
            except Exception as e:
                logger.warning(f"Map cell build failed for {param}: {e}")

        if has_map:
            what_shows = r_map_desc.get(desc_key, {}).get('what_shows', '')
            what_to_do = r_map_desc.get(desc_key, {}).get('what_to_do', '')
            lbl_shows = "What this map shows:" if not is_hi else "यह नक्शा क्या दिखाता है:"
            lbl_do = "What to do:" if not is_hi else "क्या करें:"
            cell_data = [
                [Paragraph(label, _map_title_s)],
                [map_img],
                [Paragraph(f"<b>{lbl_shows}</b> {what_shows}", _map_desc_s)],
                [Paragraph(f"<b>{lbl_do}</b> {what_to_do}", _map_do_s)],
            ]
        else:
            no_data_msg = (
                "No satellite observation data was available for this layer during the selected period."
                if not is_hi else
                "चयनित अवधि के दौरान इस परत के लिए कोई उपग्रह डेटा उपलब्ध नहीं था।"
            )
            cell_data = [
                [Paragraph(label, _map_title_s)],
                [map_img],
                [Paragraph(f"<i>{no_data_msg}</i>", _map_desc_s)],
            ]

        cell_table = Table(cell_data, colWidths=[CELL_W])
        cell_table.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (0,0), GREEN_LIGHT),
            ('BACKGROUND',    (0,2), (0,-1), colors.white),
            ('BOX',           (0,0), (-1,-1), 0.8, BORDER_COL),
            ('LINEBELOW',     (0,0), (0,0), 0.5, GREEN_MID),
            ('ALIGN',         (0,0), (-1,-1), 'CENTER'),
            ('ALIGN',         (0,2), (0,-1), 'LEFT'),
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
            ('VALIGN',        (0,2), (0,-1), 'TOP'),
            ('TOPPADDING',    (0,0), (-1,-1), 4.5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4.5),
            ('LEFTPADDING',   (0,0), (-1,-1), 5),
            ('RIGHTPADDING',  (0,0), (-1,-1), 5),
        ]))
        return cell_table

    # Build all 4 map cells and arrange in 2x2 grid
    cells = [_build_map_cell(m) for m in _map_meta]

    row1 = Table([[cells[0], cells[1]]], colWidths=[CELL_W + 3*mm, CELL_W + 3*mm])
    row1.setStyle(TableStyle([
        ('VALIGN',       (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING',  (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (0,0), 4),
        ('RIGHTPADDING', (1,0), (1,0), 0),
        ('TOPPADDING',   (0,0), (-1,-1), 0),
        ('BOTTOMPADDING',(0,0), (-1,-1), 4),
    ]))
    row2 = Table([[cells[2], cells[3]]], colWidths=[CELL_W + 3*mm, CELL_W + 3*mm])
    row2.setStyle(TableStyle([
        ('VALIGN',       (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING',  (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (0,0), 4),
        ('RIGHTPADDING', (1,0), (1,0), 0),
        ('TOPPADDING',   (0,0), (-1,-1), 0),
        ('BOTTOMPADDING',(0,0), (-1,-1), 0),
    ]))
    story.append(row1)
    story.append(row2)
    story.append(Spacer(1, 8))

    # ── Legend Bar Guide Box ──────────────────────────────────────────────────
    leg_guide_text = (
        "<b>Legend Bar Guide:</b> All condition maps above use a relative 5-level classification from <b>Highest</b> (darkest shade) to <b>Lowest</b> (lightest pale shade). Darker areas indicate stronger crop vigor or higher moisture. Zones marked as <b>Low</b> or <b>Lowest</b> indicate field areas lagging behind and should be prioritized for ground inspection."
        if not is_hi else
        "<b>लीजेंड बार गाइड:</b> ऊपर दिए गए सभी नक्शे <b>Highest</b> (गहरा रंग) से <b>Lowest</b> (हल्का रंग) तक 5-स्तरीय वर्गीकरण का उपयोग करते हैं। गहरे रंग के क्षेत्र बेहतर फसल या अधिक नमी दर्शाते हैं। <b>Low</b> या <b>Lowest</b> चिन्हित क्षेत्र कमजोर वृद्धि दर्शाते हैं और स्थलीय निरीक्षण के लिए प्राथमिकता दिए जाने चाहिए।"
    )
    leg_box = Table([[Paragraph(leg_guide_text, ParagraphStyle(
        "LegGuide", fontName=pdf_font_name, fontSize=7.6, leading=10.8,
        textColor=colors.HexColor("#1B5E20"),
        wordSelectMethod='shaping' if is_hi else 'default'
    ))]], colWidths=[W])
    leg_box.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), GREEN_LIGHT),
        ('BOX',           (0,0), (-1,-1), 0.6, GREEN_MID),
        ('TOPPADDING',    (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING',   (0,0), (-1,-1), 7),
        ('RIGHTPADDING',  (0,0), (-1,-1), 7),
    ]))
    story.append(leg_box)
    story.append(Spacer(1, 8))

    # ── Important Note ────────────────────────────────────────────────────────
    note_text = (
        "<b>Important Note</b><br/>"
        "This report is based on satellite observations and is intended to help identify areas that may need "
        "attention. Field inspection, soil testing, and advice from a qualified agriculture expert may be "
        "required to confirm the exact cause and decide the suitable treatment."
        if not is_hi else
        "<b>महत्वपूर्ण सूचना</b><br/>"
        "यह रिपोर्ट उपग्रह अवलोकनों पर आधारित है और उन क्षेत्रों की पहचान करने में मदद करती है जहां ध्यान देने की आवश्यकता हो सकती है। "
        "सटीक कारण की पुष्टि करने और उपयुक्त उपचार तय करने के लिए खेत का निरीक्षण, मिट्टी परीक्षण और योग्य कृषि विशेषज्ञ की सलाह आवश्यक हो सकती है।"
    )
    note_box_data = [[Paragraph(
        note_text,
        ParagraphStyle("ImpNote", fontName=pdf_font_name, fontSize=7.6, leading=11.2,
                       textColor=colors.HexColor("#333333"),
                       wordSelectMethod='shaping' if is_hi else 'default')
    )]]
    note_box = Table(note_box_data, colWidths=[W])
    note_box.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), colors.HexColor("#FFF9C4")),
        ('BOX',           (0,0), (-1,-1), 0.8, colors.HexColor("#F57F17")),
        ('TOPPADDING',    (0,0), (-1,-1), 6.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6.5),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ('RIGHTPADDING',  (0,0), (-1,-1), 8),
    ]))
    story.append(note_box)
    story.append(Spacer(1, 4))

    def _draw_page(canvas, doc):
        """Footer only — the story already renders the header table as content."""
        draw_footer(canvas, doc)

    doc.build(story, onFirstPage=_draw_page, onLaterPages=_draw_page)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"KrishiZest_Report_{start_date}_{end_date}.pdf",
    )
