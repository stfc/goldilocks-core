"""Server-owned deployment configuration for the Workbench.

This module is the single transport seam for deployment-time values. Operators
configure the bounded computation gate and the pseudopotential metadata injected
into Workbench requests through the environment or a mounted data volume; the
browser never submits these values. The Python/CLI/MCP paths remain intact and
bypass this seam.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

__all__ = [
    "COMPUTE_LIMIT_ENV",
    "COMPUTE_WAIT_ENV",
    "DEFAULT_COMPUTE_LIMIT",
    "DEFAULT_COMPUTE_WAIT_SECONDS",
    "DeploymentConfig",
    "PSEUDO_METADATA_ENV",
    "PSEUDO_ROOT_ENV",
    "WEB_DIST_ENV",
]

COMPUTE_LIMIT_ENV = "GOLDILOCKS_COMPUTE_LIMIT"
COMPUTE_WAIT_ENV = "GOLDILOCKS_COMPUTE_WAIT_SECONDS"
PSEUDO_METADATA_ENV = "GOLDILOCKS_PSEUDO_METADATA"
PSEUDO_ROOT_ENV = "GOLDILOCKS_PSEUDO_ROOT"
WEB_DIST_ENV = "GOLDILOCKS_WEB_DIST"

DEFAULT_COMPUTE_LIMIT = 2
DEFAULT_COMPUTE_WAIT_SECONDS = 5.0


@dataclass(frozen=True)
class DeploymentConfig:
    """Operator-configured transport capacity and injected pseudo metadata.

    ``compute_limit`` bounds concurrent Core computations per process; a wait
    longer than ``compute_wait_seconds`` for a free slot surfaces a retryable
    ``server_busy`` failure. ``pseudo_metadata`` is injected into Workbench
    requests that do not supply their own. These values are deliberately
    conservative defaults, not site limits — they require measurement.
    """

    compute_limit: int = DEFAULT_COMPUTE_LIMIT
    compute_wait_seconds: float = DEFAULT_COMPUTE_WAIT_SECONDS
    pseudo_metadata: tuple[PseudoMetadata, ...] = ()

    @classmethod
    def from_environ(cls, env: Mapping[str, str] | None = None) -> "DeploymentConfig":
        """Build a config from an environment mapping (defaults to ``os.environ``)."""
        env = os.environ if env is None else env
        return cls(
            compute_limit=_read_int(env, COMPUTE_LIMIT_ENV, DEFAULT_COMPUTE_LIMIT),
            compute_wait_seconds=_read_float(
                env, COMPUTE_WAIT_ENV, DEFAULT_COMPUTE_WAIT_SECONDS
            ),
            pseudo_metadata=_read_pseudo_metadata(env),
        )


def _read_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}.") from None
    if value < 1:
        raise ValueError(f"{name} must be >= 1, got {value}.")
    return value


def _read_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}.") from None
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}.")
    return value


def _read_pseudo_metadata(env: Mapping[str, str]) -> tuple[PseudoMetadata, ...]:
    """Load injected pseudo metadata from a JSON manifest or a UPF root."""
    metadata_path = env.get(PSEUDO_METADATA_ENV)
    if metadata_path:
        return _load_pseudo_json(Path(metadata_path))
    root = env.get(PSEUDO_ROOT_ENV)
    if root:
        return tuple(load_pseudo_metadata(Path(root)))
    return ()


def _load_pseudo_json(path: Path) -> tuple[PseudoMetadata, ...]:
    """Load ``PseudoMetadata`` entries from an administrator JSON manifest."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, Mapping):
        entries: list[Any] = list(data.values())
    elif isinstance(data, list):
        entries = data
    else:
        raise ValueError(
            f"{PSEUDO_METADATA_ENV} file must contain a list or object of "
            "pseudopotential metadata."
        )
    return tuple(_coerce_pseudo(entry) for entry in entries)


def _coerce_pseudo(value: Any) -> PseudoMetadata:
    if isinstance(value, PseudoMetadata):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("Each pseudopotential metadata entry must be a JSON object.")
    return PseudoMetadata(**dict(value))
