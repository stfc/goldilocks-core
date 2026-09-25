#!/usr/bin/env python3
"""Sum mutmut's per-shard exported CI stats into one file for the score gate.

`mutmut export-cicd-stats` writes killed/total (plus other counters) as flat
integers -- merging shards is just summing matching keys across each shard's
json, so check_mutation_score.py can run once against the combined total
instead of once per shard (stfc/goldilocks-core#231's mutation-testing matrix).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: merge_mutation_stats.py OUTPUT SHARD_STATS...", file=sys.stderr)
        return 2
    output, *shard_paths = (Path(p) for p in sys.argv[1:])

    merged: dict[str, int] = {}
    for path in shard_paths:
        for key, value in json.loads(path.read_text()).items():
            merged[key] = merged.get(key, 0) + int(value)

    output.write_text(json.dumps(merged))
    print(f"Merged {len(shard_paths)} shard(s) into {output}: {merged}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
