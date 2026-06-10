# Bundle stage

Owner: `bundle.py`

The Bundle stage writes a portable output directory containing generated input files and a `manifest.json` that records the full provenance chain.

## Input

- `CoreRecommendation` with generated files
- Output directory path

## Output

- `manifest.json` file
- Generated input files under `inputs/`
- JSON-safe manifest dictionary (returned to the caller)

## Directory layout

```text
{output_dir}/
├── manifest.json
└── inputs/
    └── qe.in
```

Pseudopotential files are not copied. If the caller needs pseudo files, they must copy them separately using the paths in `PseudopotentialSelection.filepath`.

## Manifest schema

```json
{
  "manifest_version": 1,
  "intent": { ... },
  "analysis": { ... },
  "advice": { ... },
  "selection": { ... },
  "generated_files": [
    {
      "path": "inputs/qe.in",
      "role": "input",
      "bytes": 456
    }
  ],
  "warnings": ["..."]
}
```

### Fields

| Field | Type | Description |
| --- | --- | --- |
| `manifest_version` | int | Schema version. Currently always `1`. |
| `intent` | dict | Serialized `CalculationIntent`. |
| `analysis` | dict | Serialized `StructureAnalysisRecord`. |
| `advice` | dict | Serialized `ParameterAdvice`. |
| `selection` | dict | Serialized `SelectionRecord`. |
| `generated_files` | list | File metadata: `path`, `role`, `bytes`. Content is not included in the manifest. |
| `warnings` | list[str] | Aggregated warnings from the recommendation. |

The manifest is written with `json.dumps(indent=2, sort_keys=True)` for deterministic output.

## Versioning

`manifest_version` is an integer. Increment it when the schema changes incompatibly. Version 1 is the initial schema.

## Path traversal protection

`_resolve_bundle_path()` resolves each generated file path relative to the output directory and rejects paths that escape the bundle root. A `GeneratedFile(path="../outside.in")` will raise `ValueError`.

## What the bundle does not do

- It does not copy pseudopotential files into the bundle directory.
- It does not include the structure file.
- It does not execute calculations.
- It does not depend on Runner, AiiDA, or frontend assumptions.

## Building a manifest without writing files

`build_bundle_manifest()` returns the manifest dictionary without writing to disk. Useful for JSON API responses that don't need directory output.