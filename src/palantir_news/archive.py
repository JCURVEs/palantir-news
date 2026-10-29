"""Write analyzed Palantir posts into year/month/day Markdown archives."""

from __future__ import annotations

import re
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
    ]
    newsletter = analysis.get("newsletter")
    used_images: set[int] = set()
    images = article.get("inline_images") or []
    if newsletter:
        lines.extend(["**뉴스레터 본문:**", "", f"*{newsletter['dek']}*", ""])
        for paragraph in newsletter["lead"]:
            lines.extend([paragraph, ""])
        if article.get("image_url"):
            lines.extend([f"![원문 대표 이미지]({article['image_url']})", ""])
        for section in newsletter["sections"]:
            lines.extend([f"### {section['heading']}", ""])
            for paragraph in section["paragraphs"]:
                lines.extend([paragraph, ""])
            for index, image in enumerate(images):
                if index in used_images or not section.get("source_heading") or image.get("section") != section["source_heading"]:
                    continue
                lines.extend([f"![원문 이미지 {index + 1}]({image['url']})", ""])
                if image.get("caption"):
                    lines.extend([image["caption"], ""])
                used_images.add(index)
        lines.extend(["### 정리하면", "", newsletter["closing"], ""])
    if analysis.get("key_points"):
        lines.extend(["**핵심 내용:**", ""])
        lines.extend(f"- {point}" for point in analysis["key_points"])
        lines.append("")
    if analysis.get("technical_detail"):
        lines.extend(["**기술 해설:**  ", str(analysis["technical_detail"]), ""])
    lines.extend([
        "**쉬운설명:**  ",
        str(analysis["easy_explainer"]),
        "",
        f"**출처:** {article['url']}",
        "",
        f"**원문제목:** {article['title']}",
        "",
    ])
    if article.get("image_url") and not newsletter:
        lines.extend([f"![원문 대표 이미지]({article['image_url']})", ""])
    remaining_images = [(index, image) for index, image in enumerate(images) if index not in used_images]
    if remaining_images:
        lines.extend(["**원문 속 이미지:**", ""])
        for index, image in remaining_images:
            lines.extend([f"![원문 이미지 {index + 1}]({image['url']})", ""])
            if image.get("caption"):
                lines.extend([image["caption"], ""])
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
        previous_dates = {}
        if path.exists():
            old_content = path.read_text(encoding="utf-8")
            previous_dates = {
                match.group("url"): match.group("date")
                for match in re.finditer(
                    r"\*\*수집일:\*\* (?P<date>\d{4}-\d{2}-\d{2}).*?\*\*출처:\*\* (?P<url>https?://\S+)",
                    old_content,
                    re.DOTALL,
                )
            }
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
            content.append(render_article(article, previous_dates.get(article["url"], collected_on)))
        path.write_text("\n".join(content).rstrip() + "\n", encoding="utf-8")
    return sum(len(items) for items in grouped.values())

