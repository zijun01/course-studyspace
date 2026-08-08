#!/usr/bin/env python3
"""Create the stable nine-category course library without overwriting user content."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "library"
CATEGORIES = ["AI课", "写作课", "自学课", "专注课", "思考课", "财富课", "家庭教育课", "教练课", "英语课"]


def write_once(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def main():
    LIBRARY.mkdir(parents=True, exist_ok=True)
    catalog = {
        "schema_version": "1.0",
        "categories": [{"id": name, "name": name, "path": name} for name in CATEGORIES],
        "course_mappings": {
            "802": {
                "category": "AI课",
                "title": "2026.07.30.Claude.Code.是个大模型调度器",
                "source_url": "https://webapp.songy.info/#/courses/details?course_id=802",
            }
        },
    }
    write_once(LIBRARY / "catalog.json", json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    for category in CATEGORIES:
        category_dir = LIBRARY / category
        (category_dir / "courses").mkdir(parents=True, exist_ok=True)
        write_once(
            category_dir / "AGENTS.md",
            f"""# {category} Codex 工作区

本目录是一个独立课程类别的 Codex 工作区。

- 默认只使用本类别下的课程、笔记和上下文。
- 回答课程问题时引用课程 ID、原文和时间点。
- 不把阅读清理稿冒充原始转写；需要核对时读取 `transcripts/raw.jsonl`。
- 可在本类别内创建笔记、研究、脚本和其他用户要求的产物。
- 跨类别工作只在用户明确指定来源后进行。
""",
        )
        write_once(
            category_dir / "CATEGORY_CONTEXT.md",
            f"# {category}｜类别长期上下文\n\n> 由 Codex 在用户确认后持续整理。课程原文仍以各课程目录为准。\n",
        )

    course_dir = LIBRARY / "AI课" / "courses" / "802-Claude-Code是个大模型调度器"
    (course_dir / "transcripts").mkdir(parents=True, exist_ok=True)
    (course_dir / "notes").mkdir(parents=True, exist_ok=True)
    write_once(
        course_dir / "course.json",
        json.dumps(
            {
                "schema_version": "1.0",
                "course_id": 802,
                "category": "AI课",
                "title": "2026.07.30.Claude.Code.是个大模型调度器",
                "source_url": "https://webapp.songy.info/#/courses/details?course_id=802",
                "site_album_id": 6,
                "site_album_title": "笑来分享合集",
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
    )
    print(LIBRARY)


if __name__ == "__main__":
    main()
