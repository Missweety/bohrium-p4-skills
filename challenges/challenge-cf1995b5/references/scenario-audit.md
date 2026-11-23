# Finite-domain scenario audit

Input JSON fields: `domains` maps each decision parameter to its actual finite allowed values; `contracts` supplies `source`, numeric `budget_cap` and `availability` mapping resource names to `[start_h,end_h]` windows; `versions` contains three entries with `id`, `parameters`, `parameter_evidence` (name/source), `cost_items` (quantity/unit_price/source), and `bookings` (resource/start_h/end_h). Optional `power` has `design: two_independent_equal_variance_two_sided`, `n_per_group`, `difference`, `sd`, `alpha`, `target`, `source`. Use common time origin and consistent units.

Example only: domain `temperature:[20,25]`, budget 100, instrument A available 0–8 h; each candidate uses a sourced value, a sourced cost and a non-overlapping booking. It is synthetic and not an official case. Verify source transcription and unit conversions independently; no assumptions about future measured results.
