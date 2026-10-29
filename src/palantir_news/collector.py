"""Collect official Palantir Blog posts from Medium's sitemap and article metadata."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


SITEMAP_URL = "https://blog.palantir.com/sitemap/sitemap.xml"
ARTICLE_ID_RE = re.compile(r"-([0-9a-f]{8,})$")
USER_AGENT = "Palantir-News-Archive/1.0 (+https://github.com/JCURVEs/palantir-news)"
BLOCKED_PAGE_MARKERS = (
    "just a moment",
    "verify you are human",
    "checking your browser",
    "captcha challenge",
    "access denied",
    "enable javascript and cookies",
)


def normalize_url(url: str) -> str:
    """Remove tracking query strings and fragments from a canonical article URL."""
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def article_id_from_url(url: str) -> str | None:
    """Return a Medium article identifier when the URL is an article."""
    match = ARTICLE_ID_RE.search(normalize_url(url))
    return match.group(1) if match else None


def build_session() -> requests.Session:
    """Build a retrying HTTP session suitable for a moderate historical crawl."""
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def parse_sitemap(xml_content: bytes | str) -> list[str]:
    """Extract canonical article URLs from a Medium publication sitemap."""
    root = ElementTree.fromstring(xml_content)
    urls: list[str] = []
    seen: set[str] = set()
    for node in root.findall(".//{*}loc"):
        url = normalize_url(node.text or "")
        if article_id_from_url(url) and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def fetch_sitemap(session: requests.Session | None = None) -> list[str]:
    """Fetch the official Palantir Blog sitemap."""
    client = session or build_session()
    response = client.get(SITEMAP_URL, timeout=30)
    response.raise_for_status()
    return parse_sitemap(response.content)


def _json_ld_objects(soup: BeautifulSoup) -> Iterable[dict[str, Any]]:
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict):
                yield item


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\ufffd", "'").split())


def has_readable_body(body: str) -> bool:
    """Reject short or access-control pages before sending text to the model."""
    text = body.strip()
    prefix = text[:600].lower()
    return len(text) >= 200 and not any(marker in prefix for marker in BLOCKED_PAGE_MARKERS)


def _medium_image_url(image_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9*_.-]+", image_id):
        return ""
    return f"https://miro.medium.com/v2/resize:fit:1200/{image_id}"


def _html_inline_images(article: Any, cover_url: str) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    seen = {cover_url}
    section = ""
    for node in article.find_all(["h2", "h3", "figure"]):
        if node.name in ("h2", "h3"):
            section = _clean_text(node.get_text(" ", strip=True))
            continue
        img = node.find("img")
        if not img:
            continue
        candidate = str(img.get("data-src") or img.get("src") or "")
        parts = urlsplit(candidate)
        if parts.scheme != "https" or parts.netloc != "miro.medium.com" or candidate in seen:
            continue
        seen.add(candidate)
        caption = node.find("figcaption")
        images.append({
            "url": candidate,
            "caption": _clean_text(caption.get_text(" ", strip=True)) if caption else "",
            "section": section,
        })
    return images


def parse_article_html(url: str, html: str) -> dict[str, Any]:
    """Parse stable metadata and readable article text from a Medium page."""
    soup = BeautifulSoup(html, "html.parser")
    metadata = next(
        (
            item
            for item in _json_ld_objects(soup)
            if item.get("datePublished") and item.get("headline")
        ),
        None,
    )
    if not metadata:
        raise ValueError(f"Article JSON-LD not found: {url}")

    canonical_url = normalize_url(str(metadata.get("url") or url))
    article_id = str(metadata.get("identifier") or article_id_from_url(canonical_url) or "")
    article = soup.find("article")
    body = _clean_text(article.get_text(" ", strip=True)) if article else ""
    images = metadata.get("image") or []
    if isinstance(images, str):
        images = [images]
    author = metadata.get("author") or {}
    if isinstance(author, list):
        author = author[0] if author else {}

    cover_url = str(images[0]) if images else ""
    return {
        "id": article_id,
        "url": canonical_url,
        "title": _clean_text(str(metadata.get("headline", ""))),
        "description": _clean_text(str(metadata.get("description", ""))),
        "published_at": str(metadata["datePublished"]),
        "modified_at": str(metadata.get("dateModified", "")),
        "author": _clean_text(str(author.get("name", "Palantir"))) if isinstance(author, dict) else "Palantir",
        "image_url": cover_url,
        "inline_images": _html_inline_images(article, cover_url) if article else [],
        "body": body,
        "analysis": None,
        "analysis_status": "pending",
    }


def parse_medium_json(url: str, raw: str) -> dict[str, Any]:
    """Parse Medium's public JSON representation for an article."""
    payload_text = raw.split("</x>", 1)[-1]
    payload = json.loads(payload_text)
    value = payload["payload"]["value"]
    published = datetime.fromtimestamp(value["firstPublishedAt"] / 1000, tz=timezone.utc)
    modified = datetime.fromtimestamp(value["latestPublishedAt"] / 1000, tz=timezone.utc)
    content = value.get("content") or {}
    body_model = content.get("bodyModel") or {}
    paragraphs = body_model.get("paragraphs") or []
    body = _clean_text(" ".join(str(item.get("text", "")) for item in paragraphs))
    virtuals = value.get("virtuals") or {}
    preview = virtuals.get("previewImage") or {}
    image_id = str(preview.get("imageId", ""))
    image_url = _medium_image_url(image_id)
    inline_images: list[dict[str, str]] = []
    seen_ids = {image_id}
    section = ""
    for paragraph in paragraphs:
        if paragraph.get("type") == 3:
            section = _clean_text(str(paragraph.get("text") or ""))
        if paragraph.get("type") != 4:
            continue
        metadata = paragraph.get("metadata") or {}
        current_id = str(metadata.get("id") or "")
        current_url = _medium_image_url(current_id)
        if not current_url or current_id in seen_ids:
            continue
        seen_ids.add(current_id)
        inline_images.append({"url": current_url, "caption": "", "section": section})

    return {
        "id": str(value["id"]),
        "url": normalize_url(str(value.get("canonicalUrl") or url)),
        "title": _clean_text(str(value.get("title", ""))),
        "description": _clean_text(str(content.get("subtitle") or virtuals.get("subtitle") or "")),
        "published_at": published.isoformat().replace("+00:00", "Z"),
        "modified_at": modified.isoformat().replace("+00:00", "Z"),
        "author": "Palantir",
        "image_url": image_url,
        "inline_images": inline_images,
        "body": body,
        "analysis": None,
        "analysis_status": "pending",
    }


def fetch_article(url: str, session: requests.Session | None = None) -> dict[str, Any]:
    """Fetch and parse one Palantir Blog article."""
    client = session or build_session()
    article_id = article_id_from_url(url)
    metadata_only: dict[str, Any] | None = None
    if article_id:
        try:
            api_response = client.get(f"https://medium.com/p/{article_id}?format=json", timeout=30)
            if api_response.ok and '"payload"' in api_response.text:
                api_response.encoding = "utf-8"
                article = parse_medium_json(url, api_response.text)
                if has_readable_body(article["body"]):
                    return article
                metadata_only = article
        except (requests.RequestException, ValueError, KeyError, TypeError):
            pass

    try:
        response = client.get(normalize_url(url), timeout=30)
        response.raise_for_status()
        response.encoding = "utf-8"
        article = parse_article_html(url, response.text)
    except (requests.RequestException, ValueError):
        if metadata_only is None:
            raise
        article = metadata_only
    if not has_readable_body(article["body"]):
        article["body"] = ""
    return article


def fetch_reader_text(url: str, session: requests.Session | None = None) -> str:
    """Read a public article through Jina Reader when Medium blocks CI runners."""
    client = session or build_session()
    response = client.get(f"https://r.jina.ai/{normalize_url(url)}", timeout=60)
    response.raise_for_status()
    text = _clean_text(response.text)
    if not has_readable_body(text):
        raise ValueError(f"Reader returned insufficient content: {url}")
    return text


def publication_year(article: dict[str, Any]) -> int:
    """Return the article's actual publication year."""
    return datetime.fromisoformat(article["published_at"].replace("Z", "+00:00")).year
