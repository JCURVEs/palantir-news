from palantir_news.collector import (
    article_id_from_url,
    fetch_reader_text,
    normalize_url,
    parse_article_html,
    parse_medium_json,
    parse_sitemap,
)


def test_parse_sitemap_keeps_only_articles_and_deduplicates():
    xml = b"""<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://blog.palantir.com/tagged/ai</loc></url>
      <url><loc>https://blog.palantir.com/example-post-abcdef123456?source=x</loc></url>
      <url><loc>https://blog.palantir.com/example-post-abcdef123456</loc></url>
    </urlset>"""
    assert parse_sitemap(xml) == ["https://blog.palantir.com/example-post-abcdef123456"]


def test_parse_article_uses_json_ld_publication_date():
    html = """
    <html><head><script type="application/ld+json">
    {"@type":"SocialMediaPosting","identifier":"abcdef123456",
     "url":"https://blog.palantir.com/example-abcdef123456?source=x",
     "headline":"Example Post","description":"A useful post",
     "datePublished":"2021-03-04T10:30:00Z","dateModified":"2025-01-01T00:00:00Z",
     "author":{"name":"Palantir"},"image":["https://example.com/image.png"]}
    </script></head><body><article><h1>Example Post</h1><p>Article body.</p></article></body></html>
    """
    article = parse_article_html("https://blog.palantir.com/example-abcdef123456", html)
    assert article["published_at"] == "2021-03-04T10:30:00Z"
    assert article["modified_at"] == "2025-01-01T00:00:00Z"
    assert article["url"] == "https://blog.palantir.com/example-abcdef123456"
    assert "Article body" in article["body"]


def test_normalize_url_and_article_id():
    url = "https://blog.palantir.com/a-post-90b0a848dd3d/?source=rss#top"
    assert normalize_url(url) == "https://blog.palantir.com/a-post-90b0a848dd3d"
    assert article_id_from_url(url) == "90b0a848dd3d"


def test_parse_medium_json_uses_first_publication_timestamp():
    raw = "]) }while(1);</x>".replace(" ", "") + """{
      "payload":{"value":{
        "id":"abcdef123456","title":"API Article",
        "firstPublishedAt":1609459200000,"latestPublishedAt":1735689600000,
        "canonicalUrl":"https://blog.palantir.com/api-article-abcdef123456",
        "content":{"subtitle":"A subtitle","bodyModel":{"paragraphs":[{"text":"First"},{"text":"Second"}]}},
        "virtuals":{"previewImage":{"imageId":"1*example.jpeg"}}
      }}
    }"""
    article = parse_medium_json("https://blog.palantir.com/api-article-abcdef123456", raw)
    assert article["published_at"] == "2021-01-01T00:00:00Z"
    assert article["modified_at"] == "2025-01-01T00:00:00Z"
    assert article["description"] == "A subtitle"
    assert article["body"] == "First Second"


def test_reader_fallback_uses_canonical_source_url():
    class FakeResponse:
        text = "Palantir article content " * 20

        def raise_for_status(self):
            return None

    class FakeSession:
        def get(self, url, timeout):
            assert url == "https://r.jina.ai/https://blog.palantir.com/example-abcdef123456"
            assert timeout == 60
            return FakeResponse()

    text = fetch_reader_text(
        "https://blog.palantir.com/example-abcdef123456?source=rss",
        FakeSession(),
    )
    assert text.startswith("Palantir article content")
