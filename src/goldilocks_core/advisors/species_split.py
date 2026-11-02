"""split_species: the species of the simulated cell, one per element and
starting-magnetization class (#170).

pw.x keeps its species (``ATOMIC_SPECIES`` types) apart when it looks for
symmetry: an operation must map every atom onto one of the same type (QE
7.3 ``PW/src/symm_base.f90``, ``sgam_at`` and ``checksym``). A collinear
run sets its starting magnetization per type, so two sites seeded
differently must be two types, and every site of an element seeded alike
is one, whatever labels the uploaded file gave its sites (``Si1``..``Si40``,
``Fe0``/``Fe1``).

The magnetic step (``advisors/magnetic_config.py``'s ``magnetic_cell``)
splits the cell here once, before ``symmetry_eff`` and ``n_irr_k`` are
counted, and every later decision and the writer read that cell as it is.
The writer used to regroup the sites itself, after symmetry had been
counted on the unsplit cell: a candidate CIF of AFM NiO reported Fm-3m.
"""

from __future__ import annotations

from collections.abc import Sequence

from pymatgen.core import Element, Species, Structure

_Key = tuple[str, float | None]
"""A site's element and class (``None`` for a spin-unpolarized cell)."""


def split_species(structure: Structure, classes: Sequence[float] | None) -> Structure:
    """``structure`` with one species per element and class.

    ``classes`` holds each site's starting-magnetization class, in site
    order, or is ``None`` for a spin-unpolarized cell. Each site's label
    becomes its species label: the element symbol when every site of the
    element has the same class, otherwise the symbol numbered from 1,
    highest class first. With classes, each site's species is
    ``Species(symbol, spin=class)``, so spglib (``SpacegroupAnalyzer``)
    tells the split sites apart as pw.x will; without, a plain element.
    Site properties are kept."""
    values = (
        [None] * len(structure)
        if classes is None
        else [float(value) for value in classes]
    )
    keys = [
        (site.specie.symbol, value)
        for site, value in zip(structure, values, strict=True)
    ]
    label_by_key = _labels(keys)
    return Structure(
        structure.lattice,
        [
            Element(symbol) if value is None else Species(symbol, spin=value)
            for symbol, value in keys
        ],
        structure.frac_coords,
        labels=[label_by_key[key] for key in keys],
        site_properties=structure.site_properties,
    )


def _labels(keys: list[_Key]) -> dict[_Key, str]:
    """One label per distinct ``(element, class)`` key (``split_species``)."""
    classes_by_element: dict[str, set[float | None]] = {}
    for symbol, value in keys:
        classes_by_element.setdefault(symbol, set()).add(value)
    labels: dict[_Key, str] = {}
    for symbol, values in classes_by_element.items():
        if len(values) == 1:
            labels[(symbol, next(iter(values)))] = symbol
            continue
        for index, value in enumerate(sorted(values, reverse=True), start=1):
            labels[(symbol, value)] = f"{symbol}{index}"
    return labels
