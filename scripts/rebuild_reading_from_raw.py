#!/usr/bin/env python3
"""Rebuild readable sentence blocks from archived raw text without rerunning Whisper."""
from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COURSE = ROOT / "library" / "AI课" / "courses" / "802-Claude-Code是个大模型调度器"
RAW = COURSE / "transcripts" / "raw.jsonl"
READING = COURSE / "transcripts" / "reading.jsonl"
MARKDOWN = COURSE / "transcripts" / "reading.md"

FILLER = re.compile(r"(^|[\s，,。！？!?；;])(?:嗯+|呃+|额+|唔+)(?=[\s，,。！？!?；;]|$)")
BOUNDARIES = (
    "但是", "所以", "然后", "因为", "如果", "其实", "那么", "另外", "而且", "不过", "当然",
    "比如", "首先", "其次", "最后", "也就是说", "换句话说", "这个时候", "这时候", "一旦",
    "至于", "现在", "今天", "后来", "这就是", "同时",
)
ENDING_BOUNDARIES = ("对吧", "对不对", "是不是", "知道吗", "明白吗", "为什么", "干什么", "怎么回事", "没错")
WEAK_PAUSES = ("你看", "还有", "它其实", "他其实", "安装卸载", "在Mac上")
AFTER_PAUSES = ("的时候", "的情况下", "的话", "以后", "之后", "之前", "对你来说", "换句话说")
BAD_SENTENCE_ENDS = ("我们", "你", "我", "所以", "然后", "因为", "如果", "这个", "那个", "的", "地", "得", "去", "在", "把", "让", "跟", "是", "有", "会", "能", "要")
ASCII_WORD = re.compile(r"[A-Za-z0-9_./+@#-]")
INCOMPLETE_ENDINGS = ("干什", "页", "正在", "去研究")


def clean(text: str) -> str:
    text = FILLER.sub(r"\1", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])(?:啊+|哈+|呢)(?=[\u4e00-\u9fff，。！？、\s]|$)", "", text)
    text = re.sub(r"(这个|你就会)(?:[，、\s]*\1)+", r"\1", text)
    text = re.sub(r"([\u4e00-\u9fff])(?:[，,、\s]*\1){2,}", r"\1", text)
    return re.sub(r"\s{2,}", " ", text).strip(" ，,")


def safe_cut(text: str, proposed: int, minimum: int = 18) -> int:
    """Move a cut away from the middle of an English word, command, or path."""
    if proposed <= 0 or proposed >= len(text):
        return proposed
    if not (ASCII_WORD.fullmatch(text[proposed - 1]) and ASCII_WORD.fullmatch(text[proposed])):
        return proposed

    left = proposed
    while left > 0 and ASCII_WORD.fullmatch(text[left - 1]):
        left -= 1
    right = proposed
    while right < len(text) and ASCII_WORD.fullmatch(text[right]):
        right += 1

    if left >= minimum:
        return left
    return right


def insert_pause_before(text: str, token: str) -> str:
    cursor = len(token)
    while True:
        index = text.find(token, cursor)
        if index < 0:
            return text
        previous_stop = max(text.rfind(mark, 0, index) for mark in "，。！？；")
        clause = text[previous_stop + 1:index]
        if len(clause) >= 8 and not clause.endswith(BAD_SENTENCE_ENDS):
            text = text[:index] + "，" + text[index:]
            cursor = index + len(token) + 1
        else:
            cursor = index + len(token)


def insert_pause_after(text: str, token: str) -> str:
    cursor = 0
    while True:
        index = text.find(token, cursor)
        if index < 0:
            return text
        cut = index + len(token)
        remaining = text[cut:]
        if len(remaining) >= 7 and remaining[0] not in "，。！？；":
            text = text[:cut] + "，" + remaining
            cursor = cut + 1
        else:
            cursor = cut


def finish_sentence(text: str) -> str:
    text = text.rstrip("，,：: ")
    for token in BOUNDARIES:
        text = insert_pause_before(text, token)
    for token in WEAK_PAUSES:
        text = insert_pause_before(text, token)
    for token in AFTER_PAUSES:
        text = insert_pause_after(text, token)
    for token in ("对吧", "对不对", "是不是", "知道吗", "明白吗"):
        text = re.sub(rf"{re.escape(token)}(?=[^，。！？；])", f"{token}？", text)
    if re.search(r"[。！？!?；;]$", text):
        return text
    if text.endswith(("对吧", "对不对", "是不是", "知道吗", "明白吗", "为什么", "干什么", "怎么回事")):
        return text + "？"
    return text + "。"


def split_readable(text: str, target: int = 34, maximum: int = 48) -> list[str]:
    text = clean(text)
    if not text:
        return []
    clauses = [part for part in re.findall(r"[^。！？!?；;]+[。！？!?；;]?", text) if part.strip()]
    result = []
    for clause in clauses:
        clause = clause.strip()
        while len(clause) > maximum:
            candidates = []
            for token in ("，", ",", "：", ":", *BOUNDARIES, *ENDING_BOUNDARIES):
                start = 12
                while True:
                    index = clause.find(token, start, maximum + 1)
                    if index < 0:
                        break
                    cut = index + (len(token) if token in ENDING_BOUNDARIES else (1 if token in "，,：:" else 0))
                    left = clause[:cut].rstrip("，,：: ")
                    if left and not left.endswith(BAD_SENTENCE_ENDS):
                        candidates.append(cut)
                    start = index + len(token)
            # Without a linguistic boundary, do not guess by character count;
            # doing so can tear a Chinese word such as “干什么” in half.
            if not candidates:
                break
            cut = min(candidates, key=lambda value: abs(value - target))
            cut = safe_cut(clause, cut)
            # A slightly long sentence is preferable to an orphaned character or
            # a fragment with no natural boundary.
            if len(clause) - cut < 12:
                break
            piece, clause = clause[:cut].rstrip("，,：: "), clause[cut:].lstrip("，,：: ")
            if piece:
                result.append(finish_sentence(piece))
        if clause:
            result.append(finish_sentence(clause))
    return result


def stamp(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def join_spoken(parts: list[str]) -> str:
    joined = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        separator = " " if joined and re.search(r"[A-Za-z0-9]$", joined) and re.match(r"[A-Za-z0-9]", part) else ""
        joined += separator + part
    return joined


def reading_from_audio(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    text = join_spoken([row.get("text", "") for row in rows])
    start = float(rows[0].get("start", 0))
    end = float(rows[-1].get("end", start))
    pieces = split_readable(text)
    total_chars = sum(len(piece) for piece in pieces) or 1
    consumed = 0
    output = []
    for index, piece in enumerate(pieces):
        piece_start = start + (end - start) * consumed / total_chars
        consumed += len(piece)
        piece_end = end if index == len(pieces) - 1 else start + (end - start) * consumed / total_chars
        output.append({
            **rows[0],
            "start": round(piece_start, 2),
            "end": round(piece_end, 2),
            "text": piece,
            "raw_text": text,
            "raw_block_count": len(rows),
            "layer": "reading",
            "transform": "reading_cleanup_v5_semantic_punctuation",
            "punctuation_inferred": True,
            "time_inferred": len(pieces) > 1 or len(rows) > 1,
        })
    return output


def main():
    raw_rows = [json.loads(line) for line in RAW.read_text(encoding="utf-8").splitlines() if line.strip()]
    reading = []
    audio_group = []
    for raw in raw_rows:
        text = raw.get("text", "")
        if raw.get("source_type") == "page_text":
            reading.extend(reading_from_audio(audio_group))
            audio_group = []
            reading.append({**raw, "layer": "reading", "raw_text": text, "transform": "source_page_exact", "time_inferred": False})
            continue
        if audio_group and (
            float(raw.get("start", 0)) - float(audio_group[-1].get("end", 0)) > 3
            or not clean(audio_group[-1].get("text", "")).endswith(INCOMPLETE_ENDINGS)
        ):
            reading.extend(reading_from_audio(audio_group))
            audio_group = []
        audio_group.append(raw)
    reading.extend(reading_from_audio(audio_group))
    READING.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in reading) + "\n", encoding="utf-8")
    md = ["# 2026.07.30 Claude Code 是个大模型调度器｜阅读稿", "", "> 音频文字的阅读断句与块内时间可能为推算；原始稿见 `raw.jsonl`。", ""]
    for row in reading:
        start, end = float(row["start"]), float(row["end"])
        label = stamp(start) if abs(end - start) < 0.01 else f"{stamp(start)} → {stamp(end)}"
        md.extend([f"**{label}**", "", row["text"], ""])
    MARKDOWN.write_text("\n".join(md).rstrip() + "\n", encoding="utf-8")
    print(json.dumps({"raw_blocks": len(raw_rows), "reading_blocks": len(reading)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
