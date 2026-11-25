# Output contract adaptation (authoritative rules)

`result.json` must match the case's `output_contract`, not a template. The case file
(`/input/case.json`) or the task text controls field names, nesting and required types.
Helper artifacts (`index.json`, `relations.json`, `queries.json`, `skipped.json`,
`operations.json`, `tree.json`) are evidence for assembly; they are not the final answer.

## 1. Recognized contract shapes

`report` accepts any of these and extracts top-level field names in order:

1. JSON Schema object: `{"type":"object","properties":{...},"required":[...]}`.
2. Plain field map: `{"field": {"type": ...}, "other": "string"}`.
3. List of names: `["case_id","status","files", ...]` (bare array or wrapped).
4. List of objects: `[{"name":"files","type":"array"}, ...]`.
5. `{"fields": [...]}` or `{"fields": {...}}`.
6. A JSON string containing one of the above.
7. Nested under `output_contract` / `contract` / `result_schema` / `schema`.

If no contract can be read, `report` emits `case_id`, `status`, `files` and records the
fallback in `field_notes._contract`; status becomes `partial` (never `ok`) and
`uncertainty` contains a `contract_missing_or_unparseable` entry. Use `--fields a,b,c` to
supply names from prose, or `--contract FILE` for a standalone contract file.

## 2. Field resolution

Field names are normalized (casefold, punctuation removed, simple plural trimming) and
matched against semantic roles. Common equivalences:

| Contract wording | Result key |
| --- | --- |
| case_id, id, case | case_id |
| status, run_status | status |
| files, file_list, library_files, documents, organized_files | files |
| inventory, input_inventory, library_inventory | inventory |
| tree, directory_tree, folder_structure, library_structure | tree |
| duplicates, duplicate_files, dupes | duplicates |
| versions, version_relations, versioning | versions |
| relations, relationships | relations |
| queries, question_answers, query_answers, answers, search_results | queries |
| changes, change_log, operation_log, operations, audit, actions | changes |
| uncertainty, uncertainties, limitations, notes, open_questions | uncertainty |
| skipped, skipped_items, failures, excluded, unprocessed | skipped |
| summary, overview | summary |
| metadata, bibliographic_data, source_metadata | metadata |
| sources, provenance, source_versions | sources |
| hashes, checksums, sha256 | hashes |

Unmapped names are set to `null` and listed in `field_notes` with the reason
("contract field name not mapped; left null instead of guessing"). Never copy schema
keywords (`type`, `required`, `properties`, ...) into results.

## 3. Required payload contents

Regardless of contract names, `result.json` always contains:

- `case_id` — copied verbatim from the case (never invented).
- `status` — `ok` | `partial` | `blocked`.
- `files` — one entry per organized file with `source`, `target`, `sha256`, `size_bytes`,
  `metadata`, `tags`, `evidence`, `kind`, encoding/PDF facts and `hints`.
- `tree` — nested directory tree derived from actual targets.
- `duplicates` / `versions` / `relations` — byte-duplicate groups, shared-DOI groups and
  explicit version links, each with evidence and non-destructive recommendations.
- `changes` — actual operations (`created`, `reused`, `reused_external`), hashes and
  verification flags.
- `queries` — query results (target, locator, snippet, answered flag, reason) when queried.
- `unanswered` — every query with `answered: false` plus the reason no evidence was found;
  also surfaced in `uncertainty`.
- `coverage` — `planned`/`covered`/`unplanned`/`total` source-file counts, the
  `unplanned_files` list with reasons, and `excluded` entries supplied by the plan.
- `skipped` — every excluded item with at least one reason code and message.
- `uncertainty` — unreadable files, PDF failures, encoding fallbacks, unresolved aliases,
  incomplete metadata, skipped items, unplanned/unanswered items, truncated text and
  unmapped contract fields.
- `permissions` — path -> mode bits captured by `inventory` (ACLs are not read).

## 4. Status and honesty rules

- `ok`: files were organized and no skipped/unresolved issue remains.
- `partial`: some files were organized but at least one item is skipped, unreadable,
  unplanned, unanswered, conflicted or an unmapped contract field exists; also used when the
  `output_contract` is missing or unparseable.
- `blocked`: no files could be organized, or the index is empty/missing.
- Missing metadata is `null`/`unknown` plus a note; it is never filled from a filename,
  a guess, or a plausible-looking identifier.
- If a requested operation (destructive move, Zotero sync, import) was not actually
  performed with a real tool, it is recorded as not performed.
- Cite evidence with `file:line` or `file:page`; a hash proves bytes, not meaning.
- The platform's hidden cases and score are not observable; do not state a score or claim an
  official case was verified.

## 5. Typical assembly

```bash
python3 scripts/library.py report --out /app/output/library --case /input/case.json \
        --result /app/output/result.json
python3 scripts/library.py check  --out /app/output/library --case /input/case.json \
        --result /app/output/result.json --require-relations
```

`check` fails if a contract field is missing, a hash does not match, an unindexed file
exists, a skipped item has no reason, or `status` is not one of the three allowed values.
Exit code 0 means the contract and disk agree; 1 means a human must fix or report it.
