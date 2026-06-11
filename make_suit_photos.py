"""
Full professional CV photo pipeline with AI suit replacement via Bedrock.
  1. Open HEIC → crop to head area (color)
  2. Bedrock stable-image-search-replace: polo → long-sleeve business suit
  3. rembg: remove background
  4. Add dark studio gradient background
  5. Save color set + B&W set (522×641 each)
"""
import base64, json, io, numpy as np
from pathlib import Path
import boto3
import cv2
from PIL import Image, ImageEnhance
from pillow_heif import register_heif_opener
from rembg import remove, new_session

register_heif_opener()

SOURCE_DIR  = Path("/home/patito/Developments/cv-builder/static/uploads/cv photos/yo")
DIR_COLOR   = SOURCE_DIR / "professional" / "color"
DIR_BW      = SOURCE_DIR / "professional" / "bw"
DIR_COLOR.mkdir(parents=True, exist_ok=True)
DIR_BW.mkdir(parents=True, exist_ok=True)

REGION = "us-east-1"
MODEL  = "us.stability.stable-image-search-replace-v1:0"

bedrock = boto3.client("bedrock-runtime", region_name=REGION)

print("Loading rembg model...")
seg = new_session("u2net_human_seg")


# ── helpers ────────────────────────────────────────────────────────────────────

def studio_background_gray(w: int, h: int) -> np.ndarray:
    """Dark radial studio gradient (grayscale RGB)."""
    xs = np.linspace(-1, 1, w)
    ys = np.linspace(-1.2, 0.8, h)
    XX, YY = np.meshgrid(xs, ys)
    val = np.clip(88 - np.sqrt(XX**2 + YY**2) * 48, 30, 95).astype(np.uint8)
    return np.stack([val, val, val], axis=2)


def studio_background_color(w: int, h: int) -> np.ndarray:
    """Warm dark blue-gray studio gradient for the color set."""
    xs = np.linspace(-1, 1, w)
    ys = np.linspace(-1.2, 0.8, h)
    XX, YY = np.meshgrid(xs, ys)
    dist = np.sqrt(XX**2 + YY**2)
    r = np.clip(68  - dist * 40, 22, 78).astype(np.uint8)
    g = np.clip(72  - dist * 42, 24, 82).astype(np.uint8)
    b = np.clip(85  - dist * 46, 30, 95).astype(np.uint8)
    return np.stack([r, g, b], axis=2)


def find_head_crop(img_np: np.ndarray):
    h, w = img_np.shape[:2]
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = cascade.detectMultiScale(gray, 1.05, 4, minSize=(80, 80))
    if len(faces) == 0:
        return int(w*0.05), 0, int(w*0.95), int(h*0.65)
    fx, fy, fw, fh = sorted(faces, key=lambda f: f[2]*f[3], reverse=True)[0]
    # Tight crop: include head + collar/lapels, avoid arms extending to sides
    x1 = max(0, fx - int(fw*0.6))
    y1 = max(0, fy - int(fh*0.75))
    x2 = min(w, fx + fw + int(fw*0.6))
    y2 = min(h, fy + fh + int(fh*1.1))  # chest only — no arms
    crop_w = x2 - x1
    target_h = int(crop_w * 4 / 3)
    if (y2 - y1) < target_h:
        y2 = min(h, y1 + target_h)
    return x1, y1, x2, y2


def pil_to_b64(img: Image.Image, fmt="JPEG") -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=95)
    return base64.b64encode(buf.getvalue()).decode()


def bedrock_search_replace(img: Image.Image) -> Image.Image:
    """Replace casual polo shirt with a long-sleeve business suit via Bedrock."""
    payload = {
        "image":         pil_to_b64(img),
        "search_prompt": "polo shirt, casual shirt, short sleeve shirt",
        "prompt": (
            "dark charcoal long sleeve business suit jacket, "
            "white long sleeve dress shirt, striped necktie, "
            "professional formal attire, full suit sleeves"
        ),
        "negative_prompt": (
            "casual, polo, t-shirt, short sleeve, hoodie, sweater, jeans, "
            "bare arms, rolled sleeves"
        ),
        "output_format": "jpeg",
        "seed": 42,
    }
    resp = bedrock.invoke_model(
        modelId=MODEL,
        body=json.dumps(payload),
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(resp["body"].read())
    # Stability response: result["images"][0] = base64 JPEG
    img_b64 = result["images"][0]
    return Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGB")


# ── main pipeline ──────────────────────────────────────────────────────────────

heic_files = sorted(SOURCE_DIR.glob("*.heic"))
print(f"\nProcessing {len(heic_files)} photos…\n")

for heic in heic_files:
    stem = heic.stem
    print(f"  {heic.name}")

    # 1. Open HEIC (color)
    img_color = Image.open(heic).convert("RGB")
    img_np    = np.array(img_color)

    # 2. Crop to head area
    x1, y1, x2, y2 = find_head_crop(img_np)
    img_crop = img_color.crop((x1, y1, x2, y2))
    print(f"    crop: {x1},{y1} → {x2},{y2}  ({img_crop.size})")

    # 3. Bedrock: replace polo with long-sleeve suit (color image)
    print("    calling Bedrock search-replace…")
    img_suited = bedrock_search_replace(img_crop)
    img_suited = img_suited.resize(img_crop.size, Image.LANCZOS)

    # 4. Remove background
    print("    removing background…")
    img_no_bg = remove(img_suited, session=seg)
    alpha = img_no_bg.split()[3]
    cw, ch = img_suited.size

    # 5a. Color set — warm studio background
    bg_col = Image.fromarray(studio_background_color(cw, ch))
    bg_col.paste(img_suited, (0, 0), alpha)
    col = ImageEnhance.Contrast(bg_col).enhance(1.1)
    col = ImageEnhance.Brightness(col).enhance(1.05)
    col = col.resize((522, 641), Image.LANCZOS)
    col.save(DIR_COLOR / f"{stem}_color.jpg", "JPEG", quality=92)
    print(f"    → color/{stem}_color.jpg")

    # 5b. B&W set — gray studio background
    bg_bw = Image.fromarray(studio_background_gray(cw, ch))
    bg_bw.paste(img_suited, (0, 0), alpha)
    bw = ImageEnhance.Contrast(bg_bw.convert("L").convert("RGB")).enhance(1.15)
    bw = ImageEnhance.Brightness(bw).enhance(1.05)
    bw = bw.resize((522, 641), Image.LANCZOS)
    bw.save(DIR_BW / f"{stem}_bw.jpg", "JPEG", quality=92)
    print(f"    → bw/{stem}_bw.jpg")

print(f"\nDone.\n  Color: {DIR_COLOR}\n  B&W:   {DIR_BW}")
