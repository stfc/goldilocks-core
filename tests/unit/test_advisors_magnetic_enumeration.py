"""The enumeration worker reads enumlib's output in enumlib's numbering, and
fails loudly when pymatgen-core stops reading it where the worker can set
that order (#170).

pymatgen's ``MagneticStructureEnumerator`` is replaced by stand-ins that
read ``vasp.<n>`` files the way pymatgen-core does today (through
``enumlib_caller.glob``) or the way a later pymatgen-core might (some other
way), so these tests need no enumlib; the real enumerations are in
``tests/integration/test_enumeration_isolation.py``.
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

import pytest
from pymatgen.analysis.magnetism import analyzer
from pymatgen.command_line import enumlib_caller
from pymatgen.core import Lattice, Structure

from goldilocks_core.advisors.magnetic_enumeration import (
    _enumerate_in_private_directory,
)

_NIO = Structure.from_spacegroup(
    "Fm-3m", Lattice.cubic(4.17), ["Ni", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]]
)


_READ: list[list[str]] = []
"""The file lists the stand-ins read, in their order."""


class _ReadingThroughEnumlibCaller:
    """pymatgen-core as it is: writes enumlib's output files, then reads
    them in the order ``enumlib_caller.glob("vasp.*")`` returns."""

    def __init__(self, structure: Structure, **_kwargs: Any) -> None:
        for number in (10, 2, 1):
            Path(f"vasp.{number}").write_text("")
        _READ.append(enumlib_caller.glob("vasp.*"))
        self.ordered_structures = [structure, structure]
        self.ordered_structure_origins = ["fm", "afm"]


class _ReadingAroundEnumlibCaller:
    """A pymatgen-core that reads the same files without
    ``enumlib_caller.glob``."""

    def __init__(self, structure: Structure, **_kwargs: Any) -> None:
        for number in (10, 2, 1):
            Path(f"vasp.{number}").write_text("")
        _READ.append(glob.glob("vasp.*"))
        self.ordered_structures = [structure, structure]
        self.ordered_structure_origins = ["fm", "afm"]


def test_reads_enumlib_output_in_enumlib_numbering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``vasp.10`` comes after ``vasp.2``, whatever order the directory
    lists them in, and pymatgen's own ``glob`` is back afterwards."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        analyzer, "MagneticStructureEnumerator", _ReadingThroughEnumlibCaller
    )

    _READ.clear()
    orderings = _enumerate_in_private_directory(_NIO, {})

    assert _READ == [["vasp.1", "vasp.2", "vasp.10"]]
    assert [origin for _cell, origin in orderings] == ["fm", "afm"]
    assert enumlib_caller.glob is glob.glob


def test_an_ordering_read_around_enumlib_caller_glob_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pymatgen-core that reads enumlib's output some other way would
    leave the candidates in the filesystem's order again: the enumeration
    fails instead of listing host-dependent cells."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        analyzer, "MagneticStructureEnumerator", _ReadingAroundEnumlibCaller
    )

    with pytest.raises(RuntimeError, match=r"enumlib_caller\.glob"):
        _enumerate_in_private_directory(_NIO, {})
    assert enumlib_caller.glob is glob.glob


def test_a_ferromagnetic_only_result_needs_no_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without an antiferromagnetic ordering, enumlib's output was never
    used, so nothing had to be read through ``enumlib_caller.glob``."""

    class _FerromagneticOnly:
        def __init__(self, structure: Structure, **_kwargs: Any) -> None:
            self.ordered_structures = [structure]
            self.ordered_structure_origins = ["fm"]

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(analyzer, "MagneticStructureEnumerator", _FerromagneticOnly)

    assert _enumerate_in_private_directory(_NIO, {}) == ((_NIO, "fm"),)
