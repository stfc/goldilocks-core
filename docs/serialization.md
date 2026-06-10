# Serialization

All staged pipeline data records support JSON-safe serialization via `to_dict()`. This is the contract for CLI `--json` output, future HTTP API responses, and manifest content.

`Pipeline` is intentionally not serialized. It contains Python callables that configure how stages run. `CoreJobRequest` and `CoreJobResult` remain the serializable request/response boundary.

## Type conversions

The `to_jsonable()` function converts pipeline values to JSON-safe Python objects:

| Input type | Output | Notes |
| --- | --- | --- |
| dataclass | dict | Field names map to converted values |
| tuple | list | All items converted recursively |
| list | list | All items converted recursively |
| dict | dict | Keys converted to strings, values converted |
| `Path` | str | `str(path)` |
| `pymatgen Structure` | dict | `structure.as_dict()` — full pymatgen serialization |
| `numpy.ndarray` | list | `array.tolist()` |
| `numpy scalar` | Python scalar | `scalar.item()` |
| `None` | None | Passed through |
| `str`, `int`, `float`, `bool` | unchanged | Passed through |

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
    "accuracy_level": "standard",
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
- Circular references are not handled. Core records are acyclic, so this should not occur in practice.
- `Pipeline` callables are not JSON values. A CLI or HTTP layer that exposes backend names must resolve those names to callables outside Core.