# Changelog

## 0.9.0 — 2026-11-01

- Drag recognized rows to reorder text while retaining source-region links.
- Insert, delete and merge lines; changes update full text, progress and TXT exports.
- Rotate individual PDF pages/images by 90° and explicitly re-recognize the current page.
- Keep eight undo snapshots per page for structure, rotation and re-recognition, including saved projects.
- Add bundled Tesseract 5 through tesserocr, with official local Simplified/Traditional Chinese and English models.
- Preserve previous text if re-recognition fails; batch resume does not overwrite the preserved page.
- Extend offline, row-drop, persistence and dual-engine regression coverage.

## 0.8.0 — 2026-11-01

First public source release, based on the working v8 desktop application.

- Local Chinese–English OCR for images and multi-page scanned PDFs.
- Source-image/text linking with horizontal or vertical proofreading layouts.
- Adjustable confidence filtering and complete-text exports.
- Keyboard correction with cursor-at-start editing and Enter confirmation.
- Local Traditional-to-Simplified conversion.
- Stop/resume, autosaved progress and existing project compatibility.
- Chinese and English documentation, synthetic examples and runtime screenshots.
- Isolated Windows OCR/UI regression runner and Windows build scripts.
