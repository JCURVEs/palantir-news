from palantir_news.summarizer import build_prompt


def test_prompt_requests_concrete_mechanism_and_evidence():
    prompt = build_prompt({"title": "Example", "body": "Source detail"})

    assert "어떤 문제를 어떤 방식으로 풀었나" in prompt
    assert "실측 성과와 계획/예상 효과를 구별" in prompt
    assert "Source detail" in prompt


def test_prompt_keeps_end_of_long_article():
    prompt = build_prompt({"body": "A" * 13000 + "M" * 8000 + "Z" * 1000})

    assert "[중간 부분 생략]" in prompt
    assert "Z" * 1000 in prompt
    assert "M" * 8000 not in prompt
