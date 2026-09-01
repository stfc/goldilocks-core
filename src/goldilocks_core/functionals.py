from __future__ import annotations

import re

_RECOGNIZED_LABELS = {
    "lda": "LDA",
    "pz": "LDA",
    "sla": "LDA",
    "pw": "LDA",
    "slapz": "LDA",
    "slapznogxnogc": "LDA",
    "slapwnogxnogc": "LDA",
    "pbe": "PBE",
    "pbesol": "PBEsol",
    "perdewburkeernzerhof": "PBE",
    "perdewburkeernzerhofforsolids": "PBEsol",
    "perdewzunger": "LDA",
    "slapwpbxpbc": "PBE",
    "slapwpbepbepbe": "PBE",
    "slapwpsxpsc": "PBEsol",
}


def normalize_functional_label(value: object) -> str | None:
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
