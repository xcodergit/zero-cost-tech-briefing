#!/usr/bin/env python3
"""Zero-paid-API tech news collector and vertical video renderer."""
from __future__ import annotations

import html
import json
import logging
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import feedparser
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
OUT = ROOT / CONFIG.get("output_dir", "output")
WIDTH, HEIGHT = 1080, 1920
BG = (8, 15, 32)
WHITE = (245, 248, 255)
MUTED = (173, 188, 210)
CYAN = (69, 220, 235)
PURPLE = (135, 113, 255)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def check_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required command not found: {name}")


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"https?://\S+", "", value)
    return re.sub(r"\s+", " ", value).strip()


def entry_date(entry):
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        st = entry.get(key)
        if st:
            try:
                return datetime(*st[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
    return None


def collect_stories():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=int(CONFIG.get("max_age_hours", 36)))
    stories, seen = [], set()
    for feed_url in CONFIG["feeds"]:
        logging.info("Reading feed: %s", feed_url)
        try:
            parsed = feedparser.parse(feed_url, request_headers={"User-Agent": "ZeroCostTechBriefing/1.0"})
            if getattr(parsed, "bozo", False):
                logging.warning("Feed parser warning for %s: %s", feed_url, getattr(parsed, "bozo_exception", "unknown"))
            for entry in parsed.entries:
                title = clean_text(entry.get("title", ""))
                link = entry.get("link", "")
                if not title or not link or not link.startswith(("https://", "http://")):
                    continue
                norm = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
                if norm in seen:
                    continue
                published = entry_date(entry)
                if published is None or published < cutoff or published > now + timedelta(hours=2):
                    continue
                summary = clean_text(entry.get("summary", "") or entry.get("description", ""))
                summary = re.sub(r"\s+", " ", summary)
                summary = summary[:360].rsplit(" ", 1)[0] if len(summary) > 360 else summary
                domain = urlparse(link).netloc.lower().removeprefix("www.")
                stories.append({
                    "title": title[:180], "url": link, "source": domain or "Source",
                    "published_utc": published.isoformat(), "summary": summary, "feed": feed_url,
                })
                seen.add(norm)
        except Exception as exc:
            logging.warning("Could not read feed %s: %s", feed_url, exc)
    stories.sort(key=lambda x: x["published_utc"], reverse=True)
    limit = max(1, min(5, int(CONFIG.get("max_stories", 3))))
    selected = stories[:limit]
    if not selected:
        raise RuntimeError(
            "No recent dated stories were found. Check feed URLs or increase max_age_hours in config.json. "
            "No video was generated to avoid fabricating news."
        )
    logging.info("Selected %d recent stories", len(selected))
    return selected


def make_narration(story, index, total):
    title = story["title"].rstrip(".!?")
    summary = story["summary"].strip()
    if summary:
        summary = summary[:240].rsplit(" ", 1)[0] if len(summary) > 240 else summary
        return f"Tech briefing, story {index} of {total}. {title}. Here is the reported context. {summary}. Source: {story['source']}."
    return f"Tech briefing, story {index} of {total}. {title}. Read the original report from {story['source']} for the full details."


def load_font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def wrap_by_pixels(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_gradient():
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    pix = img.load()
    for y in range(HEIGHT):
        t = y / max(1, HEIGHT - 1)
        c = tuple(int(BG[i] * (1 - t) + (22, 31, 68)[i] * t) for i in range(3))
        for x in range(WIDTH):
            pix[x, y] = c
    return img


def create_card(story, index, total, target):
    img = draw_gradient()
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((64, 80, WIDTH - 64, 154), radius=30, fill=(20, 34, 65), outline=(47, 73, 117), width=2)
    draw.ellipse((88, 103, 116, 131), fill=CYAN)
    draw.text((140, 99), "TECH BRIEFING  /  DAILY", font=load_font(30, True), fill=WHITE)
    draw.text((72, 220), f"STORY {index:02d} / {total:02d}", font=load_font(31, True), fill=CYAN)
    for i in range(7):
        x = 760 + i * 35
        draw.line((x, 310, x, 510 + (i % 3) * 35), fill=(32, 63, 105), width=3)
    draw.rounded_rectangle((70, 310, WIDTH - 70, 555), radius=32, fill=(13, 25, 49), outline=(43, 65, 104), width=3)
    draw.text((105, 350), "WHAT'S NEW", font=load_font(27, True), fill=PURPLE)
    title_font = load_font(62, True)
    title_lines = wrap_by_pixels(draw, story["title"], title_font, WIDTH - 180)
    if len(title_lines) > 6:
        title_lines = title_lines[:5] + [title_lines[5][:max(8, len(title_lines[5]) - 3)] + "..."]
    y = 610
    for line in title_lines:
        draw.text((76, y), line, font=title_font, fill=WHITE)
        y += 82
    summary = story["summary"] or "A new development reported by the source. Open the original story for full context."
    summary = summary[:280].rsplit(" ", 1)[0] if len(summary) > 280 else summary
    body_font = load_font(34)
    body_lines = wrap_by_pixels(draw, summary, body_font, WIDTH - 180)[:7]
    y = max(y + 35, 1130)
    draw.rounded_rectangle((70, y - 35, WIDTH - 70, min(1570, y + len(body_lines) * 54 + 45)), radius=28, fill=(14, 28, 54), outline=(37, 59, 94), width=2)
    for line in body_lines:
        draw.text((105, y), line, font=body_font, fill=MUTED)
        y += 54
    draw.line((75, 1650, WIDTH - 75, 1650), fill=(53, 78, 117), width=3)
    draw.text((78, 1690), story["source"][:60], font=load_font(30, True), fill=CYAN)
    draw.text((78, 1740), f"Published: {story['published_utc'][:10]}", font=load_font(25), fill=MUTED)
    draw.text((78, 1820), "Read sources before sharing  •  Automated briefing", font=load_font(22), fill=(139, 156, 185))
    img.save(target, quality=94)


def run(cmd):
    logging.info("Running: %s", " ".join(map(str, cmd[:6])) + (" ..." if len(cmd) > 6 else ""))
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def render_segment(image_path, wav_path, mp4_path):
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", str(image_path), "-i", str(wav_path),
        "-vf", "scale=1080:1920,format=yuv420p",
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
        "-r", "30", "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-movflags", "+faststart", str(mp4_path)
    ])


def main():
    check_tool("ffmpeg")
    check_tool("espeak-ng")
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*"):
        if old.is_file():
            old.unlink()
    stories = collect_stories()
    scripts, segments = [], []
    for i, story in enumerate(stories, 1):
        narration = make_narration(story, i, len(stories))
        scripts.append(narration)
        card_path = OUT / f"card_{i:02d}.png"
        wav_path = OUT / f"voice_{i:02d}.wav"
        seg_path = OUT / f"segment_{i:02d}.mp4"
        create_card(story, i, len(stories), card_path)
        run(["espeak-ng", "-v", "en-us", "-s", "155", "-w", str(wav_path), narration])
        render_segment(card_path, wav_path, seg_path)
        segments.append(seg_path)
    concat_file = OUT / "concat.txt"
    concat_file.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in segments), encoding="utf-8")
    final_video = OUT / "tech_briefing.mp4"
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-c", "copy", "-movflags", "+faststart", str(final_video)
    ])
    (OUT / "script.txt").write_text("\n\n".join(scripts) + "\n", encoding="utf-8")
    (OUT / "sources.json").write_text(json.dumps({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stories": stories,
        "note": "Automated RSS-based briefing. Verify source pages and claims before publishing."
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-show_entries", "stream=codec_type,width,height", "-of", "json", str(final_video)
    ], check=True, capture_output=True, text=True)
    info = json.loads(probe.stdout)
    duration = float(info.get("format", {}).get("duration", 0))
    video_stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    if duration <= 1 or video_stream.get("width") != WIDTH or video_stream.get("height") != HEIGHT:
        raise RuntimeError(f"Output validation failed: duration={duration}, video={video_stream}")
    logging.info("Created %s (%.1f seconds, %sx%s)", final_video, duration, video_stream.get("width"), video_stream.get("height"))
    print(f"SUCCESS: {final_video}")
    print("Download the tech-briefing-video artifact from this GitHub Actions run.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.exception("Video generation failed: %s", exc)
        sys.exit(1)
