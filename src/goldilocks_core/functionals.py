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
    "slapwpbxpbcpbe": "PBE",
    "slapwpsxpsc": "PBEsol",
    "slapwpsxpscpbesol": "PBEsol",
}

D3BJ_FUNCTIONALS = frozenset({"PBE", "PBEsol"})
"""Canonical labels Quantum ESPRESSO's DFT-D3 has D3(BJ) damping parameters
for. pw.x passes DFT-D3 the pseudopotentials' lowercased short functional
name (QE 7.3 PW/src/input.f90:2039-2041, dft-d3/dftd3_qe.f90 ``dftd3_xc``).
The version-4 (Becke-Johnson) table in dft-d3/core.f90:286-531 has ``pbe``
and ``pbesol`` but neither LDA short name (``pz``, ``pw``), so an LDA run
stops at startup with "functional name unknown" (#141)."""


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


def has_d3bj_parameters(functional: str) -> bool:
    """Whether ``functional``, a canonical label as returned by
    ``normalize_functional_label``, is in ``D3BJ_FUNCTIONALS``. Any other
    label counts as unparameterised, including labels Goldilocks does not
    recognise."""
    return functional in D3BJ_FUNCTIONALS
