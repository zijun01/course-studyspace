#!/usr/bin/env python3
"""Acquire immutable shallow snapshots of user-approved GitHub book repositories."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "research" / "corpus"
RAW_ROOT = CORPUS / "raw" / "books" / "github"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    scope = json.loads((CORPUS / "teaching-grammar-scope.json").read_text(encoding="utf-8"))
    captured_at = datetime.now(timezone.utc)
    stamp = captured_at.strftime("%Y%m%dT%H%M%SZ")
    snapshot_root = RAW_ROOT / stamp
    snapshot_root.mkdir(parents=True, exist_ok=False)
    records = []
    for index, name in enumerate(scope["included_github_repositories"], 1):
        print(f"[{index}/{scope['included_count']}] 获取 {name}", flush=True)
        destination = snapshot_root / name
        subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", f"https://github.com/xiaolai/{name}.git", str(destination)],
            check=True,
        )
        commit = subprocess.run(
            ["git", "-C", str(destination), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        files = []
        for path in sorted(destination.rglob("*")):
            if not path.is_file() or ".git" in path.parts:
                continue
            files.append({
                "path": str(path.relative_to(destination)),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            })
        records.append({
            "repository": name,
            "source_url": f"https://github.com/xiaolai/{name}",
            "commit": commit,
            "snapshot_path": str(destination.relative_to(ROOT)),
            "file_count": len(files),
            "total_bytes": sum(item["bytes"] for item in files),
            "files": files,
        })
    manifest = {
        "schema_version": "1.0",
        "captured_at": captured_at.isoformat(),
        "source": "github.com/xiaolai",
        "repository_count": len(records),
        "snapshot_root": str(snapshot_root.relative_to(ROOT)),
        "repositories": records,
    }
    (snapshot_root / "ACQUISITION-MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (CORPUS / "github-books-acquisition.latest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"完成：{len(records)} 个仓库，{sum(item['file_count'] for item in records)} 个文件", flush=True)


if __name__ == "__main__":
    main()
