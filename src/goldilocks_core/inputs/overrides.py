"""The two override bags a caller can populate for one step.

Moved here from the top-level ``inputs.py`` module (v2 epic 2, #3) once epic 3
(#4) needed ``inputs/`` to be a package: the design doc's target tree
(goldilocks-core-design.md S8) puts structure/task/code/hpc normalization
under ``inputs/`` too, and a directory and a module can't share one name.
``HumanInput``/``LlmInput`` still don't belong to any one ``analysis/``/
``advisors/`` module -- every advisor receives one, matching
``resolution.py``'s primitives -- so they land in this package rather than
in any one of its sibling files.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HumanInput(BaseModel):
    """Operator-provided overrides for one step. Empty here: each
    advisor declares the specific fields it accepts by subclassing
    (see ``tests/unit/test_resolution.py``'s worked example) -- there
    is no shared shape to declare until a second advisor exists to
    compare against the first.

    ``extra="forbid"`` deliberately: a typo'd override field should
    fail loudly at construction, not be silently ignored the way an
    unrecognised dict key would be.

    ``allow_inf_nan=False``: no setting has a meaningful infinite or NaN
    value, and an override can reach a record, which is serialized as
    strict JSON (#137). ``--set k_distance=1e999``, a TOML ``inf`` and a
    JSON ``1e999`` all fail validation here.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class LlmInput(HumanInput):
    """Agent-provided overrides. Identical shape to ``HumanInput`` by
    construction (it *is* ``HumanInput``, not a hand-kept copy) --
    which bag a caller populated is the source label, so there is no
    separate ``source`` field for the two to disagree about."""
