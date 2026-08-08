#!/usr/bin/env python3
"""Restore the page display cache from the complete, immutable course archive."""
from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "library" / "AI课" / "courses" / "802-Claude-Code是个大模型调度器" / "transcripts" / "reading.jsonl"
CACHE = ROOT / "data" / "transcripts" / "2026.07.30.Claude.Code.是个大模型调度器-62d16d91330e777a.jsonl"


def main():
    segments = [json.loads(line) for line in ARCHIVE.read_text(encoding="utf-8").splitlines() if line.strip()]
    groups = OrderedDict()
    for segment in segments:
        key = (segment.get("order"), segment.get("content_id"), segment.get("source_type"))
        record = groups.setdefault(key, {
            "schema_version": "1.0",
            "course_id": "62d16d91330e777a",
            "source_url": segment.get("source_url"),
            "course_title": "2026.07.30.Claude.Code.是个大模型调度器",
            "content_id": segment.get("content_id"),
            "order": segment.get("order"),
            "category": "text" if segment.get("source_type") == "page_text" else "audio",
            "engine": "archive-restore",
            "segments": [],
        })
        record["segments"].append({
            "start": segment.get("start"),
            "end": segment.get("end"),
            "text": segment.get("text", ""),
            "raw_text": segment.get("raw_text"),
            "source_type": segment.get("source_type"),
            "transform": segment.get("transform"),
            "punctuation_inferred": segment.get("punctuation_inferred", False),
            "time_inferred": segment.get("time_inferred", False),
        })
    CACHE.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in groups.values()) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(groups), "segments": len(segments), "cache": str(CACHE)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
