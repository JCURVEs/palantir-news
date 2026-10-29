try:
    import httpx2 as httpx
except ImportError:
    import httpx
from datetime import datetime, timezone

from openai import RateLimitError

from palantir_news import cli


def article(article_id, published_at, status="pending"):
    item = {
        "id": article_id,
        "title": article_id,
        "url": f"https://blog.palantir.com/{article_id}",
        "published_at": published_at,
        "analysis_status": status,
    }
    if status == "complete":
        item["analysis_version"] = cli.ANALYSIS_VERSION
    return item


def rate_limit_error(retry_after):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(429, headers={"retry-after": retry_after}, request=request)
    return RateLimitError("Rate limit reached", response=response, body=None)


def test_select_pending_prioritizes_new_posts():
    records = {
        "old-failure": article("old-failure", "2020-01-01T00:00:00Z", "failed"),
        "new-pending": article("new-pending", "2026-01-01T00:00:00Z"),
        "done": article("done", "2021-01-01T00:00:00Z", "complete"),
    }
    assert [item["id"] for item in cli.select_pending(records, 1)] == ["new-pending"]
    assert [item["id"] for item in cli.select_pending(records, 5)] == ["new-pending", "old-failure"]


def test_select_pending_revisits_old_summaries_after_new_posts():
    old_complete = article("old-complete", "2020-01-01T00:00:00Z", "complete")
    old_complete.pop("analysis_version")
    old_complete["analysis"] = {"summary": "구체적인 사실과 맥락을 담은 기존 요약입니다. " * 10}
    records = {
        "old-complete": old_complete,
        "new-pending": article("new-pending", "2026-01-01T00:00:00Z"),
    }

    assert [item["id"] for item in cli.select_pending(records, 5)] == ["new-pending", "old-complete"]


def test_select_pending_prioritizes_recent_and_thin_published_summaries():
    recent = article("recent", datetime.now(timezone.utc).isoformat())
    thin = article("thin", "2021-01-01T00:00:00Z", "complete")
    thin.pop("analysis_version")
    thin["analysis"] = {"summary": "원문 본문은 보안 검증 페이지로 인해 확인되지 않았습니다."}
    older = article("older", "2022-01-01T00:00:00Z")
    records = {item["id"]: item for item in (older, thin, recent)}

    assert [item["id"] for item in cli.select_pending(records, 3)] == ["recent", "thin", "older"]


def test_select_pending_works_from_newest_historical_post():
    records = {
        "2024": article("2024", "2024-05-01T00:00:00Z"),
        "2026": article("2026", "2026-05-01T00:00:00Z"),
        "2025": article("2025", "2025-05-01T00:00:00Z"),
    }
    assert [item["id"] for item in cli.select_pending(records, 3)] == ["2026", "2025", "2024"]


def test_failed_source_does_not_starve_newsletter_refresh():
    reviewed = article("reviewed", "2024-01-01T00:00:00Z", "complete")
    reviewed["analysis_version"] = cli.ANALYSIS_VERSION - 1
    reviewed["analysis"] = {"summary": "구체적 근거를 담은 기존 요약입니다. " * 12}
    failed = article("failed", "2026-01-01T00:00:00Z", "failed")
    records = {item["id"]: item for item in (failed, reviewed)}
    assert [item["id"] for item in cli.select_pending(records, 2)] == ["reviewed", "failed"]


def test_meta_worded_summary_is_reviewed_before_other_legacy_articles():
    meta = article("meta", "2021-01-01T00:00:00Z", "complete")
    meta["analysis_version"] = cli.ANALYSIS_VERSION - 1
    meta["analysis"] = {"summary": "원문은 기술 내용을 설명합니다. " * 12}
    ordinary = article("ordinary", "2024-01-01T00:00:00Z", "complete")
    ordinary["analysis_version"] = cli.ANALYSIS_VERSION - 1
    ordinary["analysis"] = {"summary": "Palantir는 기술 내용을 설명합니다. " * 12}
    assert [item["id"] for item in cli.select_pending({"meta": meta, "ordinary": ordinary}, 2)] == ["meta", "ordinary"]


def test_rate_limit_retry_waits_then_succeeds(monkeypatch):
    calls = []
    waits = []

    def summarize(_article, api_key):
        calls.append(api_key)
        if len(calls) == 1:
            raise rate_limit_error("2")
        return {"summary": "done"}

    monkeypatch.setattr(cli, "summarize", summarize)
    monkeypatch.setattr(cli.time, "sleep", waits.append)
    assert cli.summarize_with_rate_limit_retry({}, "test-key") == {"summary": "done"}
    assert calls == ["test-key", "test-key"]
    assert waits == [3.0]


def test_rate_limit_stops_batch_without_marking_failure(monkeypatch, tmp_path):
    first = article("first", "2020-01-01T00:00:00Z")
    second = article("second", "2020-01-02T00:00:00Z")
    records = {item["id"]: item for item in (first, second)}
    fetched = []

    def fetch(_url, _session):
        fetched.append(_url)
        return {"body": "Source text " * 20}

    def summarize(_article, _api_key):
        raise rate_limit_error("120")

    monkeypatch.setattr(cli, "fetch_article", fetch)
    monkeypatch.setattr(cli, "build_session", lambda: None)
    monkeypatch.setattr(cli, "summarize_with_rate_limit_retry", summarize)
    index_path = tmp_path / "articles.jsonl"
    cli.analyze_pending([first, second], records, index_path, "test-key", 0)

    assert fetched == [first["url"]]
    assert first["analysis_status"] == "pending"
    assert second["analysis_status"] == "pending"
    assert "body" not in first
    assert cli.load_index(index_path)["first"]["analysis_status"] == "pending"


def test_failed_refresh_keeps_the_published_summary(monkeypatch, tmp_path):
    existing = article("existing", "2020-01-01T00:00:00Z", "complete")
    existing["analysis_version"] = 1
    existing["analysis"] = {"summary": "Reviewed original summary"}
    existing["body"] = "Source text " * 20

    def fail(_article, _api_key):
        raise ValueError("Incomplete analysis response")

    monkeypatch.setattr(cli, "summarize_with_rate_limit_retry", fail)
    index_path = tmp_path / "articles.jsonl"
    cli.analyze_pending([existing], {existing["id"]: existing}, index_path, "test-key", 0)

    saved = cli.load_index(index_path)["existing"]
    assert saved["analysis_status"] == "complete"
    assert saved["analysis"]["summary"] == "Reviewed original summary"
    assert saved["analysis_version"] == 1
    assert "body" not in saved


def test_analyze_pending_passes_source_headings_and_images(monkeypatch, tmp_path):
    item = article("example", "2026-01-01T00:00:00Z")
    records = {item["id"]: item}
    monkeypatch.setattr(cli, "build_session", lambda: None)
    monkeypatch.setattr(cli, "fetch_article", lambda url, session: {
        "body": "Source text " * 30,
        "source_headings": ["Implementation"],
        "inline_images": [{"url": "https://miro.medium.com/diagram.png", "section": "Implementation"}],
    })

    def summarize(current, key):
        assert current["source_headings"] == ["Implementation"]
        return {"summary": "Grounded explanation"}

    monkeypatch.setattr(cli, "summarize_with_rate_limit_retry", summarize)
    path = tmp_path / "articles.jsonl"
    cli.analyze_pending([item], records, path, "test-key", 0)
    saved = cli.load_index(path)["example"]
    assert saved["source_headings"] == ["Implementation"]
    assert saved["inline_images"][0]["section"] == "Implementation"
