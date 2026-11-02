import os
import re
import shutil
import subprocess
from pathlib import Path
from PIL import Image
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from core.media import BROWSER_BIN, create_work_dir
from schemas.requests import RenderHtmlRequest

router = APIRouter()

# Map serif/sans/mono font families to Liberation/DejaVu equivalents in Docker
_LINUX_FONT_FALLBACK_CSS = """
<style>
  @font-face { font-family: 'Georgia'; src: local('Georgia'), local('Liberation Serif'), local('DejaVu Serif'); }
  @font-face { font-family: 'Segoe UI'; src: local('Segoe UI'), local('Liberation Sans'), local('DejaVu Sans'); }
  @font-face { font-family: 'Consolas'; src: local('Consolas'), local('Liberation Mono'), local('DejaVu Sans Mono'); }
</style>
"""


def _clean_html(raw: str) -> str:
    text = raw.strip()
    m = re.search(r"(<!doctype\s+html.*</html>|<html.*</html>)", text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        text = m.group(1)
    else:
        text = re.sub(r"^\s*`+(?:html)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*`+\s*$", "", text)
    if "</head>" in text:
        return text.replace("</head>", f"{_LINUX_FONT_FALLBACK_CSS}</head>", 1)
    return _LINUX_FONT_FALLBACK_CSS + text


@router.post("/render")
async def render_html(data: RenderHtmlRequest, background_tasks: BackgroundTasks):
    if not data.html or not data.html.strip():
        raise HTTPException(status_code=400, detail="Field html tidak boleh kosong")

    fmt = data.output_format.lower().lstrip(".")
    if fmt not in ("png", "jpg", "jpeg"):
        raise HTTPException(status_code=400, detail="output_format harus png atau jpg")

    if not (64 <= data.width <= 3840 and 64 <= data.height <= 2160):
        raise HTTPException(status_code=400, detail="Dimensi harus antara 64x64 dan 3840x2160")

    work_dir = create_work_dir()
    profile_dir = os.path.join(work_dir, "browser_profile")
    os.makedirs(profile_dir, exist_ok=True)

    html_path = os.path.join(work_dir, "index.html")
    png_path = os.path.join(work_dir, "render.png")
    ext = "png" if fmt == "png" else "jpg"
    out_path = png_path if ext == "png" else os.path.join(work_dir, "render.jpg")

    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(_clean_html(data.html))

        # shortcut: spawn headless Chromium per request, switch to a persistent Playwright browser pool if concurrency > 5 req/s
        cmd = [
            BROWSER_BIN,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            f"--user-data-dir={profile_dir}",
            f"--window-size={data.width},{data.height}",
            f"--screenshot={png_path}",
            Path(html_path).as_uri(),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if not os.path.exists(png_path):
            raise HTTPException(status_code=500, detail=f"Browser render gagal: {res.stderr}")

        if ext == "png":
            media_type = "image/png"
        else:
            with Image.open(png_path) as im:
                im.convert("RGB").save(out_path, format="JPEG", quality=98, subsampling=0)
            media_type = "image/jpeg"

        background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)
        return FileResponse(out_path, media_type=media_type, filename=f"render.{ext}")

    except HTTPException:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))
