#!/usr/bin/env python3
"""Narrow [tool.mutmut] only_mutate to one CI shard's files, in place.

pyproject.toml's only_mutate already scopes mutation testing to a curated
5-file list, but that list alone produces 894 mutants (measured directly via
mutmut's own mutant-generation code, not estimated) -- too many to reliably
finish inside one CI job's timeout at --max-children 2 (stfc/goldilocks-core#231:
a real run reached only 774/894 in 45 minutes). ci.yml's mutation-testing job
matrix runs this script once per shard, against its own checkout, before
invoking mutmut, so each shard only ever sees its own files.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

PYPROJECT = Path("pyproject.toml")

# Keep in sync with pyproject.toml's own [tool.mutmut] only_mutate list --
# every file listed there must appear in exactly one shard here, or CI would
# either skip it entirely (in neither shard) or double-run it (in both). The
# split is by measured mutant count (scf.py alone is 476/894, roughly half),
# not file count, since mutant density varies wildly by file.
SHARDS: dict[str, list[str]] = {
    "scf": [
        "src/goldilocks_core/generation/quantum_espresso/scf.py",
    ],
    "rest": [
        "src/goldilocks_core/advisors/pseudo_selection.py",
        "src/goldilocks_core/functionals.py",
        "src/goldilocks_core/kmesh.py",
        "src/goldilocks_core/service/_pipeline.py",
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shard", choices=sorted(SHARDS))
    args = parser.parse_args()

    config = tomllib.loads(PYPROJECT.read_text())
    full_scope = set(config["tool"]["mutmut"]["only_mutate"])
    sharded = {f for files in SHARDS.values() for f in files}
    if full_scope != sharded:
        missing = sorted(full_scope - sharded)
        extra = sorted(sharded - full_scope)
        parser.error(
            "SHARDS in this script is out of sync with pyproject.toml's "
            f"[tool.mutmut] only_mutate: missing from SHARDS={missing}, "
            f"not in only_mutate={extra}"
        )

    files = SHARDS[args.shard]
    text = PYPROJECT.read_text()
    new_block = "only_mutate = [\n" + "".join(f'    "{f}",\n' for f in files) + "]"
    text, count = re.subn(r"only_mutate = \[[^\]]*\]", new_block, text, count=1)
    if count != 1:
        parser.error("could not find a single only_mutate = [...] block to replace")
    PYPROJECT.write_text(text)
    print(f"Restricted [tool.mutmut] only_mutate to shard {args.shard!r}: {files}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
