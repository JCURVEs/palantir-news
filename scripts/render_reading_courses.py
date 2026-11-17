"""Render the curated reading order from the course and article indexes."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE = "https://palantir-news-jcurves.ysinter.chatgpt.site"


def main() -> None:
    courses = json.loads((ROOT / "data/reading_courses.json").read_text(encoding="utf-8"))
    articles = {
        article["id"]: article
        for article in (
            json.loads(line)
            for line in (ROOT / "data/articles.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    lines = [
        "# 직무별 읽기", "",
        "Palantir 공식 직무 설명과 공개 글을 바탕으로 편집한 독립 읽기 코스입니다. 직무 교육이나 채용 자료는 아닙니다.", "",
        courses["intro"], "",
    ]
    for track in courses["tracks"]:
        lines.extend([
            f"- [{track['team']} / {track['role']}]({SITE}/course.html?track={track['id']})",
        ])
    lines.append("")

    def add_steps(title: str, steps: list[dict]) -> None:
        lines.extend([f"## {title}", ""])
        for number, step in enumerate(steps, 1):
            article = articles[step["article_id"]]
            if article["analysis_status"] != "complete" or not (article["analysis"] or {}).get("newsletter"):
                raise ValueError(f"Course article is not newsletter-ready: {article['id']}")
            title_ko = (
                article["analysis"]["newsletter"].get("title")
                or article["analysis"].get("title_ko")
                or article["title"]
            ).replace("[", "\\[").replace("]", "\\]")
            lines.extend([
                f"{number}. [{title_ko}]({SITE}/article.html?id={article['id']})",
                f"   {step['why']} ([Palantir 발표]({article['url']}), {str(article['published_at'])[:10]})",
            ])
        lines.append("")

    add_steps(courses["foundation"]["title"], courses["foundation"]["steps"])
    for track in courses["tracks"]:
        add_steps(f"{track['team']} / {track['role']}: {track['title']}", track["steps"])
    (ROOT / "READING_COURSES.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
