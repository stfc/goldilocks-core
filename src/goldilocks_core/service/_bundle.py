"""Submission-script rendering + bundle assembly, the last step of the
v2 orchestrator (v2 epic 8, #8).
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import version as package_version
from pathlib import PurePosixPath

from goldilocks_core.bundle import (
    BundleInput,
    BundleStep,
    RequestIdentity,
    StructureIdentity,
)
from goldilocks_core.generation.files import InputArtifact
from goldilocks_core.inputs.hpc import HpcProfile
from goldilocks_core.resolution import FieldState
from goldilocks_core.service._advice import Advice
from goldilocks_core.service._pseudo import PseudoAdvice, pseudo_artifacts
from goldilocks_core.steps import SharedContext, Step
from goldilocks_core.submission.slurm import render_slurm_script
from goldilocks_core.types import CalcTask


def render_submission(
    advice: Advice,
    hpc: HpcProfile,
    code: str,
    steps: tuple[Step, ...],
) -> str:
    return render_slurm_script(hpc, advice.step.resources.job.value, code, list(steps))


def to_bundle_input(
    advice: Advice,
    steps: tuple[Step, ...],
    submission_script: str,
    ctx: SharedContext,
    *,
    code: str,
    hpc: HpcProfile,
    assignments: Mapping[str, object],
    source: StructureIdentity,
) -> BundleInput:
    """Assemble one ``BundleInput`` for an ``scf_single_point`` task: the
    rendered input file(s), the pseudopotential files each step's
    ``ATOMIC_SPECIES`` card references with their table's licence
    (``service._pseudo.pseudo_artifacts``), the submission script, every
    advisor decision as a tri-state record, the advice's warnings, and the
    request it answers (``request_identity``)."""
    return assemble_bundle_input(
        advice.system.pseudo,
        steps,
        submission_script,
        ctx,
        advice.records(),
        advice.warnings(),
        request_identity(
            "scf_single_point",
            code=code,
            hpc=hpc,
            assignments=assignments,
            source=source,
        ),
    )


def request_identity(
    task: CalcTask,
    *,
    code: str,
    hpc: HpcProfile,
    assignments: Mapping[str, object],
    source: StructureIdentity,
) -> RequestIdentity:
    """The request a bundle answers (#176): ``task`` and ``code``, the
    name of the ``hpc`` profile, this goldilocks-core's version, the
    ``assignments`` ``set_overrides.build_overrides`` received (an HTTP/MCP
    body's ``overrides``, the CLI's ``--config`` then ``--set`` as typed),
    and the structure identity of ``source``, a
    ``NormalizedStructure.source`` (its content is not copied)."""
    return RequestIdentity(
        code=code,
        task=task,
        hpc=hpc.name,
        core_version=package_version("goldilocks-core"),
        overrides=dict(assignments),
        structure={
            "name": source["name"],
            "format": source["format"],
            "sha256": source["sha256"],
            "size_bytes": source["size_bytes"],
        },
    )


def assemble_bundle_input(
    pseudo: PseudoAdvice,
    steps: tuple[Step, ...],
    submission_script: str,
    ctx: SharedContext,
    records: dict[str, FieldState[object]],
    warnings: list[dict[str, object]],
    request: RequestIdentity,
) -> BundleInput:
    """Shared by ``to_bundle_input`` above and the ``dos``/``relax``
    tasks' ``to_bundle_input_dos``/``to_bundle_input_relax`` -- the
    file-assembly logic never differs between tasks, only which
    ``PseudoAdvice``/records dict feeds it (v2 epic 9, #9, #28) and the
    task ``request`` names (#176).
    ``warnings`` is the advice's own ``warnings()``, the list every
    transport returns, which ``goldilocks.json`` carries unchanged (#152).
    The UPFs and their table's licence come from ``pseudo_artifacts``,
    which raises ``AssetCorrupt`` for a file changed since its table was
    verified (#157, #177)."""
    artifacts: list[InputArtifact] = []
    for step in steps:
        for path, content in step.files.items():
            artifacts.append(
                {"path": path, "role": "input", "content": content.encode("utf-8")}
            )
    artifacts.extend(pseudo_artifacts(pseudo, PurePosixPath(ctx.pseudo_dir).as_posix()))
    artifacts.append(
        {
            "path": "submit.sh",
            "role": "submission_script",
            "content": submission_script.encode("utf-8"),
        }
    )
    return BundleInput(
        artifacts=tuple(artifacts),
        steps=tuple(
            BundleStep(name=step.name, files=tuple(step.files)) for step in steps
        ),
        records=records,
        warnings=tuple(warnings),
        request=request,
    )
