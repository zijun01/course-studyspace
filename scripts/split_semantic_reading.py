#!/usr/bin/env python3
"""Split an LLM-polished reading layer at its semantic punctuation."""
from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COURSE = ROOT / "library" / "AI课" / "courses" / "802-Claude-Code是个大模型调度器"
READING = COURSE / "transcripts" / "reading.jsonl"
MARKDOWN = COURSE / "transcripts" / "reading.md"


def sentences(text: str) -> list[str]:
    return [part.strip() for part in re.findall(r".+?[。！？；](?:[”’\"])?|.+$", text, flags=re.S) if part.strip()]


def weight(text: str) -> int:
    return max(1, len(re.sub(r"\s+", "", text)))


def stamp(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def main() -> None:
    source = [json.loads(line) for line in READING.read_text(encoding="utf-8").splitlines() if line.strip()]
    output = []
    for row in source:
        if row.get("source_type") == "page_text":
            output.append(row)
            continue
        parts = sentences(str(row.get("text", "")))
        if len(parts) <= 1:
            output.append(row)
            continue
        start = float(row["start"])
        end = float(row["end"])
        total = sum(weight(part) for part in parts)
        consumed = 0
        for index, part in enumerate(parts):
            part_start = start + (end - start) * consumed / total
            consumed += weight(part)
            part_end = end if index == len(parts) - 1 else start + (end - start) * consumed / total
            output.append({
                **row,
                "start": round(part_start, 2),
                "end": round(part_end, 2),
                "text": part,
                "transform": "reading_cleanup_v1_full_context_semantic_split",
                "time_inferred": True,
            })

    output = [row for _, row in sorted(enumerate(output), key=lambda pair: (float(pair[1]["start"]), pair[0]))]
    READING.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in output) + "\n", encoding="utf-8")
    md = [
        "# 2026.07.30 Claude Code 是个大模型调度器｜阅读稿",
        "",
        "> 音频文字经整课语义润色；句内时间按原始音频范围推算。页面原文逐字保留。原始稿见 `raw.jsonl`。",
        "",
    ]
    for row in output:
        start, end = float(row["start"]), float(row["end"])
        label = stamp(start) if abs(end - start) < 0.01 else f"{stamp(start)} → {stamp(end)}"
        md.extend([f"**{label}**", "", row["text"], ""])
    MARKDOWN.write_text("\n".join(md).rstrip() + "\n", encoding="utf-8")
    print(json.dumps({"before": len(source), "after": len(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
