# Plan schema and synthetic example

All content in this example is synthetic, not a formal case answer.

`case.json`: `{"case_id":"synthetic-demo"}`

Write `plan.json`:

```json
{
  "mode":"create", "canvas":[900,300], "title":"Synthetic treatment comparison",
  "formats":["png","pdf"], "dpi":300,
  "caption":"Synthetic interface demonstration only: A and B label illustrative samples, not a measured result.",
  "elements":[
    {"id":"sample-a","tag":"ellipse","attrs":{"cx":170,"cy":150,"rx":100,"ry":65,"fill":"#dbeafe","stroke":"#1e40af"}},
    {"id":"label-a","tag":"text","text":"Sample A","attrs":{"x":170,"y":158,"text-anchor":"middle"}},
    {"id":"label-b","tag":"text","text":"Sample B","attrs":{"x":700,"y":158,"text-anchor":"middle"}},
    {"id":"transfer","tag":"line","layer":"relations","arrow":"arrow","attrs":{"x1":285,"y1":150,"x2":595,"y2":150,"stroke":"#334155","stroke-width":3}}
  ],
  "element_map":[
    {"element":"sample-a","source":"synthetic-input.md:L1","claim":"illustrative sample A"},
    {"element":"label-a","source":"synthetic-input.md:L1"},
    {"element":"label-b","source":"synthetic-input.md:L2"},
    {"element":"transfer","source":"synthetic-input.md:L3","claim":"illustrative transfer direction A to B"}
  ],
  "uncertainty":["Synthetic example, no experimental conclusion."]
}
```

Run `python scripts/deliver.py --case case.json --plan plan.json --out work/demo`.
Inspect the actual image; do not use this generic shape as a substitute for biology from a real case.

For existing SVG edits:

```json
{
  "mode":"edit", "source_svg":"/input/figure03.svg",
  "operations":[
    {"id":"protein-label","text":"Corrected name","basis":"task.md requested correction; primary.pdf p4 Fig3"},
    {"find":"exact old leaf text","text":"exact new leaf text","basis":"task.md requested correction"}
  ],
  "element_map":[{"element":"protein-label","source":"primary.pdf p4 Fig3; figure03.svg#protein-label"}],
  "caption":"Write the actual source-derived figure caption here.",
  "uncertainty":[], "result_fields":{}
}
```

Each operation must match exactly one element. If a `text` element contains child tspans, edit its leaf tspan ID or use exact leaf `find`; replacing a rich text parent would discard styling and is rejected. `attrs` can change a target's fill/font-size/other SVG attributes, preserving the remaining attributes and children; ID and active/href changes are rejected. Scientific edits need actual evidence. No operations means `edit` fails; `copy` is available to validate/export a complete agent-authored SVG without changing it.

For charts and rich biomolecular diagrams, use the model's data analysis and SVG coding ability or available plotting library to author a complete SVG. Set `mode:copy`, `source_svg`, evidence map, caption and any task-specific fields. This exports the actual authored SVG, including curves, tspans and marker definitions; it does not reconstruct a simplified diagram.

When exact leaf matching selects text without an ID, put the leaf's stable XPath in `element_map[].element`; paths use namespace-independent SVG tag names with same-tag sibling indices. For example `/svg[1]/g[1]/text[1]/tspan[2]`. The helper records both that XPath and before/after XML. Relative linked resources are unsupported by this relocatable helper; it blocks them explicitly instead of producing an apparently valid but incomplete image. Data-URI embedded images and internal `#marker`/`#clipPath` references are supported. The PDF export record reports whether the source contains raster images; it does not claim that embedded bitmaps became vectors.
