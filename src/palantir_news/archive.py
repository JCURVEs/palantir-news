"""Write analyzed Palantir posts into year/month/day Markdown archives."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def archive_path(root: Path, published_at: str) -> Path:
    published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    return root / str(published.year) / f"{published.month:02d}월" / f"{published:%Y-%m-%d}.md"


def render_article(article: dict[str, Any], collected_on: str) -> str:
    analysis = article["analysis"]
    lines = [
        f"## [Palantir] {analysis['title_ko']}",
        "",
        f"**분야:** {analysis['category']} | **중요도:** {analysis['importance']}점",
        "",
        f"**원문발행일:** {article['published_at']}",
        "",
        f"**수집일:** {collected_on}",
        "",
        "**요약:**  ",
        str(analysis["summary"]),
        "",
        "**쉬운설명:**  ",
        str(analysis["easy_explainer"]),
        "",
        f"**출처:** {article['url']}",
        "",
        f"**원문제목:** {article['title']}",
        "",
    ]
    if article.get("image_url"):
        lines.extend([f"![Article Image]({article['image_url']})", ""])
    return "\n".join(lines)


def rebuild_archives(articles: Iterable[dict[str, Any]], root: Path) -> int:
    """Rebuild deterministic archives for every successfully analyzed article."""
    grouped: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    for article in articles:
        if article.get("analysis_status") != "complete" or not article.get("analysis"):
            continue
        grouped[archive_path(root, article["published_at"])].append(article)

    collected_on = date.today().isoformat()
    for path, items in grouped.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        day = path.stem
        content = [
            f"# Palantir News ({day})",
            "",
            "*Official Palantir Blog articles, summarized in Korean*",
            "",
            "---",
            "",
        ]
        for article in sorted(items, key=lambda item: item["published_at"]):
            content.append(render_article(article, collected_on))
        path.write_text("\n".join(content).rstrip() + "\n", encoding="utf-8")
    return sum(len(items) for items in grouped.values())

