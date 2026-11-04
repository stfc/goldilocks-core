"""``Advice``/``RunOverrides``: the pipeline-wide shapes composing the
three phases in ``_analysis.py``/``_system.py``/``_step.py`` (v2 epic 8,
#8).

Composed of the three phases' own dataclasses, not a flat 20-odd-field
dataclass: a flat shape would need to import every analysis/advisor
decision type directly for its own field annotations, which is exactly
the "god module" shape ``scripts/check_complexity.py``'s import-surface
ceiling exists to catch. Composing three already-typed sub-objects, plus
the task's ``JobOverrides`` (``_step_resources.py``) in ``RunOverrides``,
costs this module only four local origins.

``RecordTiers`` groups one task's records by the tier that produced them
(#187): analysis (the structure alone), system (shared by every step), and
each step's own. Every advice type's ``tiers()`` returns one, and its flat
``records()`` and the ``layout`` ``explain`` and ``run`` publish both come
from it, so they cannot disagree about which records exist.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TypedDict

from goldilocks_core.resolution import FieldState, Warning, collect_warnings
from goldilocks_core.service._analysis import AnalysisFacts, AnalysisOverrides
from goldilocks_core.service._step import StepAdvice, StepOverrides
from goldilocks_core.service._step_resources import JobOverrides
from goldilocks_core.service._system import SystemAdvice, SystemOverrides


@dataclass(frozen=True, slots=True)
class RunOverrides:
    """One task's request overrides, routed for that task
    (``set_overrides.build_overrides``, #154): the analysis and system
    overrides and the task's one ``job`` allocation, then ``steps``, one
    ``StepOverrides`` per step of the task that the request set anything
    for, keyed by the step's purpose (``plan.expand_task``). Typed, not a
    generic key/value bag -- each advisor's override class is separate.

    ``warnings`` holds the routing notices (a setting given without a step
    that landed on several); only a task with more than one pw.x step can
    raise one, and that task's own advice publishes them."""

    analysis: AnalysisOverrides = field(default_factory=AnalysisOverrides)
    system: SystemOverrides = field(default_factory=SystemOverrides)
    job: JobOverrides = field(default_factory=JobOverrides)
    steps: Mapping[str, StepOverrides] = field(default_factory=dict)
    warnings: tuple[Warning, ...] = ()

    def for_steps(self, purposes: Sequence[str]) -> dict[str, StepOverrides]:
        """Each of ``purposes``' (every step of the task, in run order)
        overrides, empty where the request set none. Raises ``ValueError``
        when ``steps`` holds a step outside ``purposes``: these overrides
        were routed for another task."""
        foreign = [purpose for purpose in self.steps if purpose not in purposes]
        if foreign:
            raise ValueError(
                f"overrides for step(s) {', '.join(foreign)} were routed for "
                f"another task; this task's steps are {', '.join(purposes)}"
            )
        return {
            purpose: self.steps.get(purpose, StepOverrides()) for purpose in purposes
        }


class StepLayout(TypedDict):
    """One step of ``RecordLayout``: its purpose and its records' names."""

    name: str
    records: list[str]


class RecordLayout(TypedDict):
    """Which tier and step each record of a response belongs to, by record
    name (``RecordTiers.layout``): every record is in exactly one list."""

    analysis: list[str]
    system: list[str]
    steps: list[StepLayout]


@dataclass(frozen=True, slots=True)
class RecordTiers:
    """One task's records by the tier that produced them: ``analysis``
    (the structure alone), ``system`` (shared by every step) and ``steps``,
    each step's own records by its purpose (``plan.expand_task``), in run
    order. The task's one job is listed with its first step, whose
    ``StepAdvice`` carries it."""

    analysis: Mapping[str, FieldState[object]]
    system: Mapping[str, FieldState[object]]
    steps: Mapping[str, Mapping[str, FieldState[object]]]

    def with_records(
        self, step: str, records: Mapping[str, FieldState[object]]
    ) -> RecordTiers:
        """These tiers with ``records`` added to step ``step``, which is
        appended as the last step when it has no records yet."""
        merged = {**self.steps.get(step, {}), **records}
        return RecordTiers(self.analysis, self.system, {**self.steps, step: merged})

    def records(self) -> dict[str, FieldState[object]]:
        """Every record, flat: the manifest's ``records`` object."""
        merged = {**self.analysis, **self.system}
        for records in self.steps.values():
            merged.update(records)
        return merged

    def warnings(self) -> list[dict[str, object]]:
        """Every record's own warnings (``resolution.collect_warnings``)."""
        return collect_warnings(self.records())

    def layout(self) -> RecordLayout:
        """Each tier's and step's record names: what ``explain`` and
        ``run`` publish as ``layout`` next to ``records``."""
        return {
            "analysis": list(self.analysis),
            "system": list(self.system),
            "steps": [
                {"name": name, "records": list(records)}
                for name, records in self.steps.items()
            ],
        }


@dataclass(frozen=True, slots=True)
class Advice:
    """Every ``FieldState`` produced for one structure/code/task request,
    for one of its pw.x steps (``advise_steps``): ``step`` is that step's
    own advice, on a k-mesh or, for a bands step, along the band path
    (``StepAdvice``, #118).
    ``checks.check_all(*advice.field_states(), ...)`` decides whether
    ``generate()`` may proceed; ``advice.records()`` is what
    ``BundleInput.records`` should carry unchanged -- tri-state, not the
    unwrapped values ``SystemSettings``/``PwSettings`` need."""

    analysis: AnalysisFacts
    system: SystemAdvice
    step: StepAdvice

    def field_states(self) -> tuple[FieldState[object], ...]:
        """Every ``FieldState`` except ``occupations``/``functional``/
        ``magnetic``/``electron_count``/``vdw``/``nbnd``/``boundary``, which
        ``checks.check_all`` folds in itself -- see its own docstring on why
        a caller must not repeat them here."""
        return (
            self.analysis.field_states()
            + self.system.field_states()
            + self.step.field_states()
        )

    def tiers(self, step: str = "scf") -> RecordTiers:
        """``records()`` by tier, this advice's step named ``step``, its
        purpose (``advise_steps`` keys each ``Advice`` by it): an scf
        task's unless a task's own advice passes another (#187)."""
        return RecordTiers(
            analysis=self.analysis.records(),
            system=self.system.records(),
            steps={step: self.step.records()},
        )

    def records(self) -> dict[str, FieldState[object]]:
        """One entry per analysis/advisor decision, keyed by the same
        name used throughout this package -- the manifest's ``records``
        object. No such key set is codified anywhere else in the
        codebase; this is epic 8's own convention.

        The values are the advisors' own typed ``FieldState``s, as
        ``RelaxAdvice``/``DosAdvice`` add theirs: they are projected to
        JSON once, at the boundary (``resolution.records_document``), so
        no record reaches an output by a second path (#152)."""
        return self.tiers().records()

    def warnings(self) -> list[dict[str, object]]:
        """Every record's own ``resolution.Warning``s, flattened into one
        machine-actionable list (``resolution.collect_warnings``), each
        tagged with the ``record`` it came from -- goldilocks-agent
        -design.md's "tool return value must carry a warnings array, the
        agent must relay it verbatim" requirement, as plain dicts a caller
        can filter/group by ``code``/``category``/``record`` without
        parsing text."""
        return self.tiers().warnings()
