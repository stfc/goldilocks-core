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
- **data_source**: concise supporting-data identity (for example, model name/revision and configuration digest, pseudo library, or SSSP version).
- **confidence**: optional score in [0, 1]. The default QRF Kmesh backend records its configured interval confidence.
- **details**: optional structured JSON metadata. Successful QRF inference stores its reproducibility record under `details.qrf_inference`.
- **warnings**: caveats about this choice. Read these even if the source seems authoritative.

## QRF inference details

A model-backed QRF selection records:

- the SHA-256 digest and complete structured registry configuration;
- goldilocks-core version and extractor identity, feature schema, and feature count;
- feature settings, interval confidence/quantiles, and calibration method/correction;
- every required and installed inference runtime version;
- QRF model, metallicity checkpoint, and atom-table identities.

Remote artifacts are identified by repository, filename, and immutable commit.
Local QRF, checkpoint, and atom-table files include their path and SHA-256
content hash. Paths alone are not artifact identities.

## Warning propagation

Warnings flow through the pipeline in two parallel paths:

1. **Provenance-level warnings**: each `Provenance` record carries its own `warnings` tuple. These are specific to that one decision — e.g. "SOC is not enabled automatically because it changes cost and setup" on `SpinOrbitAdvice.provenance`.

2. **Aggregate warnings**: `CoreResult.warnings` collects and de-duplicates warnings from Analyze, Advise, Kmesh, and Select in first-seen order. These are the top-level warnings every caller should surface. Each `StageRecord.warnings` retains the warnings owned by that stage.

Advice warnings remain attached to their individual provenance records as well as appearing in the aggregate, so callers can show a complete warning summary without traversing every decision record.

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
print(result.selection.k_points.provenance.details["qrf_inference"]["config_digest"])

# Why is SOC considered but not enabled?
print(result.advice.spin_orbit.provenance.source)  # "analysis"
print(result.advice.spin_orbit.provenance.reason)  # "Period-5-or-heavier elements make SOC worth considering."
print(result.advice.spin_orbit.provenance.warnings) # ("SOC is not enabled automatically because ...",)
```