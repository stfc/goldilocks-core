# Bundle stage

Owner: `bundle.py`

The Bundle stage writes a portable output directory containing generated input files and a `manifest.json` that records the full provenance chain.

## Input

- `CoreResult` from the completed pipeline (generate mode or bundle mode).
- `output_dir`: a new directory path. The parent directories are created if needed; the bundle directory itself must not already exist.

## Output

- `BundleRecord` with the bundle path and manifest dictionary.

## Layout

```text
run/
├── manifest.json
└── inputs/
    └── qe.in
```

`inputs/qe.in` is the current generated file for Quantum ESPRESSO SCF jobs.

Pseudopotential files are not copied. If the caller needs pseudo files, they must stage them separately.

## Manifest

See [bundle manifest](../manifest.md) for the versioned schema and field reference.

The manifest is written with `json.dumps(indent=2, sort_keys=True)` for deterministic output. Each generated-file entry records its bundle path and role.

## Output boundary

The output directory must not exist. Bundle refuses existing files and directories; there is no destructive overwrite mode. If a write fails, the incomplete new directory may remain for the caller to inspect or remove.

## Path traversal protection

`GeneratedFile` rejects empty, absolute, or `..`-traversing paths at construction. `CoreResult` rejects duplicate normalized generated paths, so a custom Generate backend cannot pass either condition to Bundle. Bundle reapplies the filesystem check and also rejects any generated path that would collide with `manifest.json`.

## What the bundle does not do

- It does not copy pseudopotential files.
- It does not run calculations.
- It does not overwrite existing output directories.
