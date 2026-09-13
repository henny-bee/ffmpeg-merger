import os
import uuid
import shutil
import subprocess
from typing import Optional
import httpx
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI()

# ----------------- MODELS -----------------

class MergeRequest(BaseModel):
    video_url_1: str
    video_url_2: str
    music_url: Optional[str] = None   # Link URL file MP3 musik
    music_volume: float = 1.0         # Default 100% (1.0)
    video_volume: float = 1.0         # Default 100% (1.0)

class JoinTextRequest(BaseModel):
    image_url: str
    text: str
    max_chars_per_line: Optional[int] = 30  # Otomatis turun baris jika lebih dari jumlah karakter ini
    font_size: Optional[int] = 42
    font_color: Optional[str] = "white"
    border_color: Optional[str] = "black"
    border_width: Optional[int] = 5
    y_position: Optional[str] = "h*0.22"    # Posisi atas agak ke bawah

# ----------------- HELPERS -----------------

def check_has_audio(file_path: str) -> bool:
    """Cek apakah file memiliki stream audio"""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0", file_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return "audio" in res.stdout

def get_video_duration(file_path: str) -> float:
    """Ambil durasi stream video secara presisi"""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    val = res.stdout.strip()
    if val and val != "N/A":
        try:
            return float(val)
        except ValueError:
            pass

    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return float(res.stdout.strip())

# ----------------- ENDPOINTS -----------------

@app.get("/")
def home():
    return {"status": "FFmpeg API is running!"}

@app.post("/merge")
async def merge_videos(data: MergeRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    work_dir = f"/tmp/{task_id}"
    os.makedirs(work_dir, exist_ok=True)
    
    v1_path = os.path.join(work_dir, "v1.mp4")
    v2_path = os.path.join(work_dir, "v2.mp4")
    music_path = os.path.join(work_dir, "music.mp3")
    out_path = os.path.join(work_dir, "merged.mp4")

    try:
        # 1. Unduh Video 1, Video 2, dan MP3 Musik dari link
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            r1 = await client.get(data.video_url_1)
            if r1.status_code != 200:
                raise HTTPException(status_code=400, detail="Gagal mengunduh video 1")
            with open(v1_path, "wb") as f:
                f.write(r1.content)

            r2 = await client.get(data.video_url_2)
            if r2.status_code != 200:
                raise HTTPException(status_code=400, detail="Gagal mengunduh video 2")
            with open(v2_path, "wb") as f:
                f.write(r2.content)

            has_music = bool(data.music_url)
            if has_music:
                rm = await client.get(data.music_url)
                if rm.status_code != 200:
                    raise HTTPException(status_code=400, detail="Gagal mengunduh file MP3 musik")
                with open(music_path, "wb") as f:
                    f.write(rm.content)

        # 2. Cek Durasi & Track Audio
        dur1 = get_video_duration(v1_path)
        dur2 = get_video_duration(v2_path)
        has_a1 = check_has_audio(v1_path)
        has_a2 = check_has_audio(v2_path)

        # 3. Filter Format Video (9:16 / 720x1280 30fps)
        v0_filter = f"[0:v]fps=30,scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,trim=0:{dur1},setpts=PTS-STARTPTS[v0];"
        v1_filter = f"[1:v]fps=30,scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,trim=0:{dur2},setpts=PTS-STARTPTS[v1];"

        # 4. Filter Suara Video
        if has_a1:
            a0_filter = f"[0:a]aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS,aformat=sample_rates=44100:channel_layouts=stereo,apad,atrim=0:{dur1},asetpts=PTS-STARTPTS[a0];"
        else:
            a0_filter = f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=0:{dur1},asetpts=PTS-STARTPTS[a0];"

        if has_a2:
            a1_filter = f"[1:a]aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS,aformat=sample_rates=44100:channel_layouts=stereo,apad,atrim=0:{dur2},asetpts=PTS-STARTPTS[a1];"
        else:
            a1_filter = f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=0:{dur2},asetpts=PTS-STARTPTS[a1];"

        # 5. Gabungkan Audio & Musik
        cmd_merge = ["ffmpeg", "-y", "-i", v1_path, "-i", v2_path]

        if has_music:
            cmd_merge.extend(["-stream_loop", "-1", "-i", music_path])
            concat_filter = (
                "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][aconcat];"
                f"[aconcat]volume={data.video_volume}[vo];"
                f"[2:a]aresample=async=1:first_pts=0,aformat=sample_rates=44100:channel_layouts=stereo,volume={data.music_volume}[bgm];"
                "[vo][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
            )
        else:
            concat_filter = "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]"

        full_filter = v0_filter + v1_filter + a0_filter + a1_filter + concat_filter

        cmd_merge.extend([
            "-filter_complex", full_filter,
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            out_path
        ])

        # 6. Jalankan FFmpeg
        res = subprocess.run(cmd_merge, capture_output=True, text=True)
        if res.returncode != 0:
            raise HTTPException(status_code=500, detail=f"FFmpeg render error: {res.stderr}")

        background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)
        return FileResponse(out_path, media_type="video/mp4", filename="merged.mp4")

    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/jointext")
async def join_text(data: JoinTextRequest, background_tasks: BackgroundTasks):
    """Menambahkan teks outline meme rata tengah ke gambar dengan auto-wrap"""
    task_id = str(uuid.uuid4())
    work_dir = f"/tmp/{task_id}"
    os.makedirs(work_dir, exist_ok=True)

    input_img_path = os.path.join(work_dir, "input.jpg")
    output_img_path = os.path.join(work_dir, "output.jpg")
    text_file_path = os.path.join(work_dir, "text.txt")

    try:
        # 1. Unduh Gambar
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(data.image_url)
            if resp.status_code != 200:
                raise HTTPException(status_code=400, detail="Gagal mengunduh gambar")
            with open(input_img_path, "wb") as f:
                f.write(resp.content)

        # 2. AUTO-WRAP: Bungkus teks per baris agar otomatis turun ke bawah jika kepanjangan
        lines = data.text.split("\n")
        wrapped_lines = []
        for line in lines:
            if line.strip():
                # textwrap.wrap akan memotong per spasi kata dengan rapi
                wrapped = textwrap.wrap(line, width=data.max_chars_per_line)
                wrapped_lines.extend(wrapped)
            else:
                wrapped_lines.append("")  # Menjaga spasi baris kosong jika ada enter manual

        final_text = "\n".join(wrapped_lines)

        # 3. Simpan teks yang sudah rapi ke text.txt
        with open(text_file_path, "w", encoding="utf-8") as f:
            f.write(final_text)

        # 4. Rakit Filter FFmpeg drawtext
        drawtext_filter = (
            f"drawtext=textfile='{text_file_path}':"
            f"fontsize={data.font_size}:"
            f"fontcolor={data.font_color}:"
            f"borderw={data.border_width}:"
            f"bordercolor={data.border_color}:"
            f"line_spacing=12:"
            f"x=(w-text_w)/2:"
            f"y={data.y_position}"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", input_img_path,
            "-vf", drawtext_filter,
            output_img_path
        ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise HTTPException(status_code=500, detail=f"FFmpeg text error: {res.stderr}")

        background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)
        return FileResponse(output_img_path, media_type="image/jpeg", filename="captioned.jpg")

    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))