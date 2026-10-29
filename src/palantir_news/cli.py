"""Command-line entry point for historical and incremental Palantir news collection."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from openai import RateLimitError

from .archive import rebuild_archives
from .collector import (
    article_id_from_url,
    build_session,
    fetch_article,
    fetch_reader_text,
    fetch_sitemap,
    has_readable_body,
    publication_year,
)
from .summarizer import ANALYSIS_VERSION, summarize


REVIEW_PHRASES = (
    "CAPTCHA",
    "보안 인증 페이지",
    "보안 검증 페이지",
    "접근이 차단",
    "원문 본문은",
    "원문",
)


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


def apply_editorial_overrides(records: dict[str, dict[str, Any]], directory: Path) -> int:
    """Keep manually reviewed newsletters in the same index as generated ones."""
    applied = 0
    for path in sorted(directory.glob("*.json")):
        article = records.get(path.stem)
        if article is None:
            raise ValueError(f"Editorial has no indexed article: {path.name}")
        if article.get("analysis_status") != "complete" or not article.get("analysis"):
            raise ValueError(f"Editorial article has no completed analysis: {path.name}")
        newsletter = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(newsletter, dict) or not newsletter.get("title") or not newsletter.get("sections"):
            raise ValueError(f"Editorial is incomplete: {path.name}")
        article["analysis"]["newsletter"] = newsletter
        article["newsletter_source"] = "curated"
        applied += 1
    return applied


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


def enrich_media(records: dict[str, dict[str, Any]], index_path: Path, limit: int, workers: int) -> tuple[int, int]:
    """Backfill article images without changing its approved Korean analysis."""
    candidates = [item for item in records.values() if not item.get("media_checked_at")]
    candidates.sort(key=lambda item: item["published_at"], reverse=True)
    if limit > 0:
        candidates = candidates[:limit]
    enriched = 0
    failures = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_article, item["url"], build_session()): item for item in candidates}
        for number, future in enumerate(as_completed(futures), start=1):
            item = futures[future]
            try:
                fetched = future.result()
                item["inline_images"] = fetched.get("inline_images", [])
                item["source_headings"] = fetched.get("source_headings", [])
                if fetched.get("image_url") and not item.get("image_url"):
                    item["image_url"] = fetched["image_url"]
                item["media_checked_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                enriched += 1
            except Exception as exc:
                failures += 1
                print(f"::warning::Image extraction failed for {item['url']}: {type(exc).__name__}: {exc}")
            if number % 25 == 0 or number == len(candidates):
                save_index(index_path, records)
                print(f"Checked article images {number}/{len(candidates)}")
    return enriched, failures


def select_pending(records: dict[str, dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    pending = [
        item for item in records.values()
        if item.get("newsletter_source") != "curated"
        and (item.get("analysis_status") != "complete"
             or item.get("analysis_version", 0) < ANALYSIS_VERSION)
    ]
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    def priority(item: dict[str, Any]) -> tuple[int, float]:
        status = item.get("analysis_status")
        published = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
        newest_first = -published.timestamp()
        if status != "complete":
            if status != "failed" and published >= recent_cutoff:
                return (0, newest_first)
            return (2 if status != "failed" else 4, newest_first)
        if item.get("analysis_error"):
            return (5, newest_first)
        summary = str((item.get("analysis") or {}).get("summary", ""))
        needs_review = len(summary) < 180 or any(phrase in summary for phrase in REVIEW_PHRASES)
        return (1 if needs_review else 3, newest_first)

    pending.sort(key=priority)
    return pending[:limit] if limit > 0 else pending


def summarize_with_rate_limit_retry(article: dict[str, Any], api_key: str) -> dict[str, Any]:
    for attempt in range(3):
        try:
            return summarize(article, api_key=api_key)
        except RateLimitError as exc:
            if attempt == 2:
                raise
            try:
                wait_seconds = float(exc.response.headers.get("retry-after", ""))
            except (TypeError, ValueError):
                wait_seconds = 30.0 * (attempt + 1)
            if wait_seconds > 90:
                raise
            time.sleep(max(1.0, wait_seconds) + 1.0)
    raise RuntimeError("Unreachable rate-limit retry state")


def analyze_pending(
    pending: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    index_path: Path,
    api_key: str,
    pause_seconds: float,
) -> None:
    for number, article in enumerate(pending, start=1):
        if number > 1 and pause_seconds > 0:
            time.sleep(pause_seconds)
        rate_limited = False
        was_complete = article.get("analysis_status") == "complete"
        try:
            if not article.get("body"):
                try:
                    fetched = fetch_article(article["url"], build_session())
                    article["body"] = fetched["body"]
                    article["source_headings"] = fetched.get("source_headings", [])
                    if not article.get("inline_images"):
                        article["inline_images"] = fetched.get("inline_images", [])
                except Exception:
                    article["body"] = fetch_reader_text(article["url"], build_session())
            if not has_readable_body(article["body"]):
                article["body"] = fetch_reader_text(article["url"], build_session())
            article["analysis"] = summarize_with_rate_limit_retry(article, api_key)
            article["analysis_version"] = ANALYSIS_VERSION
            article["analysis_status"] = "complete"
            article.pop("analysis_error", None)
        except RateLimitError:
            if not was_complete:
                article["analysis_status"] = "pending"
            article.pop("analysis_error", None)
            rate_limited = True
        except Exception as exc:
            if not was_complete:
                article["analysis_status"] = "failed"
            article["analysis_error"] = f"{type(exc).__name__}: {exc}"
            print(f"::warning::Analysis failed for {article['id']}: {article['analysis_error']}")
        finally:
            article.pop("body", None)
            save_index(index_path, records)
        if rate_limited:
            print(f"::warning::Groq rate limit reached after {number - 1} articles; remaining posts will retry on the next run")
            break
        print(f"Analyzed {number}/{len(pending)} ({article['analysis_status']}): {article['title']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Archive the official Palantir Blog in Korean")
    parser.add_argument("--start-year", type=int, default=2020)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--analysis-limit", type=int, default=0, help="Maximum pending posts to analyze; 0 means all")
    parser.add_argument("--analysis-pause-seconds", type=float, default=0, help="Pause between analysis requests")
    parser.add_argument("--article-id", help="Analyze one existing article ID, including a previously completed post")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--media-limit", type=int, default=0, help="Backfill images for this many existing posts; 0 disables backfill")
    parser.add_argument("--media-only", action="store_true", help="Skip sitemap collection and AI analysis while backfilling images")
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

    workers = max(1, min(args.workers, 8))
    urls = [] if args.media_only else [url for url in fetch_sitemap() if url not in ignored_urls]
    collected, failures = collect_missing(urls, records, workers)
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
    apply_editorial_overrides(records, root / "data" / "editorials")
    save_index(index_path, records)
    if args.media_limit > 0:
        enriched, media_failures = enrich_media(records, index_path, args.media_limit, workers)
        print(f"Article images checked: {enriched}; failures: {media_failures}")
    ignored_path.write_text("\n".join(sorted(ignored_urls)) + ("\n" if ignored_urls else ""), encoding="utf-8")
    if not args.media_only:
        failure_path.write_text("\n".join(failures) + ("\n" if failures else ""), encoding="utf-8")
    write_catalog(root / "CATALOG.md", records)

    if args.article_id:
        if args.article_id not in records:
            raise SystemExit(f"Article not found in index: {args.article_id}")
        pending = [records[args.article_id]]
    else:
        pending = select_pending(records, args.analysis_limit)

    key = os.getenv("GROQ_API_KEY")
    if not args.collect_only and not args.media_only and key:
        analyze_pending(pending, records, index_path, key, args.analysis_pause_seconds)
    elif not args.collect_only and not args.media_only and pending:
        print(f"GROQ_API_KEY is not configured; {len(pending)} articles remain pending")

    apply_editorial_overrides(records, root / "data" / "editorials")
    save_index(index_path, records)
    archived = rebuild_archives(records.values(), root / "archive")
    complete = sum(item.get("analysis_status") == "complete" for item in records.values())
    print(
        f"Indexed {len(records)} posts from {args.start_year}-{args.end_year}; "
        f"analyzed {complete}; archived {archived}; fetch failures {len(failures)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
