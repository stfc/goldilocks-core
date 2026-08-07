"""Dispatch-table extension tests for the Generate stage."""

from __future__ import annotations

from pymatgen.core import Lattice, Structure

from goldilocks_core.contracts import CalculationIntent, GeneratedFile
from goldilocks_core.generation import available_codes, available_tasks, generate_inputs
from goldilocks_core.generation.registry import _WRITERS, register_writer


def test_dispatch_table_routes_to_a_registered_writer() -> None:
    """A writer registered after import is routed by intent alone."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )
    sentinel = GeneratedFile(path="inputs/test.in", content="sentinel")
    code, task = "test_code", "test_task"

    # The fake writer ignores advice/selection; passing None proves the
    # dispatcher routes by intent only and never inspects the other args.
    def fake_writer(structure, intent, advice, selection) -> tuple[GeneratedFile, ...]:
        return (sentinel,)

    try:
        register_writer(code, task, fake_writer)
        files = generate_inputs(
            structure,
            CalculationIntent(code=code, task=task),
            advice=None,
            selection=None,
        )
        assert files == (sentinel,)
    finally:
        del _WRITERS[(code, task)]


def test_available_codes_and_tasks_reflect_registered_writers() -> None:
    """The public code/task listings mirror the dispatch table defaults."""
    assert available_codes() == ("quantum_espresso",)
    assert available_tasks() == ("scf_single_point",)
