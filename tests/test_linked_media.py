import json

from palantir_news.linked_media import choose_product_link, parse_product_media


def asset(kind, url, name, width=1200, height=700):
    details = {"size": 5000}
    if kind == "image/png":
        details["image"] = {"width": width, "height": height}
    return {"fields": {"file": {"contentType": kind, "fileName": name, "url": url, "details": details}}}


def test_product_page_extracts_useful_visuals_and_videos_only():
    prefix = "//images.ctfassets.net/xrfr7uokpv1b/a/b/"
    page = {"props": {"pageProps": {"page": {"fields": {
        "pageTitle": "Security Forge",
        "blocks": [
            {"fields": {"title": "Security Forge Video", "image": asset("image/png", prefix + "screenshot.png", "Screenshot.png")}},
            {"fields": {"title": "Security Forge Graphic", "image": asset("image/png", prefix + "diagram.png", "Diagram.png")}},
            {"fields": {"title": "Accenture Quote", "image": asset("image/png", prefix + "quote.png", "Quote.png")}},
            {"fields": {"title": "Detect", "text2": [asset("video/mp4", "//videos.ctfassets.net/xrfr7uokpv1b/a/b/detect.mp4", "Detect.mp4")]}}
        ]}}}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(page)}</script>'
    media = parse_product_media(html, "https://www.palantir.com/security-forge/")
    assert [(item["kind"], item["caption"]) for item in media] == [
        ("image", "Security Forge Video"), ("image", "Security Forge Graphic"), ("video", "Detect")
    ]
    assert all(item["source_title"] == "Security Forge" for item in media)


def test_product_link_requires_matching_newsletter_section():
    article = {"analysis": {"newsletter": {"sections": [
        {"heading": "고객용 Security Forge의 보안 검토"}, {"heading": "데이터 흐름"}
    ]}}}
    links = [
        {"label": "Security Forge", "url": "https://www.palantir.com/security-forge/"},
        {"label": "Unrelated", "url": "https://www.palantir.com/unrelated/"},
    ]
    assert choose_product_link(article, links) == (links[0], "고객용 Security Forge의 보안 검토")
    assert choose_product_link(article, links[1:]) is None
