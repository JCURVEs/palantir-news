"""Command-line entry point for historical and incremental Palantir news collection."""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .archive import rebuild_archives
from .collector import article_id_from_url, build_session, fetch_article, fetch_sitemap, publication_year
from .summarizer import summarize


def load_index(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            article = json.loads(line)
            records[article["id"]] = article
    return records


def save_index(path: Path, records: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records.values(), key=lambda item: (item["published_at"], item["id"]))
    public_records = []
    for item in ordered:
        public_item = dict(item)
        public_item.pop("body", None)
        public_records.append(public_item)
    text = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in public_records)
    path.write_text(text, encoding="utf-8")


def write_catalog(path: Path, records: dict[str, dict[str, Any]]) -> None:
    """Write a browsable, year-grouped index without requiring AI analysis."""
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for article in records.values():
        grouped[publication_year(article)].append(article)

    lines = [
        "# Palantir Blog Catalog",
        "",
        f"Official posts indexed: **{len(records)}**",
        "",
    ]
    for year in sorted(grouped, reverse=True):
        items = sorted(grouped[year], key=lambda item: item["published_at"], reverse=True)
        lines.extend([f"## {year} ({len(items)})", ""])
        for article in items:
            day = article["published_at"][:10]
            lines.append(f"- {day} [{article['title']}]({article['url']})")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def collect_missing(urls: list[str], existing: dict[str, dict[str, Any]], workers: int) -> tuple[list[dict[str, Any]], list[str]]:
    missing = [url for url in urls if article_id_from_url(url) not in existing]
    collected: list[dict[str, Any]] = []
    failures: list[str] = []

    def collect(url: str) -> dict[str, Any]:
        return fetch_article(url, build_session())

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(collect, url): url for url in missing}
        for number, future in enumerate(as_completed(futures), start=1):
            url = futures[future]
            try:
                collected.append(future.result())
            except Exception as exc:
                failures.append(f"{url}\t{type(exc).__name__}: {exc}")
            if number % 25 == 0 or number == len(missing):
                print(f"Collected {number}/{len(missing)} candidate pages")
    return collected, failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Archive the official Palantir Blog in Korean")
    parser.add_argument("--start-year", type=int, default=2020)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--analysis-limit", type=int, default=0, help="Maximum pending posts to analyze; 0 means all")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="Refetch already indexed article pages")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path.cwd()
    index_path = root / "data" / "articles.jsonl"
    failure_path = root / "data" / "collection_failures.txt"
    ignored_path = root / "data" / "out_of_scope_urls.txt"
    records = {} if args.refresh else load_index(index_path)
    ignored_urls = set()
    if ignored_path.exists() and not args.refresh:
        ignored_urls = {line.strip() for line in ignored_path.read_text(encoding="utf-8").splitlines() if line.strip()}

    urls = [url for url in fetch_sitemap() if url not in ignored_urls]
    collected, failures = collect_missing(urls, records, max(1, min(args.workers, 8)))
    for article in collected:
        year = publication_year(article)
        if args.start_year <= year <= args.end_year:
            records[article["id"]] = article
        else:
            ignored_urls.add(article["url"])

    records = {
        key: article
        for key, article in records.items()
        if args.start_year <= publication_year(article) <= args.end_year
    }
    save_index(index_path, records)
    ignored_path.write_text("\n".join(sorted(ignored_urls)) + ("\n" if ignored_urls else ""), encoding="utf-8")
    failure_path.write_text("\n".join(failures) + ("\n" if failures else ""), encoding="utf-8")
    write_catalog(root / "CATALOG.md", records)

    pending = [item for item in records.values() if item.get("analysis_status") != "complete"]
    pending.sort(key=lambda item: item["published_at"])
    if args.analysis_limit > 0:
        pending = pending[: args.analysis_limit]

    key = os.getenv("GROQ_API_KEY")
    if not args.collect_only and key:
        for number, article in enumerate(pending, start=1):
            try:
                if not article.get("body"):
                    article["body"] = fetch_article(article["url"], build_session())["body"]
                article["analysis"] = summarize(article, api_key=key)
                article["analysis_status"] = "complete"
                article.pop("analysis_error", None)
            except Exception as exc:
                article["analysis_status"] = "failed"
                article["analysis_error"] = f"{type(exc).__name__}: {exc}"
            article.pop("body", None)
            save_index(index_path, records)
            print(f"Analyzed {number}/{len(pending)}: {article['title']}")
    elif not args.collect_only and pending:
        print(f"GROQ_API_KEY is not configured; {len(pending)} articles remain pending")

    archived = rebuild_archives(records.values(), root / "archive")
    complete = sum(item.get("analysis_status") == "complete" for item in records.values())
    print(
        f"Indexed {len(records)} posts from {args.start_year}-{args.end_year}; "
        f"analyzed {complete}; archived {archived}; fetch failures {len(failures)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
