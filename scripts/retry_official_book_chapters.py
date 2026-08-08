#!/usr/bin/env python3
"""Retry failed official-site chapter pages and merge them into the latest snapshot."""
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
    errors = manifest.get("errors", [])
    if not errors:
        print("没有失败页面需要重试")
        return
    if not manifest.get("pages"):
        raise RuntimeError("现有清单没有成功页面，无法确定快照目录")
    snapshot_root = (ROOT / manifest["pages"][0]["snapshot_path"]).parents[1]

    def retry(item):
        body = fetch(item["source_url"])
        path = urllib.parse.urlparse(item["source_url"]).path
        marker = f"/books/"
        remainder = path.split(marker, 1)[1].split("/", 1)[1]
        parts = [re.sub(r"[^a-zA-Z0-9._-]+", "-", part) or "index" for part in remainder.split("/")]
        parts[-1] = f"{hashlib.sha256(item['source_url'].encode('utf-8')).hexdigest()[:12]}-{parts[-1]}"
        output = snapshot_root / item["work_id"] / Path(*parts).with_suffix(".html")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)
        return {
            "work_id": item["work_id"], "source_url": item["source_url"],
            "snapshot_path": str(output.relative_to(ROOT)), "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }

    successes = []
    remaining = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(retry, item): item for item in errors}
        for index, future in enumerate(as_completed(futures), 1):
            try:
                successes.append(future.result())
            except Exception as exc:
                remaining.append({**futures[future], "error": str(exc)})
            if index % 20 == 0 or index == len(errors):
                print(f"重试 {index}/{len(errors)}，仍失败 {len(remaining)}", flush=True)
    merged = {item["source_url"]: item for item in manifest["pages"]}
    merged.update({item["source_url"]: item for item in successes})
    manifest["pages"] = sorted(merged.values(), key=lambda item: (item["work_id"], item["source_url"]))
    manifest["saved_pages"] = len(manifest["pages"])
    manifest["errors"] = remaining
    snapshot_manifest = snapshot_root / "ACQUISITION-MANIFEST.json"
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    snapshot_manifest.write_text(rendered, encoding="utf-8")
    MANIFEST_PATH.write_text(rendered, encoding="utf-8")
    print(f"合并完成：{manifest['saved_pages']}/{manifest['expected_pages']}，仍失败 {len(remaining)}")


if __name__ == "__main__":
    main()
