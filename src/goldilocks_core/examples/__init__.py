"""Example crystal structures shipped with goldilocks-core.

The structures are installed with the package so that a `pip install` is enough
to run the pipeline end to end, without cloning the repository.
"""

from __future__ import annotations

from .structures import available_structures, structure, structures_path

__all__ = ["available_structures", "structure", "structures_path"]
