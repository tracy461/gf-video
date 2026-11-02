#!/usr/bin/env python3
"""Make a 15 second vertical Reel (1080x1920) from five lines of text.

Text comes from environment variables (so nothing is ever run as a command):
  ROW_ID, HOOK, TIP1, TIP2, TIP3, CTA
Optional:
  GEMINI_API_KEY          if set, a Gemini voice reads each line out loud.
                          If the voice fails, the video is made without it.
Optional files in the assets/ folder:
  assets/background.jpg   photo used behind the text (otherwise a green gradient)
  assets/logo.png         logo shown at the top
  assets/music.mp3        background music (royalty-free only)
  assets/fonts/heading.ttf and assets/fonts/body.ttf   brand fonts
The video is saved as videos/<ROW_ID>.mp4
"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
FPS = 30
SCENE_SECONDS = 3
FADE = 0.4

# Brand colours. Replace these with the exact hex codes from the brand kit.
COLOR_TOP = (31, 77, 43)        # Deep Canopy
COLOR_BOTTOM = (15, 31, 61)     # Midnight Navy
COLOR_TEXT = (250, 246, 238)    # Warm White
COLOR_ACCENT = (192, 197, 203)  # Aluminium Silver
COLOR_BUTTON = (47, 107, 63)    # Forest Green

# Voice settings
TTS_MODEL = os.environ.get("TTS_MODEL", "gemini-3.1-flash-tts-preview")
VOICE_NAME = os.environ.get("VOICE_NAME", "Kore")
PCM_RATE = 24000  # Gemini sends 24 kHz, 16-bit, mono
MAX_LINE_SECONDS = 2.7

ASSETS = "assets"
FALLBACK_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]


def find_font(name):
    path = os.path.join(ASSETS, "fonts", name)
    if os.path.exists(path):
        return path
    for p in FALLBACK_FONTS:
        if os.path.exists(p):
            return p
    sys.exit("No font found. Add assets/fonts/heading.ttf and body.ttf")


def wrap(draw, text, font, max_width):
    lines, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def fit_text(draw, text, font_path, start_size, max_width, max_height):
    """Shrink the font until the wrapped text fits in the box."""
    size = start_size
    while size > 36:
        font = ImageFont.truetype(font_path, size)
        lines = wrap(draw, text, font, max_width)
        line_h = int(size * 1.25)
        if len(lines) * line_h <= max_height:
            return font, lines, line_h
        size -= 4
    font = ImageFont.truetype(font_path, 36)
    return font, wrap(draw, text, font, max_width), int(36 * 1.25)


def draw_block(draw, lines, font, line_h, center_y, fill):
    top = center_y - (len(lines) * line_h) // 2
    for i, line in enumerate(lines):
        w = draw.textlength(line, font=font)
        draw.text(((W - w) / 2, top + i * line_h), line, font=font, fill=fill)


def add_logo(img):
    path = os.path.join(ASSETS, "logo.png")
    if not os.path.exists(path):
        return
    logo = Image.open(path).convert("RGBA")
    width = 320
    logo = logo.resize((width, int(logo.height * width / logo.width)))
    img.alpha_composite(logo, ((W - width) // 2, 120))


def make_scene(kind, text, number, heading_font, body_font, out_path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    box_w = W - 200

    if kind == "hook":
        font, lines, lh = fit_text(draw, text, heading_font, 120, box_w, 900)
        draw_block(draw, lines, font, lh, H // 2, COLOR_TEXT)
        draw.rectangle([(W // 2 - 90, H // 2 + 520), (W // 2 + 90, H // 2 + 528)], fill=COLOR_ACCENT)
    elif kind == "tip":
        badge = ImageFont.truetype(heading_font, 220)
        label = str(number)
        bw = draw.textlength(label, font=badge)
        draw.text(((W - bw) / 2, 520), label, font=badge, fill=COLOR_ACCENT)
        font, lines, lh = fit_text(draw, text, body_font, 88, box_w, 650)
        draw_block(draw, lines, font, lh, 1130, COLOR_TEXT)
    else:  # cta
        font, lines, lh = fit_text(draw, text, heading_font, 96, box_w, 520)
        draw_block(draw, lines, font, lh, 800, COLOR_TEXT)
        button_font = ImageFont.truetype(body_font, 64)
        label = "FOLLOW"
        bw = draw.textlength(label, font=button_font)
        left, top = (W - 560) // 2, 1150
        draw.rounded_rectangle([(left, top), (left + 560, top + 150)], radius=75, fill=COLOR_BUTTON, outline=COLOR_TEXT, width=4)
        draw.text(((W - bw) / 2, top + 36), label, font=button_font, fill=COLOR_TEXT)

    add_logo(img)
    img.save(out_path)


def make_background(out_path):
    photo = os.path.join(ASSETS, "background.jpg")
    if os.path.exists(photo):
        img = Image.open(photo).convert("RGB")
        scale = max(W * 2 / img.width, H * 2 / img.height)
        img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1))
        left, top = (img.width - W * 2) // 2, (img.height - H * 2) // 2
        img = img.crop((left, top, left + W * 2, top + H * 2))
        dark = Image.new("RGB", img.size, COLOR_BOTTOM)
        img = Image.blend(img, dark, 0.6)
    else:
        img = Image.new("RGB", (W * 2, H * 2))
        px = ImageDraw.Draw(img)
        for y in range(H * 2):
            t = y / (H * 2 - 1)
            row = tuple(int(COLOR_TOP[i] + (COLOR_BOTTOM[i] - COLOR_TOP[i]) * t) for i in range(3))
            px.line([(0, y), (W * 2, y)], fill=row)
    img.save(out_path)


# ---------- Voice (optional) ----------

def synth(text, key):
    """Ask Gemini to read the text. Returns raw PCM bytes, or None if it fails."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{TTS_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [{"text": "Say warmly and clearly: " + text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE_NAME}}},
        },
    }
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                data = json.load(response)
            part = data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
            return base64.b64decode(part)
        except urllib.error.HTTPError as e:
            print(f"Voice request failed ({e.code}) {e.read()[:200]!r}")
            if e.code in (429, 500, 503) and attempt < 2:
                time.sleep(20)
                continue
            return None
        except Exception as e:  # network problem or an unexpected answer
            print("Voice request failed:", repr(e)[:200])
            return None
    return None


def build_voice_track(texts, key, tmp):
    """Read each line at the start of its scene. Returns a wav path, or None."""
    total = SCENE_SECONDS * len(texts)
    track = bytearray(PCM_RATE * 2 * total)  # silence
    for i, text in enumerate(texts):
        pcm = synth(text, key)
        if not pcm:
            return None
        seconds = len(pcm) / (PCM_RATE * 2)
        if seconds > MAX_LINE_SECONDS:  # speed up a long line so it fits its scene
            tempo = min(seconds / MAX_LINE_SECONDS, 1.6)
            raw_in, raw_out = os.path.join(tmp, f"v{i}.pcm"), os.path.join(tmp, f"v{i}_fast.pcm")
            with open(raw_in, "wb") as f:
                f.write(pcm)
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(PCM_RATE), "-ac", "1", "-i", raw_in,
                 "-filter:a", f"atempo={tempo:.3f}", "-f", "s16le", raw_out],
                check=True)
            with open(raw_out, "rb") as f:
                pcm = f.read()
        offset = int((i * SCENE_SECONDS + 0.15) * PCM_RATE) * 2
        pcm = pcm[: len(track) - offset]
        track[offset:offset + len(pcm)] = pcm
        if i < len(texts) - 1:
            time.sleep(13)  # stay under the free request limit
    wav_path = os.path.join(tmp, "voice.wav")
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(PCM_RATE)
        w.writeframes(bytes(track))
    return wav_path


# ---------- Main ----------

def main():
    row_id = os.environ.get("ROW_ID", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", row_id):
        sys.exit("ROW_ID must be letters, numbers, - or _ only")
    texts = [os.environ.get(k, "").strip() for k in ("HOOK", "TIP1", "TIP2", "TIP3", "CTA")]
    if not all(texts):
        sys.exit("HOOK, TIP1, TIP2, TIP3 and CTA must all have text")

    heading_font = find_font("heading.ttf")
    body_font = find_font("body.ttf")
    os.makedirs("videos", exist_ok=True)
    out = os.path.join("videos", row_id + ".mp4")
    total = SCENE_SECONDS * len(texts)

    with tempfile.TemporaryDirectory() as tmp:
        bg = os.path.join(tmp, "bg.png")
        make_background(bg)
        scenes = []
        kinds = [("hook", None), ("tip", 1), ("tip", 2), ("tip", 3), ("cta", None)]
        for i, (text, (kind, number)) in enumerate(zip(texts, kinds)):
            path = os.path.join(tmp, f"scene{i}.png")
            make_scene(kind, text, number, heading_font, body_font, path)
            scenes.append(path)

        voice = None
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if key:
            voice = build_voice_track(texts, key, tmp)
            print("Voice-over added" if voice else "Voice failed, making a video without it")

        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS), "-t", str(total), "-i", bg]
        for path in scenes:
            cmd += ["-loop", "1", "-framerate", str(FPS), "-t", str(SCENE_SECONDS), "-i", path]
        next_index = len(scenes) + 1

        voice_index = music_index = silence_index = None
        if voice:
            cmd += ["-i", voice]
            voice_index, next_index = next_index, next_index + 1
        music = os.path.join(ASSETS, "music.mp3")
        if os.path.exists(music):
            cmd += ["-i", music]
            music_index, next_index = next_index, next_index + 1
        if voice_index is None and music_index is None:
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
            silence_index = next_index

        zoom = f"[0:v]zoompan=z='min(1+0.0003*on,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},format=yuv420p[base0]"
        parts = [zoom]
        last = "base0"
        for i in range(len(scenes)):
            start = i * SCENE_SECONDS
            out_start = SCENE_SECONDS - FADE
            parts.append(
                f"[{i + 1}:v]format=rgba,fade=t=in:st=0:d={FADE}:alpha=1,"
                f"fade=t=out:st={out_start}:d={FADE}:alpha=1,setpts=PTS+{start}/TB[s{i}]"
            )
            parts.append(f"[{last}][s{i}]overlay=eof_action=pass:format=auto[base{i + 1}]")
            last = f"base{i + 1}"
        parts.append(f"[{last}]format=yuv420p[v]")

        fade_out = f"afade=t=out:st={total - 1}:d=1"
        if voice_index is not None and music_index is not None:
            parts.append(f"[{voice_index}:a]apad=whole_dur={total},atrim=0:{total}[vo]")
            parts.append(f"[{music_index}:a]atrim=0:{total},volume=0.15[mu]")
            parts.append(f"[vo][mu]amix=inputs=2:duration=longest:dropout_transition=0,volume=1.8,{fade_out}[a]")
        elif voice_index is not None:
            parts.append(f"[{voice_index}:a]apad=whole_dur={total},atrim=0:{total},{fade_out}[a]")
        elif music_index is not None:
            parts.append(f"[{music_index}:a]atrim=0:{total},{fade_out},volume=0.35[a]")
        else:
            parts.append(f"[{silence_index}:a]atrim=0:{total}[a]")

        cmd += [
            "-filter_complex", ";".join(parts),
            "-map", "[v]", "-map", "[a]",
            "-t", str(total), "-r", str(FPS),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-movflags", "+faststart",
            out,
        ]
        subprocess.run(cmd, check=True)
    print("Saved", out)


if __name__ == "__main__":
    main()
