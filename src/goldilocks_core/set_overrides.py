"""set_overrides: the shared request-validation path (v2 epic 8, #8;
goldilocks-core-design.md S3577-3584 P3/P5, S4.2's `--set` sections).

One path, three callers: CLI's `--set KEY=VALUE`, an HTTP request body's
override object, and an MCP tool call's override argument all end up
here, building the same `RunOverrides` `service.advise()`/`generate()`
already take -- directly answers this epic's own evidence #1 ("backend
-option validation is CLI-only"): there is now exactly one place that
knows which keys exist and what they mean, not one per transport.

**Not a hand-written key list**: every key this module accepts comes
from `capabilities.bindings()`, which is `capabilities()`'s own
settings-schema walk projected to construction recipes instead of JSON
-- add an advisor's override field and it is immediately both
`--set`-able here and visible in `capabilities()`, from the same single
walk (`capabilities.py`'s own docstring explains why one walk, not two).

**CLI vs HTTP/MCP split**: `coerce_cli_value`/`parse_set_flags` are
CLI-only, converting shell strings into typed Python values (booleans,
numbers, JSON for array/object-shaped settings like `k_grid`/
`u_by_element`). HTTP/MCP request bodies are JSON already, so their
values reach `build_overrides` pre-typed and skip coercion entirely --
`build_overrides` itself is the one transport-agnostic core, matching
P1/P5: validate identically, fail the same way, regardless of caller.

**Routed per task** (#154). ``build_overrides(assignments, task=...)`` is
the only interpreter of ``steps.<step>.<key>``; the steps of a task are
``plan.expand_task``'s purposes (``scf``; ``relax``; ``vc-relax``; ``scf``,
``nscf``, ``dos``; ``scf``, ``bands``, ``bands_x``; and ``scf``, ``relax`` or
``vc-relax``, then ``ph``, ``q2r``, ``phonon_dos``, ``dispersion`` for the
phonon tasks), and each setting declares the steps it applies to
(``capabilities.SettingBinding.steps``):

- analysis and system settings describe the system, and job settings the
  task's one allocation: they are set once per task, flat.
- a step setting given flat lands on every step of the task it applies to,
  with an ``overrides.applies_to_multiple_steps`` notice when that is more
  than one (a dos task's ``k_grid`` reaches its scf and nscf steps, a band
  task's ``nbnd`` its scf and bands steps, and its ``k_grid`` its scf step
  only; a phonon task's first step is its only pw.x step, so its pw.x
  settings land there alone, ``q_grid`` reaches its ph step and
  ``k_path_distance`` its dispersion step);
  ``steps.<step>.<key>`` lands on that step only and beats the flat value
  there.
- a setting that applies to no step of the task (``press`` on an scf), a
  task-level setting given per step, a step the task does not have
  (``steps.scf.*`` in relax-phonon), a setting given without a step that the
  request also sets by step for every step it applies to, and a task that
  does not exist are refused with ``InvalidSetting``: nothing a request sets
  is dropped.
"""

from __future__ import annotations

import difflib
import json
from collections.abc import Mapping
from typing import get_args

from pydantic import ValidationError

from goldilocks_core.capabilities import SettingBinding, bindings
from goldilocks_core.failures import ExpectedFailure
from goldilocks_core.plan import expand_task
from goldilocks_core.service import (
    AnalysisOverrides,
    DosOverrides,
    JobOverrides,
    KPathOverrides,
    KpointsOverrides,
    PhononDosOverrides,
    PhOverrides,
    Q2rOverrides,
    RelaxOverrides,
    ResourceOverrides,
    RunOverrides,
    StepOverrides,
    SystemOverrides,
    applies_to_multiple_steps,
)
from goldilocks_core.types import CalcTask

_STEP_CLASSES = {
    "kpoints": KpointsOverrides,
    "resources": ResourceOverrides,
    "relax": RelaxOverrides,
    "dos": DosOverrides,
    "k_path": KPathOverrides,
    "ph": PhOverrides,
    "q2r": Q2rOverrides,
    "phonon_dos": PhononDosOverrides,
}
"""``StepOverrides``' fields, by the binding branch whose settings fill them."""

_TRUE_STRINGS = {"true", "1", "yes", "on"}
_FALSE_STRINGS = {"false", "0", "no", "off"}


class InvalidSetting(ExpectedFailure, ValueError):
    """A `--set`/override key doesn't exist, or its value doesn't match
    what that key's setting declares. Carries a message already safe
    and specific enough to show a user directly (P6's user-error path)."""

    kind = "invalid_setting"


def _did_you_mean(key: str, candidates: list[str]) -> str:
    matches = difflib.get_close_matches(key, candidates, n=3)
    if matches:
        return f"unknown setting {key!r}; did you mean: {', '.join(matches)}?"
    return f"unknown setting {key!r}; run 'goldilocks settings' to see valid keys"


def _setting(catalogue: Mapping[str, SettingBinding], key: str) -> SettingBinding:
    binding = catalogue.get(key)
    if binding is None:
        raise InvalidSetting(_did_you_mean(key, list(catalogue)))
    return binding


def split_step_key(key: str) -> tuple[str | None, str]:
    """``steps.<step>.<key>`` -> ``(step, key)``; any other key ->
    ``(None, key)``. Raises ``InvalidSetting`` for a ``steps.`` key without
    both parts; whether the step and the key exist for a task is
    ``build_overrides``' decision."""
    if not key.startswith("steps."):
        return None, key
    parts = key.split(".", 2)
    if len(parts) != 3 or not all(parts):
        raise InvalidSetting(f"malformed steps.<name>.<key> setting: {key!r}")
    return parts[1], parts[2]


def parse_set_flags(raw: list[str]) -> dict[str, str]:
    """CLI-only: splits repeated `--set KEY=VALUE` flags into a dict, each
    key as given (a ``steps.<step>.<key>`` key included, which
    ``build_overrides`` routes). Raises `InvalidSetting` for malformed
    flags (no `=`, empty key, or the same key given twice with two
    different values) -- P5's "validate immediately after parsing" applied
    to `--set` itself, not just backend options.
    """
    assignments: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            raise InvalidSetting(f"--set value {item!r} is not KEY=VALUE")
        raw_key, _, value = item.partition("=")
        key = raw_key.strip()
        if not key:
            raise InvalidSetting(f"--set value {item!r} has an empty key")
        if key in assignments and assignments[key] != value:
            raise InvalidSetting(
                f"--set {key!r} given twice with different values "
                f"({assignments[key]!r} and {value!r})"
            )
        assignments[key] = value
    return assignments


def config_assignments(document: Mapping[str, object]) -> dict[str, object]:
    """CLI-only: a ``--config`` TOML document as assignments, its
    ``[steps.<step>]`` tables as ``steps.<step>.<key>`` keys. Raises
    ``InvalidSetting`` when ``steps`` is not a table of such tables."""
    assignments = {key: value for key, value in document.items() if key != "steps"}
    steps = document.get("steps", {})
    if not isinstance(steps, dict) or not all(
        isinstance(table, dict) for table in steps.values()
    ):
        raise InvalidSetting(
            "--config 'steps' must hold [steps.<step>] tables of KEY = VALUE"
        )
    for step, table in steps.items():
        for key, value in table.items():
            assignments[f"steps.{step}.{key}"] = value
    return assignments


def coerce_cli_value(binding: SettingBinding, key: str, raw: str) -> object:
    """Convert one `--set KEY=VALUE` flag's raw string into the type
    `binding.json_type` declares. array/object-shaped settings
    (`k_grid`, `u_by_element`, ...) are parsed as JSON, since a shell
    string has no native array/object syntax of its own; everything
    else uses a direct, minimal rule."""
    kind = binding.json_type["type"]
    if kind == "boolean":
        lowered = raw.strip().lower()
        if lowered in _TRUE_STRINGS:
            return True
        if lowered in _FALSE_STRINGS:
            return False
        raise InvalidSetting(f"{key}={raw!r} is not a boolean (true/false)")
    if kind == "integer":
        try:
            return int(raw)
        except ValueError:
            raise InvalidSetting(f"{key}={raw!r} is not an integer") from None
    if kind == "number":
        try:
            return float(raw)
        except ValueError:
            raise InvalidSetting(f"{key}={raw!r} is not a number") from None
    if kind in ("array", "object"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise InvalidSetting(f"{key}={raw!r} is not valid JSON: {error}") from None
    return raw


def coerce_cli_assignments(raw_assignments: dict[str, str]) -> dict[str, object]:
    """`parse_set_flags`'s output, typed -- looks up each key's binding
    (the key after any ``steps.<step>.`` prefix; raising `InvalidSetting`
    with a did-you-mean suggestion for an unknown one, P3's spirit) and
    coerces its string value. Keys are kept as given."""
    catalogue = bindings()
    typed: dict[str, object] = {}
    for key, raw in raw_assignments.items():
        _step, name = split_step_key(key)
        typed[key] = coerce_cli_value(_setting(catalogue, name), key, raw)
    return typed


def build_overrides(
    assignments: Mapping[str, object], *, task: CalcTask
) -> RunOverrides:
    """The transport-agnostic core: `assignments` values must already
    be Python-typed (bool/int/float/str/list/dict) -- an HTTP/MCP JSON
    body already is; a CLI caller must run `coerce_cli_assignments`
    first. Each key is routed to the steps of ``task`` it applies to
    (module docstring), with a notice per flat key landing on several.

    Raises `InvalidSetting` for a ``task`` that is not a ``types.CalcTask``,
    an unknown key (with a did-you-mean suggestion), a key that applies to
    no step of ``task``, a task-level key given per step, a step ``task``
    does not have, a key given without a step that the request also sets
    for every step it applies to, and a value that doesn't fit its
    setting's real pydantic contract (wrong enum member, wrong shape), with
    that contract's own validation message."""
    if task not in get_args(CalcTask):
        raise InvalidSetting(
            f"unknown task {task!r}; tasks: {', '.join(get_args(CalcTask))}"
        )
    purposes = tuple(step.purpose for step in expand_task(task))
    catalogue = bindings()
    task_level: dict[str, object] = {}
    flat: dict[str, object] = {}
    by_step: dict[str, dict[str, object]] = {purpose: {} for purpose in purposes}
    for key, value in assignments.items():
        step, name = split_step_key(key)
        binding = _setting(catalogue, name)
        if step is not None:
            _check_step(binding, key, step, purposes, task)
            by_step[step][name] = value
        elif binding.steps is None:
            task_level[name] = value
        else:
            flat[name] = value
    landing = {
        name: _flat_landing(catalogue[name], purposes, task, by_step) for name in flat
    }
    for name, steps in landing.items():
        for step in steps:
            by_step[step][name] = flat[name]

    return RunOverrides(
        analysis=AnalysisOverrides(**_fields(catalogue, task_level, "analysis")),
        system=SystemOverrides(**_fields(catalogue, task_level, "system")),
        job=JobOverrides(**_fields(catalogue, task_level, "job")),
        steps={
            step: _step_overrides(catalogue, values)
            for step, values in by_step.items()
            if values
        },
        warnings=tuple(
            applies_to_multiple_steps(name, steps)
            for name, steps in landing.items()
            if len(steps) > 1
        ),
    )


def _listing(noun: str, values: tuple[str, ...]) -> str:
    return f"{noun}{'s' if len(values) > 1 else ''} {', '.join(values)}"


def _check_step(
    binding: SettingBinding,
    key: str,
    step: str,
    purposes: tuple[str, ...],
    task: CalcTask,
) -> None:
    """Raises ``InvalidSetting`` unless ``key`` (``steps.<step>.<setting>``)
    names a step of ``task`` its setting applies to."""
    if step not in purposes:
        raise InvalidSetting(
            f"unknown step {step!r} in {key!r}; "
            f"task {task!r} has steps: {', '.join(purposes)}"
        )
    if binding.steps is None:
        raise InvalidSetting(
            f"{binding.key!r} is set once per task, not per step: "
            f"drop the 'steps.{step}.' prefix"
        )
    if step not in binding.steps:
        raise InvalidSetting(
            f"{binding.key!r} does not apply to step {step!r} (in {key!r}); "
            f"it applies to {_listing('step', binding.steps)}"
        )


def _flat_landing(
    binding: SettingBinding,
    purposes: tuple[str, ...],
    task: CalcTask,
    by_step: Mapping[str, Mapping[str, object]],
) -> tuple[str, ...]:
    """The steps of ``task`` a flat step setting lands on: those it applies
    to, less those the request set it for by step. Raises
    ``InvalidSetting`` when it applies to no step of ``task``, or when the
    request sets it by step for every step it applies to, which leaves the
    flat value no step to land on."""
    applicable = tuple(step for step in purposes if step in binding.steps)
    if not applicable:
        raise InvalidSetting(
            f"{binding.key!r} does not apply to task {task!r}; "
            f"it applies to {_listing('task', binding.tasks)}"
        )
    landing = tuple(step for step in applicable if binding.key not in by_step[step])
    if not landing:
        raise InvalidSetting(
            f"{binding.key!r} given without a step reaches no step: the request "
            f"also sets it for {_listing('step', applicable)} "
            f"(steps.<step>.{binding.key}); drop one of the two"
        )
    return landing


def _fields(
    catalogue: Mapping[str, SettingBinding],
    values: Mapping[str, object],
    branch: str,
) -> dict[str, object]:
    """The keyword arguments of ``branch``'s composing class for the
    settings among ``values`` (setting key -> value) in that branch: a plain
    setting as it is, a ``HumanInput``'s settings validated into one."""
    grouped: dict[str, dict[str, object]] = {}
    classes: dict[str, type | None] = {}
    for key, value in values.items():
        binding = catalogue[key]
        if binding.branch != branch:
            continue
        classes[binding.outer_field] = binding.human_input_cls
        field_name = binding.inner_field or binding.outer_field
        grouped.setdefault(binding.outer_field, {})[field_name] = value

    fields: dict[str, object] = {}
    for outer_field, field_values in grouped.items():
        cls = classes[outer_field]
        if cls is None:
            fields[outer_field] = field_values[outer_field]
            continue
        try:
            fields[outer_field] = cls(**field_values)
        except ValidationError as error:
            raise InvalidSetting(
                f"invalid value(s) for {outer_field!r}: {error}"
            ) from error
    return fields


def _step_overrides(
    catalogue: Mapping[str, SettingBinding], values: Mapping[str, object]
) -> StepOverrides:
    return StepOverrides(
        **{
            branch: cls(**_fields(catalogue, values, branch))
            for branch, cls in _STEP_CLASSES.items()
        }
    )


def build_overrides_from_cli(raw: list[str], *, task: CalcTask) -> RunOverrides:
    """The full CLI path: `--set` strings in, a ready `RunOverrides` for
    ``task`` out."""
    return build_overrides(coerce_cli_assignments(parse_set_flags(raw)), task=task)
