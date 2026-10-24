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
from difflib import SequenceMatcher
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


def source_label(entry, link, feed_url):
    source = entry.get("source", {})
    label = clean_text(source.get("title", "")) if hasattr(source, "get") else ""
    title = clean_text(entry.get("title", ""))
    feed_host = urlparse(feed_url).netloc.lower().removeprefix("www.")
    link_host = urlparse(link).netloc.lower().removeprefix("www.")
    if not label and feed_host == "news.google.com" and " - " in title:
        title, possible_source = title.rsplit(" - ", 1)
        label = possible_source.strip()
    if not label:
        label = link_host if link_host and link_host != "news.google.com" else feed_host
    return title.strip(), label.strip() or "Unknown source"


def normalized_words(text):
    ignored = {
        "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with",
        "from", "by", "as", "at", "is", "are", "be", "how", "why", "what",
        "this", "that", "its", "it", "after", "over", "new", "says", "will",
    }
    return {
        word for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) > 2 and word not in ignored
    }


def title_similarity(left, right):
    a, b = normalized_words(left), normalized_words(right)
    if not a or not b:
        return 0.0
    overlap = len(a & b) / max(1, len(a | b))
    sequence = SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(b))).ratio()
    return max(overlap, sequence)


def editorial_score(story, age_hours):
    source = (story["source"] + " " + story["source_domain"]).lower()
    if "arstechnica" in source or "the verge" in source or "theverge" in source:
        source_points = 3
        source_reason = "established technology publication"
    elif "techcrunch" in source:
        source_points = 3
        source_reason = "established technology/startup publication"
    elif "google news" in source or "news.google.com" in source:
        source_points = 2
        source_reason = "news aggregator; publisher attribution checked where available"
    elif "hnrss" in source or "hacker news" in source:
        source_points = 0
        source_reason = "community discovery source"
    else:
        source_points = 1
        source_reason = "other publisher; review source context"

    freshness_points = 3 if age_hours <= 12 else 2 if age_hours <= 24 else 1
    summary_len = len(story["summary"])
    context_points = 2 if summary_len >= 180 else 1 if summary_len >= 80 else 0
    title_points = 1 if len(story["title"]) >= 28 and len(normalized_words(story["title"])) >= 5 else 0
    penalty = 2 if re.search(r"\b(podcast|sponsored|deals roundup|weekly roundup|opinion)\b", story["title"], re.I) else 0
    score = source_points + freshness_points + context_points + title_points - penalty
    reasons = [source_reason, f"published within {int(age_hours)} hours"]
    if context_points:
        reasons.append("has a usable RSS summary")
    if penalty:
        reasons.append("penalized as a less suitable briefing format")
    return score, reasons


def collect_stories():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=int(CONFIG.get("max_age_hours", 36)))
    candidates = []
    min_score = int(CONFIG.get("min_quality_score", 5))
    for feed_url in CONFIG["feeds"]:
        logging.info("Reading feed: %s", feed_url)
        try:
            parsed = feedparser.parse(feed_url, request_headers={"User-Agent": "ZeroCostTechBriefing/1.0"})
            if getattr(parsed, "bozo", False):
                logging.warning("Feed parser warning for %s: %s", feed_url, getattr(parsed, "bozo_exception", "unknown"))
            for entry in parsed.entries:
                link = entry.get("link", "")
                if not link or not link.startswith(("https://", "http://")):
                    continue
                title, source = source_label(entry, link, feed_url)
                if not title or len(normalized_words(title)) < 4:
                    continue
                published = entry_date(entry)
                if published is None or published < cutoff or published > now + timedelta(hours=2):
                    continue
                age_hours = max(0.0, (now - published).total_seconds() / 3600)
                summary = clean_text(entry.get("summary", "") or entry.get("description", ""))
                summary = re.sub(r"\s+", " ", summary)
                summary = summary[:600].rsplit(" ", 1)[0] if len(summary) > 600 else summary
                domain = urlparse(link).netloc.lower().removeprefix("www.")
                story = {
                    "title": title[:180], "url": link, "source": source[:100],
                    "source_domain": domain or urlparse(feed_url).netloc.lower(),
                    "published_utc": published.isoformat(), "summary": summary,
                    "feed": feed_url, "corroborating_sources": [], "corroborating_urls": [],
                }
                score, reasons = editorial_score(story, age_hours)
                story["quality_score"] = score
                story["quality_reasons"] = reasons
                if score < min_score:
                    logging.info("Rejected low-scoring story (%s): %s", score, story["title"])
                    continue
                candidates.append(story)
        except Exception as exc:
            logging.warning("Could not read feed %s: %s", feed_url, exc)

    # Group likely duplicate coverage across feeds. This is a heuristic, not proof
    # that two reports independently verify every detail.
    candidates.sort(key=lambda item: (item["quality_score"], item["published_utc"]), reverse=True)
    groups = []
    for story in candidates:
        matching = None
        for group in groups:
            if any(title_similarity(story["title"], member["title"]) >= 0.58 for member in group):
                matching = group
                break
        if matching is None:
            groups.append([story])
        else:
            matching.append(story)

    ranked = []
    for group in groups:
        group.sort(key=lambda item: (item["quality_score"], item["published_utc"]), reverse=True)
        representative = group[0]
        publishers = []
        urls = []
        for item in group[1:]:
            if item["source"].lower() != representative["source"].lower() and item["source"] not in publishers:
                publishers.append(item["source"])
                urls.append(item["url"])
        representative["corroborating_sources"] = publishers[:4]
        representative["corroborating_urls"] = urls[:4]
        if publishers:
            representative["quality_score"] += 2
            representative["quality_reasons"].append(
                "similar headline coverage found from another named source (heuristic corroboration)"
            )
        ranked.append(representative)

    ranked.sort(key=lambda item: (item["quality_score"], item["published_utc"]), reverse=True)
    limit = max(2, min(3, int(CONFIG.get("max_stories", 3))))
    selected = []
    source_counts = {}
    for story in ranked:
        source_key = story["source"].lower()
        if source_counts.get(source_key, 0) >= 2:
            continue
        selected.append(story)
        source_counts[source_key] = source_counts.get(source_key, 0) + 1
        if len(selected) >= limit:
            break

    minimum = max(2, int(CONFIG.get("min_stories", 2)))
    if len(selected) < minimum:
        raise RuntimeError(
            f"Quality gate: only {len(selected)} story/stories met the freshness and quality rules; "
            f"at least {minimum} are required. No video was generated. Try again on a stronger news day "
            "or review the RSS feeds and quality threshold in config.json."
        )
    logging.info("Quality gate selected %d stories; scores: %s", len(selected),
                 [story["quality_score"] for story in selected])
    return selected


def make_narration(story, index, total):
    title = story["title"].rstrip(".!?")
    summary = story["summary"].strip()
    if summary:
        summary = summary[:320].rsplit(" ", 1)[0] if len(summary) > 320 else summary
        return (
            f"Here is a tech story worth knowing, story {index} of {total}. "
            f"{title}. The available report says: {summary}. "
            f"The source is {story['source']}. Check the linked original report for full context."
        )
    return (
        f"Here is a tech story worth knowing, story {index} of {total}. {title}. "
        f"The RSS feed did not provide enough context for a detailed summary, so we are not adding "
        f"extra claims. Read the original report from {story['source']} using the source link."
    )


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
