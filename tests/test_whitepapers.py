import json
from pathlib import Path

from scripts.render_whitepaper_markdown import render


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "whitepapers" / "autoresearch.json"


def test_autoresearch_whitepaper_has_source_and_notional_caveat():
    paper = json.loads(DATA.read_text(encoding="utf-8"))
    assert paper["slug"] == "autoresearch"
    assert paper["source_url"].startswith("https://www.palantir.com/")
    assert paper["source_url"].endswith(".pdf")
    assert len(paper["sections"]) >= 8
    assert all(section["paragraphs"] and section["source_pages"] for section in paper["sections"])
    assert all(1 <= page <= 22 for section in paper["sections"] for page in section["source_pages"])
    assert "가상" in paper["abstract"]
    assert "0.88" in render(paper) and "0.90" in render(paper)


def test_autoresearch_markdown_matches_structured_source():
    paper = json.loads(DATA.read_text(encoding="utf-8"))
    output = ROOT / "whitepapers" / "autoresearch.md"
    assert output.read_text(encoding="utf-8") == render(paper)
