# Phase 2 — Worker HTML Path

**Goal:** HTML parsing for static docs, JS-rendered docs, and `llms-full.txt` fast path.

**Needs:** Phase 1 worker structure; no new shared models.

## Deliverables

- `services/worker/Dockerfile.heavy` — adds Chromium + Playwright (for Crawl4AI)
- `sources/http_url.py` — fetch single URL or crawl sitemap with depth/breadth limits
- `sources/llms_txt.py`:
  - GET `{base}/llms-full.txt` → if 200, return as one Markdown blob (skip parsing entirely)
  - else GET `{base}/llms.txt` → parse, return list of URLs to crawl
- `parsers/html_trafilatura.py`:
  - `trafilatura.extract(html, output_format="markdown", include_tables=True, include_links=False, include_comments=False)`
  - if empty or <200 chars → flag for fallback
- `parsers/html_crawl4ai.py`:
  - `BrowserConfig(headless=True)`, `CrawlerRunConfig(word_count_threshold=10)`
  - return `markdown` field directly
- Routing in `pipeline.py`:
  ```
  source.type == "llms_full"                    → llms_txt.fetch_full
  source.type == "http_url" and profile=light   → trafilatura
                                                  on fallback → requeue to heavy
  source.type == "http_url" and profile=heavy   → crawl4ai
  ```
- `enrich/anchors.py` (extended):
  - parse original HTML with `selectolax` once before MD conversion
  - extract real `<h2 id="...">` anchors; build heading→anchor map; attach to ProcessedDocument (don't only auto-generate)
- HTML cleanups (regex blocklist):
  - strip "Edit this page on GitHub" / "Previous" / "Next" / "Was this helpful?"
  - drop nav lists rendered before main content
  - tables: preserve as MD tables; generate `table_summary` if >20 rows
- `tests/`:
  - Next.js docs page snapshot
  - Stripe docs snapshot
  - JS-rendered SPA page (Playwright record-mode capture once)

## Tooling notes

- Trafilatura: BSD, in-process, no GPU → ~80% of sites.
- Crawl4AI: needs Chromium (~300 MB) → heavy image only, routed via heavy SQS queue.
- `selectolax` (lexbor): much faster DOM walking than BeautifulSoup.

## Acceptance

- A Next.js-style static docs URL → Trafilatura → correct breadcrumbs + real `#using-jwt`-style anchors mapped.
- Pure JS SPA → Trafilatura empty → pipeline requeues to heavy → Crawl4AI extracts content.
- `llms-full.txt` fast path: Anthropic's `/llms-full.txt` → ProcessedDocuments with zero HTML parsing.
- "Was this helpful?" footers removed by cleanups.

## Out of scope

PDF/Office, scheduled refresh.

## DoD

3 real docs sites parse end-to-end (one static, one JS, one llms-full.txt) · fallback path verified · `pytest services/worker` green.
