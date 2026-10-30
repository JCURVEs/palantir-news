from pathlib import Path

from palantir_news.archive import archive_path, mark_highlights, rebuild_archives, render_article
from palantir_news.cli import apply_editorial_overrides, enrich_media, load_index, save_index, write_catalog


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


def test_bold_terms_do_not_replace_yellow_highlights_or_escape_rules():
    paragraph = "Security Forge는 검증합니다. Security Forge와 <보안>을 살핍니다."
    rendered = mark_highlights(
        paragraph, ["Security Forge는 검증합니다."], ["Security Forge", "<보안>"],
    )
    assert rendered == (
        "<mark>Security Forge는 검증합니다.</mark> "
        "<strong>Security Forge</strong>와 <strong>&lt;보안&gt;</strong>을 살핍니다."
    )


def test_archive_path_uses_year_month_and_day(tmp_path):
    assert archive_path(tmp_path, "2021-03-04T10:30:00Z") == tmp_path / "2021" / "03월" / "2021-03-04.md"


def test_rebuild_archives_writes_thread_auto_style(tmp_path):
    assert rebuild_archives([sample_article()], tmp_path) == 1
    content = (tmp_path / "2021" / "03월" / "2021-03-04.md").read_text(encoding="utf-8")
    assert "## [Palantir] 예시 글" in content
    assert "**요약:**" in content
    assert "**쉬운설명:**" in content
    assert "https://blog.palantir.com/example-abcdef123456" in content


def test_rebuild_archives_keeps_existing_collection_date(tmp_path):
    article = sample_article()
    path = archive_path(tmp_path, article["published_at"])
    path.parent.mkdir(parents=True)
    path.write_text(render_article(article, "2026-10-16"), encoding="utf-8")
    rebuild_archives([article], tmp_path)
    assert "**수집일:** 2026-10-16" in path.read_text(encoding="utf-8")


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


def test_media_backfill_preserves_existing_analysis(tmp_path, monkeypatch):
    article = sample_article()
    records = {article["id"]: article}
    original_analysis = article["analysis"].copy()
    monkeypatch.setattr("palantir_news.cli.build_session", lambda: object())
    monkeypatch.setattr("palantir_news.cli.fetch_article", lambda url, session: {
        "image_url": "https://miro.medium.com/cover.png",
        "inline_images": [{"url": "https://miro.medium.com/diagram.png", "caption": "", "section": "Method"}],
    })
    index_path = tmp_path / "articles.jsonl"
    assert enrich_media(records, index_path, 1, 1) == (1, 0)
    assert article["analysis"] == original_analysis
    assert load_index(index_path)[article["id"]]["inline_images"][0]["section"] == "Method"


def test_archive_includes_detailed_analysis_and_inline_images(tmp_path):
    article = sample_article()
    article["analysis"]["key_points"] = ["데이터 흐름을 구체적으로 설명합니다."]
    article["analysis"]["technical_detail"] = "기술 흐름의 세부 단계입니다."
    article["inline_images"] = [{"url": "https://miro.medium.com/diagram.png", "caption": "", "section": "Method"}]
    rebuild_archives([article], tmp_path)
    content = archive_path(tmp_path, article["published_at"]).read_text(encoding="utf-8")
    assert "**핵심 내용:**" in content
    assert "**기술 해설:**" in content
    assert "![Palantir 이미지 1](https://miro.medium.com/diagram.png)" in content


def test_archive_places_newsletter_image_in_matching_section(tmp_path):
    article = sample_article()
    article["inline_images"] = [{"url": "https://miro.medium.com/diagram.png", "caption": "", "section": "Method"}]
    article["analysis"]["newsletter"] = {
        "dek": "구체적인 부제입니다.",
        "lead": ["도입 첫 문단입니다.", "도입 둘째 문단입니다."],
        "sections": [{"heading": "계좌와 거래를 연결하는 방법", "source_heading": "Method", "paragraphs": ["구현 설명입니다."]}],
        "closing": "확인된 의미와 한계입니다.",
    }
    rebuild_archives([article], tmp_path)
    content = archive_path(tmp_path, article["published_at"]).read_text(encoding="utf-8")
    heading = content.index("### 계좌와 거래를 연결하는 방법")
    image = content.index("![Palantir 이미지 1](https://miro.medium.com/diagram.png)")
    closing = content.index("### 정리하면")
    assert heading < image < closing
    assert content.count("![Palantir 이미지 1]") == 1


def test_newsletter_archive_matches_site_content_without_top_highlights(tmp_path):
    article = sample_article()
    article["analysis"]["newsletter"] = {
        "title": "은행 데이터의 의미를 함께 쓰는 법",
        "dek": "업무 객체를 여러 앱에 연결하는 방법입니다.",
        "lead": ["은행에서 계좌를 정의합니다. 핵심 문장입니다.", "앱마다 같은 정의를 재사용합니다."],
        "highlights": ["핵심 문장입니다."],
        "sections": [{"heading": "계좌를 객체로 정의한다", "paragraphs": ["계좌와 거래를 연결합니다."]}],
        "closing": "실무 적용 범위는 확인이 필요합니다.",
    }
    content = render_article(article, "2026-10-29")
    assert "## 은행 데이터의 의미를 함께 쓰는 법" in content
    assert "<mark>핵심 문장입니다.</mark>" in content
    assert "### 계좌를 객체로 정의한다" in content
    assert "**요약:**" not in content
    assert "**쉬운설명:**" not in content
    assert "TOP HIGHLIGHTS" not in content


def test_linked_product_media_appears_beside_matching_section():
    article = sample_article()
    article["analysis"]["newsletter"] = {
        "dek": "제품 자료를 함께 보여주는 뉴스레터입니다.",
        "lead": ["도입 문단입니다.", "두 번째 문단입니다."],
        "sections": [{"heading": "Security Forge의 검토 과정", "paragraphs": ["구체적인 제품 설명입니다."]}],
        "closing": "확인된 범위만 정리합니다.",
    }
    article["related_media"] = [{
        "kind": "image", "url": "https://images.ctfassets.net/xrfr7uokpv1b/a/b/diagram.png",
        "caption": "Security Forge Graphic", "source_url": "https://www.palantir.com/security-forge/",
        "source_title": "Security Forge", "section": "Security Forge의 검토 과정",
    }]
    content = render_article(article, "2026-10-29")
    assert content.index("### Security Forge의 검토 과정") < content.index("![Security Forge Graphic]") < content.index("### 정리하면")
    assert "[Security Forge](https://www.palantir.com/security-forge/)" in content


def test_curated_editorial_is_stored_in_public_index(tmp_path):
    article = sample_article()
    article["analysis_version"] = 2
    directory = tmp_path / "editorials"
    directory.mkdir()
    (directory / f"{article['id']}.json").write_text(
        '{"title":"검수한 제목","sections":[{"heading":"구체적 내용"}]}', encoding="utf-8"
    )
    records = {article["id"]: article}
    assert apply_editorial_overrides(records, directory) == 1
    assert article["newsletter_source"] == "curated"
    assert article["analysis"]["newsletter"]["title"] == "검수한 제목"
    from palantir_news.cli import select_pending
    assert select_pending(records, 10) == []
    path = tmp_path / "articles.jsonl"
    save_index(path, records)
    assert load_index(path)[article["id"]]["analysis"]["newsletter"]["title"] == "검수한 제목"


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
        assert article["analysis_version"] >= 2
        assert len(analysis["summary"]) >= 300
        if analysis.get("newsletter"):
            assert analysis["newsletter"]["dek"] in archived
            assert analysis["newsletter"]["sections"][0]["heading"] in archived
        else:
            assert analysis["summary"] in archived
            assert analysis["easy_explainer"] in archived

    assert "고장 나기 전에 문제를 예측" not in records["4c644e36b6fc"]["analysis"]["easy_explainer"]
