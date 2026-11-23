# Runtime results

The current `/input/case.json` and task.md are authoritative. `result.json` always retains default real artifacts:
`case_id`, `status`, `source_file`, `exports`, `element_map`, `caption`, `uncertainty`, `limits`, `source_version`, `changes`, `canvas`, `preview_status`.

- source_file: actual editable SVG path relative to output.
- exports: only successful actual SVG exports, with engine, hash and actual PNG dimensions; PDF remains vector where SVG itself uses vectors. Check any source embedded raster separately.
- element_map: records `{element, source, data_ref?, claim?, status?}`. element matches an existing SVG ID. source points to actual material plus locator. Numeric data_ref includes the actual table/row/figure/condition. Every semantic generated element needs mapping; decorative elements may be explicitly marked in the plan.
- changes: exact target before/after XML plus scientific/workorder basis. Unedited structure survives.
- uncertainty: real gaps, conflicts or inference limits, not boilerplate assurance.
- status: `ok` only when requested exports and required contract fields exist. This is a technical result; the agent must separately verify meaning, types and visual quality. `partial` for missing exports or contract values; `blocked` for malformed input, ambiguous edit target or missing evidence map.

`plan.result_fields` supplies extra field values required by this case. No computed artifact field can be overridden. Contract forms supported for required-field detection: a list of names, a list of `{name:...}`/`{field:...}`, `{fields:[...]}`, `{fields:{...}}`, plain field dictionary, or JSON Schema (`properties`/`required`). Basic JSON Schema object/array/string/number/integer/boolean/null, enum, nested properties/items and required are checked. Other validation keywords and contracts conveyed in natural language remain the agent's responsibility. Never guess their semantics or claim this helper is a complete schema validator.

Technical outputs are `graphical_abstract.svg`, optional `.png`/`.pdf`, `element_map.json`, `changes.json`, `caption.md`, `export-checks.json`, and `result.json`. Use the task's actual filenames when specified, and ensure every path in JSON points to a delivered file. Incomplete runs must identify what is missing; no renderer means actual SVG remains useful but the requested PNG/PDF are incomplete.

For an anonymous original SVG leaf, `changes[].element` and the evidence map may use a stable structural XPath such as `/svg[1]/g[1]/text[1]/tspan[2]`; `changes[].xpath` always records this path. This avoids adding IDs or flattening unchanged source formatting. Non-self-contained external/local `href` or CSS `url(...)` resource references are explicitly rejected; embed those resources into an authored source and record packaging changes, or export the original in its resource context with another real tool. The helper will not silently drop a linked image/font after relocation.

If the task requires a different type for a standard field (e.g. source_file is an object rather than a filename), treat the helper's JSON as an intermediate artifact report. Adapt the final JSON to the exact current schema with the actual source/export metadata, preserving original case_id and evidence. Do not force this helper's default field types onto the official contract. Recheck the adapted final result against the full case requirements.
