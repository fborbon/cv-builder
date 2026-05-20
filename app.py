from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, HTMLResponse
from jinja2 import Environment, FileSystemLoader
import json, base64, tempfile, re
from pathlib import Path

app = FastAPI(title="CV Builder")
BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "data" / "cv.json"
UPLOADS_DIR = BASE_DIR / "static" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
ui_tpl = Jinja2Templates(directory=str(BASE_DIR / "templates"))
pdf_env = Environment(loader=FileSystemLoader(str(BASE_DIR / "templates" / "pdf")))

TEMPLATES = {
    "classic":   "Classic",
    "modern":    "Modern",
    "executive": "Executive",
    "tech":      "Tech / Developer",
    "creative":  "Creative",
    "minimal":   "Minimal",
}


def load_cv() -> dict:
    return json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else {}


def save_cv(data: dict):
    DATA_FILE.parent.mkdir(exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_photo_b64(cv: dict) -> str | None:
    photo_path_str = (cv.get("personal") or {}).get("photo") or ""
    if not photo_path_str:
        return None
    photo_file = BASE_DIR / photo_path_str.lstrip("/")
    if not photo_file.exists():
        return None
    ext = photo_file.suffix.lower().lstrip(".")
    mime = "jpeg" if ext == "jpg" else ext
    return f"data:image/{mime};base64,{base64.b64encode(photo_file.read_bytes()).decode()}"


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return ui_tpl.TemplateResponse(request, "ui/index.html", {
        "templates_list": TEMPLATES,
    })


@app.get("/api/cv")
async def get_cv():
    return load_cv()


@app.put("/api/cv")
async def update_cv(request: Request):
    data = await request.json()
    save_cv(data)
    return {"status": "saved"}


@app.post("/api/upload-photo")
async def upload_photo(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(400, "Only JPG / PNG / WEBP images are accepted")
    dest = UPLOADS_DIR / f"photo{ext}"
    dest.write_bytes(await file.read())
    return {"path": f"/static/uploads/photo{ext}"}


@app.get("/preview/{template_name}", response_class=HTMLResponse)
async def preview_cv(template_name: str):
    if template_name not in TEMPLATES:
        raise HTTPException(404, "Template not found")
    cv = load_cv()
    # For browser preview the server can serve static files directly;
    # pass photo as a regular URL so the iframe can load it without base64 bloat.
    photo_url = (cv.get("personal") or {}).get("photo") or None
    html = pdf_env.get_template(f"{template_name}.html").render(
        cv=cv, photo_b64=photo_url
    )
    return HTMLResponse(content=html)


def _clamp_page_margins(html: str, min_mm: float = 10.0) -> str:
    """Ensure @page top/bottom margins are never below min_mm.

    Handles all CSS margin shorthand forms (1–4 values) and any CSS unit
    (including bare 0 which is treated as 0 mm).  Only touches @page blocks.
    """
    _UNIT_TO_MM = {"mm": 1, "cm": 10, "px": 25.4 / 96, "pt": 25.4 / 72, "in": 25.4}

    def to_mm(val: str, unit: str) -> float:
        return float(val) * _UNIT_TO_MM.get(unit, 1)  # bare 0 (no unit) → 0 mm

    def process_page(m: re.Match) -> str:
        block = m.group(0)

        def clamp(margin_m: re.Match) -> str:
            parts_str = margin_m.group(1).strip()
            # Match numeric values with optional CSS unit
            tokens = re.findall(r"(-?\d+(?:\.\d+)?)(mm|cm|px|pt|in|em|rem)?", parts_str)
            # Filter out empty matches that the regex can produce
            tokens = [(v, u) for v, u in tokens if v]
            if not tokens or any(u in ("em", "rem") for _, u in tokens):
                return margin_m.group(0)  # can't convert relative units — leave alone

            vals_mm = [to_mm(v, u) for v, u in tokens]
            n = len(vals_mm)

            # Apply min floor to top (index 0) and bottom (index 2 for n≥3, same as top for n≤2)
            if n == 1:
                vals_mm[0] = max(vals_mm[0], min_mm)
            elif n == 2:
                vals_mm[0] = max(vals_mm[0], min_mm)   # top & bottom (same slot)
            elif n >= 3:
                vals_mm[0] = max(vals_mm[0], min_mm)   # top
                vals_mm[2] = max(vals_mm[2], min_mm)   # bottom

            return "margin: " + " ".join(f"{v:.3f}mm" for v in vals_mm) + ";"

        return re.sub(r"margin\s*:\s*([^;]+);", clamp, block)

    return re.sub(r"@page\s*\{[^}]*\}", process_page, html)


def _scale_css(html: str, factor: float) -> str:
    """Multiply every CSS unit value (including negative ones) inside <style> tags
    by *factor*.  Never touches body text or @page size keywords."""
    def process_style(m: re.Match) -> str:
        css = m.group(1)
        for unit in ("pt", "px", "mm", "rem", "em"):
            # -? handles negative values like margin: -15mm -18mm
            css = re.sub(
                rf"(-?\d+(?:\.\d+)?){unit}",
                lambda x, u=unit: f"{float(x.group(1)) * factor:.3f}{u}",
                css,
            )
        return f"<style>{css}</style>"
    return re.sub(r"<style>(.*?)</style>", process_style, html, flags=re.DOTALL)


def _fit_to_pages(html: str, target: int) -> str:
    """Scale HTML so WeasyPrint produces exactly `target` pages.

    Compression (n > target): binary-search the MAXIMUM scale where pages ≤ target.
    Expansion  (n < target): binary-search the MINIMUM scale where pages ≥ target.
    Both searches start from a guaranteed bracket so they always converge correctly.
    Up to 9 WeasyPrint renders total.
    """
    from weasyprint import HTML as WP

    base = str(BASE_DIR)
    n = len(WP(string=html, base_url=base).render().pages)

    if n == target:
        return _clamp_page_margins(html)   # still enforce the 10 mm floor

    if n > target:
        # ── Compress ────────────────────────────────────────────────────────────
        # lo = confirmed fits (very aggressive), hi = confirmed overflows (original)
        lo, hi = 0.3, 1.0
        for _ in range(8):
            mid = (lo + hi) / 2
            if len(WP(string=_scale_css(html, mid), base_url=base).render().pages) <= target:
                lo = mid   # fits — try larger (more readable)
            else:
                hi = mid   # overflows — try smaller
        return _clamp_page_margins(_scale_css(html, lo))

    else:
        # ── Expand ──────────────────────────────────────────────────────────────
        # lo = confirmed too few pages (original), hi = confirmed enough pages
        lo, hi = 1.0, 3.0
        for _ in range(8):
            mid = (lo + hi) / 2
            if len(WP(string=_scale_css(html, mid), base_url=base).render().pages) < target:
                lo = mid   # still too few — scale up more
            else:
                hi = mid   # reached target — try scaling down a bit
        # hi = minimum scale that produces ≥ target pages
        return _clamp_page_margins(_scale_css(html, hi))


@app.get("/api/generate/{template_name}")
async def generate_pdf(template_name: str, pages: int = 0):
    if template_name not in TEMPLATES:
        raise HTTPException(404, "Template not found")

    cv = load_cv()
    html = pdf_env.get_template(f"{template_name}.html").render(
        cv=cv, photo_b64=get_photo_b64(cv)
    )

    if pages > 0:
        html = _fit_to_pages(html, pages)

    from weasyprint import HTML
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        tmp_path = f.name

    HTML(string=html, base_url=str(BASE_DIR)).write_pdf(tmp_path)

    name = (cv.get("personal") or {}).get("name", "cv").replace(" ", "_")
    suffix = f"_{pages}p" if pages > 0 else ""
    return FileResponse(
        tmp_path,
        media_type="application/pdf",
        filename=f"{name}_{template_name}{suffix}.pdf",
    )


# ── GitHub portfolio ──────────────────────────────────────────────────────────

@app.get("/api/github-repos")
async def github_repos(username: str):
    """Proxy the GitHub public repos list — avoids CORS and hides the API call."""
    import urllib.request, urllib.error
    from starlette.concurrency import run_in_threadpool

    def fetch():
        url = (
            f"https://api.github.com/users/{username}/repos"
            "?sort=updated&per_page=50&type=public"
        )
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "CV-Portfolio-App/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise HTTPException(e.code, f"GitHub: {e.reason}")
        except Exception as e:
            raise HTTPException(502, str(e))
        return [
            {
                "name":        r["name"],
                "description": r.get("description") or "",
                "url":         r["html_url"],
                "language":    r.get("language") or "",
                "topics":      r.get("topics", []),
                "stars":       r.get("stargazers_count", 0),
                "forks":       r.get("forks_count", 0),
                "updated":     (r.get("updated_at") or "")[:10],
                "homepage":    r.get("homepage") or "",
                "fork":        r.get("fork", False),
            }
            for r in data
        ]

    return await run_in_threadpool(fetch)


@app.post("/api/repo-summaries")
async def repo_summaries(request: Request):
    """For each repo in the request body, fetch its README and return a
    5-sentence plain-text summary extracted from the first meaningful paragraphs."""
    import urllib.request, urllib.error, base64
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from starlette.concurrency import run_in_threadpool

    repos = await request.json()   # [{username, name, description, language, topics}, …]

    # ── strip markdown to plain text ─────────────────────────────────────────
    _MD_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
    _MD_INLINE_CODE = re.compile(r"`[^`\n]+`")
    _MD_IMAGE      = re.compile(r"!\[.*?\]\(.*?\)")
    _MD_LINK       = re.compile(r"\[([^\]]+)\]\([^\)]+\)")
    _MD_HEADER     = re.compile(r"^#{1,6}\s+.+$", re.MULTILINE)
    _MD_HR         = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)
    _MD_BULLET     = re.compile(r"^[-*+]\s+", re.MULTILINE)
    _MD_NUMBERED   = re.compile(r"^\d+\.\s+", re.MULTILINE)
    _MD_EMPHASIS   = re.compile(r"[*_]{1,2}([^*_\n]+)[*_]{1,2}")
    _MD_BADGE      = re.compile(r"\[!\[.*?\]\(.*?\)\]\(.*?\)")  # shields.io badges

    def strip_markdown(text: str) -> str:
        text = _MD_BADGE.sub("", text)
        text = _MD_CODE_BLOCK.sub("", text)
        text = _MD_INLINE_CODE.sub("", text)
        text = _MD_IMAGE.sub("", text)
        text = _MD_LINK.sub(r"\1", text)
        text = _MD_HEADER.sub("", text)
        text = _MD_HR.sub("", text)
        text = _MD_BULLET.sub("", text)
        text = _MD_NUMBERED.sub("", text)
        text = _MD_EMPHASIS.sub(r"\1", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def extract_sentences(text: str, n: int = 5):
        """Split text into sentences and return up to n useful ones."""
        parts = re.split(r"(?<=[.!?])\s+", text.replace("\n", " "))
        good = []
        for s in parts:
            s = s.strip()
            if (len(s) > 50
                    and not s.lower().startswith("http")
                    and re.search(r"[a-zA-Z]{4,}", s)
                    and not re.match(r"^[^a-zA-Z]+$", s)):
                good.append(s)
                if len(good) >= n:
                    break
        return good

    def fallback_sentences(repo: dict) -> list[str]:
        """Build template sentences from repo metadata when README is missing."""
        name  = repo["name"].replace("-", " ").replace("_", " ")
        desc  = repo.get("description", "")
        lang  = repo.get("language", "")
        topics = repo.get("topics", [])

        sents = []
        if desc:
            sents.append(desc if desc.endswith(".") else desc + ".")
        sents.append(f"The project is implemented primarily in {lang}." if lang
                     else f"{name.title()} is an open-source project on GitHub.")
        if topics:
            sents.append(f"Key areas covered include {', '.join(topics[:4])}.")
        sents.append(f"The {name} repository is publicly available on GitHub for anyone to explore.")
        sents.append("Contributions, issues, and pull requests are welcome from the community.")
        return sents[:5]

    def summarise_repo(repo: dict) -> tuple[str, str]:
        username = repo.get("username", "")
        name     = repo["name"]
        url = f"https://api.github.com/repos/{username}/{name}/readme"
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/vnd.github.v3+json",
                     "User-Agent": "CV-Portfolio-App/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                data   = json.loads(resp.read())
                raw    = base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
                plain  = strip_markdown(raw)
                sents  = extract_sentences(plain)
        except Exception:
            sents = []

        if len(sents) < 5:
            sents = (sents + fallback_sentences(repo))[:5]

        return name, " ".join(sents)

    def fetch_all():
        results = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(summarise_repo, r): r["name"] for r in repos[:30]}
            for fut in as_completed(futures):
                try:
                    name, summary = fut.result()
                    results[name] = summary
                except Exception:
                    pass
        return results

    return await run_in_threadpool(fetch_all)


# ── Cover letter PDF ──────────────────────────────────────────────────────────

@app.post("/api/generate-letter-pdf")
async def generate_letter_pdf(request: Request):
    data      = await request.json()
    cv        = load_cv()
    personal  = cv.get("personal", {})

    html = pdf_env.get_template("letter.html").render(
        personal  = personal,
        photo_b64 = get_photo_b64(cv),
        company   = data.get("company", ""),
        position  = data.get("position", ""),
        recipient = data.get("recipient", "Hiring Manager"),
        body_text = data.get("body_text", ""),
        date_str  = data.get("date_str", ""),
    )

    from weasyprint import HTML
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        tmp_path = f.name
    HTML(string=html, base_url=str(BASE_DIR)).write_pdf(tmp_path)

    name = personal.get("name", "cover_letter").replace(" ", "_")
    return FileResponse(tmp_path, media_type="application/pdf",
                        filename=f"{name}_cover_letter.pdf")
