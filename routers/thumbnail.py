import os
import re
import shutil
import subprocess
import httpx
from PIL import Image, ImageDraw, ImageFilter
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from core.media import FFMPEG_BIN, create_work_dir, load_font, upscale_to_720p
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
            if data.upscale:
                img = upscale_to_720p(img)
            elif img.size != (1280, 720):
                img = img.resize((1280, 720), Image.Resampling.LANCZOS)
        except Exception:
            cmd = [
                FFMPEG_BIN, "-y",
                "-ss", str(data.timestamp),
                "-i", input_path,
                "-vf", "crop=min(iw\\,ih*16/9):min(ih\\,iw*9/16)",
                "-frames:v", "1",
                "-update", "1",
                frame_path
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0 or not os.path.exists(frame_path):
                raise HTTPException(status_code=500, detail=f"FFmpeg crop error: {res.stderr}")
            with Image.open(frame_path) as raw_frame:
                frame_im = raw_frame.copy()
            if data.upscale:
                img = upscale_to_720p(frame_im)
            else:
                img = frame_im.resize((1280, 720), Image.Resampling.LANCZOS).convert("RGBA")

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
        ], 25)

        max_w = int(w * 0.94)
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

        line_h = int(data.font_size * 1.34)
        total_h = len(lines) * line_h
        x_start = 38
        y_start = h - total_h - 18

        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.rounded_rectangle(
            [16, y_start - 14, w - 16, h - 8],
            radius=28,
            fill=(10, 18, 32, 185)
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=3))
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
                        [x - 7, y + cap_top - 6, x + seg_w + 7, y + cap_bot + 8],
                        radius=9,
                        fill=(220, 20, 20, 255)
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
            bx2, by1 = w - 2, 2
            bx1, by2 = bx2 - sw - 22, by1 + sh + 16
            odraw.rounded_rectangle([bx1, by1, bx2, by2], radius=10, fill=(0, 0, 0, 215))
            odraw.text((bx1 + 11, by1 + 7 - sbbox[1]), clean_src, font=src_font, fill=(255, 255, 255, 255))

        if data.logo_url and data.logo_url.strip():
            logo_input = data.logo_url.strip()
            if logo_input.startswith(("http://", "https://")):
                logo_path = os.path.join(work_dir, "logo_img")
                async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                    lresp = await client.get(logo_input)
                    if lresp.status_code != 200:
                        raise HTTPException(status_code=400, detail="Gagal mengunduh logo")
                    with open(logo_path, "wb") as f:
                        f.write(lresp.content)
            else:
                if not os.path.exists(logo_input):
                    raise HTTPException(status_code=400, detail=f"File logo tidak ditemukan: {logo_input}")
                logo_path = logo_input

            with Image.open(logo_path) as raw_logo:
                logo_im = raw_logo.convert("RGBA").resize((120, 120), Image.Resampling.LANCZOS)
            mask = Image.new("L", (120, 120), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, 120, 120], radius=18, fill=255)
            r, g, b, a = logo_im.split()
            logo_im.putalpha(Image.composite(a, Image.new("L", (120, 120), 0), mask))
            overlay.paste(logo_im, (0, 0), logo_im)

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
