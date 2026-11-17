import io
from PIL import Image, ImageDraw, ImageFont

PRESETS = {
    "ssc": {"min_kb": 20, "max_kb": 50, "width": 350, "height": 450, "dpi": (200, 200)},
    "upsc": {"min_kb": 20, "max_kb": 100, "width": 350, "height": 350, "dpi": (200, 200)},
    "ibps_thumb": {"min_kb": 10, "max_kb": 20, "width": 240, "height": 240, "dpi": (200, 200)},
    "neet_postcard": {"min_kb": 50, "max_kb": 200, "width": 600, "height": 900, "dpi": (200, 200)},
}

def resize_and_compress_image(
    image_bytes: bytes,
    target_kb: int = None,
    preset: str = None,
    candidate_name: str = None,
    dop: str = None,
    dpi: int = 200
) -> bytes:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    
    # 1. Preset dimensions apply karein
    if preset and preset in PRESETS:
        p = PRESETS[preset]
        img = img.resize((p["width"], p["height"]), Image.Resampling.LANCZOS)
        if not target_kb:
            target_kb = int((p["min_kb"] + p["max_kb"]) / 2)
        dpi = p.get("dpi", (dpi, dpi))[0]

    # 2. Candidate Name & Date of Photo (DOP) Strip Add Karein
    if candidate_name or dop:
        strip_height = max(50, int(img.height * 0.16))
        new_img = Image.new("RGB", (img.width, img.height + strip_height), "white")
        new_img.paste(img, (0, 0))
        
        draw = ImageDraw.Draw(new_img)
        text_line_1 = (candidate_name or "").strip().upper()
        text_line_2 = f"DOP: {dop}".strip() if dop else ""

        font_size = max(14, int(strip_height * 0.32))
        font = None
        for font_name in ["C:\\Windows\\Fonts\\arialbd.ttf", "C:\\Windows\\Fonts\\arial.ttf", "arial.ttf"]:
            try:
                font = ImageFont.truetype(font_name, size=font_size)
                break
            except Exception:
                continue

        if font is None:
            font = ImageFont.load_default()
            
        y_text = img.height + 4
        if text_line_1:
            draw.text((img.width // 2, y_text), text_line_1, fill="black", anchor="mm", font=font)
            y_text += font_size + 4
        if text_line_2:
            draw.text((img.width // 2, y_text), text_line_2, fill="black", anchor="mm", font=font)
            
        img = new_img

    # 3. Target KB Iterative Binary-Search Compression
    if not target_kb or target_kb <= 0:
        target_kb = 35
        
    target_bytes = target_kb * 1024
    low, high = 10, 95
    best_output = None
    best_diff = float("inf")

    for _ in range(8):
        mid = (low + high) // 2
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=mid, dpi=(dpi, dpi), optimize=True)
        size = buf.tell()
        diff = abs(size - target_bytes)
        
        if diff < best_diff:
            best_diff = diff
            best_output = buf.getvalue()
            
        if size > target_bytes:
            high = mid - 1
        else:
            low = mid + 1
            
        if low > high:
            break

    return best_output if best_output else image_bytes