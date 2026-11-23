# Output contract — `result.json`

`result.json` is written by `scripts/kernel.py emit` to `/app/output/result.json`.
It is the machine-checkable face of the deliverable: **every contract field appears**,
values keep the type the case asked for (dict / list / string / nested), and contract
values are **never** nested under an extra `fields` object.

The producer also writes `contract_fields` (ordered names found in the case) and
`unmapped_contract_fields` (contract names with no canonical producer, emitted as `null`).

## Canonical fields

| Field | Type | Meaning |
|-|-|-|
| `case_id` | string | Case id from `case.json`; falls back to `local-<hash>` |
| `status` | string | `ok` / `partial` / `blocked` / `failed` |
| `source_file` | string | Primary figure, e.g. `route.svg` (empty string when blocked) |
| `exports` | list[dict] | Rasterized files: `{path, format, width_px, height_px, dpi, engine}` |
| `preview` | dict | `{status, notes}`; `status=ok` only with a real PNG, else `unavailable` |
| `extraction` | dict | `{mode, files, coverage, warnings}` |
| `element_map` | list[dict] | One row per component / connection / stage (see below) |
| `parts` | list[dict] | Components with `id,label,type,status,evidence,quote,data_ref,sub` |
| `connections` | list[dict] | `id,from,to,kind,direction,status,evidence,quote,data_ref` |
| `stages` | list[dict] | `id,order,label,objective,methods,inputs,outputs,depends_on,milestone,status,evidence,quote` |
| `route_graph` | dict \| null | The graph actually rendered (`parts/connections/stages/units/scale_bar`) |
| `legend` | list[dict] | Line-type legend items shown on the figure |
| `units` | dict | Unit labels parsed from the case/material (e.g. `flow=mL/min`) |
| `scale_bar` | dict | Scale marker: `{label, kind, note}`; qualitative if no lengths |
| `figure_png` | string \| null | `route.png` when a real PNG exists |
| `figure_pdf` | string \| null | `route.pdf` when a real PDF exists |
| `caption` | string | Figure caption; also written to `caption.md` |
| `selfcheck` | dict | `{ok, verdict, checks, errors, warnings, stats}` |
| `deliverables` | list[dict] | Every artifact: `{path, role, format, exists, bytes, sha256}` |
| `sources` | list[string] | Source locators / files used |
| `limits` | string | Limitations joined with ` \| ` (per the default graphics contract; `uncertainty` stays an array) |
| `uncertainty` | list[string] | Inferred elements, unspecified dimensions, unresolved items |
| `change_log` | string | What changed; for edits includes before/after sha256 |
| `metrics` | dict | Counts: `parts, connections, stages, element_map, typed_parts` |
| `title` | string | Figure title |
| `element_map_file` | string | `element_map.json` |
| `caption_file` | string | `caption.md` |
| `change_details` | dict | Full edit log (edit mode) or extraction mode |
| `success` | bool | `status == "ok"` |

Producer-only keys are harmless: extra keys beyond the contract are retained.

## `element_map` row

```json
{
  "element": "reactor",
  "label": "固定床反应器",
  "type": "part",              // part | connection | stage | legend | units | scale | edit
  "subtype": "reactor",
  "source": "protocol.md:L3",  // locator; "generated:*" for generated helpers
  "locator": "protocol.md:L3",
  "quote": "装置由原料瓶、蠕动泵、固定床反应器、冷凝器和产物收集瓶组成。",
  "data_ref": "protocol.md:L3",
  "status": "stated"           // stated | inferred | generated
}
```

Rules enforced by `kernel.py check` and `route_check.py`:

1. `part`, `connection`, `stage` rows must carry a source locator; a missing locator
   demotes the row to `inferred`.
2. `quote` must be a verbatim excerpt when `status=stated`.
3. `legend`, `units`, `scale` are `generated` (derived from connection kinds/spec).
4. No element may be invented: every component must appear in the source text or in a
   structured `parts` field.

## Status policy

```
blocked  : 0 components, 0 directed connections, 0 real route steps (placeholder stage
           does not count), unreadable/malformed case, or scan with no text layer.
           selfcheck=FAIL; no route.svg/png/pdf is written; reason + checked files/lines
           go in limits/uncertainty.
partial  : diagram produced but any of: <2 stages, missing PNG/PDF, selfcheck not ok,
           or SVG-edit without a rasterizer.
ok       : SVG + >=1 connection + >=1 real step + non-empty PNG & PDF + selfcheck.ok.
```

Missing milestone is **not** a hard failure: it produces a warning plus an uncertainty
line, and never a fabricated milestone marker.

`ok` is never reported when a declared deliverable is missing: `kernel.py emit`
downgrades to `partial` and appends an uncertainty line.

## Example (abbreviated)

```json
{
  "case_id": "demo-001",
  "status": "ok",
  "source_file": "route.svg",
  "exports": [{"path":"route.png","format":"png","engine":"matplotlib"},
              {"path":"route.pdf","format":"pdf","engine":"matplotlib"}],
  "preview": {"status":"ok","notes":[]},
  "extraction": {"mode":"text_candidates","files":["protocol.md"],
                 "coverage":{"mentions":9},"warnings":[]},
  "element_map": [{"element":"reactor","label":"固定床反应器","type":"part",
                   "source":"protocol.md:L3","locator":"protocol.md:L3",
                   "quote":"装置由原料瓶、蠕动泵、固定床反应器、冷凝器和产物收集瓶组成。",
                   "status":"stated"}],
  "parts": [{"id":"reactor","label":"固定床反应器","type":"reactor","status":"stated"}],
  "connections": [{"id":"c1","from":"pump","to":"reactor","kind":"flow",
                   "status":"stated","evidence":"protocol.md:L4"}],
  "stages": [{"id":"s1","order":1,"label":"装填催化剂并检查气密性","status":"stated"}],
  "caption": "固定床加氢评价装置：5 个部件、4 条流向、3 个步骤…",
  "selfcheck": {"ok": true, "verdict": "PASS"},
  "deliverables": [{"path":"route.svg","role":"figure_svg","exists":true,"bytes":14066}],
  "limits": "Units were not specified; the figure is qualitative.",
  "uncertainty": ["unspecified dimension: 反应器床层高度未给出 (protocol.md:L6)"],
  "sources": ["protocol.md"],
  "change_log": "initial generation from 1 material file; no manual edits",
  "metrics": {"parts":5,"connections":4,"stages":3,"element_map":15}
}
```

## Alias tolerance

Case fields are matched case-insensitively and across common spellings. Examples:

| Contract spelling | Canonical |
|-|-|
| `steps`, `phases`, `milestones` | `stages` |
| `components`, `equipment`, `devices` | `parts` |
| `links`, `pipes`, `edges`, `flows` | `connections` |
| `legend`, `figcaption` | `caption` |
| `editlog`, `changes`, `diff` | `change_log` |
| `provenance`, `sourcemap` | `element_map` |
| `limits`, `caveats` | `limits` |
| `uncertainties`, `unknowns` | `uncertainty` |
| `装置清单`, `部件清单`, `设备清单` | `parts` |
| `连接关系`, `连线`, `流向` | `connections` |
| `技术路线`, `步骤`, `阶段` | `stages` |
| `图注`, `图题` | `caption` |
| `自检`, `机检` | `selfcheck` |
| `证据`, `证据链`, `元素映射` | `element_map` |
| `限制`, `局限` | `limits` |
| `不确定度`, `不确定性` | `uncertainty` |

Chinese contract keys are preserved by `kernel.norm()` and mapped through
`ZH_ALIASES`; they are no longer stripped to an empty string.

`output_contract` itself may be a list of names, a JSON-schema object
(`{"properties": {...}}`), an array of `{name|key|field}` objects, or a comma/newline
string; all four are parsed.
