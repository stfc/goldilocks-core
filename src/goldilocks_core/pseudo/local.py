"""Add pseudopotentials Core did not install, and remember that they exist.

A user with pseudopotentials of their own -- generated in-house, or from a
library Core has not registered -- can already run against them: ``--pseudo-root
PATH`` bypasses the registry entirely, because the read layer scans disk rather
than consulting a catalogue. What they cannot get out of a bare directory is a
**cutoff**. Installed tables carry a sidecar holding each element's recommended
cutoff and the table-level relativistic and accuracy stamps; a hand-assembled
directory has none, so selection finds the pseudopotentials, cannot recommend a
basis, and reports the elements as uncovered.

``add`` closes that: it copies a directory under the pseudopotential root, writes
the same sidecar an installed table gets, and records the table in a registry
beside the user's own files. From that point the table is indistinguishable from
a fetched one -- it lists, it is selected from, and it deletes.

One rule shapes the interface, and every argument here follows from it:

**Table-level facts are supplied; element-level facts are read.** The functional,
the relativistic mode, the accuracy tier and the licence are properties of the
collection, not of any file in it -- exactly the facts stfc/goldilocks-core#150
and #152 moved out of per-file guessing. Which element a file holds, what type it
is and what cutoff it wants are properties of the file, so they come from
``parse_upf``, and a directory ``parse_upf`` cannot answer for is rejected rather
than half-added. Retyping per-element data that is already in the files invites a
transcription error no later check would catch.

Public tables everyone would want -- a new SSSP release, a new PseudoDojo version
-- do not belong here. Those go in the packaged registry, where their sizes and
digests are measured rather than taken on trust, so that every user benefits.
This is for pseudopotentials that should never be shipped to anyone else.
"""

from __future__ import annotations

import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from goldilocks_core.pseudo.install import pseudo_root
from goldilocks_core.pseudo.parse_upf import parse_upf_folders
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.pseudo.table_registry import (
    FILE_RELATIVISTIC,
    LOCAL_PROVIDER,
    PseudoTable,
    load_local_tables,
    load_tables,
    local_registry_path,
)

ADD_COMMAND = "gl pp add"
"""What a user runs to add pseudopotentials of their own."""

_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
"""A name becomes a directory under the cache and an argument to ``rmtree``."""

_RELATIVISTIC_SUFFIX = {"SR": "-sr", "FR": "-fr", "NR": "-nr"}
"""Every registered name ends this way; an added one is held to it too."""

UNSTATED = "not stated"
"""Shown where a user gave no licence or citation, rather than implying one."""


class NotAddable(ValueError):
    """A directory cannot be added as a table, and the message says why."""


def canonical_name(name: str, relativistic: str) -> str:
    """Return ``name`` bearing the suffix its relativistic mode requires.

    Names are read, not just typed: a user picks a table out of ``gl pp
    available`` by reading the functional and relativistic mode off its name,
    and a table that broke the convention would be the one nobody could place.
    Appending is silent because the mode was already given as a flag -- there is
    nothing to confirm, only a spelling to settle.
    """
    suffix = _RELATIVISTIC_SUFFIX[relativistic]
    return name if name.endswith(suffix) else f"{name}{suffix}"


def add(
    source: Path,
    *,
    name: str,
    functional: str,
    relativistic: str,
    accuracy: str,
    version: str = "local",
    licence: str = UNSTATED,
    citation: str = UNSTATED,
    root: Path | None = None,
) -> PseudoTable:
    """Add the pseudopotentials in ``source`` as a table, and return it.

    Args:
        source: a directory of ``*.upf`` files. Copied, not referenced, so the
            table survives the original being moved or deleted, and so ``gl pp
            delete`` has something of its own to remove.
        name: what to call it. Given the relativistic suffix if it lacks one.
        functional, relativistic, accuracy: table-level classification, in the
            registry's vocabulary.
        version, licence, citation: recorded and shown, never interpreted.
        root: pseudopotential root. Defaults to the user cache.

    Raises:
        NotAddable: the name is unusable or taken, the directory holds no
            pseudopotentials, or ``parse_upf`` cannot read an element or a
            cutoff pair out of one of them. Nothing is copied in that case.
    """
    if relativistic not in _RELATIVISTIC_SUFFIX:
        raise NotAddable(
            f"relativistic must be one of {', '.join(_RELATIVISTIC_SUFFIX)}, "
            f"not {relativistic!r}"
        )

    name = canonical_name(name, relativistic)
    if _SAFE_NAME.fullmatch(name) is None:
        raise NotAddable(
            f"{name!r} is not usable as a table name. Letters, digits and "
            "'.', '_', '+', '-' only, starting with a letter or digit: the name "
            "becomes a directory under the pseudopotential root."
        )

    existing = load_tables().get(name)
    if existing is not None:
        raise NotAddable(
            f"a table called {name} already exists"
            + (
                f"; remove it with `gl pp delete {name}` first"
                if existing.provider == LOCAL_PROVIDER
                else f", published by {existing.provider}. Choose another name."
            )
        )

    source = Path(source)
    if not source.is_dir():
        raise NotAddable(f"{source} is not a directory")

    cutoffs = _read_cutoffs(source)

    base = root or pseudo_root()
    destination = base / LOCAL_PROVIDER / name
    sidecar = base / LOCAL_PROVIDER / f"{name}.json"
    if destination.exists() or sidecar.exists():
        raise NotAddable(
            f"{name} already has files under {base}; remove them or choose another name"
        )

    copied = _copy_pseudos(source, destination)
    payload = json.dumps(
        {
            "_relativistic": FILE_RELATIVISTIC[relativistic],
            "_accuracy": accuracy,
            **cutoffs,
        },
        indent=2,
    )
    sidecar.write_text(payload, encoding="utf-8")

    table = PseudoTable(
        name=name,
        provider=LOCAL_PROVIDER,
        upstream_table=name,
        version=version,
        functional=functional,
        relativistic=relativistic,
        accuracy=accuracy,
        licence=licence,
        upstream_url=str(source.resolve()),
        citation=citation,
        elements=tuple(sorted(cutoffs)),
        installed_bytes=sum(path.stat().st_size for path in copied)
        + len(payload.encode()),
        note=f"added from {source.resolve()}; Core cannot re-fetch it",
    )
    _remember(table)

    return table


def forget(name: str) -> None:
    """Drop ``name`` from the local registry, leaving files alone.

    Called when an added table is deleted. Without it the entry would outlive
    its pseudopotentials and list forever as uninstalled, with nothing able to
    install it: there is no upstream to fetch a local table from.
    """
    remaining = {
        table_name: table
        for table_name, table in load_local_tables().items()
        if table_name != name
    }
    _write_local(remaining)


def _read_cutoffs(source: Path) -> dict[str, dict[str, float]]:
    """Return each element's cutoff pair, or refuse to add the directory.

    Every fact here is element-level, so every one of them is read out of the
    files. A directory that cannot answer is rejected outright rather than added
    and left unusable: the same "omit rather than fabricate" policy the fetched
    tables apply to elements whose upstream report carries no hint, moved earlier
    to where the user can still do something about it.
    """
    parsed = parse_upf_folders(source)
    if not parsed:
        raise NotAddable(f"{source} contains no .upf files")

    unnamed = [Path(m.filepath).name for m in parsed if not m.element]
    if unnamed:
        raise NotAddable(
            "cannot tell which element these are for, from either their header "
            f"or their filename: {', '.join(sorted(unnamed))}"
        )

    _reject_duplicate_elements(parsed)

    cutoffs: dict[str, dict[str, float]] = {}
    uncut: list[str] = []
    for metadata in parsed:
        pair = metadata.sssp_recommended_cutoff
        if (
            not isinstance(pair, dict)
            or not pair.get("ecutwfc_ry")
            or not pair.get("ecutrho_ry")
        ):
            uncut.append(f"{metadata.element} ({Path(metadata.filepath).name})")
            continue

        cutoffs[str(metadata.element)] = {
            "cutoff_wfc": float(pair["ecutwfc_ry"]),
            "cutoff_rho": float(pair["ecutrho_ry"]),
        }

    if uncut:
        raise NotAddable(
            "these declare no recommended cutoff, so no input could be written "
            f"from them: {', '.join(sorted(uncut))}. A UPF header has to give "
            "both wfc_cutoff and rho_cutoff. There is no flag for it: a cutoff "
            "belongs to the pseudopotential, and one value typed for a whole "
            "table would be wrong for most of its elements."
        )

    return cutoffs


def _reject_duplicate_elements(parsed: list[PseudoMetadata]) -> None:
    """Refuse a directory holding two pseudopotentials for the same element.

    The reader ranks several candidates for an element happily. A sidecar cannot:
    it is keyed by element, so one of the two cutoffs would silently win.
    """
    by_element: dict[str, list[str]] = defaultdict(list)
    for metadata in parsed:
        by_element[str(metadata.element)].append(Path(metadata.filepath).name)

    clashes = {
        element: names for element, names in by_element.items() if len(names) > 1
    }
    if clashes:
        listed = "; ".join(
            f"{element}: {', '.join(sorted(names))}"
            for element, names in sorted(clashes.items())
        )
        raise NotAddable(
            f"more than one pseudopotential per element, which leaves the "
            f"recommended cutoff ambiguous: {listed}"
        )


def _copy_pseudos(source: Path, destination: Path) -> list[Path]:
    """Copy the pseudopotentials into ``destination`` and return what landed."""
    destination.mkdir(parents=True, exist_ok=True)

    copied = []
    for path in sorted(source.glob("*.upf", case_sensitive=False)):
        target = destination / path.name
        shutil.copyfile(path, target)
        copied.append(target)

    return copied


def _remember(table: PseudoTable) -> None:
    """Record ``table`` in the local registry, preserving what is already there."""
    _write_local({**load_local_tables(), table.name: table})


def _write_local(tables: dict[str, PseudoTable]) -> None:
    """Rewrite the local registry from ``tables``.

    Hand-serialised because the standard library reads TOML and does not write
    it, and a dependency for six scalar fields would be a poor trade. Strings go
    through ``json.dumps``, whose escaping a TOML basic string shares.
    """
    path = local_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if not tables:
        path.unlink(missing_ok=True)
        return

    blocks = [
        "# Pseudopotential tables added with `gl pp add`.\n"
        "#\n"
        "# Written by Core, not by hand: the entries describe files it copied,\n"
        "# and editing one here would not move them. Add and delete instead.\n"
    ]
    for name, table in tables.items():
        fields = {
            "provider": table.provider,
            "upstream_table": table.upstream_table,
            "version": table.version,
            "functional": table.functional,
            "relativistic": table.relativistic,
            "accuracy": table.accuracy,
            "licence": table.licence,
            "upstream_url": table.upstream_url,
            "citation": table.citation,
            "note": table.note,
        }
        lines = [f"[tables.{json.dumps(name)}]"]
        lines += [f"{key} = {json.dumps(value)}" for key, value in fields.items()]
        lines.append(f"elements = {json.dumps(list(table.elements))}")
        lines.append(f"installed_bytes = {table.installed_bytes}")
        blocks.append("\n".join(lines) + "\n")

    path.write_text("\n".join(blocks), encoding="utf-8")
