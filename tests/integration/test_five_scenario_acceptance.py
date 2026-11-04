"""The five-scenario acceptance harness (v2 epic 9, #9).

A permanent regression suite, not a one-off manual QA pass -- each
scenario below is verbatim from ``goldilocks-implementation-plan.md``
S6.2's table (one test class per row) and stays in the tree after v1's
tree is deleted. Each proves the one architectural bet its row names,
the same reasoning `goldilocks-core-design.md` gives for why an
scf-only smoke test can't stand in for it: tri-state/poison-object
propagation across a real dependency chain (scenario 3), the
simulated-cell/``symmetry_eff`` species-splitting pipeline
(scenario 4), and per-program-typed step settings on a real multi-step
path (scenario 5) have no other standing test that exercises all of
them together, end to end, through the real ``advise()``/``check()``/
``generate()`` orchestrators (or, for scenario 2, the real CLI
subprocess) rather than one advisor in isolation.

**Two corrections to the design doc's own table**, found empirically
while building this suite, both documented inline at the assertion
they affect rather than silently worked around:

- Scenario 3's "unrelated fields (``cutoffs``, ``functional``) resolve
  normally" is only half true: ``cutoffs``/``electron_count`` both read
  ``pseudo.metadata``, so once no table has a fully-relativistic Ce
  pseudopotential at all, they block too, same as the six named
  fields -- already confirmed correct, unrelated behaviour by
  ``test_service_v2.py``'s own
  ``test_unknown_table_id_degrades_the_whole_pseudopotential_chain``.
  ``functional``/``k_sampling``/``occupations``/``boundary`` are the
  fields that are genuinely independent of the pseudopotential chain.
- Scenario 4's "``n_irr_k`` strictly greater" does not hold for classic
  collinear AFM orderings: they only ever break translational
  symmetry, and the k-point count depends only on the rotations pw.x
  keeps -- confirmed for real below by recomputing ``n_irr_k`` on the
  identical relabeled cell/mesh with the spin distinction merged back
  out (unchanged), corrected to "never decreases", decided with the user
  2026-09-14 (v2 epic 9 module 3).

Scenario 2 also exposed a genuine, undocumented granularity gap: the
design doc's "source=human only on mixing_beta, siblings keep
ml/llm/heuristic" assumed per-scalar provenance *within* one compound
decision (``ConvergenceDecision`` bundles ``conv_thr``/``mixing_beta``/
``mixing_mode``/etc. under one ``FieldState``/``Provenance``, by design
-- see ``inputs/overrides.py``'s own docstring). Fixed for real here,
not reinterpreted away: ``Provenance``/``ResolvedField`` gained an
additive, opt-in ``field_sources`` map (``resolution.py``), and
``advisors/convergence.py`` is the first (so far only) advisor to
populate it -- every other advisor's ``Provenance.field_sources`` stays
``None``, unchanged behaviour.
"""

from __future__ import annotations

import dataclasses
import io
import json
import re

import pytest
from pymatgen.core import Lattice, Structure
from pymatgen.io.ase import AseAtomsAdaptor
from support import mc3d_42058_silicon, run_cli, sssp_fixture_table_spec

from goldilocks_core.advisors.magnetic_config import MagneticConfigHumanInput
from goldilocks_core.advisors.magnetic_enumeration import enumlib_installed
from goldilocks_core.advisors.n_irr_k import n_irr_k
from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.examples.structures import structure as example_structure
from goldilocks_core.inputs.hpc import Hardware, HpcProfile, Partition
from goldilocks_core.pw_symmetry import irreducible_kpoint_count, pw_rotations
from goldilocks_core.resolution import Blocked
from goldilocks_core.service import (
    RunOverrides,
    SystemOverrides,
    advise,
    advise_dos,
    check,
    check_dos,
    generate,
    generate_dos,
)
from goldilocks_core.set_overrides import build_overrides
from goldilocks_core.step_settings import DosSettings
from goldilocks_core.steps import SharedContext


def _hpc() -> HpcProfile:
    hardware = Hardware(
        cores_per_node=64, mem_per_node_gb=250, max_nodes=100, max_walltime_h=168
    )
    return HpcProfile(
        name="test-cluster",
        scheduler="slurm",
        launcher="srun",
        modules={"quantum_espresso": ("qe/7.2",)},
        partitions={"scarf": Partition(name="scarf", hardware=hardware, default=True)},
    )


def _silicon() -> Structure:
    return Structure(Lattice.cubic(5.43), ["Si", "Si"], [[0, 0, 0], [0.25, 0.25, 0.25]])


def _installed_store(tmp_path, monkeypatch) -> AssetStore:
    spec, registry_table = sssp_fixture_table_spec(tmp_path / "sources")
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *a, **kw: {registry_table.id: registry_table},
    )
    store = AssetStore(tmp_path / "store")
    store.install(spec, sssp_preparer(registry_table))
    return store


class TestScenario1PlainScf:
    """Row 1: "the trunk works end to end" -- the one scenario every
    other v2 epic already exercises repeatedly; kept here mainly for
    the round-trip-parse half, which nothing else in the suite does."""

    def test_generate_has_no_blocking_and_the_input_round_trips_through_ase(
        self, tmp_path, monkeypatch
    ) -> None:
        from ase.io.espresso import read_espresso_in

        store = _installed_store(tmp_path, monkeypatch)
        silicon = _silicon()

        advice = advise(silicon, hpc=_hpc(), store=store)
        report = check(advice)
        assert report.ok, report.blocking

        steps = generate(advice, report)
        assert len(steps) == 1
        atoms = read_espresso_in(io.StringIO(steps[0].files["scf.in"]))
        assert atoms.get_chemical_formula() == "Si2"


def _card(content: str, header: str, rows: int) -> list[str]:
    lines = content.splitlines()
    start = lines.index(header) + 1
    return [line.strip() for line in lines[start : start + rows]]


class TestWrittenFrame:
    """#140: the cell pw.x is given is the cell n_irr_k counts. MC3D's
    diamond Si (mc3d-42058) comes in pymatgen's frame, where pw.x keeps 4
    of its 48 operations and ran 282 k-points of a 10x10x10 mesh against
    the 47 recorded; it is now written in cubic axes."""

    def test_the_written_cell_is_the_cell_counted(self, tmp_path, monkeypatch) -> None:
        from ase.io.espresso import read_espresso_in

        store = _installed_store(tmp_path, monkeypatch)
        advice = advise(
            mc3d_42058_silicon(),
            hpc=_hpc(),
            overrides=build_overrides(
                {"k_grid": [10, 10, 10]}, task="scf_single_point"
            ),
            store=store,
        )
        report = check(advice)
        assert report.ok, report.blocking

        (step,) = generate(advice, report)

        content = step.files["scf.in"]
        # cubic axes, rows of the (a/2)(1, 0, 1) type; the rotation's 1e-17
        # residues are written as exact zeros
        assert _card(content, "CELL_PARAMETERS angstrom", 3) == [
            "2.715888689  0  2.715888689",
            "2.715888689  2.715888689  0",
            "0  2.715888689  2.715888689",
        ]
        assert _card(content, "ATOMIC_POSITIONS crystal", 2) == [
            "Si  0.5  0.5  0.5",
            "Si  0.75  0.75  0.75",
        ]
        assert re.search(r"^\s*ibrav\s*=\s*0\s*$", content, re.M)
        written = AseAtomsAdaptor.get_structure(read_espresso_in(io.StringIO(content)))
        rotations = pw_rotations(written)
        assert len(rotations) == 48
        assert advice.records()["n_irr_k"].value == 47
        assert irreducible_kpoint_count(rotations, (10, 10, 10), (0, 0, 0)) == 47

    def test_the_scf_and_nscf_of_a_dos_task_write_one_cell(
        self, tmp_path, monkeypatch
    ) -> None:
        """The nscf step reads the scf step's charge density from the shared
        outdir, so both must be written in the same frame."""
        store = _installed_store(tmp_path, monkeypatch)
        advice = advise_dos(mc3d_42058_silicon(), hpc=_hpc(), store=store)
        report = check_dos(advice)
        assert report.ok, report.blocking

        scf, nscf, _dos = generate_dos(advice, report)

        decks = [scf.files["scf.in"], nscf.files["nscf.in"]]
        cells = [_card(deck, "CELL_PARAMETERS angstrom", 3) for deck in decks]
        positions = [_card(deck, "ATOMIC_POSITIONS crystal", 2) for deck in decks]
        assert cells[0] == cells[1]
        assert positions[0] == positions[1]
        assert advice.records()["magnetic"].value.frame.rotated is True


class TestScenario2ExplicitFieldOverride:
    """Row 2: ``--set mixing_beta=0.2`` through the real CLI subprocess
    (not the internal core API) -- one of this epic's own required
    "at least one scenario through the delivery layer" proofs."""

    def test_set_mixing_beta_marks_only_that_field_human(self, real_assets) -> None:
        silicon = example_structure("Si.cif")

        baseline = run_cli("explain", str(silicon), "--hpc", "scarf", "--json")
        overridden = run_cli(
            "explain",
            str(silicon),
            "--hpc",
            "scarf",
            "--set",
            "mixing_beta=0.2",
            "--json",
        )
        assert baseline.returncode == 0, baseline.stderr
        assert overridden.returncode == 0, overridden.stderr

        before = json.loads(baseline.stdout)["records"]["convergence"]
        after = json.loads(overridden.stdout)["records"]["convergence"]

        assert after["field_sources"]["mixing_beta"] == "human"
        assert after["value"]["mixing_beta"] == 0.2
        for sibling in ("conv_thr", "etot_conv_thr", "mixing_mode", "electron_maxstep"):
            assert after["field_sources"][sibling] in {"ml", "llm", "heuristic"}
            assert after["value"][sibling] == before["value"][sibling]


class TestScenario3SocOnCerium:
    """Row 3: tri-state field resolution + poison-object propagation
    across a real dependency chain. Ce + SSSP (the only table
    lanthanides may use) with no fully-relativistic entry is the
    concrete case named in the design doc -- table *selection* itself
    fails, no asset store needed.

    The design doc names six fields (``pseudos``, ``relativistic``,
    ``noncolin``, ``k_sampling``'s Gamma-only restriction, doubled
    ``nbnd``, non-collinear-shaped ``starting_magnetization``); this
    codebase carries them as four real top-level ``FieldState``s
    (``pseudo.metadata``, ``pseudo.relativistic``, ``magnetic`` --
    which bundles both ``noncolin`` and ``starting_magnetization`` into
    one ``magnetic_config()`` decision -- and ``nbnd``). The Gamma-only
    restriction has no field of its own because it is structurally moot
    in v2: generation never emits QE's special ``K_POINTS gamma`` card
    at all (confirmed v2 epic 9 module 2), so there is nothing for SOC
    to have needed to restrict.
    """

    def _advise(self, hpc: HpcProfile):
        cerium = Structure(Lattice.cubic(5.16), ["Ce"], [[0.0, 0.0, 0.0]])
        overrides = RunOverrides(
            system=SystemOverrides(
                magnetic=MagneticConfigHumanInput(spin_orbit_coupling=True)
            )
        )
        return advise(cerium, hpc=hpc, overrides=overrides)

    def test_the_named_fields_all_block_from_one_root_cause(self) -> None:
        advice = self._advise(_hpc())

        blocked_fields = (
            advice.system.pseudo.metadata,
            advice.system.pseudo.relativistic,
            advice.system.magnetic,
            advice.step.kpoints.nbnd,
        )
        assert all(isinstance(field, Blocked) for field in blocked_fields)

        root_causes = {field.root_cause() for field in blocked_fields}
        assert len(root_causes) == 1, root_causes
        assert "Ce" in next(iter(root_causes))

    def test_unrelated_fields_resolve_normally(self) -> None:
        advice = self._advise(_hpc())

        assert advice.system.functional.ok
        assert advice.step.kpoints.k_sampling.ok
        assert advice.step.kpoints.occupations.ok
        assert advice.system.boundary.ok

        # Correction (found 2026-09-14): the design doc lists `cutoffs`
        # here too, but `cutoffs()`/`electron_count()` both read
        # `pseudo.metadata` and correctly block once it does -- see the
        # module docstring above.
        assert isinstance(advice.system.cutoffs, Blocked)
        assert isinstance(advice.system.electron_count, Blocked)


_ENUMLIB_MISSING = not enumlib_installed()


@pytest.mark.skipif(
    _ENUMLIB_MISSING,
    reason="needs the enumlib executables (enum.x, makeStr.py) on PATH",
)
class TestScenario4Afm:
    """Row 4: simulated-cell plumbing + symmetry recompute +
    k-point propagation. Rock-salt FeO, the design doc's own worked
    example (Fe -> Fe1/Fe2)."""

    def test_split_cell_symmetry_eff_and_n_irr_k(self) -> None:
        hpc = _hpc()
        rock_salt_feo = Structure(
            Lattice.cubic(4.3), ["Fe", "O"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]
        )
        overrides = RunOverrides(
            system=SystemOverrides(
                magnetic=MagneticConfigHumanInput(magnetic_ordering="afm")
            )
        )

        advice = advise(rock_salt_feo, hpc=hpc, overrides=overrides)

        assert advice.system.magnetic.ok
        relabeled = advice.system.cell.value.structure
        assert len(set(relabeled.species)) > len(set(rock_salt_feo.species))

        assert advice.system.symmetry_eff.ok
        assert advice.system.symmetry_eff.value != advice.analysis.symmetry.value

        assert advice.step.kpoints.n_irr_k.ok
        afm_n_irr_k = advice.step.kpoints.n_irr_k.value

        # Corrected assertion (v2 epic 9 module 3, decided with the
        # user): "never decreases", not "strictly greater". Proven
        # directly: recompute n_irr_k on the *same* written cell and the
        # *same* mesh, only merging Fe1/Fe2's spin distinction back into
        # plain "Fe" -- isolating species-splitting as the only variable.
        # The merged cell is a supercell, where pw.x allows no fractional
        # translation (#140), but this group is symmorphic, so it keeps
        # every rotation and the count does not change: the AFM ordering
        # only breaks translational symmetry.
        merged = Structure(
            relabeled.lattice,
            [str(site.specie.element) for site in relabeled],
            relabeled.frac_coords,
        )
        ignoring_split = n_irr_k(
            dataclasses.replace(advice.system.cell.value, structure=merged),
            advice.step.kpoints.k_sampling,
        )
        assert ignoring_split.ok
        assert afm_n_irr_k >= ignoring_split.value

        # Against the default (FM) advice on the same input: the AFM
        # cell's mesh is one its cubic group maps onto itself, n x n x n
        # in enumlib's skewed basis, and has fewer irreducible k-points
        # than the FM cell's. Meshing each axis on its own gave 9x10x9
        # there, which broke the group: 230 irreducible k-points against
        # the FM cell's 56, once read here as the cost of the bigger cell
        # (#163).
        fm_advice = advise(rock_salt_feo, hpc=hpc)
        assert fm_advice.step.kpoints.n_irr_k.ok
        assert len(set(advice.step.kpoints.k_sampling.value.mesh)) == 1
        assert afm_n_irr_k < fm_advice.step.kpoints.n_irr_k.value


class TestScenario5DosMultiStep:
    """Row 5: per-step typed settings. The type-level absence
    (``DosSettings`` has no ``k_sampling``/``n_irr_k``/``nbnd``/
    ``convergence`` attributes at all) has been true since v2 epic 6;
    what v2 epic 9 module 4 added is a real producer for the *other*
    half -- a genuine three-step ``advise_dos``/``check_dos``/
    ``generate_dos`` path, not just the data structure."""

    def test_dos_settings_structurally_lacks_pw_only_fields(self) -> None:
        field_names = {field.name for field in dataclasses.fields(DosSettings)}

        assert {"emin", "emax", "delta_e", "ngauss"} <= field_names
        assert field_names.isdisjoint({"k_sampling", "n_irr_k", "nbnd", "convergence"})

    def test_advise_check_generate_dos_produce_a_real_three_step_bundle(
        self, tmp_path, monkeypatch
    ) -> None:
        store = _installed_store(tmp_path, monkeypatch)

        advice = advise_dos(_silicon(), hpc=_hpc(), store=store)
        report = check_dos(advice)
        assert report.ok, report.blocking
        ctx = SharedContext(prefix="si", outdir="./scratch", pseudo_dir="./pseudo")

        steps = generate_dos(advice, report, ctx=ctx)

        assert [step.name for step in steps] == ["scf", "nscf", "dos"]
        assert [step.executable for step in steps] == ["pw.x", "pw.x", "dos.x"]
        for step in steps:
            (content,) = step.files.values()
            assert "prefix           = 'si'" in content
            assert "outdir           = './scratch'" in content
