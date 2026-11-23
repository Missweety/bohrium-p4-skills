# Output contract

`result.json` is written to `/app/output/result.json` by `scripts/emit_result.py`.
It is a **flat object** (no `fields` / `data` wrapper). Every field named by the case's
`output_contract` is present; unmatched names are `null` and listed in
`unmapped_contract_fields`.

## 1. Core fields

| field | type | meaning |
|---|---|---|
| `case_id` | string | from `case_id/caseId/id/task_id/...`; `local-<hash>` if absent |
| `status` | `ok` \| `partial` \| `blocked` \| `failed` | see §5 |
| `mode` | `create` \| `edit` | pipeline branch actually taken |
| `source_file` | string \| null | editable SVG relative to output dir (`figure.svg`) |
| `figure_svg` | string \| null | same as `source_file` |
| `figure_png` | string \| null | `figure.png` |
| `figure_pdf` | string \| null | `figure.pdf` |
| `exports` | string[] | files that exist, relative paths |
| `deliverables` | object[] | `{path, role, format, exists, bytes, sha256}` |
| `element_map` | object[] | one row per entity/edge (+ compartments, legend); see §2 |
| `element_map_file` | string | `element_map.json` |
| `element_map_counts` | object | `{entities, edges, compartments, rows}` |
| `caption` | string | self-contained figure caption, no invented mechanisms |
| `caption_file` | string | `caption.md` |
| `selfcheck` | object | `{verdict, errors[], warnings[], stats{}}` |
| `selfcheck_file` | string | `selfcheck.json` |
| `mechanism_graph` | object | `{schema, compartments[], nodes{}, edges[], conflicts[], isolated_entities[], unresolved_edges[]}` |
| `nodes` | object[] | full extracted entities (id,label,type,compartment,status,evidence[],aliases,data_ref) |
| `edges` | object[] | full relations (id,source,target,kind,status,evidence[],label,data_ref) |
| `compartments` | object[] | `{id,label,order}` for the four bands |
| `isolated_entities` | string[] | entities with degree 0 |
| `conflicts` | string[] | same-name divergent type/compartment |
| `unresolved_edges` | object[] | endpoint/kind failures, explicitly **not drawn** |
| `token_inventory` | object[] | every symbol-like token found in materials: `{token,key,node_id,count}` |
| `token_recall` | number | fraction of `token_inventory` resolved to entities; `<0.8` is a hard-gate FAIL |
| `missing_relations` | object[] | stated relation intents that could not be drawn; non-empty is a hard-gate FAIL |
| `edge_endpoint_errors` | object[] | edges whose source/target is not in `nodes`; non-empty is a hard-gate FAIL |
| `binding_annotations` | object[] | stated ligand/binding partners kept as annotations (e.g. EGF bound by EGFR) rather than a second arrow |
| `limits` | string[] | scope/renderer/evidence limitations |
| `uncertainty` | string[] | inferred compartments, inferred edges, bottom-line caveats |
| `sources` | object[] | `{file,path,exists,chars,sha256,role}` incl. `case.json` |
| `change_log` | string | one-line generation/edit summary |
| `change_details` | object | create: `{mode,changes,case_sha256}`; edit: hashes + change list |
| `metrics` | object | counts, quote coverage, PNG dims/bytes, crossings, etc. |
| `input_files` | object[] | `{path,exists,chars}` |
| `blocked_reason` | string | non-empty only when `status=blocked` |
| `unmapped_contract_fields` | string[] | contract names that could not be mapped |

Alias tolerance: `figure_svg/svg/source/editable_source → source_file`,
`relations/interactions → edges`, `entities → nodes`,
`source_map/provenance → element_map`, `limitations → limits`,
`risks → uncertainty`, `changes/edit_log → change_log`, etc.
`output_contract` may be an object (`required/properties/fields`), a list of names,
a list of `{name|key|field}`, a nested schema or a comma string.

## 2. `element_map` row

```json
{
  "element": "node:egfr",
  "label": "EGFR",
  "kind": "entity",
  "type": "receptor",
  "compartment": "membrane",
  "source": "paper.md#line 12",
  "file": "paper.md",
  "page": null,
  "section": "line 12",
  "quote": "EGFR activation promotes AKT phosphorylation in the cytoplasm.",
  "quote_verified": true,
  "data_ref": "nodes[0]",
  "status": "stated"
}
```

Rules enforced by `scripts/check.py`:

1. every node and every edge has a row;
2. `source` is non-empty for `status=stated`;
3. `quote` is non-empty and, unless `MECH_TRUST_EVIDENCE=1`, occurs verbatim
   (whitespace-normalised) in the re-extracted materials;
4. `kind` is `entity` / `edge` / `compartment` / `decoration`;
5. `status` is `stated` / `inferred` / `unresolved`;
6. `page` is an integer when the locator is a PDF page, otherwise `null`;
   `section` always carries the human-readable locator.

Structured relation with no prose sentence naming both endpoints: `source` points at
`case.json#relations[i]`, `quote` is that relation's JSON, `status=inferred`.

## 3. Figure semantics

- SVG has real `<text>` (not paths), `<title>/<desc>` per `<g class="node ...">` and
  `<g class="edge ...">`, plus `data-node-id`, `data-type`, `data-compartment`,
  `data-kind`, `data-status-value`.
- Layers: `layer-title`, `layer-compartments`, `layer-edges`, `layer-nodes`,
  `layer-legend`, `layer-notes` (edit adds `layer-annotations`).
- Arrow heads are per-kind `<marker>` elements, each labelled in the legend.
- Inferred entities/edges use dashed outlines/arrow lines.
- Palette is Okabe–Ito + viridis + a fixed neutral set; `check.py` rejects off-palette
  data colours.

## 4. PNG / PDF

`figure.png` must be ≥800×600, >1500 unique colours, >1% non-white pixels.
`figure.pdf` must start with `%PDF` and exceed 1000 bytes. If no rasterizer exists,
SVG is still emitted and `status=partial`; PNG/PDF are reported `exists=false`.

## 5. Status rules

| status | rule |
|---|---|
| `ok` | selfcheck `PASS` AND SVG+PNG+PDF exist AND PNG quality gate passes. Edit mode also requires ≥1 applied change and `structure_preserved=true`. |
| `partial` | figure exists but any warning/export gap; or edit without a full raster. |
| `blocked` | `nodes==0` OR `edges==0` OR a hard-gate error (`token_recall<0.8`, non-empty `missing_relations`, non-empty `edge_endpoint_errors`): **no figure files are emitted** (stale ones removed), `blocked_reason` + `uncertainty` explain, evidence is listed in `sources`/`input_files`. |
| `failed` | pipeline exception; a complete result is still written. |

`kernel.py check` fails only on dishonesty: missing `case_id`/`status`, a contract field
absent, `status=ok` with selfcheck FAIL or a missing/empty declared deliverable, or an
empty caption/element_map when not blocked.

## 6. Edit mode additions

`change_details` carries `before_sha256`, `after_sha256`, `changes[]`
(`{op,target,value,applied,count,origin}`), `structure_preserved`,
`removed_elements`, `changed_text_elements`. `sources` gains the edited source SVG with
its pre-edit hash. `change_log` states how many operations applied and both hashes.
