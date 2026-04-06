from PIL import Image, ImageEnhance, ImageDraw, ImageFilter
import sys
import os

try:
    img_path = r'c:\Users\Admin\Desktop\LCB Fertilizer\frontend\src\assets\img_NDVI.png'
    out_path = r'c:\Users\Admin\Desktop\LCB Fertilizer\frontend\src\assets\img_lai.png'
    
    # 1. Load image
    img = Image.open(img_path).convert('RGBA')
    w, h = img.size

    # 2. Add a very subtle, general dark wash over the entire image 
    # (this mimics the low-brightness "blur" look of the other tabs without being a harsh black dot)
    overall_dark = Image.new('RGBA', (w, h), (10, 30, 10, 90)) # Soft dark olive wash
    img = Image.alpha_composite(img, overall_dark)

    # 3. Add a slight, wider, very soft blur just behind the icon to make it pop,
    # but color it natural dark green, not black.
    shadow = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    
    cx, cy = w//2, h//2
    r_shadow = min(w, h) * 0.40
    
    # Draw dark green subtle ellipse
    draw.ellipse((cx - r_shadow, cy - r_shadow, cx + r_shadow, cy + r_shadow), fill=(10, 30, 10, 140))
    
    # Extreme blur to just make it a soft gradient
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=w*0.25))

    final_img = Image.alpha_composite(img, shadow)

    # 4. Save
    final_img.save(out_path)
    print("Success")
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
