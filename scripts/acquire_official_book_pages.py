#!/usr/bin/env python3
"""Save immutable official-site HTML snapshots for in-scope books."""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "research" / "corpus"
BASE = "https://lixiaolai.com"
BOOK_PAGES = {
    "little-book-of-ai": "/books/little-book-of-ai",
    "1000-hours": "/books/1000-hours",
    "help-to-be-helped": "/books/help-to-be-helped",
    "regular-investing-in-box": "/books/regular-investing-changes-fate",
    "blockchainlittlebook.com": "/books/blockchain-little-book",
    "the-self-cultivation-of-leeks": "/books/the-self-cultivation-of-leeks",
    "zuoxiangqicheng": "/books/zuoxiangqicheng",
    "time-as-a-friend": "/books/befriending-time",
    "public-speaking-with-meaning": "/books/i-have-a-say",
    "writing-comparison-in-english": "/books/writing-comparison-in-english",
}


def fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140 Safari/537.36"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def main() -> None:
    captured = datetime.now(timezone.utc)
    stamp = captured.strftime("%Y%m%dT%H%M%SZ")
    destination = CORPUS / "raw" / "books" / "official-site" / stamp
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    all_pages = {"books-index": "/books", **BOOK_PAGES}
    for index, (work_id, route) in enumerate(all_pages.items(), 1):
        url = BASE + route
        print(f"[{index}/{len(all_pages)}] 获取 {url}", flush=True)
        body = fetch(url)
        path = destination / f"{re.sub(r'[^a-zA-Z0-9.-]+', '-', work_id)}.html"
        path.write_bytes(body)
        records.append({
            "work_id": work_id,
            "source_url": url,
            "snapshot_path": str(path.relative_to(ROOT)),
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        })
        time.sleep(0.6)
    missing = sorted(set(json.loads((CORPUS / "teaching-grammar-scope.json").read_text(encoding="utf-8"))["included_github_repositories"]) - set(BOOK_PAGES))
    manifest = {
        "schema_version": "1.0",
        "captured_at": captured.isoformat(),
        "source": BASE,
        "page_count": len(records),
        "pages": records,
        "in_scope_repositories_without_books_page": missing,
    }
    (destination / "ACQUISITION-MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (CORPUS / "official-book-pages-acquisition.latest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
