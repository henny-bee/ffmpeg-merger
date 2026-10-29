import os
import shutil
import subprocess
import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from core.media import FFMPEG_BIN, create_work_dir, check_has_audio, get_video_duration
from schemas.requests import MergeRequest

router = APIRouter()


@router.post("/merge")
async def merge_videos(data: MergeRequest, background_tasks: BackgroundTasks):
    work_dir = create_work_dir()
    v1_path = os.path.join(work_dir, "v1.mp4")
    v2_path = os.path.join(work_dir, "v2.mp4")
    music_path = os.path.join(work_dir, "music.mp3")
    out_path = os.path.join(work_dir, "merged.mp4")

    has_v2 = bool(data.video_url_2)
    has_music = bool(data.music_url)

    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            r1 = await client.get(data.video_url_1)
            if r1.status_code != 200:
                raise HTTPException(status_code=400, detail="Gagal mengunduh video 1")
            with open(v1_path, "wb") as f:
                f.write(r1.content)

            if has_v2:
                r2 = await client.get(data.video_url_2)
                if r2.status_code != 200:
                    raise HTTPException(status_code=400, detail="Gagal mengunduh video 2")
                with open(v2_path, "wb") as f:
                    f.write(r2.content)

            if has_music:
                rm = await client.get(data.music_url)
                if rm.status_code != 200:
                    raise HTTPException(status_code=400, detail="Gagal mengunduh file MP3 musik")
                with open(music_path, "wb") as f:
                    f.write(rm.content)

        dur1 = get_video_duration(v1_path)
        has_a1 = check_has_audio(v1_path)

        cmd_merge = [FFMPEG_BIN, "-y", "-i", v1_path]
        music_input_index = 1

        if has_v2:
            cmd_merge.extend(["-i", v2_path])
            music_input_index = 2

            dur2 = get_video_duration(v2_path)
            has_a2 = check_has_audio(v2_path)

            v0_filter = f"[0:v]fps=30,scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,trim=0:{dur1},setpts=PTS-STARTPTS[v0];"
            v1_filter = f"[1:v]fps=30,scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,trim=0:{dur2},setpts=PTS-STARTPTS[v1];"

            if has_a1:
                a0_filter = f"[0:a]aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS,aformat=sample_rates=44100:channel_layouts=stereo,apad,atrim=0:{dur1},asetpts=PTS-STARTPTS[a0];"
            else:
                a0_filter = f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=0:{dur1},asetpts=PTS-STARTPTS[a0];"

            if has_a2:
                a1_filter = f"[1:a]aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS,aformat=sample_rates=44100:channel_layouts=stereo,apad,atrim=0:{dur2},asetpts=PTS-STARTPTS[a1];"
            else:
                a1_filter = f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=0:{dur2},asetpts=PTS-STARTPTS[a1];"

            base_filters = v0_filter + v1_filter + a0_filter + a1_filter + "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v_base][a_base];"
        else:
            v0_filter = f"[0:v]fps=30,scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,trim=0:{dur1},setpts=PTS-STARTPTS[v_base];"
            if has_a1:
                a0_filter = f"[0:a]aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS,aformat=sample_rates=44100:channel_layouts=stereo,apad,atrim=0:{dur1},asetpts=PTS-STARTPTS[a_base];"
            else:
                a0_filter = f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=0:{dur1},asetpts=PTS-STARTPTS[a_base];"

            base_filters = v0_filter + a0_filter

        if has_music:
            cmd_merge.extend(["-stream_loop", "-1", "-i", music_path])
            audio_filter = (
                f"[a_base]volume={data.video_volume}[vo];"
                f"[{music_input_index}:a]aresample=async=1:first_pts=0,aformat=sample_rates=44100:channel_layouts=stereo,volume={data.music_volume}[bgm];"
                "[vo][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
            )
        else:
            audio_filter = f"[a_base]volume={data.video_volume}[a]"

        full_filter = base_filters + audio_filter

        cmd_merge.extend([
            "-filter_complex", full_filter,
            "-map", "[v_base]",
            "-map", "[a]",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            out_path
        ])

        res = subprocess.run(cmd_merge, capture_output=True, text=True)
        if res.returncode != 0:
            raise HTTPException(status_code=500, detail=f"FFmpeg render error: {res.stderr}")

        background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)
        return FileResponse(out_path, media_type="video/mp4", filename="merged.mp4")

    except HTTPException:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))
