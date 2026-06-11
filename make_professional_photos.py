"""
Convert HEIC photos from yo/ folder into professional CV headshots:
  - Remove background, add studio gradient
  - Convert to B&W
  - Crop to head+shoulder area
"""
import os
import sys
import numpy as np
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter
from pillow_heif import register_heif_opener
import cv2
from rembg import remove, new_session

register_heif_opener()

SOURCE_DIR = Path("/home/patito/Developments/cv-builder/static/uploads/cv photos/yo")
OUTPUT_DIR = SOURCE_DIR / "professional"
OUTPUT_DIR.mkdir(exist_ok=True)

# rembg session (loads model once)
print("Loading rembg model...")
session = new_session("u2net_human_seg")


def studio_background(width: int, height: int) -> np.ndarray:
    """Dark studio gradient matching photo_professional.jpg style."""
    # Radial gradient: ~88 gray at center, ~40 at edges
    xs = np.linspace(-1, 1, width)
    ys = np.linspace(-1.2, 0.8, height)  # center slightly above midpoint
    XX, YY = np.meshgrid(xs, ys)
    dist = np.sqrt(XX ** 2 + YY ** 2)
    val = np.clip(88 - dist * 48, 30, 95)
    bg = val.astype(np.uint8)
    return np.stack([bg, bg, bg], axis=2)


def find_head_crop(img_rgb: np.ndarray):
    """Return (x1, y1, x2, y2) crop for head+shoulder area."""
    h, w = img_rgb.shape[:2]
    gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)

    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    # Try at multiple scales
    faces = cascade.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=4, minSize=(80, 80))

    if len(faces) == 0:
        # Fallback: use top 65% of image centered horizontally
        x1 = int(w * 0.05)
        y1 = 0
        x2 = int(w * 0.95)
        y2 = int(h * 0.65)
        return x1, y1, x2, y2

    # Largest face
    faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
    fx, fy, fw, fh = faces[0]

    # Expand: above head, below chin (neck+shoulders), sides
    pad_top    = int(fh * 0.75)   # room above head
    pad_bottom = int(fh * 1.4)    # neck + upper chest
    pad_side   = int(fw * 0.75)   # shoulders width

    x1 = max(0, fx - pad_side)
    y1 = max(0, fy - pad_top)
    x2 = min(w, fx + fw + pad_side)
    y2 = min(h, fy + fh + pad_bottom)

    # Ensure at least a 3:4 portrait ratio
    crop_w = x2 - x1
    crop_h = y2 - y1
    target_h = int(crop_w * 4 / 3)
    if crop_h < target_h:
        extra = target_h - crop_h
        y2 = min(h, y2 + extra)

    return x1, y1, x2, y2


def process(heic_path: Path, output_path: Path):
    print(f"  {heic_path.name} → {output_path.name}")

    # 1. Open HEIC
    img_pil = Image.open(heic_path).convert("RGB")

    # 2. Detect head crop on original full image
    img_np = np.array(img_pil)
    x1, y1, x2, y2 = find_head_crop(img_np)
    img_cropped = img_pil.crop((x1, y1, x2, y2))

    # 3. Remove background (returns RGBA)
    img_no_bg = remove(img_cropped, session=session)

    # 4. Composite over studio gradient background
    cw, ch = img_cropped.size
    bg = Image.fromarray(studio_background(cw, ch))
    alpha = img_no_bg.split()[3]
    bg.paste(img_cropped, (0, 0), alpha)

    # 5. Convert to grayscale (B&W)
    bw = bg.convert("L")

    # 6. Slight contrast boost to match studio look
    bw = ImageEnhance.Contrast(bw.convert("RGB")).enhance(1.15)
    bw = ImageEnhance.Brightness(bw).enhance(1.05)

    # 7. Resize to standard portrait size (522 × 641)
    bw = bw.resize((522, 641), Image.LANCZOS)

    # 8. Save
    bw.save(output_path, "JPEG", quality=92)


heic_files = sorted(SOURCE_DIR.glob("*.heic"))
print(f"\nFound {len(heic_files)} photos. Processing...\n")

for heic in heic_files:
    out = OUTPUT_DIR / (heic.stem + "_professional.jpg")
    try:
        process(heic, out)
    except Exception as exc:
        print(f"  ERROR on {heic.name}: {exc}")

print(f"\nDone. Results saved to: {OUTPUT_DIR}")
