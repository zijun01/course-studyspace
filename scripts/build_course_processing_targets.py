#!/usr/bin/env python3
"""Build the exact bulk transcription target list from the user-approved scope."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "research" / "corpus"
ALBUM_CATEGORIES = {
    23: "财富课", 22: "AI课", 6: "AI课", 18: "英语课", 1: "财富课",
    7: "思考课", 16: "专注课", 11: "自学课", 13: "家庭教育课",
    9: "教练课", 4: "家庭教育课", 15: "家庭教育课", 3: "写作课", 2: "财富课",
}


def main() -> None:
    catalog = json.loads((CORPUS / "songy-course-catalog.latest.json").read_text(encoding="utf-8"))
    scope = json.loads((CORPUS / "course-album-scope.json").read_text(encoding="utf-8"))
    included_album_ids = {int(item["album_id"]): item["title"] for item in scope["included"]}
    partial = scope["partially_included"][0]
    targets = []
    for community in catalog["communities"]:
        for album in community["albums"]:
            album_id = int(album["id"])
            if album_id not in included_album_ids and album_id != int(partial["album_id"]):
                continue
            for course in album["courses"]:
                course_id = int(course["id"])
                if album_id == int(partial["album_id"]) and course_id != int(partial["anchor_course_id"]):
                    created_at = str(course.get("created_at") or "")
                    if created_at < partial["anchor_created_at"]:
                        continue
                targets.append({
                    "course_id": course_id,
                    "title": course.get("title", ""),
                    "album_id": album_id,
                    "album_title": album.get("title", ""),
                    "course_category": ALBUM_CATEGORIES[album_id],
                    "source_url": f"https://webapp.songy.info/#/courses/details?course_id={course_id}",
                })
    unique = {item["course_id"]: item for item in targets}
    result = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selection_rule": "13 complete albums plus album 6 from course 792 onward",
        "target_count": len(unique),
        "targets": sorted(unique.values(), key=lambda item: (item["album_id"], item["course_id"])),
    }
    (CORPUS / "course-processing-targets.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"课程批处理目标：{len(unique)} 节")


if __name__ == "__main__":
    main()
