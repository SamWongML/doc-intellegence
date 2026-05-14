# Phase 3 — Worker PDF/Office (Optional)

**Skip this phase entirely if no doc source is PDF/DOCX/PPTX/image.** Implement only on first customer demand.

**Goal:** add Docling-based parsing for binary doc formats.

**Needs:** Phase 2 worker structure.

## Deliverables

- Extend `services/worker/Dockerfile.heavy` with Docling deps. Note: Docling downloads ~1–2 GB of model weights on first run — either bake into the image or mount EFS.
- `parsers/docling_parser.py`:
  - `DocumentConverter().convert(input_path)` → `DoclingDocument`
  - `doc.export_to_markdown()` → canonical Markdown
  - preserve tables, code blocks, equations
  - page numbers as anchor pseudo-IDs (`#page-12`)
- Routing: `source.type == "http_url"` with `Content-Type` PDF/Office → heavy queue, docling parser.

## Acceptance

- Sample PDF spec sheet → ProcessedDocument with tables preserved as MD tables and clean reading order.

## Out of scope

Image content extraction beyond captioning.

## DoD

PDF sample end-to-end · tests in `services/worker` green.
