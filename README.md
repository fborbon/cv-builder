# CV Builder

A local web application for building, previewing, and exporting a professional CV as a PDF — with cover letter generation and a GitHub portfolio tab.

## Features

- **6 PDF templates** — Classic, Modern, Executive, Tech, Creative, Minimal
- **Page fitting** — automatically scale content to exactly 1 or 2 pages
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

Open `demo.html` directly in any browser — no server required.  
All menus, modals, and tabs are fully navigable with sample data pre-loaded.  
PDF generation and live preview require the server to be running.

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| PDF rendering | WeasyPrint |
| Templates | Jinja2 |
| Frontend | Vanilla JS (no framework) |

## Data privacy

`data/cv.json` and `static/uploads/` are excluded from version control via `.gitignore`.  
Use `data/cv.example.json` as the starting template.
