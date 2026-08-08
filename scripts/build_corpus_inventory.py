#!/usr/bin/env python3
"""Build a derived, reviewable corpus inventory from immutable source snapshots."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "research" / "corpus"
CATALOG = CORPUS / "songy-course-catalog.latest.json"

ALBUM_CATEGORIES = {
    "李笑来的投资课": "财富课",
    "如何用人工智能成为学习专家": "AI课",
    "笑来分享合集": "AI课/跨主题",
    "《多语的真相》音频版": "英语课",
    "英文朗读材料": "英语课",
    "《财富的真相》视频版": "财富课",
    "《思考的真相》视频版": "思考课",
    "《思考的真相》音频版": "思考课",
    "《专注的真相》视频版": "专注课",
    "《学习的真相》视频版": "自学课",
    "《学习的真相》音频版": "自学课",
    "《家教的真相》视频版": "家庭教育课",
    "《家教的真相》音频版": "家庭教育课",
    "《教练的真相》视频版": "教练课",
    "《教练的真相》音频版": "教练课",
    "“家庭建设” 分享课": "家庭教育课",
    "家庭教育直播答疑": "家庭教育课",
    "李笑来的写作课": "写作课",
}

OFFICIAL_ONLINE_BOOKS = [
    "1000 小时", "如何自助——助人即助己", "定投改变命运", "区块链小白书",
    "定投——大佬的自我修养", "自学是门手艺", "比特币白皮书中英对照翻译",
    "韭菜的自我修养", "区块链投资原则", "坐享其成", "挤挤都会有的",
    "人人都能用英语", "把时间当作朋友", "我也有话要说",
    "TOEFL iBT 高分作文 (English)", "如何写好英文书面比较句",
]


def local_course_ids() -> set[int]:
    result = set()
    for path in (ROOT / "library").glob("*/courses/*/course.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8")).get("course_id")
            if value is not None:
                result.add(int(value))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return result


def main() -> None:
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    occurrences = []
    by_id = defaultdict(list)
    for community in payload.get("communities", []):
        for album in community.get("albums", []):
            album_title = album.get("title", "")
            for course in album.get("courses", []):
                row = {
                    "course_id": int(course["id"]),
                    "title": course.get("title", ""),
                    "album_id": album.get("id"),
                    "album_title": album_title,
                    "provisional_category": ALBUM_CATEGORIES.get(album_title, "待分类"),
                    "source_url": f"https://webapp.songy.info/#/courses/details?course_id={course['id']}",
                }
                occurrences.append(row)
                by_id[row["course_id"]].append(row)

    local_ids = local_course_ids()
    unique_courses = []
    for course_id, rows in sorted(by_id.items()):
        first = rows[0]
        unique_courses.append({
            "course_id": course_id,
            "title": first["title"],
            "albums": [{"id": row["album_id"], "title": row["album_title"]} for row in rows],
            "categories": sorted({row["provisional_category"] for row in rows}),
            "source_url": first["source_url"],
            "local_status": "已入库" if course_id in local_ids else "仅有目录",
        })

    categories = Counter(row["provisional_category"] for row in occurrences)
    github_inventory = CORPUS / "xiaolai-github-repositories.latest.json"
    github_candidates = CORPUS / "github-book-candidates.json"
    github = json.loads(github_inventory.read_text(encoding="utf-8")) if github_inventory.exists() else {"repositories": []}
    candidate_data = json.loads(github_candidates.read_text(encoding="utf-8")) if github_candidates.exists() else {"candidates": []}
    result = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_snapshot": str(CATALOG.relative_to(ROOT)),
        "counts": {
            "communities": len(payload.get("communities", [])),
            "albums": sum(len(item.get("albums", [])) for item in payload.get("communities", [])),
            "course_occurrences": len(occurrences),
            "unique_course_ids": len(unique_courses),
            "duplicate_course_ids": sum(1 for rows in by_id.values() if len(rows) > 1),
            "locally_archived_course_ids": len(local_ids & set(by_id)),
        },
        "category_occurrences": dict(sorted(categories.items())),
        "github": {
            "public_repositories": len(github.get("repositories", [])),
            "non_fork_repositories": sum(not repo.get("fork", False) for repo in github.get("repositories", [])),
            "fork_repositories": sum(bool(repo.get("fork", False)) for repo in github.get("repositories", [])),
            "book_like_candidates_pending_review": len(candidate_data.get("candidates", [])),
        },
        "courses": unique_courses,
        "book_baseline": [
            {
                "title": title,
                "source": "https://lixiaolai.com/books",
                "acquisition_status": "待从官网保存",
                "completeness": "待核验",
            }
            for title in OFFICIAL_ONLINE_BOOKS
        ],
    }
    (CORPUS / "master-inventory.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    counts = result["counts"]
    lines = [
        "# 李笑来资料盘点状态", "",
        f"生成时间：{result['generated_at']}", "",
        "## 课程", "",
        f"- 网站目录记录：{counts['course_occurrences']} 条",
        f"- 唯一课程编号：{counts['unique_course_ids']} 个",
        f"- 跨专辑重复编号：{counts['duplicate_course_ids']} 个",
        f"- 已在本机课程库入库：{counts['locally_archived_course_ids']} 个",
        "", "## 电子书", "",
        f"- 官网在线书目基线：{len(OFFICIAL_ONLINE_BOOKS)} 项",
        "- 用户没有另存电子书文件；正文将从个人网站和 GitHub 官方来源建立",
        f"- GitHub 公开仓库：{result['github']['public_repositories']} 个（原创/非 Fork {result['github']['non_fork_repositories']}，Fork {result['github']['fork_repositories']}）",
        f"- GitHub 书稿候选：{result['github']['book_like_candidates_pending_review']} 个，尚待逐仓库核验正文与作者身份",
        "", "## 当前结论", "",
        "权威来源边界已经确定。课程目录已经取回，但课程正文和公开书稿尚未全部保存；现在不能宣称全集完成。",
    ]
    (CORPUS / "STATUS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
