# Known limitations

This skill is deliberately honest about what it cannot verify. It prefers a clear
`blocked` / `partial` over a plausible-looking but ungrounded figure.

## Material geometry

- The figure is **schematic, not to scale**. We never invent dimensions; the scale bar
  says `示意，非等比 / not to scale` unless the case supplies explicit lengths.
- Missing coordinates are laid out automatically (serpentine grid + stage cards). The
  result is readable but not a CAD drawing; reuse the editable `spec.json` to refine.
- Scanned PDFs and raster images without a text layer cannot be read reliably. When no
  other material yields components, the skill returns `blocked` and names the files it
  tried; it does not OCR-guess (no OCR library is assumed).

## Extraction precision

- Chinese/English device nouns are recognised from a curated suffix list
  (`反应器/冷凝器/泵/阀/瓶/罐/…`) plus explicit structured fields. Unusual equipment
  names may be missed (→ fewer parts) or a verb phrase may look like a device
  (→ extra part). Every accepted element is traceable in `element_map`; check `quote`.
- Connections use explicit verbs (`送入/接入/经/通过/→`). A flow implied across
  sentences is marked `inferred` and drawn dashed.
- Step parsing handles `步骤1:` / `1.` / `Step 1:` forms. Parallel branches are
  flattened to sequential `depends_on` by default and flagged in `uncertainty`.
- Duplicate device names are merged by name/id. If two identical devices are genuinely
  distinct (e.g. two valves), give them distinct ids in a structured `parts` list.

## Rendering

- SVG always uses real `<text>` (no outlined text) and is editable.
- PNG/PDF prefer cairosvg → rsvg-convert → inkscape → matplotlib → stdlib raster.
  If only the stdlib raster is available, CJK text is authoritative in the SVG and the
  preview is layout-only; `status` is downgraded to `partial`.
- SVG **edit** mode needs an SVG rasterizer to also emit PNG/PDF. Without one, the
  edited SVG, before/after hashes and change list are the verified deliverable, and
  `status=partial` (no PNG is fabricated).

## Contract

- Contract fields with no canonical producer are emitted as `null` and listed in
  `unmapped_contract_fields`; they are never silently dropped or nested under `fields`.
- `status=ok` is only possible with SVG + connections + non-empty PNG/PDF + passing
  selfcheck + at least two route stages. Everything else is `partial` or `blocked`.

## Not covered

- Statistical charts (use `source-traced-figure`), photo-realistic illustration,
  pixel editing of PNGs, OCR of scans, or engineering dimension tolerance.
