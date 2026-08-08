#!/usr/bin/env python3
"""Local HTTP bridge from the Chrome extension to the existing Whisper install."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

try:
    import mlx_whisper
except (ImportError, RuntimeError):
    mlx_whisper = None

try:
    import whisper
except ImportError:
    whisper = None
from codex_bridge import bridge as codex_bridge
from course_pipeline import CATEGORIES, archive_and_enhance, archive_raw, audio_character_count, find_archived_course
from terminal_bridge import bridge as terminal_bridge


HOST = "127.0.0.1"
PORT = 4317
ROOT = Path(__file__).resolve().parent
TRANSCRIPT_DIR = ROOT / "data" / "transcripts"
STAGING_DIR = ROOT / "data" / "staging"
MEDIA_CACHE_DIR = ROOT / "data" / "media-cache"
CORPUS_DIR = ROOT / "research" / "corpus"
COURSE_QUEUE_DIR = CORPUS_DIR / "course-processing-queue"
COURSE_TARGETS_PATH = CORPUS_DIR / "course-processing-targets.json"
CLASSIFICATION_REVIEW_PATH = CORPUS_DIR / "course-classification-review.json"
_classification_review_lock = threading.Lock()
MODEL_NAME = "whisper-large-v3-turbo"
MLX_MODEL_PATH = ROOT / "models" / MODEL_NAME
OPENAI_WHISPER_PYTHON = Path(
    os.environ.get("OPENAI_WHISPER_PYTHON", "~/Projects/whisper-batch/.venv-uv/bin/python")
).expanduser()
MEDIA_COOLDOWN_SECONDS = max(0, int(os.environ.get("COURSE_MEDIA_COOLDOWN_SECONDS", "0")))
MEDIA_COOLDOWN_EVERY = max(1, int(os.environ.get("COURSE_MEDIA_COOLDOWN_EVERY", "1")))
COURSE_COOLDOWN_SECONDS = max(0, int(os.environ.get("COURSE_BETWEEN_COURSES_COOLDOWN_SECONDS", "0")))
_model = None
_model_lock = threading.RLock()
_jobs = {}
_jobs_lock = threading.Lock()


def model():
    global _model
    with _model_lock:
        if _model is None:
            if whisper is None:
                raise RuntimeError("当前环境没有 OpenAI Whisper")
            print("正在加载备用 OpenAI Whisper turbo……", flush=True)
            _model = whisper.load_model("turbo")
            print("Whisper 已就绪。", flush=True)
    return _model


def transcribe_audio(path: Path, progress=None) -> tuple[dict, str]:
    """Prefer Apple Metal via MLX; retain the former CPU Whisper as a fallback."""
    if mlx_whisper is not None and MLX_MODEL_PATH.exists():
        transcribe_module = None
        original_tqdm = None
        try:
            if progress:
                transcribe_module = importlib.import_module("mlx_whisper.transcribe")
                original_tqdm = transcribe_module.tqdm.tqdm

                class ProgressTqdm(original_tqdm):
                    def update(self, amount=1):
                        self._course_reported_n = getattr(self, "_course_reported_n", 0) + amount
                        result = super().update(amount)
                        if self.total:
                            progress(min(1.0, float(self._course_reported_n) / float(self.total)))
                        return result

                transcribe_module.tqdm.tqdm = ProgressTqdm
            result = mlx_whisper.transcribe(
                str(path), path_or_hf_repo=str(MLX_MODEL_PATH), language="zh", verbose=None
            )
            if progress:
                progress(1.0)
            return result, "mlx-whisper-local"
        except Exception as exc:
            print(f"MLX 转写失败，切换备用 Whisper：{exc}", flush=True)
        finally:
            if transcribe_module is not None and original_tqdm is not None:
                transcribe_module.tqdm.tqdm = original_tqdm
    if whisper is not None:
        return model().transcribe(str(path), language="zh", task="transcribe", verbose=False), "openai-whisper-local"
    if OPENAI_WHISPER_PYTHON.exists():
        script = (
            "import json,sys,whisper; m=whisper.load_model('turbo'); "
            "r=m.transcribe(sys.argv[1],language='zh',task='transcribe',verbose=False); "
            "print(json.dumps(r,ensure_ascii=False))"
        )
        completed = subprocess.run(
            [str(OPENAI_WHISPER_PYTHON), "-c", script, str(path)],
            check=True, capture_output=True, text=True,
        )
        return json.loads(completed.stdout), "openai-whisper-local-fallback"
    raise RuntimeError("MLX 与备用 Whisper 均不可用")


def course_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def load_classification_reviews() -> dict:
    try:
        payload = json.loads(CLASSIFICATION_REVIEW_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload.get("reviews"), dict) else {"schema_version": "1.0", "reviews": {}, "album_orders": {}}
    except (OSError, json.JSONDecodeError):
        return {"schema_version": "1.0", "reviews": {}, "album_orders": {}}


def album_order_key(target: dict) -> str:
    album_id = target.get("album_id")
    return f"id:{album_id}" if album_id is not None else f"title:{target.get('album_title') or '未分专辑'}"


def ordered_review_courses(targets: list[dict], saved_orders: dict) -> list[dict]:
    groups = {}
    album_keys = []
    for target in targets:
        key = album_order_key(target)
        if key not in groups:
            groups[key] = []
            album_keys.append(key)
        groups[key].append(target)
    courses = []
    global_index = 0
    for key in album_keys:
        base = groups[key]
        by_id = {str(item.get("course_id")): item for item in base}
        stored = [str(value) for value in saved_orders.get(key, []) if str(value) in by_id]
        effective_ids = stored + [value for value in by_id if value not in stored]
        original_positions = {str(item.get("course_id")): index for index, item in enumerate(base, 1)}
        for album_index, course_number in enumerate(effective_ids, 1):
            global_index += 1
            target = by_id[course_number]
            courses.append({
                **target,
                "current_global_order": global_index,
                "original_album_order": original_positions[course_number],
                "current_album_order": album_index,
            })
    return courses


def classification_review_payload() -> dict:
    targets_payload = json.loads(COURSE_TARGETS_PATH.read_text(encoding="utf-8"))
    targets = targets_payload.get("targets", [])
    review_payload = load_classification_reviews()
    reviews = review_payload.get("reviews", {})
    reviewed = sum(1 for target in targets if str(target.get("course_id")) in reviews)
    categories = list(CATEGORIES)
    for review in reviews.values():
        category = str(review.get("decided_category") or "").strip()
        if category and category not in categories:
            categories.append(category)
    courses = ordered_review_courses(targets, review_payload.get("album_orders", {}))
    return {
        "courses": courses,
        "reviews": reviews,
        "categories": categories,
        "total": len(targets),
        "reviewed": reviewed,
        "remaining": len(targets) - reviewed,
        "updated_at": review_payload.get("updated_at"),
    }


def save_classification_review(course_number: int, decided_category: str, note: str, decided_order: int | None = None, decided_title: str = "") -> dict:
    if not decided_category or len(decided_category) > 40:
        raise ValueError("课程类别不能为空，且不能超过 40 个字")
    if len(note) > 2000:
        raise ValueError("判断说明不能超过 2000 个字")
    if decided_order is not None and not 1 <= decided_order <= 9999:
        raise ValueError("课程顺序必须是 1 到 9999 之间的数字")
    if not decided_title or len(decided_title) > 200:
        raise ValueError("课程名称不能为空，且不能超过 200 个字")
    targets_payload = json.loads(COURSE_TARGETS_PATH.read_text(encoding="utf-8"))
    target = next((item for item in targets_payload.get("targets", []) if int(item.get("course_id")) == course_number), None)
    if not target:
        raise ValueError("课程不在当前分类总账中")
    with _classification_review_lock:
        payload = load_classification_reviews()
        now = datetime.now(timezone.utc).isoformat()
        key = album_order_key(target)
        same_album = [item for item in targets_payload.get("targets", []) if album_order_key(item) == key]
        base_ids = [str(item.get("course_id")) for item in same_album]
        existing_order = [str(value) for value in payload.get("album_orders", {}).get(key, []) if str(value) in base_ids]
        effective_order = existing_order + [value for value in base_ids if value not in existing_order]
        moving_id = str(course_number)
        effective_order.remove(moving_id)
        insert_at = min((decided_order or len(effective_order) + 1) - 1, len(effective_order))
        effective_order.insert(insert_at, moving_id)
        payload.setdefault("album_orders", {})[key] = effective_order
        review = {
            "course_id": course_number,
            "title": target.get("title", ""),
            "album_id": target.get("album_id"),
            "album_title": target.get("album_title", ""),
            "original_category": target.get("course_category", ""),
            "decided_category": decided_category,
            "decided_order": decided_order,
            "decided_title": decided_title,
            "note": note,
            "reviewed_at": now,
        }
        payload.setdefault("reviews", {})[str(course_number)] = review
        payload["schema_version"] = "1.0"
        payload["updated_at"] = now
        CLASSIFICATION_REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = CLASSIFICATION_REVIEW_PATH.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(CLASSIFICATION_REVIEW_PATH)
    return review


def classification_board_payload(targets_payload: dict | None = None, review_payload: dict | None = None) -> dict:
    targets_payload = targets_payload or json.loads(COURSE_TARGETS_PATH.read_text(encoding="utf-8"))
    targets = targets_payload.get("targets", [])
    review_payload = review_payload or load_classification_reviews()
    reviews = review_payload.get("reviews", {})
    renames = review_payload.get("category_renames", {})
    categories = [str(renames.get(category, category)) for category in CATEGORIES]
    for category in review_payload.get("custom_categories", []):
        if category and category not in categories:
            categories.append(category)
    saved_category_order = [str(value) for value in review_payload.get("category_order", []) if str(value) in categories]
    categories = saved_category_order + [category for category in categories if category not in saved_category_order]
    assignments = {}
    items_by_id = {}
    for target in targets:
        course_number = str(target.get("course_id"))
        review = reviews.get(course_number, {})
        category = str(review.get("decided_category") or target.get("course_category") or "未分类")
        category = str(renames.get(category, category))
        if category not in categories:
            categories.append(category)
        assignments[course_number] = category
        items_by_id[course_number] = {
            **target,
            "display_title": review.get("decided_title") or target.get("title") or f"课程 {course_number}",
            "note": review.get("note", ""),
            "reviewed": bool(review),
        }
    saved_orders = review_payload.get("category_orders", {})
    columns = []
    for category in categories:
        valid_ids = [course_number for course_number in items_by_id if assignments[course_number] == category]
        stored = [str(value) for value in saved_orders.get(category, []) if str(value) in valid_ids]
        effective_ids = stored + [value for value in valid_ids if value not in stored]
        columns.append({"category": category, "courses": [items_by_id[value] for value in effective_ids]})
    return {"columns": columns, "total": len(targets), "updated_at": review_payload.get("updated_at")}


def update_classification_board(payload: dict) -> dict:
    action = str(payload.get("action") or "move")
    with _classification_review_lock:
        targets_payload = json.loads(COURSE_TARGETS_PATH.read_text(encoding="utf-8"))
        review_payload = load_classification_reviews()
        now = datetime.now(timezone.utc).isoformat()
        if action == "create_category":
            name = str(payload.get("name") or "").strip()
            if not name or len(name) > 40:
                raise ValueError("新类别名称不能为空，且不能超过 40 个字")
            current_names = [column["category"] for column in classification_board_payload(targets_payload, review_payload)["columns"]]
            if name in current_names:
                raise ValueError("已经存在同名类别")
            custom = review_payload.setdefault("custom_categories", [])
            if name not in CATEGORIES and name not in custom:
                custom.append(name)
        elif action == "rename_category":
            old_name = str(payload.get("old_name") or "").strip()
            new_name = str(payload.get("new_name") or "").strip()
            if not old_name or not new_name or len(new_name) > 40:
                raise ValueError("类别名称不能为空，且不能超过 40 个字")
            current_board = classification_board_payload(targets_payload, review_payload)
            current_names = [column["category"] for column in current_board["columns"]]
            if old_name not in current_names:
                raise ValueError("找不到要改名的类别")
            if new_name != old_name and new_name in current_names:
                raise ValueError("已经存在同名类别")
            renames = review_payload.setdefault("category_renames", {})
            for source, value in list(renames.items()):
                if value == old_name:
                    renames[source] = new_name
            if old_name in CATEGORIES:
                renames[old_name] = new_name
            custom = review_payload.setdefault("custom_categories", [])
            review_payload["custom_categories"] = [new_name if value == old_name else value for value in custom]
            for review in review_payload.setdefault("reviews", {}).values():
                if review.get("decided_category") == old_name:
                    review["decided_category"] = new_name
            orders = review_payload.setdefault("category_orders", {})
            if old_name in orders:
                orders[new_name] = orders.pop(old_name)
            review_payload["category_order"] = [new_name if value == old_name else value for value in review_payload.get("category_order", [])]
        elif action == "reorder_categories":
            requested = [str(value).strip() for value in payload.get("categories", []) if str(value).strip()]
            if len(requested) != len(set(requested)):
                raise ValueError("类别顺序中存在重复项")
            current_board = classification_board_payload(targets_payload, review_payload)
            existing = [column["category"] for column in current_board["columns"]]
            if set(requested) != set(existing):
                raise ValueError("类别顺序不完整")
            review_payload["category_order"] = requested
        elif action in {"move", "edit"}:
            course_number = int(payload.get("course_id"))
            target = next((item for item in targets_payload.get("targets", []) if int(item.get("course_id")) == course_number), None)
            if not target:
                raise ValueError("课程不在当前分类总账中")
            existing_review = review_payload.setdefault("reviews", {}).get(str(course_number), {})
            target_category = str(payload.get("target_category") or existing_review.get("decided_category") or target.get("course_category") or "").strip()
            decided_title = str(payload.get("decided_title") or existing_review.get("decided_title") or target.get("title") or "").strip()
            note = str(payload.get("note") if "note" in payload else existing_review.get("note", "")).strip()
            if not target_category or len(target_category) > 40:
                raise ValueError("目标类别无效")
            if not decided_title or len(decided_title) > 200 or len(note) > 2000:
                raise ValueError("课程名称或说明过长")
            review_payload["reviews"][str(course_number)] = {
                **existing_review,
                "course_id": course_number,
                "title": target.get("title", ""),
                "album_id": target.get("album_id"),
                "album_title": target.get("album_title", ""),
                "original_category": target.get("course_category", ""),
                "decided_category": target_category,
                "decided_title": decided_title,
                "note": note,
                "reviewed_at": now,
            }
            custom = review_payload.setdefault("custom_categories", [])
            if target_category not in CATEGORIES and target_category not in custom:
                custom.append(target_category)
            if action == "move":
                target_index = int(payload.get("target_index", 0))
                orders = review_payload.setdefault("category_orders", {})
                moving_id = str(course_number)
                for category, values in list(orders.items()):
                    orders[category] = [str(value) for value in values if str(value) != moving_id]
                board = classification_board_payload(targets_payload, review_payload)
                target_column = next(column for column in board["columns"] if column["category"] == target_category)
                target_ids = [str(item.get("course_id")) for item in target_column["courses"] if str(item.get("course_id")) != moving_id]
                target_ids.insert(max(0, min(target_index, len(target_ids))), moving_id)
                orders[target_category] = target_ids
        else:
            raise ValueError("不支持的看板操作")
        review_payload["schema_version"] = "1.0"
        review_payload["updated_at"] = now
        temp_path = CLASSIFICATION_REVIEW_PATH.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(review_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(CLASSIFICATION_REVIEW_PATH)
    return classification_board_payload(targets_payload, review_payload)


def safe_title(title: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", title, flags=re.UNICODE).strip("-")
    return cleaned[:60] or "course"


def transcript_path(url: str, title: str = "course") -> Path:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    return TRANSCRIPT_DIR / f"{safe_title(title)}-{course_id(url)}.jsonl"


def staging_paths(url: str) -> tuple[Path, Path]:
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    key = course_id(url)
    return STAGING_DIR / f"{key}.state.json", STAGING_DIR / f"{key}.raw.jsonl"


def load_staging(url: str) -> tuple[dict, list[dict]]:
    state_path, raw_path = staging_paths(url)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {"course_url": url, "completed_items": []}
    rows = []
    if raw_path.exists():
        for line in raw_path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return state, rows


def save_staging(url: str, state: dict, rows: list[dict]) -> None:
    state_path, raw_path = staging_paths(url)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=STAGING_DIR, delete=False) as temp:
        temp.write("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n")
        raw_temp = Path(temp.name)
    raw_temp.replace(raw_path)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=STAGING_DIR, delete=False) as temp:
        temp.write(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        state_temp = Path(temp.name)
    state_temp.replace(state_path)


def jsonl_has_records(path: Path | None) -> bool:
    if not path or not path.exists():
        return False
    try:
        return any(isinstance(json.loads(line), dict) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except (OSError, json.JSONDecodeError):
        return False


def item_key(item: dict, index: int) -> str:
    return f"{item.get('id')}:{item.get('order', index)}:{item.get('category')}"


def merge_sentence_segments(raw_segments: list[dict], offset: float = 0.0) -> list[dict]:
    """Join Whisper fragments into readable sentence-like blocks without rewriting words."""
    merged = []
    current = None
    for segment in raw_segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        start = offset + float(segment["start"])
        end = offset + float(segment["end"])
        if current is None:
            current = {"start": start, "end": end, "text": text}
        else:
            previous = current["text"]
            if re.search(r"[。！？!?；;，,：:]$", previous):
                separator = " " if previous[-1:].isascii() and text[:1].isascii() else ""
            else:
                separator = " " if previous[-1:].isascii() and text[:1].isascii() else "，"
            current["text"] = previous + separator + text
            current["end"] = end
        sentence_end = bool(re.search(r"[。！？!?；;][”’\"']?$", current["text"]))
        readable_limit = current["end"] - current["start"] >= 10 or len(current["text"]) >= 52
        if sentence_end or readable_limit:
            if not sentence_end:
                current["text"] = current["text"].rstrip("，,；;：:") + "。"
                current["punctuation_inferred"] = True
            merged.append(current)
            current = None
    if current:
        if not re.search(r"[。！？!?；;][”’\"']?$", current["text"]):
            current["text"] = current["text"].rstrip("，,；;：:") + "。"
            current["punctuation_inferred"] = True
        merged.append(current)
    for block in merged:
        reading_text = block["text"]
        block["raw_text"] = "".join(
            str(segment.get("text", "")).strip()
            for segment in raw_segments
            if offset + float(segment["start"]) >= block["start"] - 0.01
            and offset + float(segment["end"]) <= block["end"] + 0.01
        )
        block["text"] = clean_reading_text(reading_text)
        block["transform"] = "reading_cleanup_v2"
    return merged


def clean_reading_text(text: str) -> str:
    """Conservative reading cleanup; preserve potentially meaningful discourse words."""
    text = re.sub(r"(^|[\s，,。！？!?；;])(?:嗯+|呃+|额+|唔+)(?=[\s，,。！？!?；;]|$)", r"\1", text)
    text = re.sub(r"([\u4e00-\u9fff])(?:[，,、\s]*\1){2,}", r"\1", text)
    text = re.sub(r"[，,]\s*[，,]+", "，", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" ，,")


def reliable_transcript_segment(segment: dict, audio_duration: float) -> bool:
    """Reject timestamp overflow and common Whisper hallucinations in trailing silence."""
    start = max(0.0, float(segment.get("start", 0)))
    end = max(start, float(segment.get("end", start)))
    text = str(segment.get("text", "")).strip()
    characters = len(re.sub(r"[^\w\u4e00-\u9fff]", "", text, flags=re.UNICODE))
    if not text or start >= audio_duration - 0.03:
        return False
    if float(segment.get("no_speech_prob", 0) or 0) > 0.6:
        return False
    if float(segment.get("avg_logprob", 0) or 0) < -1.2:
        return False
    if end - start >= 6 and characters / max(end - start, 0.01) < 0.7:
        return False
    return True


def media_duration(path: Path, fallback: float = 0.0) -> float:
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            check=True, capture_output=True, text=True,
        )
        return float(completed.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return fallback


def download_with_resume(url: str, path: Path, progress=None, attempts: int = 12) -> None:
    """Download a large media file with HTTP Range retries and a persistent partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    last_error = None
    for attempt in range(1, attempts + 1):
        existing = path.stat().st_size if path.exists() else 0
        request = urllib.request.Request(url, headers={"Range": f"bytes={existing}-"} if existing else {})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                status = getattr(response, "status", response.getcode())
                content_range = response.headers.get("Content-Range", "")
                match = re.search(r"/(\d+)$", content_range)
                if existing and status != 206:
                    existing = 0
                    mode = "wb"
                else:
                    mode = "ab" if existing else "wb"
                total = int(match.group(1)) if match else existing + int(response.headers.get("Content-Length", "0") or 0)
                with path.open(mode) as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        existing += len(chunk)
                        if progress and total:
                            progress(min(1.0, existing / total), existing, total)
                if not total or path.stat().st_size >= total:
                    return
                last_error = RuntimeError(f"下载不完整：{path.stat().st_size}/{total} 字节")
        except Exception as exc:
            if getattr(exc, "code", None) == 416 and path.exists() and path.stat().st_size > 0:
                return
            last_error = exc
        print(f"媒体下载中断，第 {attempt}/{attempts} 次自动续传：{last_error}", flush=True)
        time.sleep(min(5, attempt))
    raise RuntimeError(f"媒体多次续传失败：{last_error}")


def set_job(job_id: str, **updates):
    with _jobs_lock:
        _jobs[job_id].update(updates)


def cool_down(job_id: str, seconds: int, label: str) -> None:
    """Yield the local CPU/GPU between sustained Whisper bursts."""
    remaining = seconds
    while remaining > 0:
        set_job(job_id, status="cooling", message=f"低负荷巡航 · {label} · 还需 {remaining} 秒", media_progress=0.0)
        step = min(5, remaining)
        time.sleep(step)
        remaining -= step


def run_course_job(job_id: str, payload: dict, enhance_after: bool = True):
    try:
        resolved_category = final_course_category_map().get(int(payload.get("course_id") or course_id(payload["course_url"])))
    except (TypeError, ValueError):
        resolved_category = None
    if resolved_category:
        payload = {**payload, "course_category": resolved_category}
    url = payload["course_url"]
    title = payload.get("course_title") or "course"
    items = payload.get("items", [])
    audio_items = [item for item in items if item.get("category") in {"audio", "video"} and item.get("url")]
    cumulative = 0.0
    path = transcript_path(url, title)
    stage, raw_rows = load_staging(url)
    completed_items = set(stage.get("completed_items", []))
    media_durations = stage.get("media_durations", {})
    completed_media = sum(
        1 for index, item in enumerate(items, 1)
        if item.get("category") in {"audio", "video"} and item_key(item, index) in completed_items
    )
    set_job(job_id, total=len(audio_items), completed=completed_media)
    try:
        path.unlink(missing_ok=True)
        for index, item in enumerate(items, 1):
            category = item.get("category")
            key = item_key(item, index)
            duration = float(media_durations.get(key, float(item.get("duration", 0)) / 1000)) if category in {"audio", "video"} else 0.0
            if key in completed_items:
                cumulative += duration
                continue
            common = {
                "schema_version": "1.0",
                "course_id": int(re.search(r"[?&]course_id=(\d+)", url).group(1)) if re.search(r"[?&]course_id=(\d+)", url) else course_id(url),
                "source_url": url,
                "content_id": item.get("id"),
                "order": item.get("order", index),
            }
            if category == "text":
                text = str(item.get("text", "")).strip()
                if text:
                    raw_rows.append({**common, "source_type": "page_text", "start": cumulative, "end": cumulative, "text": text, "layer": "raw"})
            elif category in {"audio", "video"} and item.get("url"):
                audio_index = audio_items.index(item) + 1
                media_name = "视频" if category == "video" else "音频"
                strategy = item.get("media_strategy") or ("independent-audio" if category == "audio" else "video-container")
                set_job(job_id, status="downloading", current=audio_index, total=len(audio_items), completed=completed_media, media_strategy=strategy, media_source_key=item.get("media_source_key", ""), message=f"正在读取第 {audio_index}/{len(audio_items)} 段{media_name} · {strategy}")
                temp_path = MEDIA_CACHE_DIR / course_id(url) / f"{item.get('id') or index}.media"
                item_succeeded = False
                try:
                    def report_download(fraction, downloaded, total_size):
                        set_job(
                            job_id, download_progress=round(fraction, 4),
                            media_progress=round(0.2 * fraction, 4),
                            downloaded_bytes=downloaded, total_bytes=total_size,
                            message=f"正在下载第 {audio_index}/{len(audio_items)} 段{media_name} · {round(fraction * 100)}%",
                        )
                    download_with_resume(item["url"], temp_path, report_download)
                    duration = media_duration(temp_path, duration)
                    media_durations[key] = duration
                    set_job(job_id, status="transcribing", current=audio_index, total=len(audio_items), completed=completed_media, media_progress=0.2, message=f"正在转写第 {audio_index}/{len(audio_items)} 段{media_name} · 0%")
                    with _model_lock:
                        result, _engine = transcribe_audio(
                            temp_path,
                            progress=lambda fraction: set_job(
                                job_id, media_progress=round(0.2 + 0.8 * fraction, 4),
                                message=f"正在转写第 {audio_index}/{len(audio_items)} 段{media_name} · {round(fraction * 100)}%",
                            ),
                        )
                    kept_segments = 0
                    for segment in result.get("segments", []):
                        text = str(segment.get("text", "")).strip()
                        if reliable_transcript_segment(segment, duration):
                            local_start = max(0.0, float(segment["start"]))
                            local_end = min(duration, float(segment["end"]))
                            raw_rows.append({
                                **common, "source_type": "audio_transcript",
                                "start": round(cumulative + local_start, 2),
                                "end": round(cumulative + local_end, 2),
                                "text": text, "layer": "raw",
                                "avg_logprob": segment.get("avg_logprob"),
                                "no_speech_prob": segment.get("no_speech_prob"),
                                "content_start": round(cumulative, 2),
                                "content_end": round(cumulative + duration, 2),
                            })
                            kept_segments += 1
                    item_succeeded = kept_segments > 0
                finally:
                    if item_succeeded:
                        temp_path.unlink(missing_ok=True)
            cumulative += duration
            completed_items.add(key)
            stage = {
                "course_url": url, "course_title": title, "course_category": payload.get("course_category", "AI课"),
                "completed_items": sorted(completed_items), "media_durations": media_durations,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            save_staging(url, stage, raw_rows)
            if category in {"audio", "video"}:
                completed_media += 1
                set_job(job_id, completed=completed_media, total=len(audio_items), media_progress=0.0)
                if completed_media < len(audio_items) and MEDIA_COOLDOWN_SECONDS and completed_media % MEDIA_COOLDOWN_EVERY == 0:
                    cool_down(job_id, MEDIA_COOLDOWN_SECONDS, "媒体段间冷却")
        if audio_items and not any(row.get("source_type") == "audio_transcript" for row in raw_rows):
            raise RuntimeError("媒体已读取，但没有生成任何可靠文字；请检查视频音轨或媒体地址")
        if enhance_after:
            result = archive_and_enhance(
                payload,
                raw_rows,
                path,
                status=lambda state, message, progress=0.0, elapsed=0.0, limit=300: set_job(
                    job_id, status=state, message=message, media_progress=progress,
                    enhancement_elapsed=round(elapsed, 1), enhancement_limit=round(limit, 1),
                ),
            )
            message = "整节课文字稿与语义阅读稿已完成" if result["enhancement"] == "codex" else "本机文字稿已完成；Codex 润色暂时失败，可稍后重试"
            set_job(job_id, status="complete", message=message, transcript=str(path), completed=len(audio_items), total=len(audio_items), **result)
        else:
            result = archive_raw(payload, raw_rows)
            set_job(job_id, status="transcribed", message="原始稿已完成，已交给 Codex 润色队列", transcript=str(path), completed=len(audio_items), total=len(audio_items), **result)
        for staging_path in staging_paths(url):
            staging_path.unlink(missing_ok=True)
    except Exception as exc:
        print(f"整课转写失败：{exc}", flush=True)
        set_job(job_id, status="error", message=str(exc))


def run_enhancement_job(job_id: str, payload: dict, cache_path: Path):
    try:
        try:
            resolved_category = final_course_category_map().get(int(payload.get("course_id") or course_id(payload["course_url"])))
        except (TypeError, ValueError):
            resolved_category = None
        if resolved_category:
            payload = {**payload, "course_category": resolved_category}
        directory, metadata = find_archived_course(payload["course_url"])
        if not directory:
            raise RuntimeError("没有找到这节课的原始稿")
        raw_path = directory / "transcripts" / "raw.jsonl"
        raw_rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        raw_audio_characters = audio_character_count(raw_rows)
        set_job(job_id, raw_audio_characters=raw_audio_characters)
        payload = {
            **payload,
            "course_title": payload.get("course_title") or metadata.get("title") or directory.name,
            "course_category": payload.get("course_category") or metadata.get("category") or directory.parent.parent.name,
        }
        result = archive_and_enhance(
            payload, raw_rows, cache_path,
            status=lambda state, message, progress=0.0, elapsed=0.0, limit=300: set_job(
                job_id, status=state, message=message, media_progress=progress,
                enhancement_elapsed=round(elapsed, 1), enhancement_limit=round(limit, 1),
                raw_audio_characters=raw_audio_characters,
            ),
        )
        message = "语义阅读稿已完成" if result["enhancement"] == "codex" else "Codex 润色仍不可用，已保留本机文字稿"
        set_job(job_id, status="complete", message=message, transcript=str(cache_path), **result)
    except Exception as exc:
        set_job(job_id, status="error", message=str(exc))


def queue_paths():
    paths = {name: COURSE_QUEUE_DIR / name for name in ("priority", "pending", "processing", "enhance_priority", "enhance_pending", "enhancing", "complete", "failed")}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def retry_transient_network_failures(paths):
    """Return only connection-refused downloads to the durable pending queue."""
    for failed in paths["failed"].glob("*.json"):
        try:
            record = json.loads(failed.read_text(encoding="utf-8"))
            message = str(record.get("result", {}).get("message", ""))
            payload = record.get("payload")
            if payload and ("Connection refused" in message or "Errno 61" in message):
                target = paths["pending"] / failed.name
                target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                failed.unlink()
                print(f"网络恢复后自动重试课程 {payload.get('course_id')}", flush=True)
        except (OSError, json.JSONDecodeError):
            continue


def retry_missing_node_enhancements(paths):
    """Requeue transcripts whose Codex CLI could not find its Node runtime."""
    for completed in paths["complete"].glob("*.json"):
        try:
            record = json.loads(completed.read_text(encoding="utf-8"))
            result = record.get("result", {})
            payload = record.get("payload")
            error = str(result.get("enhancement_error", ""))
            if payload and result.get("enhancement") == "fallback" and "node: No such file" in error:
                target = paths["enhance_pending"] / completed.name
                target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                completed.unlink()
                print(f"Node 环境恢复后重新润色课程 {payload.get('course_id')}", flush=True)
        except (OSError, json.JSONDecodeError):
            continue


def course_layers_complete(url: str) -> bool:
    directory, _ = find_archived_course(url)
    if not directory:
        return False
    return jsonl_has_records(directory / "transcripts" / "raw.jsonl") and jsonl_has_records(directory / "transcripts" / "reading.jsonl")


def final_course_category_map() -> dict[int, str]:
    board = classification_board_payload()
    return {
        int(course["course_id"]): column["category"]
        for column in board["columns"] for course in column["courses"]
    }


def course_workspace(course_number: int) -> tuple[Path | None, dict]:
    board = classification_board_payload()
    for column in board["columns"]:
        for course in column["courses"]:
            if int(course.get("course_id")) == course_number:
                directory, metadata = find_archived_course(course.get("source_url", ""))
                return directory, {**course, **metadata, "final_category": column["category"]}
    return None, {}


def deferred_category_rank(category: str | None) -> int:
    """Ordinary courses first, Chat AI courses next, seven-year livestreams last."""
    if category == "相约七年直播":
        return 2
    if category == "AI课-Chat版":
        return 1
    return 0


def transcription_pending_order(paths) -> list[Path]:
    """Priority/audio ranking within the user's three-stage category order."""
    candidates = [(path, True) for path in paths["priority"].glob("*.json")]
    candidates += [(path, False) for path in paths["pending"].glob("*.json")]
    if not candidates:
        return []
    categories = final_course_category_map()
    ranked = []
    for path, is_priority in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            has_video = any(item.get("category") == "video" for item in payload.get("items", []))
            course_number = int(payload.get("course_id", path.stem))
            category_rank = deferred_category_rank(categories.get(course_number, payload.get("course_category")))
            within_queue = -course_number if is_priority else course_number
            ranked.append(((category_rank, 0 if is_priority else 1, 1 if has_video else 0, within_queue), path))
        except (OSError, ValueError, json.JSONDecodeError):
            ranked.append(((0, 1, 1, 10**12), path))
    return [path for _, path in sorted(ranked, key=lambda row: row[0])]


def enhancement_pending_order(paths) -> list[Path]:
    """Use the same three-stage category order for Codex enhancement."""
    candidates = [(path, True) for path in paths["enhance_priority"].glob("*.json")]
    candidates += [(path, False) for path in paths["enhance_pending"].glob("*.json")]
    if not candidates:
        return []
    categories = final_course_category_map()
    ranked = []
    for path, is_priority in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            course_number = int(payload.get("course_id", path.stem))
            category_rank = deferred_category_rank(categories.get(course_number, payload.get("course_category")))
            within_queue = -course_number if is_priority else course_number
            ranked.append(((category_rank, 0 if is_priority else 1, within_queue), path))
        except (OSError, ValueError, json.JSONDecodeError):
            ranked.append(((0, 1, 10**12), path))
    return [path for _, path in sorted(ranked, key=lambda row: row[0])]


def bulk_course_worker():
    paths = queue_paths()
    retry_transient_network_failures(paths)
    retry_missing_node_enhancements(paths)
    for interrupted in paths["processing"].glob("*.json"):
        interrupted.replace(paths["pending"] / interrupted.name)
    while True:
        pending = transcription_pending_order(paths)
        if not pending:
            time.sleep(2)
            continue
        source = pending[0]
        processing = paths["processing"] / source.name
        try:
            source.replace(processing)
            payload = json.loads(processing.read_text(encoding="utf-8"))
            url = payload["course_url"]
            job_id = f"bulk-{payload.get('course_id')}-{uuid.uuid4().hex[:8]}"
            with _jobs_lock:
                _jobs[job_id] = {"job_id": job_id, "course_url": url, "status": "queued", "message": "批处理队列开始"}
            if course_layers_complete(url):
                set_job(job_id, status="complete", message="已有完整文字稿与阅读稿，已跳过")
            else:
                directory, _ = find_archived_course(url)
                raw_path = directory / "transcripts" / "raw.jsonl" if directory else None
                if jsonl_has_records(raw_path):
                    set_job(job_id, status="transcribed", message="已有原始稿，已交给 Codex 润色队列")
                else:
                    run_course_job(job_id, payload, enhance_after=False)
            state = dict(_jobs[job_id])
            if state.get("status") == "complete":
                destination = paths["complete"]
            elif state.get("status") == "transcribed":
                destination = paths["enhance_priority"] if payload.get("priority") else paths["enhance_pending"]
            else:
                destination = paths["failed"]
            record = {"payload": payload, "result": state, "finished_at": datetime.now(timezone.utc).isoformat()}
            stored = payload if destination in {paths["enhance_priority"], paths["enhance_pending"]} else record
            (destination / processing.name).write_text(json.dumps(stored, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            processing.unlink(missing_ok=True)
            if COURSE_COOLDOWN_SECONDS:
                cool_down(job_id, COURSE_COOLDOWN_SECONDS, "课程间冷却")
        except Exception as exc:
            print(f"批处理队列失败：{exc}", flush=True)
            if processing.exists():
                failed = paths["failed"] / processing.name
                processing.replace(failed)


def bulk_enhancement_worker():
    paths = queue_paths()
    for interrupted in paths["enhancing"].glob("*.json"):
        interrupted.replace(paths["enhance_pending"] / interrupted.name)
    for ordinary in paths["enhance_pending"].glob("*.json"):
        try:
            payload = json.loads(ordinary.read_text(encoding="utf-8"))
            if payload.get("priority"):
                ordinary.replace(paths["enhance_priority"] / ordinary.name)
        except (OSError, json.JSONDecodeError):
            continue
    while True:
        pending = enhancement_pending_order(paths)
        if not pending:
            time.sleep(2)
            continue
        source = pending[0]
        processing = paths["enhancing"] / source.name
        try:
            source.replace(processing)
            payload = json.loads(processing.read_text(encoding="utf-8"))
            job_id = f"enhance-{payload.get('course_id')}-{uuid.uuid4().hex[:8]}"
            with _jobs_lock:
                _jobs[job_id] = {"job_id": job_id, "course_url": payload["course_url"], "status": "queued", "message": "等待 Codex 润色"}
            run_enhancement_job(job_id, payload, transcript_path(payload["course_url"], payload.get("course_title") or "course"))
            state = dict(_jobs[job_id])
            destination = paths["complete"] if state.get("status") == "complete" else paths["failed"]
            record = {"payload": payload, "result": state, "finished_at": datetime.now(timezone.utc).isoformat()}
            (destination / processing.name).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            processing.unlink(missing_ok=True)
        except Exception as exc:
            print(f"Codex 润色队列失败：{exc}", flush=True)
            if processing.exists():
                processing.replace(paths["failed"] / processing.name)


def bulk_queue_status():
    paths = queue_paths()
    return {name: len(list(path.glob("*.json"))) for name, path in paths.items()}


def bulk_dashboard_status():
    targets_payload = json.loads(COURSE_TARGETS_PATH.read_text(encoding="utf-8"))
    targets = targets_payload.get("targets", [])
    board = classification_board_payload(targets_payload, load_classification_reviews())
    final_courses = {
        int(course["course_id"]): {"category": column["category"], "title": course.get("display_title") or course.get("title")}
        for column in board["columns"] for course in column["courses"]
    }
    category_order = [column["category"] for column in board["columns"]]
    paths = queue_paths()
    states = {}
    for state, directory in paths.items():
        for path in directory.glob("*.json"):
            try:
                states[int(path.stem)] = state
            except ValueError:
                continue
    categories = {}
    existing = 0
    not_harvested = 0
    for target in targets:
        course_number = int(target["course_id"])
        state = states.get(course_number)
        if state is None and course_layers_complete(target["source_url"]):
            state = "complete"
            existing += 1
        elif state is None:
            state = "not_harvested"
            not_harvested += 1
        category = final_courses.get(course_number, {}).get("category", target["course_category"])
        bucket = categories.setdefault(category, {"total": 0, "complete": 0, "failed": 0, "processing": 0, "pending": 0})
        bucket["total"] += 1
        display_state = "pending" if state == "priority" else ("processing" if state in {"processing", "enhance_priority", "enhance_pending", "enhancing"} else state)
        if display_state in bucket:
            bucket[display_state] += 1

    def current_for(queue_name):
        processing_files = list(paths[queue_name].glob("*.json"))
        if not processing_files:
            return None
        try:
            payload = json.loads(processing_files[0].read_text(encoding="utf-8"))
            with _jobs_lock:
                job = next((dict(value) for value in reversed(list(_jobs.values())) if value.get("course_url") == payload.get("course_url")), {})
            raw_audio_characters = job.get("raw_audio_characters")
            reading_audio_characters = job.get("reading_audio_characters")
            if raw_audio_characters is None or reading_audio_characters is None:
                directory, metadata = find_archived_course(payload.get("course_url", ""))
                raw_audio_characters = metadata.get("raw_audio_characters", raw_audio_characters)
                reading_audio_characters = metadata.get("reading_audio_characters", reading_audio_characters)
                if directory and raw_audio_characters is None:
                    try:
                        raw_path = directory / "transcripts" / "raw.jsonl"
                        raw_rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                        raw_audio_characters = audio_character_count(raw_rows)
                    except (OSError, json.JSONDecodeError):
                        pass
            course_number = int(payload.get("course_id"))
            final = final_courses.get(course_number, {})
            return {
                "course_id": course_number, "title": final.get("title") or payload.get("course_title"),
                "category": final.get("category") or payload.get("course_category"), "album": payload.get("album_title"),
                "status": job.get("status", "preparing"), "message": job.get("message", "准备处理"),
                "media_progress": job.get("media_progress", 0), "completed_media": job.get("completed", 0),
                "total_media": job.get("total", 0),
                "raw_audio_characters": raw_audio_characters,
                "reading_audio_characters": reading_audio_characters,
            }
        except (OSError, json.JSONDecodeError):
            return None
    current_transcription = current_for("processing")
    current_enhancement = current_for("enhancing")
    if current_enhancement:
        current_enhancement["waiting"] = len(list(paths["enhance_priority"].glob("*.json"))) + len(list(paths["enhance_pending"].glob("*.json")))
    current = current_transcription or current_enhancement
    complete = sum(1 for target in targets if states.get(int(target["course_id"])) == "complete") + existing
    failed = sum(1 for target in targets if states.get(int(target["course_id"])) == "failed")
    pending = sum(1 for target in targets if states.get(int(target["course_id"])) in {"priority", "pending"})
    processing = sum(1 for target in targets if states.get(int(target["course_id"])) in {"processing", "enhance_priority", "enhance_pending", "enhancing"})
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(), "total": len(targets),
        "complete": complete, "existing": existing, "pending": pending,
        "processing": processing, "failed": failed, "not_harvested": not_harvested,
        "percent": round(complete / max(1, len(targets)) * 100, 2),
        "current": current, "current_transcription": current_transcription,
        "current_enhancement": current_enhancement, "categories": categories,
        "category_order": category_order,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "CourseStudyspace/0.1"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Course-Url, X-Course-Title, X-Chunk-Start")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/corpus/course-targets":
            try:
                payload = json.loads(COURSE_TARGETS_PATH.read_text(encoding="utf-8"))
                self._json({**payload, "queue": bulk_queue_status()})
            except (OSError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path == "/corpus/bulk-status":
            try:
                self._json(bulk_dashboard_status())
            except (OSError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path == "/corpus/classification-review":
            try:
                self._json(classification_review_payload())
            except (OSError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path == "/corpus/classification-board":
            try:
                self._json(classification_board_payload())
            except (OSError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path == "/course-classification":
            query = parse_qs(parsed.query)
            try:
                course_number = int(query.get("course_id", [""])[0])
                board = classification_board_payload()
                for column in board["columns"]:
                    course = next((item for item in column["courses"] if int(item.get("course_id")) == course_number), None)
                    if course:
                        workspace_dir, _ = find_archived_course(course.get("source_url", ""))
                        workspace_path = str(workspace_dir) if workspace_dir else ""
                        if workspace_path.startswith(str(Path.home())):
                            workspace_path = "~" + workspace_path[len(str(Path.home())):]
                        self._json({
                            "found": True,
                            "course_id": course_number,
                            "category": column["category"],
                            "title": course.get("display_title") or course.get("title"),
                            "album_title": course.get("album_title", ""),
                            "workspace_path": workspace_path,
                            "categories": [item["category"] for item in board["columns"]],
                        })
                        return
                self._json({"found": False, "course_id": course_number, "categories": [item["category"] for item in board["columns"]]})
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/corpus/dashboard":
            try:
                body = (CORPUS_DIR / "dashboard.html").read_bytes()
                self.send_response(HTTPStatus.OK)
                self._cors()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError as exc:
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path == "/health":
            self._json({
                "ok": True, "model": MODEL_NAME,
                "engine": "mlx-whisper-local" if mlx_whisper is not None else "openai-whisper-local",
                "model_loaded": _model is not None,
            })
            return
        if parsed.path == "/transcript":
            query = parse_qs(parsed.query)
            url = query.get("url", [""])[0]
            if not url:
                self._json({"error": "missing url"}, HTTPStatus.BAD_REQUEST)
                return
            matches = list(TRANSCRIPT_DIR.glob(f"*-{course_id(url)}.jsonl")) if TRANSCRIPT_DIR.exists() else []
            records = []
            if matches:
                for line in matches[0].read_text(encoding="utf-8").splitlines():
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            directory, metadata = find_archived_course(url)
            if directory:
                if metadata.get("raw_audio_characters") is None:
                    try:
                        raw_rows = [json.loads(line) for line in (directory / "transcripts" / "raw.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
                        metadata["raw_audio_characters"] = audio_character_count(raw_rows)
                    except (OSError, json.JSONDecodeError):
                        pass
                if metadata.get("reading_audio_characters") is None:
                    try:
                        reading_rows = [json.loads(line) for line in (directory / "transcripts" / "reading.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
                        metadata["reading_audio_characters"] = audio_character_count(reading_rows)
                    except (OSError, json.JSONDecodeError):
                        pass
            self._json({"records": records, "course": metadata})
            return
        if parsed.path == "/course-status":
            query = parse_qs(parsed.query)
            url = query.get("url", [""])[0]
            if not url:
                self._json({"error": "missing url"}, HTTPStatus.BAD_REQUEST)
                return
            with _jobs_lock:
                active = next((dict(job) for job in reversed(list(_jobs.values())) if job.get("course_url") == url and job.get("status") not in {"complete", "error"}), None)
            if active:
                self._json(active)
                return
            matches = list(TRANSCRIPT_DIR.glob(f"*-{course_id(url)}.jsonl")) if TRANSCRIPT_DIR.exists() else []
            if any(jsonl_has_records(path) for path in matches):
                self._json({"status": "complete", "message": "文字稿已保存"})
                return
            state, rows = load_staging(url)
            completed = state.get("completed_items", [])
            if completed or rows:
                self._json({"status": "interrupted", "current": len(completed), "message": f"已保存 {len(completed)} 个内容项，点击后继续"})
                return
            directory, _ = find_archived_course(url)
            raw_path = directory / "transcripts" / "raw.jsonl" if directory else None
            if jsonl_has_records(raw_path):
                self._json({"status": "interrupted", "message": "原始稿已完成，点击继续语义整理"})
                return
            self._json({"status": "idle", "message": "尚未生成文字稿"})
            return
        if parsed.path.startswith("/jobs/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
            with _jobs_lock:
                job = dict(_jobs.get(job_id, {}))
            if not job:
                self._json({"error": "job not found"}, HTTPStatus.NOT_FOUND)
            else:
                self._json(job)
            return
        if parsed.path == "/codex/events":
            query = parse_qs(parsed.query)
            category = query.get("category", ["AI课"])[0]
            try:
                since = float(query.get("since", ["0"])[0])
                self._json({"events": codex_bridge.events(category, since), "now": datetime.now().timestamp()})
            except (ValueError, OSError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/codex/models":
            try:
                self._json({"models": codex_bridge.list_models(), "runtime": codex_bridge.runtime_info()})
            except (RuntimeError, OSError, TimeoutError) as exc:
                self._json({"error": str(exc), "runtime": codex_bridge.runtime_info()}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if parsed.path == "/terminal/output":
            query = parse_qs(parsed.query)
            try:
                session = terminal_bridge.get(query.get("session_id", [""])[0])
                self._json(session.output(int(query.get("since", ["0"])[0])))
            except (KeyError, ValueError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if urlparse(self.path).path in {"/terminal/start", "/terminal/input", "/terminal/resize"}:
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length))
                if urlparse(self.path).path == "/terminal/start":
                    course_number = int(payload.get("course_id"))
                    directory, metadata = course_workspace(course_number)
                    if not directory:
                        raise ValueError("当前课程资料目录还不存在，请先生成文字稿")
                    session = terminal_bridge.start(str(course_number), directory, payload.get("cols", 80), payload.get("rows", 24), bool(payload.get("force")))
                    self._json({"ok": True, "session_id": session.id, "cwd": str(directory), "title": metadata.get("title") or directory.name})
                else:
                    session = terminal_bridge.get(str(payload.get("session_id") or ""))
                    if urlparse(self.path).path == "/terminal/input":
                        session.write(str(payload.get("data") or ""))
                    else:
                        session.resize(payload.get("cols", 80), payload.get("rows", 24))
                    self._json({"ok": True})
            except (json.JSONDecodeError, KeyError, TypeError, ValueError, RuntimeError, OSError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if urlparse(self.path).path == "/corpus/classification-board":
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length))
                self._json({"ok": True, **update_classification_board(payload)})
            except (json.JSONDecodeError, TypeError, ValueError, OSError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if urlparse(self.path).path == "/corpus/classification-review":
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length))
                review = save_classification_review(
                    int(payload.get("course_id")),
                    str(payload.get("decided_category") or "").strip(),
                    str(payload.get("note") or "").strip(),
                    int(payload["decided_order"]) if str(payload.get("decided_order") or "").strip() else None,
                    str(payload.get("decided_title") or "").strip(),
                )
                self._json({"ok": True, "review": review})
            except (json.JSONDecodeError, TypeError, ValueError, OSError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if urlparse(self.path).path == "/corpus/course-enqueue":
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 2 * 1024 * 1024:
                self._json({"error": "invalid course payload"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                payload = json.loads(self.rfile.read(length))
                course_number = int(payload.get("course_id"))
                if not payload.get("course_url") or not isinstance(payload.get("items"), list):
                    raise ValueError("缺少课程地址或内容")
                if payload.get("course_category") not in CATEGORIES:
                    raise ValueError("未知课程类别")
                paths = queue_paths()
                name = f"{course_number}.json"
                if any((paths[state] / name).exists() for state in ("priority", "pending", "processing", "enhance_priority", "enhance_pending", "enhancing", "complete")) or course_layers_complete(payload["course_url"]):
                    self._json({"ok": True, "course_id": course_number, "queued": False, "reason": "already-present"})
                    return
                queue_name = "priority" if payload.get("priority") else "pending"
                target = paths[queue_name] / name
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=paths[queue_name], delete=False) as temp:
                    temp.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
                    temporary = Path(temp.name)
                temporary.replace(target)
                try:
                    targets_payload = json.loads(COURSE_TARGETS_PATH.read_text(encoding="utf-8"))
                    targets = targets_payload.setdefault("targets", [])
                    if not any(int(item["course_id"]) == course_number for item in targets):
                        targets.append({
                            "course_id": course_number, "title": payload.get("course_title", ""),
                            "album_id": payload.get("album_id"), "album_title": payload.get("album_title", ""),
                            "course_category": payload.get("course_category"), "source_url": payload.get("course_url"),
                        })
                        targets_payload["total_targets"] = len(targets)
                        COURSE_TARGETS_PATH.write_text(json.dumps(targets_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                except (OSError, json.JSONDecodeError):
                    pass
                self._json({"ok": True, "course_id": course_number, "queued": True}, HTTPStatus.ACCEPTED)
            except (json.JSONDecodeError, ValueError, OSError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if urlparse(self.path).path == "/catalog/import":
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 10 * 1024 * 1024:
                self._json({"error": "invalid catalog payload"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                payload = json.loads(self.rfile.read(length))
                communities = payload.get("communities")
                if payload.get("source") != "songy-account" or not isinstance(communities, list):
                    raise ValueError("课程目录格式无法识别")
                captured_at = str(payload.get("captured_at") or datetime.now(timezone.utc).isoformat())
                album_count = sum(len(item.get("albums", [])) for item in communities if isinstance(item, dict))
                course_count = sum(
                    len(album.get("courses", []))
                    for item in communities if isinstance(item, dict)
                    for album in item.get("albums", []) if isinstance(album, dict)
                )
                CORPUS_DIR.mkdir(parents=True, exist_ok=True)
                snapshots = CORPUS_DIR / "sources" / "songy"
                snapshots.mkdir(parents=True, exist_ok=True)
                stamp = re.sub(r"[^0-9]", "", captured_at)[:14] or datetime.now().strftime("%Y%m%d%H%M%S")
                snapshot = snapshots / f"course-catalog-{stamp}.json"
                snapshot.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                latest = CORPUS_DIR / "songy-course-catalog.latest.json"
                latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                self._json({
                    "ok": True, "communities": len(communities), "albums": album_count,
                    "courses": course_count, "snapshot": str(snapshot), "latest": str(latest)
                }, HTTPStatus.CREATED)
            except (json.JSONDecodeError, ValueError, OSError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if urlparse(self.path).path == "/codex/message":
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length))
                category = payload.get("category", "AI课")
                text = str(payload.get("text", "")).strip()
                if not text:
                    raise ValueError("问题不能为空")
                model = str(payload.get("model") or "").strip() or None
                effort = str(payload.get("effort") or "").strip() or None
                direct_answer = codex_bridge.direct_answer(text, model=model, effort=effort)
                if direct_answer:
                    self._json({"ok": True, "direct_answer": direct_answer, "runtime": codex_bridge.runtime_info()})
                    return
                result = codex_bridge.send_message(
                    category=category,
                    text=text,
                    course_id=payload.get("course_id"),
                    course_title=str(payload.get("course_title") or "").strip(),
                    album_title=str(payload.get("album_title") or "").strip(),
                    selection=str(payload.get("selection", "")),
                    model=model,
                    effort=effort,
                )
                self._json({"ok": True, "turn": result}, HTTPStatus.ACCEPTED)
            except (json.JSONDecodeError, ValueError, RuntimeError, OSError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if urlparse(self.path).path == "/codex/approval":
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length))
                codex_bridge.answer_approval(str(payload.get("request_id", "")), str(payload.get("decision", "")))
                self._json({"ok": True})
            except (json.JSONDecodeError, ValueError, RuntimeError, OSError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if urlparse(self.path).path == "/transcribe-course":
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 2 * 1024 * 1024:
                self._json({"error": "invalid course payload"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                payload = json.loads(self.rfile.read(length))
                if not payload.get("course_url") or not isinstance(payload.get("items"), list):
                    raise ValueError("missing course_url or items")
                if payload.get("course_category", "AI课") not in CATEGORIES:
                    raise ValueError("未知课程类别")
                existing_files = list(TRANSCRIPT_DIR.glob(f"*-{course_id(payload['course_url'])}.jsonl")) if TRANSCRIPT_DIR.exists() else []
                completed_file = next((path for path in existing_files if jsonl_has_records(path)), None)
                if completed_file and not payload.get("force", False):
                    if payload.get("force_enhance", False):
                        job_id = uuid.uuid4().hex
                        with _jobs_lock:
                            _jobs[job_id] = {"job_id": job_id, "course_url": payload["course_url"], "status": "queued", "current": 0, "total": 0, "message": "准备重新整理阅读稿"}
                        threading.Thread(target=run_enhancement_job, args=(job_id, payload, completed_file), daemon=True).start()
                        self._json({"ok": True, "job_id": job_id}, HTTPStatus.ACCEPTED)
                        return
                    self._json({"ok": True, "cached": True, "transcript": str(completed_file)})
                    return
                with _jobs_lock:
                    existing = next((job for job in _jobs.values() if job.get("course_url") == payload["course_url"] and job.get("status") not in {"complete", "error"}), None)
                if existing:
                    self._json({"ok": True, "job_id": existing["job_id"], "existing": True}, HTTPStatus.ACCEPTED)
                    return
                archived_directory, _ = find_archived_course(payload["course_url"])
                archived_raw = archived_directory / "transcripts" / "raw.jsonl" if archived_directory else None
                job_id = uuid.uuid4().hex
                with _jobs_lock:
                    _jobs[job_id] = {"job_id": job_id, "course_url": payload["course_url"], "status": "queued", "current": 0, "total": 0, "message": "等待处理"}
                if jsonl_has_records(archived_raw):
                    _jobs[job_id]["message"] = "原始稿已完成，准备继续语义整理"
                    threading.Thread(target=run_enhancement_job, args=(job_id, payload, transcript_path(payload["course_url"], payload.get("course_title") or "course")), daemon=True).start()
                else:
                    threading.Thread(target=run_course_job, args=(job_id, payload), daemon=True).start()
                self._json({"ok": True, "job_id": job_id}, HTTPStatus.ACCEPTED)
            except (json.JSONDecodeError, ValueError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if urlparse(self.path).path != "/transcribe":
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return

        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 25 * 1024 * 1024:
            self._json({"error": "invalid audio size"}, HTTPStatus.BAD_REQUEST)
            return

        url = self.headers.get("X-Course-Url", "").strip()
        title = unquote(self.headers.get("X-Course-Title", "course").strip())
        try:
            chunk_start = float(self.headers.get("X-Chunk-Start", "0"))
        except ValueError:
            chunk_start = 0.0
        if not url:
            self._json({"error": "missing course URL"}, HTTPStatus.BAD_REQUEST)
            return

        audio = self.rfile.read(length)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as temp:
                temp.write(audio)
                temp_path = Path(temp.name)
            with _model_lock:
                result, engine = transcribe_audio(temp_path)
            valid_segments = [
                segment for segment in result.get("segments", [])
                if reliable_transcript_segment(segment, max(float(segment.get("end", 0)), 0.1))
            ]
            segments = merge_sentence_segments(valid_segments, chunk_start)
            for segment in segments:
                segment["start"] = round(segment["start"], 2)
                segment["end"] = round(segment["end"], 2)
            record = {
                "schema_version": "1.0",
                "course_id": course_id(url),
                "source_url": url,
                "course_title": title,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "chunk_start": chunk_start,
                "engine": engine,
                "model": MODEL_NAME,
                "language": result.get("language", "zh"),
                "segments": segments,
            }
            path = transcript_path(url, title)
            with path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._json({"ok": True, "record": record})
        except Exception as exc:
            print(f"转写失败：{exc}", flush=True)
            self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {format % args}", flush=True)


if __name__ == "__main__":
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Thread(target=bulk_course_worker, daemon=True, name="bulk-course-worker").start()
    threading.Thread(target=bulk_enhancement_worker, daemon=True, name="bulk-enhancement-worker").start()
    print(f"课程转写服务已启动：http://{HOST}:{PORT}", flush=True)
    print(f"文字稿目录：{TRANSCRIPT_DIR}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
    finally:
        terminal_bridge.stop()
        codex_bridge.stop()
        server.server_close()
