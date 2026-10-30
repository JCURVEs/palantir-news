"""Render curated whitepaper data as a readable GitHub Markdown article."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def append_table(lines: list[str], table: dict) -> None:
    lines.extend([f"*{table['caption']}*", ""])
    headers = [str(value).replace("|", "\\|") for value in table["headers"]]
    lines.extend(["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"])
    for row in table["rows"]:
        values = [str(value).replace("|", "\\|") for value in row]
        lines.append("| " + " | ".join(values) + " |")
    lines.append("")


def render(data: dict) -> str:
    source = data["source_url"]
    lines = [
        f"# {data['title']}",
        "",
        data["subtitle"],
        "",
        f"[Palantir 백서: {data['source_title']}]({source})",
        "",
        "> " + data["abstract"],
        "",
    ]
    for paragraph in data["lead"]:
        lines.extend([paragraph, ""])
    companion = data.get("companion")
    if companion:
        lines.extend([f"## {companion['title']}", "", companion["description"], ""])
        for diagram in companion["diagrams"]:
            lines.extend([f"![{diagram['alt']}](assets/{diagram['file']})", "", f"*{diagram['caption']}*", ""])
        for table in companion["tables"]:
            append_table(lines, table)
        lines.extend(["> " + companion["note"], ""])
    for index, section in enumerate(data["sections"], start=1):
        lines.extend([f"## {index:02d}. {section['heading']}", ""])
        for paragraph in section["paragraphs"]:
            lines.extend([paragraph, ""])
        table = section.get("table")
        if table:
            append_table(lines, table)
        if section.get("note"):
            lines.extend(["> " + section["note"], ""])
        pages = section.get("source_pages", [])
        if pages:
            links = " · ".join(f"[p.{page}]({source}#page={page})" for page in pages)
            lines.extend([f"Palantir 백서: {links}", ""])
    lines.extend(["---", "", data["disclaimer"], ""])
    return "\n".join(lines)


def main() -> None:
    source = ROOT / "data" / "whitepapers" / "autoresearch.json"
    output = ROOT / "whitepapers" / "autoresearch.md"
    data = json.loads(source.read_text(encoding="utf-8"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(data), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
