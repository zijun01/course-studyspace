#!/usr/bin/env python3
"""Repair chapter snapshot path collisions found by hash verification."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "research" / "corpus"
MANIFEST_PATH = CORPUS / "official-book-chapters-acquisition.latest.json"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140 Safari/537.36"


def fetch(url: str) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    encoded = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/"), parsed.query, parsed.fragment))
    request = urllib.request.Request(encoded, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=35) as response:
        return response.read()


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    invalid = []
    for row in manifest["pages"]:
        path = ROOT / row["snapshot_path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            invalid.append(row)
    print(f"检测到 {len(invalid)} 个路径碰撞页面", flush=True)

    def repair(row):
        body = fetch(row["source_url"])
        old = ROOT / row["snapshot_path"]
        slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", urllib.parse.unquote(urllib.parse.urlparse(row["source_url"]).path.rsplit("/", 1)[-1])) or "chapter"
        output = old.parent / f"{hashlib.sha256(row['source_url'].encode('utf-8')).hexdigest()[:12]}-{slug}.html"
        output.write_bytes(body)
        return {**row, "snapshot_path": str(output.relative_to(ROOT)), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}

    repaired = {}
    errors = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(repair, row): row for row in invalid}
        for index, future in enumerate(as_completed(futures), 1):
            try:
                item = future.result()
                repaired[item["source_url"]] = item
            except Exception as exc:
                errors.append({"source_url": futures[future]["source_url"], "error": str(exc)})
            if index % 20 == 0 or index == len(invalid):
                print(f"修复 {index}/{len(invalid)}，失败 {len(errors)}", flush=True)
    manifest["pages"] = [repaired.get(row["source_url"], row) for row in manifest["pages"]]
    manifest["errors"] = errors
    manifest["saved_pages"] = len(manifest["pages"]) - len(errors)
    snapshot_root = (ROOT / manifest["pages"][0]["snapshot_path"]).parents[1]
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    (snapshot_root / "ACQUISITION-MANIFEST.json").write_text(rendered, encoding="utf-8")
    MANIFEST_PATH.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
