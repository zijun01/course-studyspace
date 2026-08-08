#!/usr/bin/env python3
"""Acquire all chapter pages linked from saved official book landing pages."""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "research" / "corpus"
BASE = "https://lixiaolai.com"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140 Safari/537.36"


def fetch(url: str) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    request_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/"), parsed.query, parsed.fragment))
    for attempt in range(4):
        try:
            request = urllib.request.Request(request_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=35) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"无法获取 {url}")


def main() -> None:
    landing_manifest = json.loads((CORPUS / "official-book-pages-acquisition.latest.json").read_text(encoding="utf-8"))
    landing_dir = ROOT / Path(landing_manifest["pages"][0]["snapshot_path"]).parent
    captured = datetime.now(timezone.utc)
    stamp = captured.strftime("%Y%m%dT%H%M%SZ")
    destination = CORPUS / "raw" / "books" / "official-site-chapters" / stamp
    destination.mkdir(parents=True, exist_ok=False)
    jobs = []
    for page in landing_manifest["pages"]:
        if page["work_id"] == "books-index":
            continue
        route = urllib.parse.urlparse(page["source_url"]).path.rstrip("/")
        html = (ROOT / page["snapshot_path"]).read_text(encoding="utf-8")
        links = sorted(set(re.findall(r'href="([^"]+)"', html)))
        for link in links:
            path = urllib.parse.urlparse(link).path.rstrip("/")
            if path.startswith(route + "/"):
                jobs.append((page["work_id"], BASE + path, path[len(route) + 1 :]))
    print(f"准备获取 {len(jobs)} 个章节页面", flush=True)
    records = []
    errors = []

    def acquire(job):
        work_id, url, relative = job
        body = fetch(url)
        safe_parts = [re.sub(r"[^a-zA-Z0-9._-]+", "-", part) or "index" for part in relative.split("/")]
        safe_parts[-1] = f"{hashlib.sha256(url.encode('utf-8')).hexdigest()[:12]}-{safe_parts[-1]}"
        output = destination / work_id / Path(*safe_parts).with_suffix(".html")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)
        return {
            "work_id": work_id, "source_url": url,
            "snapshot_path": str(output.relative_to(ROOT)), "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(acquire, job): job for job in jobs}
        for index, future in enumerate(as_completed(futures), 1):
            try:
                records.append(future.result())
            except Exception as exc:
                work_id, url, _ = futures[future]
                errors.append({"work_id": work_id, "source_url": url, "error": str(exc)})
            if index % 20 == 0 or index == len(jobs):
                print(f"进度 {index}/{len(jobs)}，失败 {len(errors)}", flush=True)
            time.sleep(0.12)
    manifest = {
        "schema_version": "1.0", "captured_at": captured.isoformat(),
        "source": BASE, "expected_pages": len(jobs), "saved_pages": len(records),
        "errors": errors, "pages": sorted(records, key=lambda item: (item["work_id"], item["source_url"])),
    }
    (destination / "ACQUISITION-MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (CORPUS / "official-book-chapters-acquisition.latest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"完成：保存 {len(records)}/{len(jobs)} 页，失败 {len(errors)} 页", flush=True)


if __name__ == "__main__":
    main()
