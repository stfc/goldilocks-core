"""enumerate_orderings: pymatgen's ``MagneticStructureEnumerator``, run where
its process-wide side effects cannot reach the caller (#136).

pymatgen runs enumlib inside monty's ``ScratchDir(".")``: it ``chdir``s the
whole process into a temporary directory under the current one, writes
``struct_enum.in`` and reads ``vasp.*`` by relative path, and starts
``enum.x``/``makeStr.py`` there. Two enumerations on request threads moved
each other's working directory and deleted each other's files, and the
server's cwd could be left in a deleted directory.

Every enumeration therefore runs on one long-lived worker process
(``worker_process.WorkerProcess``), one at a time, inside a fresh private
directory under the system temporary directory that is deleted afterwards.
The caller's cwd and files are never touched; concurrent callers queue on the
worker. Only the worker imports pymatgen's enumeration stack.

The worker also reads enumlib's ``vasp.<n>`` output files in enumlib's own
numbering (``_in_enumlib_order``), not the directory's read order, which the
filesystem decides: pymatgen keeps the first ``max_orderings`` structures,
smallest cells first, ties in the order it reads them, so the same structure
gave different candidates on different hosts (#170). pymatgen-core reads
those files through ``command_line.enumlib_caller.glob`` and leaves them in
the order ``glob`` returns, so the worker replaces that name for each
enumeration; an enumeration that returns an antiferromagnetic ordering
without reading through it raises, since a pymatgen-core that reads them
some other way would make the candidates host-dependent again.
"""

from __future__ import annotations

import glob
import os
import shutil
import tempfile
from functools import partial
from typing import TYPE_CHECKING, Any

from goldilocks_core.worker_process import WorkerProcess

if TYPE_CHECKING:
    from pymatgen.core import Structure

_ENUMERATOR_EXECUTABLES = ("enum.x", "multienum.x")
_STRUCTURE_MAKER_EXECUTABLES = ("makestr.x", "makeStr.x", "makeStr.py")
"""The names pymatgen's ``command_line.enumlib_caller`` looks up on PATH
(``ENUM_CMD``, ``MAKESTR_CMD``); it refuses to enumerate without one of
each."""

_ENUMERATION_WORKER = WorkerProcess()


def enumlib_installed() -> bool:
    """Whether PATH has an enumlib enumerator and a structure maker."""
    return all(
        any(shutil.which(name) is not None for name in names)
        for names in (_ENUMERATOR_EXECUTABLES, _STRUCTURE_MAKER_EXECUTABLES)
    )


def enumerate_orderings(
    structure: Structure, **enumerator_kwargs: Any
) -> tuple[tuple[Structure, str], ...]:
    """Every ordering ``MagneticStructureEnumerator(structure,
    **enumerator_kwargs)`` produces, as ``(structure, origin)`` pairs in the
    enumerator's order: a spin-decorated structure and pymatgen's label for
    the strategy that produced it (``"fm"``, ``"afm"``, ...).

    Raises what the enumerator raises, re-raised from the worker, and
    ``worker_process.WorkerDied`` if the worker process dies."""
    return _ENUMERATION_WORKER.run(
        _enumerate_in_private_directory, structure, enumerator_kwargs
    )


def _enumerate_in_private_directory(
    structure: Structure, enumerator_kwargs: dict[str, Any]
) -> tuple[tuple[Structure, str], ...]:
    """Worker side of ``enumerate_orderings``: enumerate with this process's
    cwd inside a new temporary directory, reading enumlib's output files in
    their own numbering (``_in_enumlib_order``), then leave and delete it.

    Raises ``RuntimeError`` when an antiferromagnetic ordering comes back
    although pymatgen never read enumlib's output through
    ``enumlib_caller.glob`` (module docstring)."""
    from pymatgen.analysis.magnetism.analyzer import MagneticStructureEnumerator
    from pymatgen.command_line import enumlib_caller

    patterns_read: list[str] = []
    directory_order = enumlib_caller.glob
    with tempfile.TemporaryDirectory(prefix="goldilocks-enumlib-") as scratch:
        os.chdir(scratch)
        enumlib_caller.glob = partial(_in_enumlib_order, read=patterns_read)
        try:
            enumerator = MagneticStructureEnumerator(structure, **enumerator_kwargs)
        finally:
            enumlib_caller.glob = directory_order
            os.chdir(tempfile.gettempdir())
    origins = enumerator.ordered_structure_origins
    if "afm" in origins and not patterns_read:
        raise RuntimeError(
            "pymatgen-core returned antiferromagnetic orderings without reading "
            "enumlib's vasp.<n> files through enumlib_caller.glob, so their "
            "order, and which orderings it kept, follow the filesystem (#170)"
        )
    return tuple(zip(enumerator.ordered_structures, origins, strict=True))


def _in_enumlib_order(pattern: str, *, read: list[str]) -> list[str]:
    """The files ``glob.glob(pattern)`` finds, sorted by the number after
    their last dot, with ``pattern`` appended to ``read``: pymatgen's
    ``EnumlibAdaptor`` reads ``glob("vasp.*")``, and makeStr numbers those
    files in enumlib's order. A name without a number raises
    ``ValueError``."""
    read.append(pattern)
    return sorted(glob.glob(pattern), key=lambda name: int(name.rpartition(".")[2]))
