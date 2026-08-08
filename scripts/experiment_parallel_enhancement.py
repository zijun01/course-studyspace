#!/usr/bin/env python3
"""Create a non-destructive, parallel Codex transcript-enhancement experiment."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from course_pipeline import PROMPT, audio_groups, build_reading, markdown, write_jsonl


COURSE_ID = 815
COURSE_TITLE = "2026.08.06.自然语言自动化——斜杠命令"
COURSE_DIR = next(ROOT.glob(f"library/*/courses/{COURSE_ID}-*"))
RAW_PATH = COURSE_DIR / "transcripts" / "raw.jsonl"
OUTPUT_JSONL = COURSE_DIR / "transcripts" / "reading.parallel-experiment.jsonl"
OUTPUT_MD = COURSE_DIR / "transcripts" / "reading.parallel-experiment.md"
REPORT_PATH = COURSE_DIR / "transcripts" / "parallel-experiment.report.json"


def run_codex(task: str, timeout: int = 900) -> str:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as result:
        result_path = Path(result.name)
    process = subprocess.Popen(
        ["codex", "exec", "--ephemeral", "--ignore-rules", "--skip-git-repo-check", "-c", "mcp_servers.chrome-devtools.enabled=false", "-s", "read-only", "-C", str(ROOT), "-o", str(result_path), "-"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=os.environ.copy(), start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(task, timeout=timeout)
        if process.returncode:
            raise RuntimeError((stderr or stdout or "Codex failed")[-1600:])
        return result_path.read_text(encoding="utf-8").strip()
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        raise RuntimeError(f"Codex experiment exceeded {timeout} seconds")
    finally:
        result_path.unlink(missing_ok=True)


def json_value(answer: str, opening: str, closing: str):
    start, end = answer.find(opening), answer.rfind(closing)
    if start < 0 or end < start:
        raise RuntimeError("Codex did not return valid JSON")
    return json.loads(answer[start:end + 1])


def balanced_chunks(groups: list[dict], count: int = 3) -> list[list[dict]]:
    target = sum(len(group["raw_text"]) for group in groups) / count
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


def main() -> None:
    started = time.monotonic()
    raw_rows = [json.loads(line) for line in RAW_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    groups = audio_groups(raw_rows)
    compact = [{"group_id": group["group_id"], "text": group["raw_text"]} for group in groups]
    print(f"[1/4] 全课理解：{len(groups)} 个媒体语组，{sum(len(x['text']) for x in compact)} 字", flush=True)
    brief_task = f"""阅读以下整节课程转写，只提取供后续润色使用的全局约束。不得润色正文。
只输出 JSON 对象：
{{"logic":["课程论证节点"],"terms":["必须保持一致的术语或命令"],"style":["老师口吻特点"],"risks":["容易误改之处"]}}
课程：{COURSE_TITLE}
全文：{json.dumps(compact, ensure_ascii=False)}
"""
    brief = json_value(run_codex(brief_task, timeout=600), "{", "}")
    chunks = balanced_chunks(groups, 3)
    rules = PROMPT.read_text(encoding="utf-8")
    print(f"[2/4] 并行润色：{len(chunks)} 块，字数 {[sum(len(g['raw_text']) for g in chunk) for chunk in chunks]}", flush=True)

    def polish(index: int, chunk: list[dict]) -> dict[str, str]:
        first = groups.index(chunk[0])
        last = groups.index(chunk[-1])
        before = groups[first - 1]["raw_text"] if first > 0 else ""
        after = groups[last + 1]["raw_text"] if last + 1 < len(groups) else ""
        targets = [{"group_id": group["group_id"], "text": group["raw_text"]} for group in chunk]
        task = f"""{rules}

课程：{COURSE_TITLE}
全课逻辑与术语约束：{json.dumps(brief, ensure_ascii=False)}
前一语组上下文（仅理解，不输出）：{before}
后一语组上下文（仅理解，不输出）：{after}

润色下面目标语组。每个 group_id 恰好返回一次，不得合并、遗漏、新增。只输出 JSON 数组：
[{{"group_id":"0","text":"润色后的完整文字"}}]
目标：{json.dumps(targets, ensure_ascii=False)}
"""
        rows = json_value(run_codex(task), "[", "]")
        mapping = {str(row["group_id"]): str(row["text"]).strip() for row in rows}
        expected = {group["group_id"] for group in chunk}
        if set(mapping) != expected or any(not mapping[key] for key in expected):
            raise RuntimeError(f"chunk {index} returned incomplete groups")
        print(f"  块 {index + 1}/{len(chunks)} 完成", flush=True)
        return mapping

    polished: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(polish, index, chunk): index for index, chunk in enumerate(chunks)}
        for future in as_completed(futures):
            polished.update(future.result())

    print("[3/4] 本机校验与时间戳回贴", flush=True)
    expected = {group["group_id"] for group in groups}
    if set(polished) != expected:
        raise RuntimeError(f"missing groups: {sorted(expected - set(polished))}")
    reading, _ = build_reading(raw_rows, polished)
    write_jsonl(OUTPUT_JSONL, reading)
    OUTPUT_MD.write_text(markdown(reading, COURSE_TITLE + "（并行实验稿）"), encoding="utf-8")
    long_unpunctuated = [
        row for row in reading
        if row.get("source_type") == "audio_transcript"
        and len(row.get("text", "")) > 55
        and not any(mark in row["text"] for mark in "，。！？；：")
    ]
    report = {
        "course_id": COURSE_ID, "groups": len(groups), "chunks": len(chunks),
        "raw_characters": sum(len(group["raw_text"]) for group in groups),
        "reading_rows": len(reading), "missing_groups": len(expected - set(polished)),
        "long_unpunctuated_rows": len(long_unpunctuated),
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "output_jsonl": str(OUTPUT_JSONL), "output_markdown": str(OUTPUT_MD),
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[4/4] 完成：{json.dumps(report, ensure_ascii=False)}", flush=True)


if __name__ == "__main__":
    main()
