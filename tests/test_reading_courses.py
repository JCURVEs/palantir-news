import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_reading_courses_reference_ready_newsletters():
    courses = json.loads((ROOT / "data/reading_courses.json").read_text(encoding="utf-8"))
    articles = {
        article["id"]: article
        for article in (
            json.loads(line)
            for line in (ROOT / "data/articles.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }

    assert {track["id"] for track in courses["tracks"]} == {"delta", "echo", "design", "platform"}
    for course in [courses["foundation"], *courses["tracks"]]:
        ids = [step["article_id"] for step in course["steps"]]
        assert ids and len(ids) == len(set(ids))
        for step in course["steps"]:
            article = articles[step["article_id"]]
            assert article["analysis_status"] == "complete"
            assert article["analysis"].get("newsletter")
            assert len(step["why"]) >= 20
