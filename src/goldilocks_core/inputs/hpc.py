"""hpc: cluster profile schema and TOML loader.

New in v2 (v2 epic 7, #7); no v1 precedent -- v1's CLI wizard
(`cli/wizard/hpc.py`, deleted from the v2 tree) did live runtime
auto-detection via `sinfo`/`sacctmgr`/`module avail` rather than a
stored profile. This codebase instead ships static profile files:
`advisors/job_resources.py` reads a profile's hardware/partition specs
directly, rather than re-probing a live scheduler at every call (this
package does not assume it is even running on the cluster it is
generating inputs for).

``[hardware]`` is the baseline; ``[partitions.<name>]`` override only
what differs, inheriting everything else -- the same pattern
aiida-quantumespresso's own protocol files use (a shared
``default_inputs`` baseline, each protocol only listing its diffs).
Exactly one partition must set ``default = true``.

Units are baked into field names (``mem_per_node_gb``, not
``"256GB"``) so no unit-string parser is needed -- TOML numbers are
just numbers.

``inputs/profiles/scarf.toml`` is STFC SCARF's real configuration,
verified against live ``sinfo``/``scontrol show partition``/
``sacctmgr`` output (2026-09-14), not an invented example: SCARF's
``scarf``/``devel``/``preemptable`` partitions share one heterogeneous
node pool where ``sinfo`` reports only a *minimum* guaranteed spec
(e.g. "64+ CPUs", "257000+ MB") -- many nodes have more, but sizing off
the minimum is the only safe default across a mixed pool. ``ibis`` is
excluded (restricted to a different account than this profile assumes
access for). ``account`` is deliberately not a profile field at all --
it is personal to whoever is submitting, not a property of the
cluster, so it stays a human override (``--set account=...``), never a
package-shipped default.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib import resources

from goldilocks_core.failures import ExpectedFailure


@dataclass(frozen=True, slots=True)
class Hardware:
    cores_per_node: int
    mem_per_node_gb: float
    max_nodes: int
    max_walltime_h: float


@dataclass(frozen=True, slots=True)
class Partition:
    name: str
    hardware: Hardware
    default: bool = False


@dataclass(frozen=True, slots=True)
class HpcProfile:
    name: str
    scheduler: str
    launcher: str
    modules: dict[str, tuple[str, ...]]
    partitions: dict[str, Partition]

    def default_partition(self) -> Partition:
        for partition in self.partitions.values():
            if partition.default:
                return partition
        raise ValueError(f"hpc profile {self.name!r} declares no default partition")

    def partition(self, name: str) -> Partition:
        try:
            return self.partitions[name]
        except KeyError:
            available = ", ".join(sorted(self.partitions))
            raise ValueError(
                f"hpc profile {self.name!r} has no partition {name!r}; "
                f"available: {available}"
            ) from None


class InvalidHpcProfile(ExpectedFailure, ValueError):
    """A profile TOML file is missing required fields or malformed, or a
    named profile doesn't exist. Made an ``ExpectedFailure`` in v2 epic
    8 (#8): a bad ``--hpc`` name is a user-input error like any other
    (``StructureInputError``, ``GenerationError``, ...), not a bug --
    the one CLI/HTTP/MCP validation path needs to be able to catch it
    the same uniform way."""

    kind = "invalid_hpc_profile"


def load_hpc_profile(name: str) -> HpcProfile:
    resource = resources.files("goldilocks_core.inputs.profiles").joinpath(
        f"{name}.toml"
    )
    try:
        with resource.open("rb") as source:
            data = tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise InvalidHpcProfile(f"cannot read hpc profile {name!r}: {error}") from error
    return _parse_profile(name, data)


def list_hpc_profiles() -> tuple[str, ...]:
    """Every profile name shipped under ``inputs/profiles/`` -- added for
    v2 epic 8's ``capabilities`` contract (``hpc_profiles[]``), which
    needs every profile, not just one named one. No consumer needed this
    before now: ``--hpc``'s own choices and ``goldilocks assets``-style
    listing both live in the delivery layer, not here."""
    names = [
        entry.name.removesuffix(".toml")
        for entry in resources.files("goldilocks_core.inputs.profiles").iterdir()
        if entry.name.endswith(".toml")
    ]
    return tuple(sorted(names))


def resolve_hpc_profile(name: str | None, *, field: str = "hpc") -> HpcProfile:
    """The one policy for turning an optional caller-given profile name
    into a real ``HpcProfile``, shared by the CLI's ``--hpc`` and HTTP/
    MCP's ``hpc`` request field (v2 epic 8, #8) -- an explicit name
    always wins; with none given, exactly one installed profile is an
    unambiguous default, and more than one requires the caller to
    choose. ``field`` only changes the wording of that error, so a CLI
    caller sees ``--hpc`` and a transport caller sees the request field
    name it actually used.
    """
    if name is not None:
        return load_hpc_profile(name)
    available = list_hpc_profiles()
    if len(available) == 1:
        return load_hpc_profile(available[0])
    if not available:
        raise InvalidHpcProfile("no HPC profiles are installed under inputs/profiles/")
    raise InvalidHpcProfile(
        f"{field} is required when more than one profile is installed: "
        + ", ".join(available)
    )


def _parse_profile(name: str, data: dict[str, object]) -> HpcProfile:
    try:
        hardware_defaults = data["hardware"]
        raw_partitions = data["partitions"]
        scheduler = data["scheduler"]
        launcher = data["launcher"]
    except KeyError as error:
        raise InvalidHpcProfile(
            f"hpc profile {name!r} is missing required field {error}"
        ) from error

    partitions: dict[str, Partition] = {}
    for partition_name, overrides in raw_partitions.items():
        merged = {**hardware_defaults, **overrides}
        hardware = Hardware(
            cores_per_node=merged["cores_per_node"],
            mem_per_node_gb=merged["mem_per_node_gb"],
            max_nodes=merged["max_nodes"],
            max_walltime_h=merged["max_walltime_h"],
        )
        partitions[partition_name] = Partition(
            name=partition_name,
            hardware=hardware,
            default=bool(overrides.get("default", False)),
        )

    defaults = [
        partition.name for partition in partitions.values() if partition.default
    ]
    if len(defaults) != 1:
        found = ", ".join(defaults) or "none"
        raise InvalidHpcProfile(
            f"hpc profile {name!r} must have exactly one default partition; "
            f"found {found}"
        )

    return HpcProfile(
        name=name,
        scheduler=scheduler,
        launcher=launcher,
        modules={
            code: tuple(module_lines)
            for code, module_lines in data.get("modules", {}).items()
        },
        partitions=partitions,
    )
