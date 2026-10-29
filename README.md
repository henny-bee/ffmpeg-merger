# ffpp — FFmpeg Processing API

A lightweight **FastAPI** service for processing video and images with **FFmpeg**.
Built for vertical (9:16) content pipelines — convenient to drive from automation
tools like n8n or Make, or any script that can send an HTTP request.

Every endpoint takes a **URL** as input (no file uploads) and returns the rendered
file directly in the response.

## Features

- **`/merge`** — concatenate two videos (or process a single one), normalize to 720x1280, and mix in background music with independent volume control.
- **`/jointext`** — burn meme-style text (outlined, centered, auto-wrapped) onto an image.
- **`/image-to-video`** — turn a still image into a 1080x1920 HD video of any duration, with a silent audio track.
- **`/thumbnail`** — extract the middle frame of a video, center-crop to 16:9 (`1280x720`), and render a news-style headline with blurred dark shadow, `*...*` red highlight boxes, and a bottom-right `Source:` badge.

## Stack

| Component | Details |
|---|---|
| Python | 3.10 (slim) |
| Framework | FastAPI + Uvicorn |
| HTTP client | httpx (async, follows redirects) |
| Media | ffmpeg / ffprobe |

## Running

### Docker (recommended)

```bash
docker build -t ffpp .
docker run -p 10000:10000 ffpp
```

The port is configurable via the `PORT` environment variable (default `10000`):

```bash
docker run -p 8080:8080 -e PORT=8080 ffpp
```

### Local

Requires `ffmpeg` and `ffprobe` installed and available on your `PATH`.

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 10000 --reload
```

Interactive API docs are served at `http://localhost:10000/docs`.

> **Note:** temporary working files are written to `/tmp/<uuid>/`, so running
> natively on Windows requires adjusting the paths in `app.py`. Use Docker or
> WSL for the intended experience.

## Endpoints

### `GET /`

Health check.

```json
{ "status": "FFmpeg API is running!" }
```

---

### `POST /merge`

Concatenates two videos into one, or processes just the first when `video_url_2`
is omitted. Each input is normalized first (30 fps, scaled to 720x1280 with
letterbox padding, `yuv420p`) so the concatenation doesn't glitch. Videos without
an audio stream get a silent track generated for them, keeping audio and video
durations in sync.

When `music_url` is provided, the track is looped indefinitely and then trimmed
to the video length (`amix ... duration=first`).

**Request body**

| Field | Type | Default | Description |
|---|---|---|---|
| `video_url_1` | string | *required* | URL of the first video |
| `video_url_2` | string | `null` | URL of the second video (optional) |
| `music_url` | string | `null` | URL of an MP3 background track (optional) |
| `music_volume` | float | `1.0` | Music volume, `1.0` = 100% |
| `video_volume` | float | `1.0` | Original video audio volume, `1.0` = 100% |

**Example**

```bash
curl -X POST http://localhost:10000/merge \
  -H "Content-Type: application/json" \
  -d '{
    "video_url_1": "https://example.com/clip-a.mp4",
    "video_url_2": "https://example.com/clip-b.mp4",
    "music_url": "https://example.com/bgm.mp3",
    "music_volume": 0.25,
    "video_volume": 1.0
  }' --output merged.mp4
```

**Response:** `video/mp4` (`merged.mp4`) — H.264 / AAC 192k, `+faststart`.

---

### `POST /jointext`

Burns meme-style text onto an image: horizontally centered, outlined, and
**auto-wrapped** based on `max_chars_per_line`. Explicit newlines (`\n`) in the
text are preserved.

**Request body**

| Field | Type | Default | Description |
|---|---|---|---|
| `image_url` | string | *required* | URL of the source image |
| `text` | string | *required* | Text to overlay |
| `max_chars_per_line` | int | `30` | Character budget before wrapping |
| `font_size` | int | `42` | Font size |
| `font_color` | string | `"white"` | Text color (FFmpeg color name or hex) |
| `border_color` | string | `"black"` | Outline color |
| `border_width` | int | `5` | Outline thickness |
| `y_position` | string | `"h*0.22"` | Vertical position, as an FFmpeg expression |

**Example**

```bash
curl -X POST http://localhost:10000/jointext \
  -H "Content-Type: application/json" \
  -d '{
    "image_url": "https://example.com/photo.jpg",
    "text": "Deploying on a Friday afternoon\nand everything is fine",
    "max_chars_per_line": 28,
    "font_size": 48
  }' --output captioned.jpg
```

**Response:** `image/jpeg` (`captioned.jpg`).

---

### `POST /image-to-video`

Turns a single still image into a video of a given duration. The image is scaled
with its aspect ratio preserved and padded to fit the target canvas. The output
always carries an audio track (silent), so it stays safe to feed back into
`/merge`.

**Request body**

| Field | Type | Default | Description |
|---|---|---|---|
| `image_url` | string | *required* | URL of the source image |
| `duration` | float | `9.0` | Video duration in seconds |
| `fps` | int | `30` | Frame rate |
| `width` | int | `1080` | Output width |
| `height` | int | `1920` | Output height |

**Example**

```bash
curl -X POST http://localhost:10000/image-to-video \
  -H "Content-Type: application/json" \
  -d '{
    "image_url": "https://example.com/poster.jpg",
    "duration": 5,
    "width": 1080,
    "height": 1920
  }' --output video.mp4
```

**Response:** `video/mp4` (`video_hd_<duration>s.mp4`) — encoded with
`-tune stillimage`, `crf 20`, capped at 2 threads to keep memory usage low.

## Operational notes

- **Encoding preset.** Every endpoint uses `-preset ultrafast` to keep responses
  fast; file sizes are larger than they would be with a slower preset.
- **Memory.** `/image-to-video` deliberately caps `-threads 2` to avoid OOM (502)
  crashes on low-RAM hosts such as Render's free tier.
- **Cleanup.** The `/tmp/<uuid>/` working directory is removed via
  `BackgroundTasks` once the response is sent, and immediately on error.
- **Download timeouts.** 120 seconds for `/merge`, 60 seconds for the others.
- **Error handling.** Failed downloads return `400`; FFmpeg render failures
  return `500` along with the captured `stderr` for debugging.

## Project structure

```
.
├── app.py                     # FastAPI entrypoint (registers routers)
├── core/
│   └── media.py               # FFmpeg/FFprobe helpers, temp dir, font loader
├── schemas/
│   └── requests.py            # Pydantic request models
├── routers/
│   ├── merge.py               # POST /merge
│   ├── jointext.py            # POST /jointext
│   ├── image_to_video.py      # POST /image-to-video
│   └── thumbnail.py           # POST /thumbnail
├── requirements.txt           # fastapi, uvicorn, httpx, pillow
├── Dockerfile                 # python:3.10-slim + ffmpeg + fonts
└── README.md
```
