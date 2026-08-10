"""Install SSSP tables from the Materials Cloud Archive.

The Archive is an InvenioRDM instance, so the record and its files are resolved
by the same code that serves PSDI -- only the API base differs.

An SSSP table is an archive of pseudopotentials drawn from several projects,
under several licences, alongside a JSON sidecar that maps each element to its
file, that file's digest, and its recommended cutoffs. The sidecar plays the
part the dojo reports play for PseudoDojo: fetched first, it says what every
pseudopotential should hash to before any of them is written.

Nothing is redistributed. The bytes travel from the Archive to the user, which
is what makes a table assembled from GPL-licensed files installable at all.
"""

from __future__ import annotations

import json
import tarfile
import tempfile
from pathlib import Path

from goldilocks_core.artifacts import psdi
from goldilocks_core.artifacts.cache import store_verified
from goldilocks_core.artifacts.remote import HttpClient

MATERIALS_CLOUD_API = "https://archive.materialscloud.org/api"
"""Base URL of the Materials Cloud Archive API."""

LIBRARY = "sssp"
"""Library directory name. Load-bearing: selection derives it from the path."""


class TableIncomplete(RuntimeError):
    """An archive did not contain what its sidecar describes."""


def install(
    record: str,
    table: str,
    *,
    root: Path,
    api: str = MATERIALS_CLOUD_API,
    http: HttpClient | None = None,
) -> Path:
    """Install ``table`` from Archive ``record`` and return its directory.

    The sidecar is written beside the table rather than inside it, named after
    the directory, which is where cutoff discovery already looks for it.

    Args:
        record: Archive record identifier; pins the record version.
        table: table name within the record, without extension.
        root: pseudopotential root the table is installed under.
        api: API base URL.
        http: HTTP client, for tests.

    Returns:
        The directory holding the installed ``*.upf`` files.

    Raises:
        TableIncomplete: the archive and its sidecar disagree.
        goldilocks_core.artifacts.cache.ChecksumMismatch: a pseudopotential did
            not match the digest the sidecar publishes.
    """
    destination = root / LIBRARY / table
    if any(destination.glob("*.upf", case_sensitive=False)):
        return destination

    with tempfile.TemporaryDirectory() as scratch:
        staged = Path(scratch)
        sidecar = psdi.fetch(
            record,
            f"{table}.json",
            destination=staged / "sidecar.json",
            api=api,
            http=http,
        )
        entries = json.loads(sidecar.read_text())
        digests = {value["filename"]: value["md5"] for value in entries.values()}

        archive = psdi.fetch(
            record,
            f"{table}.tar.gz",
            destination=staged / "table.tar.gz",
            api=api,
            http=http,
        )
        _unpack_verified(archive, destination, digests)

        (destination.parent / f"{table}.json").write_bytes(sidecar.read_bytes())

    return destination


def _unpack_verified(archive: Path, destination: Path, digests: dict[str, str]) -> None:
    """Unpack pseudopotentials, verifying each against its published digest."""
    seen: set[str] = set()

    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue

            filename = Path(member.name).name
            expected = digests.get(filename)
            if expected is None:
                raise TableIncomplete(f"{filename} has no sidecar entry to verify it")

            extracted = tar.extractfile(member)
            if extracted is None:
                continue

            store_verified([extracted.read()], destination / filename, "md5", expected)
            seen.add(filename)

    missing = ", ".join(sorted(set(digests) - seen))
    if missing:
        raise TableIncomplete(
            f"the sidecar describes files absent from the archive: {missing}"
        )
