"""Select substantive media from an official product page linked by an article."""

from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .collector import build_session


SPACE = "/xrfr7uokpv1b/"
MEDIA_HOSTS = {"image": "images.ctfassets.net", "video": "videos.ctfassets.net"}
USEFUL_IMAGE = re.compile(r"screenshot|graphic|diagram|workflow|interface|architecture|video", re.I)
EXCLUDED_IMAGE = re.compile(r"logo|quote|icon|social|asset[_ ]?105", re.I)


def choose_product_link(article: dict[str, Any], links: Iterable[dict[str, str]]) -> tuple[dict[str, str], str] | None:
    newsletter = (article.get("analysis") or {}).get("newsletter") or {}
    sections = [section.get("heading", "") for section in newsletter.get("sections") or []]
    matches = []
    for index, link in enumerate(links):
        label = link.get("label", "").casefold()
        if len(label) < 4 or not link.get("url", "").startswith("https://www.palantir.com/"):
            continue
        for heading in sections:
            if label in heading.casefold():
                matches.append((-len(label), index, link, heading))
                break
    if not matches:
        return None
    _, _, link, heading = sorted(matches, key=lambda item: (item[1], item[0]))[0]
    return link, heading


def _asset_url(value: str, kind: str) -> str | None:
    url = "https:" + value if value.startswith("//") else value
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != MEDIA_HOSTS[kind] or not parts.path.startswith(SPACE):
        return None
    return url


def parse_product_media(html: str, page_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return []
    try:
        page = json.loads(script.string)["props"]["pageProps"]["page"]
        blocks = page["fields"]["blocks"]
        page_title = str(page["fields"].get("pageTitle") or "Palantir product")
    except (KeyError, TypeError, ValueError):
        return []
    images: list[dict[str, str]] = []
    videos: list[dict[str, str]] = []
    seen = set()

    def walk(node: Any, caption: str = "") -> None:
        if isinstance(node, list):
            for item in node:
                walk(item, caption)
            return
        if not isinstance(node, dict):
            return
        fields = node.get("fields")
        if isinstance(fields, dict):
            alt = fields.get("altText")
            title = fields.get("title")
            if isinstance(alt, str) and alt.strip():
                caption = alt.strip()
            elif isinstance(title, str) and title.strip() and (not caption or "blocks" in fields or "impactStudies" in fields or "image" in fields or "text2" in fields):
                caption = title.strip()
            file = fields.get("file")
            if isinstance(file, dict):
                content_type = file.get("contentType", "")
                kind = "image" if content_type in {"image/png", "image/jpeg", "image/webp"} else "video" if content_type == "video/mp4" else ""
                url = _asset_url(str(file.get("url") or ""), kind) if kind else None
                name = str(file.get("fileName") or "")
                if url and url not in seen:
                    if kind == "image":
                        size = (file.get("details") or {}).get("image") or {}
                        if (size.get("width") or 0) >= 800 and (size.get("height") or 0) >= 350 and USEFUL_IMAGE.search(caption + " " + name) and not EXCLUDED_IMAGE.search(caption + " " + name):
                            images.append({"kind": kind, "url": url, "caption": caption, "source_url": page_url, "source_title": page_title})
                            seen.add(url)
                    elif (file.get("details") or {}).get("size", 0) <= 100_000_000:
                        videos.append({"kind": kind, "url": url, "caption": caption or name, "source_url": page_url, "source_title": page_title})
                        seen.add(url)
            for key, value in fields.items():
                if key not in {"file", "metadata", "sys"}:
                    walk(value, caption)
        else:
            for key, value in node.items():
                if key not in {"metadata", "sys"}:
                    walk(value, caption)

    walk(blocks)
    return images[:3] + videos[:5]


def fetch_product_media(page_url: str) -> list[dict[str, str]]:
    parts = urlsplit(page_url)
    if parts.scheme != "https" or parts.netloc != "www.palantir.com":
        raise ValueError("Only official Palantir product pages are allowed")
    response = build_session().get(page_url, timeout=30)
    response.raise_for_status()
    return parse_product_media(response.text, page_url)
