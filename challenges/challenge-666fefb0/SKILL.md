---
name: research-library-organizer
description: >-
  Organize a real research library: inventory real file types, decode text
  (UTF-8/UTF-8-SIG/GB18030), probe PDFs, copy files through a validated plan
  with partial-failure handling, detect byte duplicates, shared DOIs and
  preprint/published/supplementary/correction relations, search metadata and
  body text, and assemble result.json from the case output_contract. Use for
  文献与资料自动分类, 科研资料整理, 文献库盘点, 去重与版本关系, 文件清单与改名,
  批量整理, library classification, literature deduplication, metadata inventory.
version: 2.0.0
---

# Research library organizer (evidence-first)

This skill turns a messy research directory into a verified, searchable library and a
case-shaped `result.json`. It never invents metadata, never deletes source files and never
claims an operation that did not happen on disk.

## 1. When to use it

Use when the task asks to inventory, classify, rename, organize, deduplicate or index a
collection of papers, notes, bibliography exports, PDFs, scans, aliases or administrative
version notes, or to answer questions over that collection with locatable evidence.

Do not use it for literature discovery/search on the web, single-paper deep reading,
translation or writing polish. This skill organizes what is actually on disk.

## 2. Runtime contract

- Inputs: `/input/case.json` and `/input/task.md`. Attached materials may be under `/input`
  or another directory named by the case; read the actual files, never assume content from
  a filename or from these instructions.
- Work area: `/app/work`; final artifacts under `/app/output`.
- Deliverable: `/app/output/result.json` containing `case_id` plus every field of the case
  `output_contract`, with honest `status`, evidence, uncertainty and change records.
- Budget: 64 model requests, 900 s, 16384 tokens per response. Run the pipeline once, then
  improve incrementally; save partial deliverables early.
- Runtime: Python 3 standard library only. `pdftotext` / `pdfinfo` are used when present;
  their absence degrades PDF text extraction but does not crash the pipeline.
- Environment note (Linux vs macOS): paths are normalized to Unicode NFC, so names created
  on either platform resolve consistently.

## 3. Quick start (script paths are absolute because the skill is installed at `/skills/weekly-skill`)

```bash
K=/skills/weekly-skill
S=/input/materials             # set to the directory that actually holds the library;
                               # if the library is directly in /input, do not plan case.json/task.md
W=/app/work
O=/app/output/library

python3 "$K/scripts/library.py" inventory --source "$S" --out "$W/inventory.json"
# read $W/inventory.json, then write $W/plan.json (schema in section 4)
python3 "$K/scripts/library.py" validate-plan --source "$S" --out "$O" --plan "$W/plan.json"
python3 "$K/scripts/library.py" apply --source "$S" --out "$O" --plan "$W/plan.json" --allow-partial
python3 "$K/scripts/library.py" dupes --out "$O"
python3 "$K/scripts/library.py" search --out "$O" --queries-file "$W/queries.txt"
python3 "$K/scripts/library.py" report --out "$O" --case /input/case.json
python3 "$K/scripts/library.py" check --out "$O" --case /input/case.json --result /app/output/result.json --require-relations
```

`report` writes `/app/work/result.json` by default when `--out` is `/app/work/library`;
pass `--result /app/output/result.json` to be explicit. Copy or rerun with the required
path; do not leave the deliverable only inside the work area.

## 4. Writing `plan.json`

```json
{
  "files": [
    {
      "source": "relative/path/in/source/tree",
      "target": "Category/Year/filename.ext",
      "metadata": {
        "title": "exact title or null",
        "authors": ["First Last"],
        "year": 2021,
        "doi": "10.xxxx/yyyy",
        "venue": "exact venue or null",
        "type": "article|preprint|thesis|notes|metadata|admin|supplementary"
      },
      "tags": ["topic", "method"],
      "version_relation": "preprint|published|supplementary|correction|null",
      "evidence": ["file.txt:line 12", "paper.pdf:page 3"],
      "reason": "why this category and name follow from the evidence"
    }
  ],
  "exclude": [
    {"source": "relative/path/to/skip", "reason": "explicit reason this file is out of scope"}
  ]
}
```

`exclude` is optional. Every source file not listed in `files` is reported as
`not_in_plan` (status `partial`); a file listed in `exclude` with a reason is recorded as
`excluded` instead and remains visible in `coverage.excluded`, `skipped.json` and
`result.json` without pretending it was organized.

Rules:

1. Plan every file that needs organizing, including aliases, supplements, bibliography
   exports and administrative records. `apply` records source files that no plan entry
   covers as `not_in_plan` skipped items and reports `coverage`
   (`planned`/`covered`/`unplanned`/`total`); any `unplanned` file makes the run `partial`.
2. `source` must match an inventoried path (NFC); do not plan symlinks as sources — plan the
   real file they point to.
3. `target` is relative, must stay inside the output root, and must be unique. The tool
   refuses `..`, absolute paths, symlinked parents, reserved record names and different
   content already at the target.
4. `evidence` and `reason` are mandatory. Cite a real line (text) or page (PDF). Never
   infer a title, author, year or DOI from a filename alone or from a guess: use
   `null`/`unknown` when the material does not say.
5. Use inventory `hints` only as leads; confirm against the quoted excerpt or the original
   before putting a value in `metadata`.
6. Keep version roles evidence-based: preprint/arXiv, published/peer-reviewed,
   supplementary, correction/erratum, accepted manuscript. Same DOI does not mean same bytes.
7. Prefer stable categories (topic/type/year). Cross-topic files get tags, not duplicates.
8. Never delete, rename or modify source files. This skill only copies.

## 5. Step-by-step

### 5.1 inventory

`inventory` records every entry: type sniffed from magic bytes (PDF, ZIP/OLE, image,
archive, text), extension, size, SHA-256, permissions, readability, text encoding
(UTF-8-SIG → UTF-8 → GB18030 → Big5 → Latin-1 with a confidence flag), PDF facts
(`pdf_status`: `ok`, `not_a_pdf`, `encrypted`, `no_text_layer`, `pdf_error`; page count),
a text excerpt, evidence-located metadata hints, and symlink target details (never followed
outside the source root). Unreadable files stay in the inventory with a reason.

If inventory reports `not_a_pdf`, `encrypted` or `no_text_layer`, record the limitation and
do not treat the bytes as reliable text.

### 5.2 validate-plan

Always run this before `apply`. It reports blocking errors (`source_missing`,
`source_unreadable`, `source_symlink`, `duplicate_target`, `target_conflict`,
`target_invalid`, missing `evidence`/`reason`) and warnings (unplanned files, incomplete
metadata, changed suffix). Exit code 1 means the plan has errors; fix them first.

### 5.3 apply

Strict by default: any plan error aborts before writing anything. With `--allow-partial`,
invalid items are skipped and written to `skipped.json` with codes and reasons while the
rest are copied. Copies are exclusive-create + SHA-256 verified; a target with different
content is never overwritten. Outputs: `index.json`, `inventory.json`, `operations.json`,
`skipped.json`, `tree.json`, and a text cache under `.library-cache/` (internal; ignored by
`check` and not part of the organized library). The source tree is inventoried once per run
and that single result is reused; `operations.json` is accumulated in memory (flushed every
50 entries) and written atomically at the end.

If a previous run was hard-interrupted, a target may exist with a partial hash and no
`operations.json` record. Strict mode reports `interrupted_partial` with a prompt to delete
or rename that file; `--allow-partial` records it as skipped. A leftover target whose hash
matches the source is verified and reused (`created: false`), and an operation record is
added.

`--dry-run` prints the operations without creating files or directories.

### 5.4 dupes

Builds `relations.json` with:

- `byte_identical` groups by full SHA-256 (exact duplicate downloads);
- `same_doi_different_content` groups from explicit DOI strings in text or plan metadata;
- `version_relation` when explicit preprint/published/supplementary/correction markers
  coexist in the same DOI group;
- `alias_links` parsed from files that explicitly declare `Alias "X" -> file`.

Every relation carries evidence locators and a recommendation (`keep`, `archive`,
`keep_as_attachment`, `manual_confirm`) with `auto_delete: false`. The tool never deletes.

### 5.5 search

Searches both plan metadata and extracted body text, returning the file, line or page and a
snippet. `--queries-file` accepts a JSON list/`{"queries": [...]}` or one query per line and
writes `queries.json` with an `answered` flag per question. Phrase search is tried first;
natural-language questions fall back to distinctive terms and report `mode: "terms"` plus
`matched_terms` and `term_coverage`.

Use the case's real questions. Answer from `queries.json`; if `answered` is false, say the
evidence is absent instead of guessing.

### 5.6 report

Reads the case `output_contract` (JSON Schema, dict field map, list of names, list of
`{name,type}` objects, `{fields: [...]}`, bare array, or a JSON string) and writes
`result.json` with `case_id`, `status` and every contract field, plus `files` (with hashes
and metadata), `tree`, `duplicates`, `versions`, `relations`, `changes`, `queries`,
`unanswered`, `coverage`, `skipped` and `uncertainty`. Contract fields that cannot be
filled are `null` and listed in `field_notes`; nothing is fabricated. See
`references/output-contract.md`.

If the `output_contract` is missing or cannot be parsed, the generic schema is emitted,
`status` is downgraded to `partial`, and `uncertainty` says the contract was unavailable.
Unanswered queries are written to `unanswered` (with a reason) and surfaced in
`uncertainty`. `coverage` reports `planned`/`covered`/`unplanned`/`total` plus explicit
exclusions; `permissions` uses the mode bits already captured by `inventory`.

Status: `ok` = indexed files with no skipped/unresolved issues; `partial` = files were
organized but something is skipped, unreadable or unmapped; `blocked` = nothing could be
organized or the index is empty.

### 5.7 check

Verifies index ↔ disk consistency (existence, hash, size, no unindexed files), skipped
reasons, `result.json` presence, `case_id`, allowed status, `queries.json` readability, and
(with `--case`) every contract field. It accepts a list-shaped `case.json` and reports a
malformed helper JSON as a problem instead of crashing. Exit 0 = pass, 1 = problems. Run it before finishing; paste the final
status into your response rather than claiming success.

## 6. Failure handling and degradation

- Missing/unreadable source: default strict run fails without writing; with
  `--allow-partial` it is skipped with a reason and the run continues. Report `partial`.
- Broken PDF: marked `not_a_pdf`; encrypted: `encrypted`; scanned: `no_text_layer`. No text
  is trusted from these files; cite that limitation.
- GBK/GB18030 text is decoded and its actual encoding recorded; `encoding_fallback: true`
  and low confidence are surfaced as uncertainty.
- Filename NFC/NFD differences are normalized before matching; original name is preserved in
  `nfc_normalized`.
- Symlinks are recorded with target, readability and whether the target stays inside the
  root; they are never copied outside the root.
- No `pdftotext`: PDF entries keep `pdf_status: "unavailable"`; search falls back to
  metadata and other files.
- Interrupted copy: exclusive create plus per-operation journal; unverified partial files
  are removed on error. Rerun the same plan to continue; already verified copies are reused.
  A leftover partial file with no operation record is reported as `interrupted_partial`
  (delete or rename it, or rerun with `--allow-partial` to skip it).

## 7. Idempotency and rollback

Rerunning the same plan does not rewrite copies whose hash matches; the index stays
byte-identical and ownership of previously created copies is preserved.

```bash
python3 "$K/scripts/library.py" rollback --out /app/output/library
```

Rollback removes only copies recorded as created by this tool whose hash is unchanged.
Modified copies are preserved and reported as `modified_preserved`; reused pre-existing
files are never removed. After rollback the index is historical, so `check` will report
missing files by design; rerun `apply` to rebuild, or state that the library was rolled back.

## 8. Example (synthetic illustration, not a case result)

Input `demo/` contains `a.txt` ("Title: Example; Author: Li; Year: 2020") and `b.md`
(byte-identical to `a.txt`). Commands:

```bash
python3 "$K/scripts/library.py" inventory --source demo --out work/inventory.json
cat > work/plan.json <<'JSON'
{"files":[
 {"source":"a.txt","target":"Notes/2020/example.txt","metadata":{"title":"Example","authors":["Li"],"year":2020},"tags":["notes"],"evidence":["a.txt:line 1"],"reason":"title/author/year are explicit"},
 {"source":"b.md","target":"Notes/2020/example.md","metadata":{"title":"Example"},"tags":["notes"],"evidence":["b.md:line 1"],"reason":"same content, second copy retained"}
]}
JSON
python3 "$K/scripts/library.py" apply --source demo --out out/library --plan work/plan.json
python3 "$K/scripts/library.py" dupes --out out/library
python3 "$K/scripts/library.py" search --out out/library --query Example
```

Expected (synthetic): two indexed files, one `byte_identical` relation recommending keep
`Notes/2020/example.md` / archive `Notes/2020/example.txt` (the canonical key prefers the
lexically smaller path when both are equal depth), and a search hit at `line 1` in each
file. This is an interface illustration only; it is not an official case output.

## 9. Limitations

- Text search is lexical, not semantic; phrase and term matching are reported separately.
- PDF extraction depends on `pdftotext`; image-only scans yield `no_text_layer`.
- DOI and version detection only use explicit strings found in text or plan metadata.
- Aliases are parsed only from explicit declarations (`Alias "X" -> file`, `别名 ... -> file`,
  `参见 file`); free-form references are not inferred.
- Large libraries: extracted text is capped per file and in total; truncation is reported in
  `uncertainty`, and relation/search coverage may be reduced.
- `permissions` reports the mode bits captured by `inventory` (path -> mode); ACLs are not read.
- Hidden evaluation cases and platform scores are not observable here; this skill provides
  reproducible tooling and honest artifacts, not a guaranteed score.
