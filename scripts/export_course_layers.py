#!/usr/bin/env python3
"""Export one generated transcript into traceable raw and reading layers."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data" / "transcripts"
DEST = ROOT / "library" / "AI课" / "courses" / "802-Claude-Code是个大模型调度器" / "transcripts"


def stamp(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def main():
    matches = sorted(SOURCE_DIR.glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not matches:
        raise SystemExit("没有找到可导出的课程文字稿")
    source = matches[0]
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    DEST.mkdir(parents=True, exist_ok=True)
    raw_path = DEST / "raw.jsonl"
    reading_path = DEST / "reading.jsonl"
    markdown_path = DEST / "reading.md"
    raw_lines = []
    reading_lines = []
    markdown = ["# 2026.07.30 Claude Code 是个大模型调度器｜阅读稿", "", "> 来源课程：course_id=802；所有音频文字均可回到起止时间。", ""]
    for row in rows:
        for segment in row.get("segments", []):
            common = {
                "schema_version": "1.0",
                "course_id": 802,
                "content_id": row.get("content_id"),
                "order": row.get("order"),
                "source_type": segment.get("source_type"),
                "start": segment.get("start"),
                "end": segment.get("end"),
                "source_url": row.get("source_url"),
            }
            raw = {**common, "text": segment.get("raw_text", segment.get("text", "")), "layer": "raw"}
            reading = {
                **common,
                "text": segment.get("text", ""),
                "raw_text": segment.get("raw_text"),
                "layer": "reading",
                "transform": segment.get("transform"),
                "punctuation_inferred": bool(segment.get("punctuation_inferred", False)),
            }
            raw_lines.append(json.dumps(raw, ensure_ascii=False))
            reading_lines.append(json.dumps(reading, ensure_ascii=False))
            start = float(segment.get("start", 0))
            end = float(segment.get("end", start))
            label = stamp(start) if abs(end - start) < 0.01 else f"{stamp(start)} → {stamp(end)}"
            markdown.extend([f"**{label}**", "", segment.get("text", ""), ""])
    raw_path.write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
    reading_path.write_text("\n".join(reading_lines) + "\n", encoding="utf-8")
    markdown_path.write_text("\n".join(markdown).rstrip() + "\n", encoding="utf-8")
    print(json.dumps({"source": str(source), "raw_blocks": len(raw_lines), "reading_blocks": len(reading_lines), "destination": str(DEST)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
