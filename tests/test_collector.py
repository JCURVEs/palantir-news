from palantir_news.collector import (
    article_id_from_url,
    fetch_article,
    fetch_feed_bodies,
    fetch_reader_text,
    has_readable_body,
    normalize_url,
    parse_article_html,
    parse_publication_feed,
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


def test_publication_feed_recovers_new_post_when_article_page_is_blocked():
    xml = b'''<rss xmlns:content="http://purl.org/rss/1.0/modules/content/">
    <channel><item><title>New official post</title>
    <link>https://blog.palantir.com/new-post-abcdef123456?source=rss</link>
    <pubDate>Fri, 30 Oct 2026 02:00:00 GMT</pubDate>
    <content:encoded><![CDATA[<h2>How it works</h2><figure><img src="https://cdn-images-1.medium.com/max/1024/1*diagram.png"></figure>
    <p>Palantir explains the mechanism. ''' + b"Detail " * 45 + b'''</p>]]></content:encoded>
    </item><item><title>Not official</title><link>https://evil.example/post-123456abcdef</link>
    <pubDate>Fri, 30 Oct 2026 02:00:00 GMT</pubDate></item></channel></rss>'''
    articles = parse_publication_feed(xml)
    assert len(articles) == 1
    assert articles[0]["id"] == "abcdef123456"
    assert articles[0]["published_at"] == "2026-10-30T02:00:00Z"
    assert articles[0]["source_headings"] == ["How it works"]
    assert articles[0]["image_url"].startswith("https://miro.medium.com/")
    assert articles[0]["analysis_status"] == "pending"


def test_official_feed_supplies_recent_article_body_and_headings():
    class FakeResponse:
        content = b'''<rss xmlns:content="http://purl.org/rss/1.0/modules/content/">
        <channel><item><link>https://blog.palantir.com/example-abcdef123456?source=rss</link>
        <content:encoded><![CDATA[<h2>What changed</h2><p>Detailed Palantir explanation. ''' + b"A" * 220 + b'''</p>]]></content:encoded>
        </item></channel></rss>'''

        def raise_for_status(self):
            pass

    class FakeSession:
        def get(self, url, timeout):
            assert url == "https://blog.palantir.com/feed"
            assert timeout == 30
            return FakeResponse()

    result = fetch_feed_bodies(FakeSession())
    assert result["abcdef123456"]["source_headings"] == ["What changed"]
    assert "Detailed Palantir explanation." in result["abcdef123456"]["body"]


def test_article_collects_only_official_product_links():
    html = '''<script type="application/ld+json">{
      "headline":"Security", "datePublished":"2026-01-01T00:00:00Z"
    }</script><article><h2>Product</h2><p><a href="https://www.palantir.com/security-forge/?utm=x">Security Forge</a>
    <a href="https://evil.example/product">Other product</a></p></article>'''
    article = parse_article_html("https://blog.palantir.com/security-abcdef123456", html)
    assert article["related_links"] == [{
        "url": "https://www.palantir.com/security-forge/", "label": "Security Forge", "section": "Product",
    }]


def test_tag_feed_adds_older_articles_without_replacing_publication_entry():
    class FakeResponse:
        def __init__(self, article_id):
            self.content = (f'<rss xmlns:content="http://purl.org/rss/1.0/modules/content/">'
                            f'<channel><item><link>https://blog.palantir.com/post-{article_id}</link>'
                            f'<content:encoded><![CDATA[<p>{"Details " * 40}</p>]]></content:encoded>'
                            '</item></channel></rss>').encode()

        def raise_for_status(self):
            pass

    class FakeSession:
        def get(self, url, timeout):
            assert timeout == 30
            if url.endswith("/feed"):
                return FakeResponse("abcdef123456")
            assert url.endswith("/feed/tagged/data%20platform")
            return FakeResponse("123456abcdef")

    bodies = fetch_feed_bodies(FakeSession(), ["data platform", "data platform"])
    assert set(bodies) == {"abcdef123456", "123456abcdef"}


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
    assert article["body"] == "First\n\nSecond"


def test_parse_medium_json_collects_distinct_body_images_with_section():
    raw = "</x>" + """{"payload":{"value":{
      "id":"abcdef123456","title":"Image Article",
      "firstPublishedAt":1609459200000,"latestPublishedAt":1609459200000,
      "content":{"bodyModel":{"paragraphs":[
        {"type":4,"metadata":{"id":"1*cover.png"}},
        {"type":3,"text":"How it works"},
        {"type":4,"metadata":{"id":"1*diagram.png"}},
        {"type":4,"metadata":{"id":"1*diagram.png"}},
        {"type":4,"metadata":{"id":"https://evil.example/image"}}
      ]}},"virtuals":{"previewImage":{"imageId":"1*cover.png"}}
    }}}"""
    article = parse_medium_json("https://blog.palantir.com/image-abcdef123456", raw)
    assert article["inline_images"] == [{
        "url": "https://miro.medium.com/v2/resize:fit:1200/1*diagram.png",
        "caption": "",
        "section": "How it works",
    }]
    assert article["source_headings"] == ["How it works"]


def test_parse_html_collects_figure_and_caption():
    html = """<script type="application/ld+json">{
      "headline":"Example","datePublished":"2021-01-01T00:00:00Z",
      "image":"https://miro.medium.com/cover.png"
    }</script><article><h2>Method</h2><figure>
      <img src="https://miro.medium.com/diagram.png"><figcaption>System diagram</figcaption>
    </figure></article>"""
    article = parse_article_html("https://blog.palantir.com/example-abcdef123456", html)
    assert article["inline_images"] == [{
        "url": "https://miro.medium.com/diagram.png",
        "caption": "System diagram",
        "section": "Method",
    }]
    assert article["source_headings"] == ["Method"]


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


def test_access_challenge_is_not_readable_article_content():
    assert not has_readable_body("Just a moment... Verify you are human. " * 20)
    assert not has_readable_body("A short preview")
    assert has_readable_body("The article explains the implementation. " * 20)


def test_fetch_article_retries_html_when_medium_body_is_blocked():
    url = "https://blog.palantir.com/example-abcdef123456"
    html = """<html><head><script type="application/ld+json">
    {"identifier":"abcdef123456","url":"https://blog.palantir.com/example-abcdef123456",
     "headline":"Example Post","datePublished":"2021-03-04T10:30:00Z"}
    </script></head><body><article><p>""" + "Detailed source content. " * 20 + """</p></article></body></html>"""

    class FakeResponse:
        def __init__(self, text, ok=True):
            self.text = text
            self.ok = ok
            self.encoding = None

        def raise_for_status(self):
            return None

    class FakeSession:
        def get(self, requested, timeout):
            if "format=json" in requested:
                return FakeResponse('"payload" Just a moment. Verify you are human.')
            assert requested == url
            return FakeResponse(html)

    article = fetch_article(url, FakeSession())
    assert article["title"] == "Example Post"
    assert "Detailed source content" in article["body"]


def test_fetch_article_keeps_metadata_when_body_is_blocked():
    url = "https://blog.palantir.com/example-abcdef123456"
    api_json = """</x>{"payload":{"value":{
      "id":"abcdef123456","title":"Example Post","firstPublishedAt":1609459200000,
      "latestPublishedAt":1609459200000,
      "content":{"bodyModel":{"paragraphs":[{"text":"Just a moment. Verify you are human."}]}}
    }}}"""

    class FakeResponse:
        ok = True

        def __init__(self, text):
            self.text = text
            self.encoding = None

        def raise_for_status(self):
            return None

    class FakeSession:
        def get(self, requested, timeout):
            return FakeResponse(api_json if "format=json" in requested else "<html>Access denied</html>")

    article = fetch_article(url, FakeSession())
    assert article["title"] == "Example Post"
    assert article["published_at"] == "2021-01-01T00:00:00Z"
    assert article["body"] == ""
    assert article["analysis_status"] == "pending"
