#!/usr/bin/env python
"""Report what the registered pseudopotential tables actually contain.

Run manually, never in CI: it downloads the dojo report archive of every
PseudoDojo table in the registry and compares what is published against what
``pseudo_registry.toml`` claims. The reports are a few kilobytes each, but this
still reaches the network, and the numbers change only when upstream republishes.

    uv run python scripts/survey_pseudo_tables.py

Coverage recorded in the registry has to be measured rather than read from
documentation -- covered element counts differ between tables that the naming
suggests are siblings, and one table publishes cutoffs for fewer elements than
it ships pseudopotentials for.
"""

from __future__ import annotations

import io
import json
import sys
import tarfile
from concurrent.futures import ThreadPoolExecutor

import requests

from goldilocks_core.artifacts.pseudodojo import PSEUDO_DOJO_BASE
from goldilocks_core.pseudo.table_registry import load_tables

_TIMEOUT_SECONDS = 120


def published_elements(table: str) -> tuple[set[str], int]:
    """Return the elements a table publishes, and how many carry a cutoff hint.

    ``table`` is the upstream name, not ours: the URL is built from what the
    provider calls the table.
    """
    archive = requests.get(
        f"{PSEUDO_DOJO_BASE}/{table}_djrepo.tgz", timeout=_TIMEOUT_SECONDS
    ).content

    elements: set[str] = set()
    with_hint = 0
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            if not member.name.endswith(".djrepo"):
                continue
            report = json.load(tar.extractfile(member))
            elements.add(report["symbol"])
            if (report.get("hints") or {}).get("high", {}).get("ecut"):
                with_hint += 1

    return elements, with_hint


def transfer_bytes(table: str) -> int:
    """Return the size of the pseudopotential archive, without fetching it."""
    response = requests.head(
        f"{PSEUDO_DOJO_BASE}/{table}_upf.tgz",
        allow_redirects=True,
        timeout=_TIMEOUT_SECONDS,
    )
    return int(response.headers["Content-Length"])


def main() -> int:
    """Compare the registry against the published tables. Return 1 on drift."""
    registry = load_tables()
    fetchable = [t for t in registry.values() if t.provider == "pseudodojo"]

    print(f"Checking {len(fetchable)} PseudoDojo tables against the registry.\n")
    drifted = False

    with ThreadPoolExecutor(max_workers=5) as pool:
        surveys = pool.map(
            lambda t: (
                t,
                *published_elements(t.upstream_table),
                transfer_bytes(t.upstream_table),
            ),
            fetchable,
        )

        for table, elements, with_hint, size in surveys:
            recorded = set(table.elements)
            problems = []

            if elements != recorded:
                problems.append(f"added {sorted(elements - recorded)}")
                problems.append(f"removed {sorted(recorded - elements)}")
            if with_hint != len(elements):
                problems.append(
                    f"{len(elements) - with_hint} elements have no high hint"
                )
            if size != table.transfer_bytes:
                problems.append(f"transfer_bytes {table.transfer_bytes} -> {size}")

            status = "; ".join(problems) if problems else "matches"
            drifted = drifted or bool(problems)
            print(f"  {table.name:<34} {len(elements):>3} elements   {status}")

    if drifted:
        print("\nThe registry is out of date. Update it and re-run.")
    else:
        print("\nEvery table matches what the registry records.")

    return 1 if drifted else 0


if __name__ == "__main__":
    sys.exit(main())
