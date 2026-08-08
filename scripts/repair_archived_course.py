#!/usr/bin/env python3
"""Re-transcribe one archived course with current timestamp/confidence safeguards."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from course_pipeline import archive_and_enhance, find_archived_course  # noqa: E402
from local_server import reliable_transcript_segment, transcript_path, transcribe_audio  # noqa: E402


def duration(path: Path) -> float:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(completed.stdout.strip())


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("course_url")
    args = parser.parse_args()
    directory, metadata = find_archived_course(args.course_url)
    if not directory:
        raise SystemExit("没有找到课程归档")

    old_raw = read_jsonl(directory / "transcripts" / "raw.jsonl")
    cache = transcript_path(args.course_url, metadata.get("title") or "course")
    cached_records = read_jsonl(cache)
    audio_urls = {
        (row.get("order"), row.get("content_id")): row.get("audio_url")
        for row in cached_records if row.get("category") == "audio" and row.get("audio_url")
    }
    page_rows = {
        (row.get("order"), row.get("content_id")): row
        for row in old_raw if row.get("source_type") == "page_text"
    }
    ordered_keys = sorted(set(audio_urls) | set(page_rows), key=lambda key: (key[0] or 0, key[1] or 0))

    backup_root = ROOT / "data" / "backups" / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-course-{metadata.get('course_id')}"
    backup_root.mkdir(parents=True)
    shutil.copytree(directory / "transcripts", backup_root / "transcripts")
    shutil.copy2(directory / "course.json", backup_root / "course.json")
    shutil.copy2(cache, backup_root / cache.name)
    print(f"备份：{backup_root}", flush=True)

    cumulative = 0.0
    raw_rows: list[dict] = []
    items = []
    for position, key in enumerate(ordered_keys, 1):
        order, content_id = key
        common = {
            "schema_version": "1.0", "course_id": int(metadata["course_id"]),
            "source_url": args.course_url, "content_id": content_id, "order": order,
        }
        if key in page_rows:
            text = page_rows[key]["text"]
            raw_rows.append({
                **common, "source_type": "page_text", "start": round(cumulative, 2),
                "end": round(cumulative, 2), "text": text, "layer": "raw",
            })
            items.append({"id": content_id, "order": order, "category": "text", "text": text, "duration": 0})
            continue

        url = audio_urls[key]
        print(f"[{position}/{len(ordered_keys)}] 下载并转写音频 {content_id}", flush=True)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temporary:
            audio_path = Path(temporary.name)
        try:
            urllib.request.urlretrieve(url, audio_path)
            audio_duration = duration(audio_path)
            result, engine = transcribe_audio(audio_path)
            kept = 0
            for segment in result.get("segments", []):
                if not reliable_transcript_segment(segment, audio_duration):
                    continue
                local_start = max(0.0, float(segment["start"]))
                local_end = min(audio_duration, float(segment["end"]))
                raw_rows.append({
                    **common, "source_type": "audio_transcript",
                    "start": round(cumulative + local_start, 2),
                    "end": round(cumulative + local_end, 2),
                    "text": str(segment["text"]).strip(), "layer": "raw",
                    "avg_logprob": segment.get("avg_logprob"),
                    "no_speech_prob": segment.get("no_speech_prob"),
                    "content_start": round(cumulative, 2),
                    "content_end": round(cumulative + audio_duration, 2),
                    "engine": engine,
                })
                kept += 1
            print(f"  {audio_duration:.2f} 秒，保留 {kept} 个可靠片段", flush=True)
            items.append({
                "id": content_id, "order": order, "category": "audio",
                "duration": round(audio_duration * 1000), "url": url,
            })
            cumulative += audio_duration
        finally:
            audio_path.unlink(missing_ok=True)

    payload = {
        "course_url": args.course_url, "course_title": metadata.get("title") or directory.name,
        "course_category": metadata.get("category") or directory.parent.parent.name, "items": items,
    }
    result = archive_and_enhance(
        payload, raw_rows, cache,
        status=lambda state, message: print(f"{state}: {message}", flush=True),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
