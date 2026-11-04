from __future__ import annotations

import pytest

from goldilocks_core.steps import (
    DEFAULT_OUTDIR,
    DEFAULT_PREFIX,
    DEFAULT_PSEUDO_DIR,
    ExitStatusCheck,
    SharedContext,
    StdoutMarkerCheck,
    Step,
    default_shared_context,
)

_CHECK = ExitStatusCheck("./out/pwscf.save/data-file-schema.xml")


def _step(**fields) -> Step:
    return Step(
        name="scf", executable="pw.x", stdout="scf.out", completion=_CHECK, **fields
    )


def test_step_defaults_to_no_args_and_empty_files() -> None:
    step = _step()

    assert step.args == ()
    assert step.files == {}
    assert step.workdir is None


def test_step_defaults_to_the_whole_allocation() -> None:
    """``ntasks=None``: the program runs on every task the job allocates."""
    step = _step()

    assert step.ntasks is None


def test_step_declares_no_stop_file_or_restart_data_by_default() -> None:
    """Only the ph.x writer declares the stop file a job timer creates and
    the data a rerun resumes from (#215)."""
    step = _step()

    assert step.stop_file is None
    assert step.restart_data == ()


@pytest.mark.parametrize(
    "missing, fields",
    [
        ("completion", {"stdout": "scf.out"}),
        ("stdout", {"completion": _CHECK}),
    ],
)
def test_step_requires_a_completion_check_and_a_stdout_file(
    missing: str, fields: dict[str, object]
) -> None:
    """#129: no writer can produce a step the submission script cannot
    check, or a marker check with no stdout to read."""
    with pytest.raises(TypeError, match=missing):
        Step(name="scf", executable="pw.x", **fields)


def test_step_fields_are_keyword_only() -> None:
    with pytest.raises(TypeError):
        Step("scf", "pw.x", "scf.out", _CHECK)  # type: ignore[misc]


def test_stdout_marker_check_defaults_to_job_done() -> None:
    assert StdoutMarkerCheck().marker == "JOB DONE"


def test_step_carries_code_specific_args_opaquely() -> None:
    step = _step(
        args=("-npool", "4", "-in", "scf.in"), files={"scf.in": "&CONTROL\n/\n"}
    )

    assert step.args == ("-npool", "4", "-in", "scf.in")
    assert step.files["scf.in"].startswith("&CONTROL")


def test_step_is_frozen() -> None:
    step = _step()

    with pytest.raises(AttributeError):
        step.executable = "ph.x"  # type: ignore[misc]


def test_shared_context_is_frozen() -> None:
    ctx = SharedContext(prefix="pwscf", outdir="./out", pseudo_dir="./pseudo")

    with pytest.raises(AttributeError):
        ctx.prefix = "other"  # type: ignore[misc]


def test_default_shared_context_matches_qe_and_v1_defaults() -> None:
    ctx = default_shared_context()

    assert ctx == SharedContext(
        prefix=DEFAULT_PREFIX, outdir=DEFAULT_OUTDIR, pseudo_dir=DEFAULT_PSEUDO_DIR
    )
    assert ctx.prefix == "pwscf"
    assert ctx.outdir == "./out"
    assert ctx.pseudo_dir == "./pseudo"
