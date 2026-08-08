#!/usr/bin/env python3
"""Capture xiaolai's public GitHub inventory and derive book-like candidates."""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "research" / "corpus"
SOURCE_DIR = CORPUS / "sources" / "github"

KNOWN_BOOK_REPOS = {
    "100-Very-Short-Sentences-in-American-English", "1000-hours",
    "a-new-english-reading-handbook", "apple-computer-literacy",
    "bitcoin-whitepaper-chinese-translation", "blockchainlittlebook.com",
    "chitchat-on-translation", "help-to-be-helped", "INB-Principles", "ji",
    "little-book-of-ai", "most-common-american-idioms", "no-one-did-it",
    "public-speaking-with-meaning", "quit-smoking-instantly",
    "regular-investing-in-box", "slidology-from-xiaolai",
    "spreadsheets-for-investors", "the-self-cultivation-of-leeks",
    "time-as-a-friend", "toefl-ibt-vocabulary-in-context", "too-late", "twe185",
    "writing-comparison-in-english", "xiaolai.github.io", "zuoxiangqicheng",
}

BOOK_WORDS = re.compile(
    r"book|handbook|guide|教程|手册|白皮书|写给|作文|词汇|课程|幻灯课|小说|朗读材料",
    re.IGNORECASE,
)


def main() -> None:
    completed = subprocess.run(
        [
            "gh", "api", "--paginate", "--slurp",
            "users/xiaolai/repos?per_page=100&sort=full_name",
        ],
        check=True, capture_output=True, text=True,
    )
    pages = json.loads(completed.stdout)
    repos = [repo for page in pages for repo in page]
    captured_at = datetime.now(timezone.utc).isoformat()
    compact = [
        {
            "name": repo.get("name"), "full_name": repo.get("full_name"),
            "html_url": repo.get("html_url"), "description": repo.get("description") or "",
            "fork": bool(repo.get("fork")), "archived": bool(repo.get("archived")),
            "created_at": repo.get("created_at"), "updated_at": repo.get("updated_at"),
            "pushed_at": repo.get("pushed_at"), "default_branch": repo.get("default_branch"),
            "license": (repo.get("license") or {}).get("spdx_id"),
        }
        for repo in repos
    ]
    payload = {
        "schema_version": "1.0", "source": "github-api/users/xiaolai/repos",
        "captured_at": captured_at, "repository_count": len(compact), "repositories": compact,
    }
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = re.sub(r"[^0-9]", "", captured_at)[:14]
    (SOURCE_DIR / f"repositories-{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (CORPUS / "xiaolai-github-repositories.latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    candidates = []
    for repo in compact:
        haystack = f"{repo['name']} {repo['description']}"
        reason = []
        if repo["name"] in KNOWN_BOOK_REPOS:
            reason.append("人工种子书目")
        if BOOK_WORDS.search(haystack):
            reason.append("名称或简介含书籍线索")
        if reason and not repo["fork"]:
            candidates.append({**repo, "candidate_reason": reason, "verification": "待检查仓库正文"})
    derived = {
        "schema_version": "1.0", "generated_at": captured_at,
        "source_snapshot": "xiaolai-github-repositories.latest.json",
        "scope_note": "候选不等于作者作品；需逐仓库核验 README、正文、作者和版本。Fork 已排除。",
        "candidate_count": len(candidates), "candidates": candidates,
    }
    (CORPUS / "github-book-candidates.json").write_text(
        json.dumps(derived, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
