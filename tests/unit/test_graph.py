"""Tests for type-keyed graph resolution and execution.

The executor is stage-agnostic: it resolves a task's graph from each stage's
declared input and output record types and hands one opaque context object to
every stage as ``ctx``. These tests pin that contract without coupling to any
real task's context shape.
"""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from goldilocks_core.graph import Preset, StageSpec, TaskSpec, execute


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


def test_linear_graph_runs_only_requested_output_dependencies() -> None:
    ran: list[str] = []

    def make_a(*, ctx) -> StubA:
        ran.append("a")
        return StubA()

    def make_b(a: StubA, *, ctx) -> StubB:
        ran.append("b")
        return StubB(a.value + "b")

    def make_c(b: StubB, *, ctx) -> StubC:
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

    records = execute(task, (StubC,), SimpleNamespace())
    assert records[StubC] == StubC("abc")
    assert ran == ["a", "b", "c"]

    ran.clear()
    records = execute(task, (StubB,), SimpleNamespace())
    assert records[StubB] == StubB("ab")
    assert ran == ["a", "b"]


def test_parallel_roots_share_dependencies_without_running_siblings() -> None:
    ran: list[str] = []

    def make_a(*, ctx) -> StubA:
        ran.append("a")
        return StubA()

    def make_b(a: StubA, *, ctx) -> StubB:
        ran.append("b")
        return StubB()

    def make_c(a: StubA, *, ctx) -> StubC:
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

    execute(task, (StubB,), SimpleNamespace())
    assert ran == ["a", "b"]

    ran.clear()
    execute(task, (StubB, StubC), SimpleNamespace())
    assert ran == ["a", "b", "c"]
    assert ran.count("a") == 1


def test_partial_query_returns_only_requested_records() -> None:
    ran: list[str] = []

    def make_a(*, ctx) -> StubA:
        ran.append("a")
        return StubA()

    def make_b(a: StubA, *, ctx) -> StubB:
        ran.append("b")
        return StubB()

    def make_c(b: StubB, *, ctx) -> StubC:
        ran.append("c")
        return StubC()

    def make_d(c: StubC, *, ctx) -> StubD:
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

    records = execute(task, (StubB, StubD), SimpleNamespace())

    assert ran == ["a", "b", "c", "d"]
    assert ran.count("b") == 1
    assert tuple(records) == (StubB, StubD)
    assert StubA not in records
    assert StubC not in records


def test_missing_producer_raises_value_error() -> None:
    task = TaskSpec(task="missing", stages=(), presets=())

    with pytest.raises(ValueError, match="No stage produces.*MissingRecord"):
        execute(task, (MissingRecord,), SimpleNamespace())


def test_missing_dependency_producer_raises_value_error() -> None:
    task = TaskSpec(
        task="missing-dependency",
        stages=(StageSpec(StubB, (MissingRecord,), lambda value, *, ctx: StubB()),),
        presets=(),
    )

    with pytest.raises(ValueError, match="No stage produces.*MissingRecord"):
        execute(task, (StubB,), SimpleNamespace())


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
        execute(task, (StubA,), SimpleNamespace())


def test_execute_passes_context_opaquely_to_stages() -> None:
    """The executor hands the same context object to each stage as ``ctx``."""
    ctx = SimpleNamespace(marker="ctx")
    received: list[object] = []

    def inspect(*, ctx) -> StubA:
        received.append(ctx)
        return StubA()

    task = TaskSpec(
        task="context",
        stages=(StageSpec(StubA, (), inspect),),
        presets=(),
    )

    execute(task, (StubA,), ctx)

    assert received == [ctx]


def test_task_preset_lookup() -> None:
    recommend = Preset("recommend", (StubA, StubB))
    task = TaskSpec(task="preset", stages=(), presets=(recommend,))

    assert task.preset("recommend") is recommend
    with pytest.raises(KeyError):
        task.preset("unknown")
