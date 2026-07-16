# Serialization

All staged pipeline data records support JSON-safe serialization via `to_dict()`. This is the contract for CLI `--json` output, HTTP API responses, and [manifest](manifest.md) content.

The request-boundary records also deserialize from their `to_dict()` form via `from_dict` classmethods: `CalculationIntent.from_dict`, `CalculationHints.from_dict`, `CoreJobRequest.from_dict`, and `PseudoMetadata.from_dict`. They reject non-dicts and unknown keys, run the same `__post_init__` validators as Python construction, and are the shared JSON→domain path used by the HTTP transport (and intended for MCP). `CoreResult` is response-only and has no `from_dict`.

`Pipeline` is intentionally not serialized. It contains Python callables that configure how stages run. `CoreJobRequest` and `CoreResult` remain the serializable request/response boundary.

## Type conversions

The `to_jsonable()` function converts pipeline values to JSON-safe Python objects:

| Input type | Output | Notes |
| --- | --- | --- |
| dataclass | dict | Field names map to converted values |
| tuple | list | All items converted recursively |
| list | list | All items converted recursively |
| dict | dict | Supported scalar, enum, and path keys become strings; values are converted recursively; stringification collisions raise `ValueError` |
| `Enum` | converted enum value | The value is validated recursively |
| `Path` | str | `str(path)` |
| `pymatgen Structure` | dict | `structure.as_dict()` converted recursively |
| `numpy.ndarray` | list | `array.tolist()` converted recursively |
| `numpy scalar` | Python scalar | `scalar.item()` converted recursively |
| `None` | None | Passed through |
| `str`, `int`, finite `float`, `bool` | unchanged | Passed through |

`to_jsonable()` raises `ValueError` for NaN or infinity at any nesting depth. It raises `TypeError` for unsupported values or dictionary-key types instead of returning an object that `json.dumps()` cannot encode. Sets, complex numbers, callables, and arbitrary objects are not supported JSON values.

## Structured model provenance

`Provenance.details` is `null` for decisions without additional structured
metadata. Successful default QRF inference stores a JSON-safe reconstruction
record under `details.qrf_inference`, including the complete registry
configuration and digest, extractor/Core identity, runtime versions, and remote
commit or local SHA-256 artifact identities.

## Open-ended intervals

`KMeshEntry.k_distance_interval` represents an upper bound that is unbounded above as `null` (`None` in Python), rather than as `Infinity`. For example, `[0.2, null]` preserves the interval's unbounded upper endpoint while remaining RFC-compliant JSON. `to_jsonable()` continues to reject every non-finite JSON number at any nesting depth.

## None handling

`None` values are included in the output dict, not omitted. A field with value `None` appears as `"field_name": null` in JSON. This preserves schema consistency: callers can distinguish "field not present" from "field is None."

## Example output

For a silicon structure with default settings:

```json
{
  "intent": {
    "code": "quantum_espresso",
    "task": "scf_single_point",
    "functional": "PBE",
    "pseudo_mode": "efficiency"
  },
  "analysis": {
    "formula": "Si1",
    "reduced_formula": "Si",
    "site_count": 1,
    "elements": ["Si"],
    "contains_transition_metals": false,
    "contains_lanthanides": false,
    "contains_actinides": false,
    "contains_heavy_elements": false,
    "magnetic_elements": [],
    "heavy_elements": [],
    "disorder_warnings": [],
    "disordered_site_count": 0,
    "space_group_symbol": "Fd-3m",
    "space_group_number": 227,
    "crystal_system": "cubic",
    "dimensionality": "unknown",
    "electronic_character": "unknown",
    "analysis_warnings": ["..."]
  },
  "advice": {
    "k_points": {
      "spacing": 0.2,
      "explicit_grid": null,
      "mesh_type": "monkhorst-pack",
      "provenance": {
        "source": "default",
        "reason": "Use the default VASP-style k-point spacing.",
        "data_source": null,
        "confidence": null,
        "details": null,
        "warnings": []
      }
    },
    "smearing": { "..." : "..." },
    "magnetism": { "..." : "..." },
    "spin_orbit": { "..." : "..." },
    "pseudopotentials": { "..." : "..." },
    "convergence": { "..." : "..." }
  },
  "selection": {
    "k_points": {
      "grid": [8, 8, 8],
      "shift": [0, 0, 0],
      "mesh_type": "monkhorst-pack",
      "provenance": { "..." : "..." }
    },
    "pseudopotentials": [],
    "warnings": []
  },
  "generated_files": [],
  "warnings": ["..."]
}
```

## Limitations

- `pymatgen Structure` serialization produces a large nested dict. Callers that don't need the full structure may want to strip it.
- NumPy arrays are converted to nested lists. Very large feature vectors may produce large JSON output.
- NaN and infinity are deliberately rejected because RFC-compliant JSON has no representation for them.
- Circular references are not handled. Core records are acyclic, so this should not occur in practice.
- `Pipeline` callables are not JSON values. A CLI or HTTP layer that exposes backend names must resolve those names to callables outside Core.