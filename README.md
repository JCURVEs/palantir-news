# Palantir News

Palantir 공식 블로그의 글을 수집해 한국어로 정리하는 아카이브입니다.

- 대상: `https://blog.palantir.com/`
- 기간: 2020~2026년
- 구조: `archive/{연도}/{월}/{발행일}.md`
- 원본 인덱스: `data/articles.jsonl`
- 요약 항목: 한국어 제목, 요약, 쉬운 설명, 분야, 중요도

## 수집 현황

2026년 9월 30일 기준 공식 사이트맵과 실제 최초 발행일을 대조해 287개 글을 확보했습니다.

| 연도 | 글 수 |
|---:|---:|
| 2020 | 8 |
| 2021 | 44 |
| 2022 | 88 |
| 2023 | 49 |
| 2024 | 39 |
| 2025 | 36 |
| 2026 | 23 |

전체 원문 목록은 [`CATALOG.md`](CATALOG.md)에서 확인할 수 있습니다.

## 실행

```bash
python -m venv .venv
pip install -e .
palantir-news --start-year 2020 --end-year 2026
```

한국어 분석에는 `GROQ_API_KEY`가 필요합니다. 키가 없으면 원문 메타데이터와 본문을 먼저 수집하고 분석 상태를 `pending`으로 보존합니다.

```bash
palantir-news --start-year 2020 --end-year 2026 --collect-only
palantir-news --start-year 2020 --end-year 2026 --analysis-limit 10
```

GitHub Actions는 새 글과 미분석 글을 확인하며, 완료된 글은 다시 분석하지 않습니다.
