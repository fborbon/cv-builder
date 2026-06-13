# CV Builder

**[▶ Live Demo](https://www.forwardforecasting.eu/cv-builder/)**

A local web application for building, previewing, and exporting a professional CV as a PDF — with cover letter generation and a GitHub portfolio tab.

## Features

- **4 PDF templates** — Modern, Executive, Tech / Developer, Creative
- **Page fitting** — content is automatically scaled to fit exactly 2 pages, with Education and Certifications always pushed to page 2
- **Cover Letter** — quick auto-draft from CV data, or guided interactive mode (past jobs + target role)
- **Portfolio tab** — load any GitHub user's public repos with auto-generated 5-sentence summaries from READMEs
- **Live preview** — in-browser A4 page preview with zoom controls

## Quick start

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp data/cv.example.json data/cv.json
uvicorn app:app --reload
```

Open [http://localhost:8000](http://localhost:8000).

## Demo

**[https://www.forwardforecasting.eu/cv-builder/](https://www.forwardforecasting.eu/cv-builder/)** — open in any browser, no server required.  
All menus, modals, and tabs are fully navigable with sample data pre-loaded.  
PDF generation and live preview require the server to be running locally.

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| PDF rendering | WeasyPrint |
| Templates | Jinja2 |
| Frontend | Vanilla JS (no framework) |

## CV photo pipeline

The headshot used in the PDF templates was prepared from a casual phone photo
using two standalone scripts (`make_professional_photos.py` and
`make_suit_photos.py`). They aren't required to run the app, but document the
tooling behind a "studio portrait" look:

| Step | Technology | How it works |
|---|---|---|
| HEIC decoding | `pillow-heif` | Registers an HEIF/HEIC plugin for Pillow so iPhone `.heic` photos open like any other image format |
| Head/shoulder cropping | OpenCV Haar cascade (`haarcascade_frontalface_default`) | A classical detector trained on many face/non-face image patches; it scans the photo at multiple scales to find the largest face, then expands that box outward into a 3:4 head-and-shoulders crop |
| Background removal | `rembg` (U²-Net, `u2net_human_seg` model) | A deep neural network trained for person segmentation; it produces a per-pixel alpha mask separating the subject from the background, used to cut the subject out cleanly |
| Studio backdrop | NumPy radial gradient | A procedural dark vignette (gray for B&W, blue-gray for color) is generated and the cutout subject is composited onto it, mimicking a photo-studio background |
| Outfit replacement | AWS Bedrock — Stability AI "Stable Image Search & Replace" | A generative diffusion model: given a text prompt for what to find (e.g. "polo shirt") and what to put there instead (e.g. "dark business suit"), it inpaints a photorealistic replacement garment over that region |
| Tone & sizing | Pillow (`ImageEnhance`, `Image.resize`) | Grayscale conversion plus contrast/brightness curves for the studio look, then Lanczos resampling to the 522×641 portrait size used across all templates |

These scripts need extra dependencies not in `requirements.txt`
(`opencv-python`, `rembg`, `pillow-heif`, `numpy`) and, for the
outfit-replacement step, `boto3` with AWS credentials for Bedrock
(`us-east-1`) — that step calls a billed Bedrock model per image.

## Data privacy

`data/cv.json` and `static/uploads/` are excluded from version control via `.gitignore`.  
Use `data/cv.example.json` as the starting template.
