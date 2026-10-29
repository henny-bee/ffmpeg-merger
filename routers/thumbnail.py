import os
import re
import shutil
import subprocess
import httpx
from PIL import Image, ImageDraw, ImageFilter
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from core.media import FFMPEG_BIN, create_work_dir, load_font
from schemas.requests import ThumbnailRequest

router = APIRouter()


@router.post("/thumbnail")
async def create_thumbnail(data: ThumbnailRequest, background_tasks: BackgroundTasks):
    media_input = data.video_url or data.image_url
    if not media_input:
        raise HTTPException(status_code=400, detail="Harap isi video_url atau image_url")

    fmt = data.output_format.lower().lstrip(".")
    if fmt not in ("jpg", "jpeg", "jpng", "png"):
        raise HTTPException(status_code=400, detail="output_format harus png, jpg, atau jpng")

    work_dir = create_work_dir()
    ext = "png" if fmt == "png" else "jpg"
    frame_path = os.path.join(work_dir, "frame.png")
    out_path = os.path.join(work_dir, f"thumbnail.{ext}")

    try:
        if media_input.startswith(("http://", "https://")):
            input_path = os.path.join(work_dir, "input_media")
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                resp = await client.get(media_input)
                if resp.status_code != 200:
                    raise HTTPException(status_code=400, detail="Gagal mengunduh media")
                with open(input_path, "wb") as f:
                    f.write(resp.content)
        else:
            input_path = media_input
            if not os.path.exists(input_path) and input_path.lower().endswith(".jpng"):
                base = input_path[:-5]
                for alt in (".jpg", ".jpeg", ".png"):
                    if os.path.exists(base + alt):
                        input_path = base + alt
                        break
            if not os.path.exists(input_path):
                raise HTTPException(status_code=400, detail=f"File tidak ditemukan: {media_input}")

        try:
            with Image.open(input_path) as probe_im:
                img = probe_im.convert("RGBA")
            iw, ih = img.size
            target_r = 16 / 9
            if abs((iw / ih) - target_r) > 0.02:
                if iw / ih > target_r:
                    nw = int(ih * target_r)
                    img = img.crop(((iw - nw) // 2, 0, (iw + nw) // 2, ih))
                else:
                    nh = int(iw / target_r)
                    img = img.crop((0, (ih - nh) // 2, iw, (ih + nh) // 2))
            if img.size != (1280, 720):
                img = img.resize((1280, 720), Image.Resampling.LANCZOS)
        except Exception:
            cmd = [
                FFMPEG_BIN, "-y",
                "-ss", str(data.timestamp),
                "-i", input_path,
                "-vf", "crop=min(iw\\,ih*16/9):min(ih\\,iw*9/16),scale=1280:720:flags=lanczos,unsharp=3:3:0.6:3:3:0.0",
                "-frames:v", "1",
                "-update", "1",
                frame_path
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0 or not os.path.exists(frame_path):
                raise HTTPException(status_code=500, detail=f"FFmpeg crop error: {res.stderr}")
            img = Image.open(frame_path).convert("RGBA")

        w, h = img.size

        # shortcut: pakai font sistem (Impact di Windows / DejaVu Condensed di Docker), ganti ke custom .ttf jika butuh identik lintas OS
        font = load_font([
            r"C:\Windows\Fonts\impact.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ], data.font_size)
        src_font = load_font([
            r"C:\Windows\Fonts\seguisb.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ], 22)

        max_w = int(w * 0.85)
        space_w = font.getlength(" ")
        lines = []
        for raw_line in data.text.split("\n"):
            tokens = []
            for part in re.split(r"(\*[^*]+\*)", raw_line):
                if not part:
                    continue
                hl = part.startswith("*") and part.endswith("*")
                clean = part[1:-1] if hl else part
                for word in clean.split():
                    tokens.append((word, hl))

            cur, cur_w = [], 0.0
            for word, hl in tokens:
                ww = font.getlength(word)
                if cur and cur_w + space_w + ww > max_w:
                    lines.append(cur)
                    cur, cur_w = [(word, hl)], ww
                else:
                    cur_w = cur_w + space_w + ww if cur else ww
                    cur.append((word, hl))
            if cur:
                lines.append(cur)

        line_h = int(data.font_size * 1.38)
        total_h = len(lines) * line_h
        x_start = int(w * 0.072)
        y_start = h - total_h - 56

        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.rounded_rectangle(
            [x_start - 35, y_start - 25, w - x_start + 35, y_start + total_h + 25],
            radius=30,
            fill=(6, 23, 58, 235)
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=28))
        img = Image.alpha_composite(img, shadow)

        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        cap_top, _, _, cap_bot = font.getbbox("ABCDEFGHIJKLMNOPQRSTUVWXYZ")

        for idx, line in enumerate(lines):
            y = y_start + idx * line_h
            x = float(x_start)
            i = 0
            while i < len(line):
                if line[i][1]:
                    j = i
                    seg_words = []
                    while j < len(line) and line[j][1]:
                        seg_words.append(line[j][0])
                        j += 1
                    seg_w = font.getlength(" ".join(seg_words))
                    odraw.rounded_rectangle(
                        [x - 6, y + cap_top - 7, x + seg_w + 6, y + cap_bot + 9],
                        radius=9,
                        fill=(239, 43, 45, 255)
                    )
                    x += seg_w + space_w
                    i = j
                else:
                    x += font.getlength(line[i][0]) + space_w
                    i += 1

            x = float(x_start)
            for word, _ in line:
                odraw.text((x, y), word, font=font, fill=(255, 255, 255, 255))
                x += font.getlength(word) + space_w

        if data.source and data.source.strip():
            clean_src = data.source.replace("*", "").strip()
            if not clean_src.lower().startswith("source:"):
                clean_src = f"Source: {clean_src}"
            sbbox = src_font.getbbox(clean_src)
            sw, sh = sbbox[2] - sbbox[0], sbbox[3] - sbbox[1]
            bx2, by2 = w - 18, h - 6
            bx1, by1 = bx2 - sw - 22, by2 - sh - 16
            odraw.rectangle([bx1, by1, bx2, by2], fill=(0, 0, 0, 215))
            odraw.text((bx1 + 11, by1 + 6 - sbbox[1]), clean_src, font=src_font, fill=(255, 255, 255, 255))

        final_img = Image.alpha_composite(img, overlay)
        if ext == "png":
            final_img.save(out_path, format="PNG")
            media_type = "image/png"
        else:
            final_img.convert("RGB").save(out_path, format="JPEG", quality=98, subsampling=0)
            media_type = "image/jpeg"

        background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)
        return FileResponse(out_path, media_type=media_type, filename=f"thumbnail.{ext}")

    except HTTPException:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))
