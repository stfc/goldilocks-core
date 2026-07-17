# Bundle stage

Owner: `bundle.py`

The Bundle stage publishes a portable output directory containing generated input files and a `manifest.json` that records the full provenance chain.

## Input

- `CoreResult` with generated files
- Output directory path

## Output

- `BundleRecord` with the output directory path and manifest dictionary
- `manifest.json` file
- Generated input files under `inputs/`

## Directory layout

```text
{output_dir}/
├── manifest.json
└── inputs/
    └── qe.in
```

Pseudopotential files are not copied. If the caller needs pseudo files, they must copy them separately using the paths in `PseudopotentialSelection.filepath`.

## Manifest schema

See [bundle manifest](../manifest.md) for the versioned schema and field reference.

The manifest is written with `json.dumps(indent=2, sort_keys=True)` for deterministic output. Each generated-file entry records the UTF-8 byte count and SHA-256 digest of the exact bytes written.

## Publication boundary

The output directory must not exist. Bundle refuses existing files, directories, and symlinks; there is no destructive overwrite mode.

Before creating output, Bundle reapplies the inherited `GeneratedFile` and `CoreResult` construction checks, resolves every generated path, and rejects manifest or file/directory layout conflicts. Collision checks use the target platform's semantics: Windows treats backslashes as separators and compares path components case-insensitively. For a Windows target, each component is also rejected when it ends in a period or space, is a reserved DOS device name (including extensions), contains an ASCII control character or one of `"`, `*`, `:`, `<`, `>`, `?`, or `|`; colon rejection also excludes alternate data stream syntax. POSIX preserves distinct legal backslash, case, and Windows-reserved variants. It then writes the complete bundle to a unique sibling staging directory on the destination filesystem. The staging directory is atomically renamed to the absent destination with a native no-replace operation on Linux, macOS, and Windows. Other platforms fail explicitly rather than weakening the no-overwrite guarantee.

If writing or publication fails, Bundle attempts staging cleanup up to twice and preserves the original exception. A cleanup or staging-existence-probe failure is attached to that exception as a note, including the staging path and whether residue remains or cannot be verified. After publication succeeds, the same cleanup or probe problem emits a non-fatal `RuntimeWarning` instead: the returned bundle remains successfully published. Bundle cannot guarantee staging removal or verification after arbitrary filesystem failures; it does not publish a completed destination bundle or modify an existing destination.

## Path traversal protection

`GeneratedFile` rejects empty, absolute, or `..`-traversing paths at construction. `CoreResult` rejects duplicate normalized generated paths, so a custom Generate backend cannot pass either condition to Bundle. Bundle reapplies those contract checks and resolves each path beneath the output directory as a defensive filesystem check before staging. The additional Windows component rules are enforced by Bundle only when its target platform is Windows; they are not a global `GeneratedFile` restriction.

## What the bundle does not do

- It does not copy pseudopotential files into the bundle directory.
- It does not include the structure file.
- It does not execute calculations.
- It does not depend on Runner, AiiDA, or frontend assumptions.

## Building a manifest without writing files

`build_bundle_manifest()` returns the manifest dictionary without writing to disk. Useful for JSON API responses that don't need directory output.