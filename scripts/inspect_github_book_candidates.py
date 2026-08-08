#!/usr/bin/env python3
"""Inspect candidate repository trees without downloading book bodies."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "research" / "corpus"


def gh_json(path: str):
    completed = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def main() -> None:
    source = json.loads((CORPUS / "github-book-candidates.json").read_text(encoding="utf-8"))
    inspected = []
    for candidate in source.get("candidates", []):
        name = candidate["name"]
        branch = candidate.get("default_branch") or "master"
        try:
            tree = gh_json(f"repos/xiaolai/{name}/git/trees/{branch}?recursive=1")
            paths = [item.get("path", "") for item in tree.get("tree", []) if item.get("type") == "blob"]
            text_paths = [path for path in paths if Path(path).suffix.lower() in {".md", ".markdown", ".txt", ".html", ".htm"}]
            book_paths = [path for path in paths if Path(path).suffix.lower() in {".epub", ".pdf", ".mobi", ".azw", ".azw3"}]
            chapter_paths = [path for path in text_paths if any(word in path.lower() for word in ("chapter", "chapters", "book", "manuscript", "content"))]
            inspected.append({
                **candidate,
                "tree_status": "complete" if not tree.get("truncated") else "truncated",
                "file_count": len(paths),
                "text_file_count": len(text_paths),
                "book_file_count": len(book_paths),
                "chapter_like_file_count": len(chapter_paths),
                "sample_text_paths": text_paths[:30],
                "book_paths": book_paths,
                "structure_assessment": (
                    "strong_book_candidate" if book_paths or len(text_paths) >= 5
                    else "possible_short_manuscript" if text_paths
                    else "not_supported_by_tree"
                ),
            })
        except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            inspected.append({**candidate, "tree_status": "error", "error": str(exc)})
    result = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(inspected),
        "strong_book_candidates": sum(item.get("structure_assessment") == "strong_book_candidate" for item in inspected),
        "candidates": inspected,
    }
    (CORPUS / "github-book-candidates.inspected.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    labels = {
        "strong_book_candidate": "很像书稿",
        "possible_short_manuscript": "可能是短书或单文件书稿",
        "not_supported_by_tree": "目录结构暂不支持",
    }
    lines = [
        "# GitHub 书稿候选——请用户判断", "",
        "> 这是一份候选清单，不是最终书目。请在“你的判断”一栏填写：是 / 不是 / 不确定。", "",
        "判断时请注意：Fork 可能仍保存李笑来自己的旧作，但也可能只是收藏了他人的项目；仓库名像书，也不证明作者就是李笑来。", "",
        "| 序号 | 候选 | 当前机器判断 | 文字文件 | 成品书文件 | 你的判断 |",
        "|---:|---|---|---:|---:|---|",
    ]
    for index, item in enumerate(inspected, 1):
        title = item.get("description") or item["name"]
        link = f"[{title}]({item['html_url']})<br><code>{item['name']}</code>"
        assessment = labels.get(item.get("structure_assessment"), "检查失败")
        lines.append(
            f"| {index} | {link} | {assessment} | {item.get('text_file_count', 0)} | "
            f"{item.get('book_file_count', 0)} |  |"
        )
    lines.extend([
        "", "## 怎么把判断告诉我", "",
        "你可以直接说序号，例如：`2、4、7 是；13、18 不是；其余不确定。`",
        "也可以直接在表格最后一列填写后保存。",
    ])
    (CORPUS / "REVIEW-GITHUB-BOOKS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
