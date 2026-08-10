"""Install PseudoDojo pseudopotential tables from the upstream site.

PseudoDojo publishes its tables itself, so Core fetches them from the source
rather than from a copy. Nothing is redistributed, no licence notice has to be
carried forward, and the copy cannot drift from what upstream publishes.

A table is two archives whose URLs differ by one segment: ``<table>_upf.tgz``
holds the pseudopotentials and ``<table>_djrepo.tgz`` holds one dojo report per
element. The reports carry the digest of every UPF file, so integrity comes
from upstream even though we host nothing -- and because each file is checked
individually, a corrupt member is caught rather than only a corrupt download.

The reports also carry the recommended cutoffs, which the UPF files do not --
confirmed by inspecting a UPF header directly: ``rho_cutoff`` is a generation
parameter recorded alongside ``mesh_size`` and ``l_max``, not a converged-basis
recommendation, and it does not even move in the right direction (Si's is
larger than O's while Si needs the smaller basis). ``install`` writes those
cutoffs out as a sidecar next to the installed table, in the schema cutoff
discovery already reads, so PseudoDojo tables need no parser change.
"""

from __future__ import annotations

import json
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from goldilocks_core.artifacts import remote
from goldilocks_core.artifacts.cache import artifact_path, store_verified
from goldilocks_core.artifacts.remote import HttpClient

PSEUDO_DOJO_BASE = "https://www.pseudo-dojo.org/pseudos"
"""Base URL the PseudoDojo project serves its tables from."""

LIBRARY = "pseudodojo"
"""Library directory name. Load-bearing: selection derives it from the path."""

HARTREE_TO_RYDBERG = 2.0
"""djrepo hints are in Hartree (the ABINIT convention); QE cutoffs are in Ry."""

DEFAULT_DUAL = 4
"""``ecutrho = DEFAULT_DUAL * ecutwfc``, for norm-conserving pseudopotentials.

djrepo publishes no charge-density cutoff at all, so this has to be chosen.
4 is the value norm-conserving pseudopotentials are usually quoted at and QE's
own default; ``aiida-pseudo`` uses 8 for the same PseudoDojo tables. Measured
on SSSP's ultrasoft Si (a different pseudopotential formalism, not a like-for-
like check), the published dual is 240/30 = 8. Picked provisionally rather
than settled: see stfc/goldilocks-core#149 for the follow-up.
"""

_UPF_DIGEST_KEY = "md5_upf"


@dataclass(frozen=True, slots=True)
class _ReportedPseudo:
    """What one element's dojo report says about its UPF file."""

    digest: str
    ecutwfc_ry: float | None


class TableIncomplete(RuntimeError):
    """An archive did not contain what its dojo reports describe."""


@dataclass(frozen=True, slots=True)
class DojoTable:
    """A PseudoDojo table and what fetching it will cost.

    Attributes:
        table: table identifier, e.g. ``nc-sr-04_pbesol_standard``.
        upf_url: URL of the pseudopotential archive.
        djrepo_url: URL of the dojo report archive.
        upf_bytes: transfer size of the pseudopotential archive, if published.
        djrepo_bytes: transfer size of the report archive, if published.
    """

    table: str
    upf_url: str
    djrepo_url: str
    upf_bytes: int | None
    djrepo_bytes: int | None

    @property
    def total_bytes(self) -> int | None:
        """Bytes crossing the network for a full install, if both are known."""
        if self.upf_bytes is None or self.djrepo_bytes is None:
            return None
        return self.upf_bytes + self.djrepo_bytes


def archive_urls(table: str, *, base: str = PSEUDO_DOJO_BASE) -> tuple[str, str]:
    """Return the ``(upf, djrepo)`` archive URLs for ``table``."""
    return f"{base}/{table}_upf.tgz", f"{base}/{table}_djrepo.tgz"


def describe(
    table: str,
    *,
    base: str = PSEUDO_DOJO_BASE,
    http: HttpClient | None = None,
) -> DojoTable:
    """Report what installing ``table`` will transfer, without transferring it."""
    upf_url, djrepo_url = archive_urls(table, base=base)
    return DojoTable(
        table=table,
        upf_url=upf_url,
        djrepo_url=djrepo_url,
        upf_bytes=remote.transferred_size(upf_url, http=http),
        djrepo_bytes=remote.transferred_size(djrepo_url, http=http),
    )


def install(
    table: str,
    *,
    root: Path | None = None,
    base: str = PSEUDO_DOJO_BASE,
    http: HttpClient | None = None,
) -> Path:
    """Install ``table`` into the pseudopotential cache and return its directory.

    The reports are fetched first: they are three orders of magnitude smaller
    than the table and they say what every file in it should hash to, so the
    expected digests are known before a single pseudopotential is written.

    Layout follows the ``<library>/<source_set>/`` convention that selection
    derives library and source set from, so an installed table is indistinguishable
    from one the user downloaded by hand.

    Args:
        table: table identifier, e.g. ``nc-sr-04_pbesol_standard``.
        root: pseudopotential root. Defaults to the user cache.
        base: base URL, so a mirror or a local copy can be substituted.
        http: HTTP client, for tests.

    Returns:
        The directory holding the installed ``*.upf`` files.

    Raises:
        TableIncomplete: the archives disagree about which elements exist.
        goldilocks_core.artifacts.cache.ChecksumMismatch: a pseudopotential did
            not match the digest its dojo report publishes.
    """
    pseudo_root = root or artifact_path("pseudopotentials")
    upf_directory = pseudo_root / LIBRARY / f"{table}_upf"
    djrepo_directory = pseudo_root / LIBRARY / f"{table}_djrepo"
    sidecar = pseudo_root / LIBRARY / f"{table}_upf.json"

    if any(upf_directory.glob("*.upf", case_sensitive=False)):
        return upf_directory

    upf_url, djrepo_url = archive_urls(table, base=base)
    reports = _install_reports(djrepo_url, djrepo_directory, http=http)
    _install_pseudos(upf_url, upf_directory, reports, http=http)
    _write_cutoff_sidecar(sidecar, reports)

    return upf_directory


def _install_reports(
    url: str,
    destination: Path,
    *,
    http: HttpClient | None,
) -> dict[str, _ReportedPseudo]:
    """Unpack the dojo reports and return each element's digest and cutoff."""
    reports: dict[str, _ReportedPseudo] = {}
    destination.mkdir(parents=True, exist_ok=True)

    for name, payload in _archive_members(url, ".djrepo", http=http):
        element = Path(name).stem
        (destination / f"{element}.djrepo").write_bytes(payload)

        report = json.loads(payload)
        if _UPF_DIGEST_KEY not in report:
            raise TableIncomplete(
                f"dojo report for {element} publishes no {_UPF_DIGEST_KEY}"
            )

        ecut_ha = (report.get("hints") or {}).get("high", {}).get("ecut")
        reports[element] = _ReportedPseudo(
            digest=report[_UPF_DIGEST_KEY],
            ecutwfc_ry=ecut_ha * HARTREE_TO_RYDBERG if ecut_ha is not None else None,
        )

    if not reports:
        raise TableIncomplete(f"no dojo reports found in {url}")

    return reports


def _install_pseudos(
    url: str,
    destination: Path,
    reports: dict[str, _ReportedPseudo],
    *,
    http: HttpClient | None,
) -> None:
    """Unpack pseudopotentials, verifying each against its published digest."""
    seen: set[str] = set()

    for name, payload in _archive_members(url, ".upf", http=http):
        element = Path(name).stem
        reported = reports.get(element)
        if reported is None:
            raise TableIncomplete(f"{element}.upf has no dojo report to verify it")

        store_verified(
            [payload], destination / f"{element}.upf", "md5", reported.digest
        )
        seen.add(element)

    missing = ", ".join(sorted(set(reports) - seen))
    if missing:
        raise TableIncomplete(
            f"dojo reports describe elements absent from the table: {missing}"
        )


def _write_cutoff_sidecar(
    destination: Path, reports: dict[str, _ReportedPseudo]
) -> None:
    """Write recommended cutoffs in the schema cutoff discovery already reads.

    Elements whose report carries no ``high`` hint are omitted rather than
    given a fabricated cutoff; selection then reports them as uncovered
    instead of silently under-converged.
    """
    sidecar = {
        element: {
            "cutoff_wfc": reported.ecutwfc_ry,
            "cutoff_rho": reported.ecutwfc_ry * DEFAULT_DUAL,
        }
        for element, reported in reports.items()
        if reported.ecutwfc_ry is not None
    }
    destination.write_text(json.dumps(sidecar, indent=2))


def _archive_members(
    url: str,
    suffix: str,
    *,
    http: HttpClient | None,
):
    """Yield ``(name, payload)`` for archive members ending in ``suffix``.

    The archive is streamed to a temporary file rather than held in memory, and
    removed once unpacked; only one member is resident at a time.
    """
    with tempfile.TemporaryDirectory() as scratch:
        archive = remote.download(url, Path(scratch) / "archive.tgz", http=http)

        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                if not member.isfile() or not member.name.lower().endswith(suffix):
                    continue

                extracted = tar.extractfile(member)
                if extracted is None:
                    continue
                yield member.name, extracted.read()
