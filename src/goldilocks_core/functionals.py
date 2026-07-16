"""Canonical exchange-correlation functional labels."""

from __future__ import annotations

import re

_RECOGNIZED_LABELS = {
    "lda": "LDA",
    "pz": "LDA",
    "sla": "LDA",
    "slapz": "LDA",
    "slapznogxnogc": "LDA",
    "pbe": "PBE",
    "pbesol": "PBEsol",
    "perdewburkeernzerhof": "PBE",
    "perdewburkeernzerhofforsolids": "PBEsol",
    "perdewzunger": "LDA",
    "slapwpbxpbc": "PBE",
    "slapwpsxpsc": "PBEsol",
}


def normalize_functional_label(value: object) -> str | None:
    """Return the canonical label for a supported functional spelling.

    Unknown labels are stripped but otherwise preserved so they cannot be
    silently treated as a different functional.
    """
    if not isinstance(value, str):
        return None

    label = value.strip()
    if not label:
        return None

    compact = re.sub(r"[^a-z0-9]+", "", label.casefold())
    recognized = _RECOGNIZED_LABELS.get(compact)
    if recognized is not None:
        return recognized

    return label
