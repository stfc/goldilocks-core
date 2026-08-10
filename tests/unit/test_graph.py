"""Tests for type-keyed graph resolution and execution."""

from dataclasses import dataclass

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.contracts import CalculationHints, CalculationIntent
from goldilocks_core.graph import (
    Preset,
    RunContext,
    StageSpec,
    TaskSpec,
    execute,
)
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata


@dataclass
class StubA:
    value: str = "a"


@dataclass
class StubB:
    value: str = "b"


@dataclass
class StubC:
    value: str = "c"


@dataclass
class StubD:
    value: str = "d"


class MissingRecord:
    pass


STRUCTURE_INPUT = Structure(Lattice.cubic(1.0), ["H"], [[0.0, 0.0, 0.0]])


def test_linear_graph_runs_only_requested_output_dependencies() -> None:
    ran: list[str] = []

    def make_a(*, ctx: RunContext) -> StubA:
        ran.append("a")
        return StubA()

    def make_b(a: StubA, *, ctx: RunContext) -> StubB:
        ran.append("b")
        return StubB(a.value + "b")

    def make_c(b: StubB, *, ctx: RunContext) -> StubC:
        ran.append("c")
        return StubC(b.value + "c")

    task = TaskSpec(
        task="linear",
        stages=(
            StageSpec(StubA, (), make_a),
            StageSpec(StubB, (StubA,), make_b),
            StageSpec(StubC, (StubB,), make_c),
        ),
        presets=(),
    )

    records = execute(task, (StubC,), RunContext(structure_input=STRUCTURE_INPUT))
    assert records[StubC] == StubC("abc")
    assert ran == ["a", "b", "c"]

    ran.clear()
    records = execute(task, (StubB,), RunContext(structure_input=STRUCTURE_INPUT))
    assert records[StubB] == StubB("ab")
    assert ran == ["a", "b"]


def test_parallel_roots_share_dependencies_without_running_siblings() -> None:
    ran: list[str] = []

    def make_a(*, ctx: RunContext) -> StubA:
        ran.append("a")
        return StubA()

    def make_b(a: StubA, *, ctx: RunContext) -> StubB:
        ran.append("b")
        return StubB()

    def make_c(a: StubA, *, ctx: RunContext) -> StubC:
        ran.append("c")
        return StubC()

    task = TaskSpec(
        task="parallel",
        stages=(
            StageSpec(StubA, (), make_a),
            StageSpec(StubB, (StubA,), make_b),
            StageSpec(StubC, (StubA,), make_c),
        ),
        presets=(),
    )

    execute(task, (StubB,), RunContext(structure_input=STRUCTURE_INPUT))
    assert ran == ["a", "b"]

    ran.clear()
    execute(task, (StubB, StubC), RunContext(structure_input=STRUCTURE_INPUT))
    assert ran == ["a", "b", "c"]
    assert ran.count("a") == 1


def test_partial_query_returns_only_requested_records() -> None:
    ran: list[str] = []

    def make_a(*, ctx: RunContext) -> StubA:
        ran.append("a")
        return StubA()

    def make_b(a: StubA, *, ctx: RunContext) -> StubB:
        ran.append("b")
        return StubB()

    def make_c(b: StubB, *, ctx: RunContext) -> StubC:
        ran.append("c")
        return StubC()

    def make_d(c: StubC, *, ctx: RunContext) -> StubD:
        ran.append("d")
        return StubD()

    task = TaskSpec(
        task="partial",
        stages=(
            StageSpec(StubA, (), make_a),
            StageSpec(StubB, (StubA,), make_b),
            StageSpec(StubC, (StubB,), make_c),
            StageSpec(StubD, (StubC,), make_d),
        ),
        presets=(),
    )

    records = execute(task, (StubB, StubD), RunContext(structure_input=STRUCTURE_INPUT))

    assert ran == ["a", "b", "c", "d"]
    assert ran.count("b") == 1
    assert tuple(records) == (StubB, StubD)
    assert StubA not in records
    assert StubC not in records


def test_missing_producer_raises_value_error() -> None:
    task = TaskSpec(task="missing", stages=(), presets=())

    with pytest.raises(ValueError, match="No stage produces.*MissingRecord"):
        execute(task, (MissingRecord,), RunContext(structure_input=STRUCTURE_INPUT))


def test_missing_dependency_producer_raises_value_error() -> None:
    task = TaskSpec(
        task="missing-dependency",
        stages=(StageSpec(StubB, (MissingRecord,), lambda value, *, ctx: StubB()),),
        presets=(),
    )

    with pytest.raises(ValueError, match="No stage produces.*MissingRecord"):
        execute(task, (StubB,), RunContext(structure_input=STRUCTURE_INPUT))


def test_cycle_raises_value_error() -> None:
    task = TaskSpec(
        task="cycle",
        stages=(
            StageSpec(StubA, (StubB,), lambda value, *, ctx: StubA()),
            StageSpec(StubB, (StubA,), lambda value, *, ctx: StubB()),
        ),
        presets=(),
    )

    with pytest.raises(ValueError, match="Cycle detected"):
        execute(task, (StubA,), RunContext(structure_input=STRUCTURE_INPUT))


def test_run_context_reaches_stage_as_keyword_argument() -> None:
    intent = CalculationIntent(task="context-test")
    hints = CalculationHints(k_grid=(2, 2, 2))
    metadata = PseudoMetadata(
        filepath="Si.UPF",
        filename="Si.UPF",
        header_format="attr",
    )

    def backend(structure):
        return None

    def classifier(structure):
        return "metal", "test", 0.9

    context = RunContext(
        structure_input=STRUCTURE_INPUT,
        intent=intent,
        hints=hints,
        pseudo_metadata=(metadata,),
        kmesh_backend=backend,
        metallicity_classifier=classifier,
    )

    def inspect_context(*, ctx: RunContext) -> StubA:
        assert ctx.intent is intent
        assert ctx.hints is hints
        assert ctx.pseudo_metadata == (metadata,)
        assert ctx.kmesh_backend is backend
        assert ctx.metallicity_classifier is classifier
        return StubA()

    task = TaskSpec(
        task="context",
        stages=(StageSpec(StubA, (), inspect_context),),
        presets=(),
    )

    assert execute(task, (StubA,), context)[StubA] == StubA()


def test_task_preset_lookup() -> None:
    recommend = Preset("recommend", (StubA, StubB))
    task = TaskSpec(task="preset", stages=(), presets=(recommend,))

    assert task.preset("recommend") is recommend
    with pytest.raises(KeyError):
        task.preset("unknown")
