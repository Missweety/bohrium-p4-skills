---
name: source-bound-scientific-schematic
description: Generate or edit a scientific schematic from the actual supplied papers, biological sources, data and original SVG; retain editable layers, trace every important visual element, and export the actual SVG to inspected PNG/PDF.
metadata:
  version: "2.1.0"
license: MIT
---

# Deliver the source-bound scientific schematic, including source-preserving edits

Use this skill for the current case's real drawing workorder. Read `/input/case.json`, `/input/task.md`, and all referenced source files; locate alternate input paths only if those are absent. Work in `/app/work`; deliver actual artifacts and `result.json` in `/app/output`. Discover installed tools from `environment/resources.yaml` and commands. The task's filenames, export specifications and complete output contract take priority over examples here.

Do not substitute a tidy four-box summary for the requested biology, pathways, chart or source-figure editing. Source figure03 and primary biological references must be opened, including the actual diagram and relevant figure captions. Read primary sources before deciding entity identity, cellular location, hierarchy, relation direction, inhibition versus activation, experimental versus hypothesized mechanism, numerical values, n, units and uncertainty. An XML parse or successful export does not verify those judgements.

## Choose the actual operation

- **Existing SVG / figure03 edit:** inspect its full appearance and XML. Keep original geometry, IDs, groups, curves, markers, unrequested text and styles. Apply only the requested scientific/visual changes. Do not replace the source with a generic newly drawn diagram. Edit leaf `tspan` text where appropriate so nested font styling survives. If a requested change needs a new path/structure, edit XML deliberately and keep a before/after structural diff; the included helper handles leaf text and attributes, not arbitrary surgery.
- **New schematic:** express the actual requested mechanism, structure, or workflow as a visual narrative, then actually draw the relevant scientific entities and spatial/causal relations. Four elements need not mean four rectangular panels. Use biological/material/device shapes, meaningful grouping and precise arrow semantics. Code the diagram with named SVG groups and editable `text`; use the helper's primitives or author a richer SVG directly and use `mode: copy` to export it.
- **Actual source data chart:** load the actual table and units, produce a chart directly from those values with an appropriate scale and uncertainty. Avoid invented values, categorical quantities encoded as continuous magnitudes, decorative area distortion, or converting correlation into causation. Generate a named editable SVG with a plotting library or explicit XML; then export that exact file. Keep the processed data and plotting code.

## Scientific plan before rendering

Write `/app/work/figure-plan.md` with the task's required changes/deliverables and a concise entity–relation–evidence table. Each key label, arrow, numerical value, legend entry and conclusion needs an actual filename plus page/figure/table row or line locator. For numeric claims include comparison, denominator/n, units and statistic. Mark an inference explicitly and draw a distinguishable edge style; omit unsupported mechanisms. Mark source conflicts instead of choosing a convenient value. Recheck *all* changed scientific elements, plus any new or central relations, against the source, not merely two samples.

Use restrained colors with shape/line redundancy. Keep text readable at the target physical size. Relational arrowheads, inhibitory bars, grouping, compartment membership, legend and scale must communicate the intended semantics; avoid arrow paths crossing a label. Use the current size/format requirements; when unspecified, begin around 1200×700 user units, 18–24 unit body text, then inspect the rendered result. Long labels may be wrapped; do not enforce an arbitrary word count or force valid source diagrams into a fixed layer naming scheme.

## Helper interface

Run from this skill directory, or use its absolute script path:

```bash
python scripts/deliver.py --case /input/case.json --plan /app/work/plan.json --out /app/output
```

Read [references/plan-and-example.md](references/plan-and-example.md) for the plan schema and a **synthetic** minimal invocation. The script requires actual element locators supplied by the agent; it does not extract or invent scientific relations. It supports `create` primitives, `edit` by unique ID or exact leaf text, and `copy` of an agent-authored complete SVG. It always writes real source SVG, evidence map, changes, caption, export checks and structured result. Rename/copy files and update their references if the case demands different names. Add all task-specific output fields in `result_fields`; see [references/output-contract.md](references/output-contract.md).

Exports render the **actual SVG**, using CairoSVG, rsvg-convert or Inkscape. Python 3.10+ is required; the geometry/editing helper itself uses standard library. CairoSVG can be installed with `python -m pip install CairoSVG` (tested 2.9.1; requires native Cairo); alternatively use installed rsvg-convert or Inkscape. Do not spend the full case budget on installation: try an available real renderer, then retain source and return a precise partial result if none works. There is no fake preview, text-free substitute or redraw-from-spec fallback. The helper writes the requested dpi into PNG `pHYs` metadata and reads it back as `density_dpi`; pixel dimensions still follow canvas × scale, so set `scale` when the task specifies a physical print size rather than pixels. A missing renderer leaves PNG/PDF reported as missing, never as verified.

## Finish the case

1. Save an early source draft; improve the same drawing incrementally within the 900-second execution budget.
2. Render actual SVG to PNG and PDF. Open the PNG (and PDF where needed), inspect full size and thumbnail: text glyphs, long labels, marker direction, clipping, layer order, legend, preserved source curves, data mapping and target physical size. If fonts are missing, use an installed compatible font and document substitution; no unreadable glyph boxes as success.
3. On edits, compare the before and after appearance and XML. The helper retains unmodified nested `tspan` elements and rejects unknown or ambiguous targets. Verify no unrequested scientific content changed. Save the source hash and change basis.
4. Correct layout/science problems and render again. Check target resolution/dimensions and actual file contents, not just headers. The helper's file checks are a minimum technical gate, never a scientific or aesthetic score.
5. Check every original output-contract field, its type and its requested semantics. Preserve case_id. Add actual paths/structured values as required; never output JSON Schema descriptors (`type`, `properties`, `required`) as answers. Unknown fields need an informed implementation or honest partial status.
6. Deliver all requested artifacts and a useful caption identifying conditions, abbreviations, uncertainty and sources. Missing material, unsupported operation, ambiguous science and rendering failure are distinct limits. A blocked/partial run must not inherit old success. Describe actual evidence; do not invent baseline gains, hidden-case scores, GitHub availability or formal evaluation results.

The platform supplies the formal cases and comparisons. Examples here illustrate interfaces only. This skill improves deterministic source preservation and faithful exports; actual scientific quality depends on reading and verifying the current materials.

If a source contains relative images, linked fonts or external CSS, the helper blocks relocation instead of dropping content. Make it self-contained with explicit logged packaging changes or export in the original resource context with an available tool. Preserve those resources and original scientific layout. The export report identifies embedded raster content; a vector PDF can still contain original raster images. For official schemas whose source/export field types differ from the helper defaults, adapt the helper's artifact report into the required final schema, keeping true paths and evidence; details are in the output-contract reference.

A plain `<!DOCTYPE ...>` declaration (as written by Illustrator/Inkscape) is stripped before parsing; entity declarations (`<!ENTITY`) are still refused. If a source has percentage `width`/`height` and no `viewBox`, it has no intrinsic canvas: the helper renders it on an explicit 1200×700 user-unit fallback, writes absolute width/height plus a `viewBox` into the delivered SVG, and records `canvas_assumed` and an uncertainty note instead of blocking the case. An empty `formats` list is rejected as blocked; an empty caption yields `status=partial` with `caption missing`, never `ok`.

## Change record

- 2.1.0 (2026-11-22): accept plain SVG DOCTYPE (reject entities) so real Illustrator/Inkscape sources are editable; handle percentage-sized/no-viewBox sources with a documented fallback canvas and normalized absolute canvas; unwrap nested `output_contract`/`contract` and accept `field_name`-style field lists; empty `formats` no longer passes as `ok`; empty caption downgrades to `partial`.
- 2.0.0 (2026-11-21): rewrite as a single source-bound helper. Leaf-only text edits preserve untouched nested `tspan`/attributes and reject rich-text parents; exports use only real SVG renderers (CairoSVG/rsvg/Inkscape) with no layout-only preview; source-edit mode accepts the original layer structure and checks unchanged XML; `result.json` merges draft fields and validates contract list/schema without emitting schema descriptors as answers.
- 2.0.1 (2026-11-21): write requested dpi into PNG `pHYs` and read it back as `density_dpi`; document that pixel size follows canvas × scale. Fixes the machine-checkable export-resolution line.

A nonzero helper exit means the current run failed: never treat an older result.json as current success; unsafe output guard failures intentionally do not write any result.
