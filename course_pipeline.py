#!/usr/bin/env python3
"""Generic archive and semantic-reading pipeline for every course."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LIBRARY = ROOT / "library"
PROMPT = ROOT / "prompts" / "course-transcript-enhancement-v1.md"
CATEGORIES = ("AI课", "写作课", "自学课", "专注课", "思考课", "财富课", "家庭教育课", "教练课", "英语课")


def safe_name(value: str, limit: int = 72) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value, flags=re.UNICODE).strip("-")
    return (cleaned or "course")[:limit]


def numeric_course_id(url: str, fallback: str = "course") -> str:
    match = re.search(r"[?&]course_id=(\d+)", url)
    return match.group(1) if match else safe_name(fallback, 24)


def course_directory(category: str, url: str, title: str) -> Path:
    if category not in CATEGORIES:
        raise ValueError(f"未知课程类别：{category}")
    return LIBRARY / category / "courses" / f"{numeric_course_id(url)}-{safe_name(title)}"


def find_archived_course(url: str) -> tuple[Path | None, dict]:
    prefix = f"{numeric_course_id(url)}-"
    for category in CATEGORIES:
        for directory in (LIBRARY / category / "courses").glob(f"{prefix}*"):
            metadata_path = directory / "course.json"
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                metadata = {}
            if metadata.get("source_url") in {None, url}:
                return directory, metadata
    return None, {}


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp:
        temp.write(text)
        temporary = Path(temp.name)
    temporary.replace(path)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    atomic_text(path, "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n")


def join_text(parts: list[str]) -> str:
    result = ""
    for value in parts:
        value = str(value).strip()
        if not value:
            continue
        spacer = " " if result and result[-1:].isascii() and value[:1].isascii() else ""
        result += spacer + value
    return result


def audio_character_count(rows: list[dict]) -> int:
    """Count spoken letters and numbers; exclude punctuation and page text."""
    return sum(
        sum(1 for character in str(row.get("text", "")) if character.isalnum())
        for row in rows
        if row.get("source_type") == "audio_transcript"
    )


def clean_fallback(text: str) -> str:
    text = re.sub(r"(^|[\s，。！？；])(?:嗯+|呃+|额+|唔+)(?=[\s，。！？；]|$)", r"\1", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])(?:啊+|哈+|呢)(?=[\u4e00-\u9fff，。！？、\s]|$)", "", text)
    text = re.sub(r"(这个|你就会)(?:[，、\s]*\1)+", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ，")
    return text if re.search(r"[。！？；]$", text) else text + "。"


def split_long_audio_rows(rows: list[dict], maximum_characters: int = 4000) -> list[list[dict]]:
    """Split one long media item on ASR-row boundaries without changing timestamps."""
    total = audio_character_count(rows)
    if total <= maximum_characters:
        return [rows]
    chunk_count = max(2, (total + maximum_characters - 1) // maximum_characters)
    target = (total + chunk_count - 1) // chunk_count
    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_characters = 0
    for row in rows:
        current.append(row)
        current_characters += audio_character_count([row])
        remaining_rows = len(rows) - sum(len(chunk) for chunk in chunks) - len(current)
        if current_characters >= target and len(chunks) + 1 < chunk_count and remaining_rows > 0:
            chunks.append(current)
            current = []
            current_characters = 0
    if current:
        chunks.append(current)
    return chunks


def audio_groups(raw_rows: list[dict]) -> list[dict]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in raw_rows:
        if row.get("source_type") == "audio_transcript":
            grouped[(row.get("content_id"), row.get("order"))].append(row)
    output = []
    for content_id, order in grouped:
        rows = grouped[(content_id, order)]
        rows.sort(key=lambda row: (float(row["start"]), float(row["end"])))
        for chunk in split_long_audio_rows(rows):
            output.append({
                "group_id": str(len(output)),
                "content_id": content_id,
                "order": order,
                "start": min(float(row["start"]) for row in chunk),
                "end": max(float(row["end"]) for row in chunk),
                "raw_text": join_text([row["text"] for row in chunk]),
                "source_url": chunk[0].get("source_url"),
                "course_id": chunk[0].get("course_id"),
                "rows": chunk,
            })
    return output


def enhance_with_codex(groups: list[dict], course_title: str, progress=None) -> dict[str, str]:
    rules = PROMPT.read_text(encoding="utf-8")
    source = [{"group_id": group["group_id"], "text": group["raw_text"]} for group in groups]
    task = f"""{rules}

当前课程：{course_title}

请结合所有输入的完整上下文，逐组润色。每个 group_id 必须恰好返回一次；不得合并、遗漏或新增组。只输出 JSON 数组，不要 Markdown：
[{{"group_id":"0","text":"润色后的完整文字"}}]

输入：
{json.dumps(source, ensure_ascii=False)}
"""
    # Short lessons retain a five-minute safety window. Longer transcripts get
    # proportionally more time, capped at twenty minutes so one bad invocation
    # can never block the durable queue forever.
    timeout_seconds = min(1200, max(300, 180 + len(task) / 50))
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as result_file:
        result_path = Path(result_file.name)
    try:
        process = subprocess.Popen(
            ["codex", "exec", "--ephemeral", "--ignore-rules", "--skip-git-repo-check", "-c", "mcp_servers.chrome-devtools.enabled=false", "-s", "read-only", "-C", str(ROOT), "-o", str(result_path), "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=os.environ.copy(),
            start_new_session=True,
        )
        started = time.monotonic()
        first_communicate = True
        while True:
            elapsed = time.monotonic() - started
            remaining = timeout_seconds - elapsed
            if remaining <= 0:
                break
            try:
                stdout, stderr = process.communicate(
                    task if first_communicate else None,
                    timeout=min(1, remaining),
                )
                break
            except subprocess.TimeoutExpired:
                first_communicate = False
                elapsed = time.monotonic() - started
                if progress:
                    progress(min(0.99, elapsed / timeout_seconds), elapsed, timeout_seconds)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            limit_minutes = max(5, round(timeout_seconds / 60))
            raise RuntimeError(f"Codex 整课润色超过自适应上限 {limit_minutes} 分钟，已保留本机阅读稿并继续队列")
        if process.returncode:
            raise RuntimeError((stderr or stdout or "Codex 润色失败")[-1200:])
        answer = result_path.read_text(encoding="utf-8").strip()
        start, end = answer.find("["), answer.rfind("]")
        if start < 0 or end < start:
            raise RuntimeError("Codex 没有返回 JSON 数组")
        rows = json.loads(answer[start:end + 1])
        mapping = {str(row["group_id"]): str(row["text"]).strip() for row in rows}
        expected = {group["group_id"] for group in groups}
        if set(mapping) != expected or any(not mapping[key] for key in expected):
            raise RuntimeError("Codex 返回的课程语块不完整")
        return mapping
    finally:
        result_path.unlink(missing_ok=True)


def codex_output(task: str, timeout: float, tick=None) -> str:
    """Run one isolated Codex task while exposing honest elapsed-time updates."""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as result_file:
        result_path = Path(result_file.name)
    process = subprocess.Popen(
        ["codex", "exec", "--ephemeral", "--ignore-rules", "--skip-git-repo-check", "-c", "mcp_servers.chrome-devtools.enabled=false", "-s", "read-only", "-C", str(ROOT), "-o", str(result_path), "-"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=os.environ.copy(), start_new_session=True,
    )
    started = time.monotonic()
    first = True
    try:
        while True:
            elapsed = time.monotonic() - started
            remaining = timeout - elapsed
            if remaining <= 0:
                break
            try:
                stdout, stderr = process.communicate(task if first else None, timeout=min(1, remaining))
                break
            except subprocess.TimeoutExpired:
                first = False
                if tick:
                    tick(time.monotonic() - started, timeout)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise RuntimeError(f"Codex 超过 {round(timeout / 60)} 分钟安全上限")
        if process.returncode:
            raise RuntimeError((stderr or stdout or "Codex 润色失败")[-1600:])
        return result_path.read_text(encoding="utf-8").strip()
    finally:
        result_path.unlink(missing_ok=True)


def parsed_json(answer: str, opening: str, closing: str):
    start, end = answer.find(opening), answer.rfind(closing)
    if start < 0 or end < start:
        raise RuntimeError("Codex 没有返回有效 JSON")
    return json.loads(answer[start:end + 1])


def balanced_semantic_chunks(groups: list[dict], count: int = 3) -> list[list[dict]]:
    target = sum(len(group["raw_text"]) for group in groups) / max(1, count)
    chunks, current, size = [], [], 0
    for group in groups:
        remaining_slots = count - len(chunks)
        if current and size >= target and remaining_slots > 1:
            chunks.append(current)
            current, size = [], 0
        current.append(group)
        size += len(group["raw_text"])
    if current:
        chunks.append(current)
    return chunks


def enhance_parallel_with_codex(groups: list[dict], course_title: str, progress=None) -> dict[str, str]:
    """Understand the whole course once, then polish three contiguous chunks in parallel."""
    if not groups:
        return {}
    compact = [{"group_id": group["group_id"], "text": group["raw_text"]} for group in groups]
    total_characters = sum(len(row["text"]) for row in compact)
    brief_timeout = min(600, max(300, 180 + total_characters / 40))
    if progress:
        progress(0.01, "阶段 1/3 · Codex 正在理解全课逻辑与术语", 0, brief_timeout)
    brief_task = f"""阅读以下整节课程转写，只提取供后续润色使用的全局约束。不得润色正文。
只输出 JSON 对象：
{{"logic":["课程论证节点"],"terms":["必须保持一致的术语或命令"],"style":["老师口吻特点"],"risks":["容易误改之处"]}}
课程：{course_title}
全文：{json.dumps(compact, ensure_ascii=False)}
"""
    def brief_tick(elapsed, limit):
        if progress:
            progress(min(0.18, 0.18 * elapsed / limit), f"阶段 1/3 · 全课理解已等待 {int(elapsed)//60}:{int(elapsed)%60:02d}", elapsed, limit)
    brief = parsed_json(codex_output(brief_task, brief_timeout, brief_tick), "{", "}")
    chunks = balanced_semantic_chunks(groups, 3)
    rules = PROMPT.read_text(encoding="utf-8")
    if progress:
        progress(0.2, f"阶段 2/3 · {len(chunks)} 个语义块并行润色 · 已完成 0/{len(chunks)}", 0, 0)

    completed = 0
    progress_lock = threading.Lock()

    def polish(index: int, chunk: list[dict]) -> dict[str, str]:
        first = groups.index(chunk[0])
        last = groups.index(chunk[-1])
        before = groups[first - 1]["raw_text"] if first > 0 else ""
        after = groups[last + 1]["raw_text"] if last + 1 < len(groups) else ""
        targets = [{"group_id": group["group_id"], "text": group["raw_text"]} for group in chunk]
        task = f"""{rules}

课程：{course_title}
全课逻辑与术语约束：{json.dumps(brief, ensure_ascii=False)}
前一语组上下文（仅理解，不输出）：{before}
后一语组上下文（仅理解，不输出）：{after}
润色下面目标语组。每个 group_id 恰好返回一次，不得合并、遗漏、新增。只输出 JSON 数组：
[{{"group_id":"0","text":"润色后的完整文字"}}]
目标：{json.dumps(targets, ensure_ascii=False)}
"""
        timeout = min(900, max(300, 180 + len(task) / 35))
        def chunk_tick(elapsed, limit):
            if progress:
                with progress_lock:
                    progress(0.2 + 0.7 * completed / len(chunks), f"阶段 2/3 · 已完成 {completed}/{len(chunks)} · 第 {index + 1} 块已等待 {int(elapsed)//60}:{int(elapsed)%60:02d}", elapsed, limit)
        rows = parsed_json(codex_output(task, timeout, chunk_tick), "[", "]")
        mapping = {str(row["group_id"]): str(row["text"]).strip() for row in rows}
        expected = {group["group_id"] for group in chunk}
        if set(mapping) != expected or any(not mapping[key] for key in expected):
            raise RuntimeError(f"并行润色第 {index + 1} 块返回不完整")
        return mapping

    polished: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(polish, index, chunk) for index, chunk in enumerate(chunks)]
        for future in as_completed(futures):
            polished.update(future.result())
            with progress_lock:
                completed += 1
                if progress:
                    progress(0.2 + 0.7 * completed / len(chunks), f"阶段 2/3 · 并行润色已完成 {completed}/{len(chunks)}", 0, 0)
    expected = {group["group_id"] for group in groups}
    if set(polished) != expected:
        raise RuntimeError(f"并行润色缺少 {len(expected - set(polished))} 个语组")
    if progress:
        progress(0.95, "阶段 3/3 · 本机检查遗漏、时间戳与原文对齐", 0, 0)
    return polished


def semantic_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in re.findall(r".+?[。！？；](?:[”’\"])?|.+$", text, flags=re.S) if part.strip()]
    return parts or [text.strip()]


def weight(text: str) -> int:
    return max(1, len(re.sub(r"\s+", "", text)))


def normalized_characters(text: str) -> str:
    return "".join(character.lower() for character in str(text) if character.isalnum())


def aligned_sentence_times(group: dict, parts: list[str]) -> list[tuple[float, float, float]]:
    """Align polished sentences back to source ASR characters and their real timestamps."""
    raw_characters = ""
    raw_times: list[tuple[float, float]] = []
    for row in group["rows"]:
        characters = normalized_characters(row["text"])
        if not characters:
            continue
        start, end = float(row["start"]), float(row["end"])
        duration = max(0.01, end - start)
        raw_characters += characters
        for index in range(len(characters)):
            raw_times.append((
                start + duration * index / len(characters),
                start + duration * (index + 1) / len(characters),
            ))

    polished = "".join(normalized_characters(part) for part in parts)
    matcher = SequenceMatcher(None, polished, raw_characters, autojunk=False)
    polished_to_raw = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            polished_to_raw[block.a + offset] = block.b + offset

    output = []
    polished_cursor = 0
    previous_end = float(group["start"])
    for part in parts:
        length = len(normalized_characters(part))
        matched = [
            polished_to_raw[index]
            for index in range(polished_cursor, polished_cursor + length)
            if index in polished_to_raw
        ]
        coverage = len(matched) / max(1, length)
        if matched:
            start = raw_times[min(matched)][0]
            end = raw_times[max(matched)][1]
        else:
            ratio_start = polished_cursor / max(1, len(polished))
            ratio_end = (polished_cursor + length) / max(1, len(polished))
            start = float(group["start"]) + (float(group["end"]) - float(group["start"])) * ratio_start
            end = float(group["start"]) + (float(group["end"]) - float(group["start"])) * ratio_end
        start = max(float(group["start"]), previous_end, start)
        end = min(float(group["end"]), max(start + 0.05, end))
        output.append((start, end, coverage))
        previous_end = end
        polished_cursor += length
    return output


def build_reading(raw_rows: list[dict], polished: dict[str, str] | None) -> tuple[list[dict], str]:
    groups = audio_groups(raw_rows)
    reading = [
        {**row, "layer": "reading", "raw_text": row["text"], "transform": "source_page_exact", "time_inferred": False}
        for row in raw_rows
        if row.get("source_type") == "page_text"
    ]
    enhancement = "codex" if polished is not None else "fallback"
    for group in groups:
        text = polished[group["group_id"]] if polished is not None else clean_fallback(group["raw_text"])
        parts = semantic_sentences(text)
        timings = aligned_sentence_times(group, parts)
        emitted_parts = 0
        for part, (start, end, coverage) in zip(parts, timings):
            # A sentence with almost no source-character support is likely model-added text.
            if polished is not None and coverage < 0.35:
                continue
            emitted_parts += 1
            reading.append({
                "schema_version": "1.0", "course_id": group["course_id"], "content_id": group["content_id"],
                "order": group["order"], "source_type": "audio_transcript", "start": round(start, 2), "end": round(end, 2),
                "source_url": group["source_url"], "text": part, "raw_text": group["raw_text"], "layer": "reading",
                "transform": f"reading_{enhancement}_full_context_semantic_split", "punctuation_inferred": True,
                "time_inferred": False, "source_alignment": round(coverage, 3),
            })
        if emitted_parts == 0:
            reading.append({
                "schema_version": "1.0", "course_id": group["course_id"], "content_id": group["content_id"],
                "order": group["order"], "source_type": "audio_transcript", "start": round(group["start"], 2),
                "end": round(group["end"], 2), "source_url": group["source_url"],
                "text": clean_fallback(group["raw_text"]), "raw_text": group["raw_text"], "layer": "reading",
                "transform": "reading_fallback_source_aligned", "punctuation_inferred": True,
                "time_inferred": False, "source_alignment": 1.0,
            })
    reading = [row for _, row in sorted(enumerate(reading), key=lambda pair: (float(pair[1]["start"]), pair[0]))]
    return reading, enhancement


def cache_records(reading: list[dict], title: str, audio_urls: dict[int, str]) -> list[dict]:
    records: dict[tuple, dict] = {}
    for row in reading:
        key = (row.get("content_id"), row.get("order"), row.get("source_type"))
        record = records.setdefault(key, {
            "schema_version": "1.0", "course_id": row.get("course_id"), "source_url": row.get("source_url"),
            "course_title": title, "content_id": row.get("content_id"), "order": row.get("order"),
            "category": "text" if row.get("source_type") == "page_text" else "audio", "engine": "course-pipeline", "segments": [],
        })
        if record["category"] == "audio" and int(row.get("content_id") or 0) in audio_urls:
            record["audio_url"] = audio_urls[int(row["content_id"])]
        record["segments"].append({key: row.get(key) for key in ("start", "end", "text", "raw_text", "source_type", "transform", "punctuation_inferred", "time_inferred")})
    return list(records.values())


def markdown(reading: list[dict], title: str) -> str:
    def stamp(value: float) -> str:
        total = max(0, int(value)); return f"{total // 60:02d}:{total % 60:02d}"
    lines = [f"# {title}｜阅读稿", "", "> 音频文字经整课语义润色；句内时间按原始范围推算。页面原文逐字保留。", ""]
    for row in reading:
        start, end = float(row["start"]), float(row["end"])
        label = stamp(start) if abs(end - start) < .01 else f"{stamp(start)} → {stamp(end)}"
        lines.extend([f"**{label}**", "", row["text"], ""])
    return "\n".join(lines).rstrip() + "\n"


def update_catalog(metadata: dict) -> None:
    path = LIBRARY / "catalog.json"
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        catalog = {"schema_version": "1.0", "categories": [{"id": name, "name": name, "path": name} for name in CATEGORIES], "course_mappings": {}}
    catalog.setdefault("course_mappings", {})[str(metadata["course_id"])] = {
        "category": metadata["category"], "title": metadata["title"], "source_url": metadata["source_url"],
    }
    atomic_text(path, json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")


def archive_raw(payload: dict, raw_rows: list[dict]) -> dict:
    """Persist the immutable transcript before the slower Codex enhancement."""
    title = payload.get("course_title") or "course"
    category = payload.get("course_category") or "AI课"
    directory = course_directory(category, payload["course_url"], title)
    transcripts = directory / "transcripts"
    transcripts.mkdir(parents=True, exist_ok=True)
    (directory / "notes").mkdir(exist_ok=True)
    write_jsonl(transcripts / "raw.jsonl", raw_rows)
    raw_audio_characters = audio_character_count(raw_rows)
    metadata = {
        "schema_version": "1.0", "course_id": numeric_course_id(payload["course_url"]), "title": title,
        "category": category, "source_url": payload["course_url"],
        "updated_at": datetime.now(timezone.utc).isoformat(), "transcription": "complete",
        "enhancement": "pending", "enhancement_error": None,
        "raw_audio_characters": raw_audio_characters,
    }
    atomic_text(directory / "course.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    update_catalog(metadata)
    return {
        "directory": str(directory), "raw_segments": len(raw_rows), "enhancement": "pending",
        "raw_audio_characters": raw_audio_characters,
    }


def archive_and_enhance(payload: dict, raw_rows: list[dict], cache_path: Path, status=None) -> dict:
    title = payload.get("course_title") or "course"
    category = payload.get("course_category") or "AI课"
    directory = course_directory(category, payload["course_url"], title)
    transcripts = directory / "transcripts"
    transcripts.mkdir(parents=True, exist_ok=True)
    (directory / "notes").mkdir(exist_ok=True)
    write_jsonl(transcripts / "raw.jsonl", raw_rows)
    if status:
        status("enhancing", "正在按课程长度选择润色通道…", 0.0, 0.0)
    error = None
    enhancement_started = time.monotonic()
    groups = audio_groups(raw_rows)
    audio_characters = audio_character_count(raw_rows)
    use_parallel = audio_characters >= 4000 and len(groups) >= 2
    pipeline_name = "whole-course-brief-plus-3-parallel-chunks-v1" if use_parallel else "short-course-single-pass-v1"
    try:
        if use_parallel:
            def report(fraction, message, elapsed=0, limit=0):
                if status:
                    status("enhancing", message, fraction, elapsed, limit)
            polished = enhance_parallel_with_codex(groups, title, progress=report)
        else:
            if status:
                status("enhancing", f"短课快速通道 · 单次整课润色 · {audio_characters} 字", 0.01, 0, 0)
            def report_single(fraction, elapsed, limit):
                if status:
                    status(
                        "enhancing",
                        f"短课快速通道 · 已等待 {int(elapsed)//60}:{int(elapsed)%60:02d}",
                        fraction, elapsed, limit,
                    )
            polished = enhance_with_codex(groups, title, progress=report_single)
    except Exception as exc:
        polished = None
        error = str(exc)
    reading, enhancement = build_reading(raw_rows, polished)
    reading_audio_characters = audio_character_count(reading)
    write_jsonl(transcripts / "reading.jsonl", reading)
    atomic_text(transcripts / "reading.md", markdown(reading, title))
    audio_urls = {int(item["id"]): item.get("url", "") for item in payload.get("items", []) if item.get("category") in {"audio", "video"} and item.get("id") is not None}
    write_jsonl(cache_path, cache_records(reading, title, audio_urls))
    metadata = {
        "schema_version": "1.0", "course_id": numeric_course_id(payload["course_url"]), "title": title,
        "category": category, "source_url": payload["course_url"], "updated_at": datetime.now(timezone.utc).isoformat(),
        "transcription": "complete", "enhancement": enhancement,
        "enhancement_pipeline": pipeline_name if polished is not None else "fallback",
        "enhancement_elapsed_seconds": round(time.monotonic() - enhancement_started, 1),
        "enhancement_error": error,
        "raw_audio_characters": audio_characters,
        "reading_audio_characters": reading_audio_characters,
    }
    atomic_text(directory / "course.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    update_catalog(metadata)
    return {
        "directory": str(directory), "segments": len(reading), "enhancement": enhancement,
        "enhancement_pipeline": metadata["enhancement_pipeline"],
        "enhancement_elapsed_seconds": metadata["enhancement_elapsed_seconds"],
        "enhancement_error": error,
        "raw_audio_characters": audio_characters,
        "reading_audio_characters": reading_audio_characters,
    }
