from pathlib import Path

from palantir_news.archive import archive_path, rebuild_archives
from palantir_news.cli import load_index, save_index, write_catalog


def sample_article():
    return {
        "id": "abcdef123456",
        "url": "https://blog.palantir.com/example-abcdef123456",
        "title": "Example Post",
        "published_at": "2021-03-04T10:30:00Z",
        "image_url": "https://example.com/image.png",
        "analysis_status": "complete",
        "analysis": {
            "title_ko": "예시 글",
            "summary": "핵심 내용을 설명합니다.",
            "easy_explainer": "쉽게 설명한 내용입니다.",
            "category": "엔지니어링",
            "importance": 7,
        },
    }


def test_archive_path_uses_year_month_and_day(tmp_path):
    assert archive_path(tmp_path, "2021-03-04T10:30:00Z") == tmp_path / "2021" / "03월" / "2021-03-04.md"


def test_rebuild_archives_writes_thread_auto_style(tmp_path):
    assert rebuild_archives([sample_article()], tmp_path) == 1
    content = (tmp_path / "2021" / "03월" / "2021-03-04.md").read_text(encoding="utf-8")
    assert "## [Palantir] 예시 글" in content
    assert "**요약:**" in content
    assert "**쉬운설명:**" in content
    assert "https://blog.palantir.com/example-abcdef123456" in content


def test_write_catalog_groups_articles_by_year(tmp_path):
    article = sample_article()
    path = tmp_path / "CATALOG.md"
    write_catalog(path, {article["id"]: article})
    content = path.read_text(encoding="utf-8")
    assert "Official posts indexed: **1**" in content
    assert "## 2021 (1)" in content
    assert "[Example Post](https://blog.palantir.com/example-abcdef123456)" in content


def test_index_does_not_persist_full_article_body(tmp_path):
    article = sample_article()
    article["body"] = "Copyrighted source text"
    path = tmp_path / "articles.jsonl"
    save_index(path, {article["id"]: article})
    assert "Copyrighted source text" not in path.read_text(encoding="utf-8")
    assert "body" not in load_index(path)[article["id"]]


def test_reviewed_articles_match_their_archives():
    root = Path(__file__).resolve().parents[1]
    records = load_index(root / "data" / "articles.jsonl")
    reviewed_ids = (
        "f419faa400b3", "4c644e36b6fc", "b4024897a766",
        "399bd1a5971b", "6d451beea022", "8331676a2163",
    )

    for article_id in reviewed_ids:
        article = records[article_id]
        analysis = article["analysis"]
        archived = archive_path(root / "archive", article["published_at"]).read_text(encoding="utf-8")
        assert article["analysis_version"] == 2
        assert len(analysis["summary"]) >= 300
        assert analysis["summary"] in archived
        assert analysis["easy_explainer"] in archived

    assert "고장 나기 전에 문제를 예측" not in records["4c644e36b6fc"]["analysis"]["easy_explainer"]
