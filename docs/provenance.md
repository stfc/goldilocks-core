# Provenance

Every scientific recommendation and selection in goldilocks-core carries a `Provenance` record explaining why that value was chosen. This is the accountability mechanism: callers can inspect provenance to understand which values come from analysis, which from operator hints, and which from package defaults.

## Source types

| Source | Meaning | Example |
| --- | --- | --- |
| `analysis` | Derived from structure facts | Heavy elements detected → SOC worth considering |
| `user_hint` | Explicitly provided by the operator via `CalculationHints` | `k_grid=(4, 4, 4)` → use that exact grid |
| `default` | Package-level default when no analysis or hint applies | No magnetic elements → spin_polarized=False |
| `model` | ML model prediction | QRF k-distance prediction → k-mesh selection |
| `lookup` | Resolved from supplied metadata | Pseudo registry match → PseudoMetadata selection |
| `fallback` | No matching data was available; the value is a placeholder | No pseudo metadata provided → filename=None |

## Provenance fields

- **source**: one of the types above. The primary classification.
- **reason**: human-readable explanation of the choice. Read this to understand the decision.
- **data_source**: where the supporting data came from (e.g. model artifacts and revisions, compatible serialization runtime, pseudo library, SSSP version). Populated for `model` and `lookup` sources. QRF selections identify both the QRF and metallicity feature artifacts, including local overrides.
- **confidence**: optional score in [0, 1]. The default QRF Kmesh backend records its configured interval confidence.
- **warnings**: caveats about this choice. Read these even if the source seems authoritative.

## Warning propagation

Warnings flow through the pipeline in two parallel paths:

1. **Provenance-level warnings**: each `Provenance` record carries its own `warnings` tuple. These are specific to that one decision — e.g. "SOC is not enabled automatically because it changes cost and setup" on `SpinOrbitAdvice.provenance`.

2. **Aggregate warnings**: `CoreResult.warnings` collects warnings from analysis, Kmesh, and selection stages. These are the top-level warnings a caller should surface.

Advice-level provenance warnings are preserved in nested advice records but are **not** all aggregated into the top-level `warnings` tuples. A JSON caller should inspect nested advice provenance directly when a specific decision matters.

## Interpreting provenance

The source determines how much trust to place in a value:

- **`user_hint`**: the operator explicitly chose this. Trust it unless it conflicts with physics.
- **`analysis`**: derived from structure facts with known limitations. Check the warnings.
- **`model`**: ML prediction. Check `data_source` for the model identity and `confidence` if populated.
- **`default`**: the package chose this because no better information was available. Override if you have domain knowledge.
- **`lookup`**: resolved from metadata you supplied. Only as good as the metadata.
- **`fallback`**: nothing was available. This value is a placeholder. You must override it.

## Example

```python
from goldilocks_core import recommend

result = recommend("structure.cif")

# Why was k-spacing advised?
print(result.advice.k_points.provenance.source)   # "default"
print(result.advice.k_points.provenance.reason)   # "Use the default VASP-style k-point spacing."

# How was the concrete grid selected?
print(result.selection.k_points.provenance.source)  # "model" or fallback source
print(result.selection.k_points.provenance.confidence)  # configured QRF confidence

# Why is SOC considered but not enabled?
print(result.advice.spin_orbit.provenance.source)  # "analysis"
print(result.advice.spin_orbit.provenance.reason)  # "Period-5-or-heavier elements make SOC worth considering."
print(result.advice.spin_orbit.provenance.warnings) # ("SOC is not enabled automatically because ...",)
```