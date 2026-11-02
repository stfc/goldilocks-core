"""Tests for goldilocks_core.service (v2 epic 8, #8)."""

from __future__ import annotations

import dataclasses
import functools
import json
from pathlib import Path

import pytest
import spglib
from pymatgen.core import Lattice, Species as SpinSpecies, Structure
from support import (
    SSSP_FIXTURE_UPF as _UPF,
    fcc_lead,
    hcp_gadolinium,
    in_memory_source,
    mc3d_42058_silicon,
    sssp_fixture_table_spec as _sssp_table_spec,
)

from goldilocks_core.advisors import magnetic_config as magnetic_config_module
from goldilocks_core.advisors.magnetic_config import MagneticConfigHumanInput
from goldilocks_core.advisors.magnetic_enumeration import enumlib_installed
from goldilocks_core.advisors.parallelisation import (
    diag_grid_side,
)
from goldilocks_core.advisors.size import Species, memory_estimate, resource_estimate
from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.pseudopotentials.upf import parse_upf_metadata
from goldilocks_core.assets.store import AssetCorrupt, AssetStore
from goldilocks_core.bundle import DirectoryOutput, is_complete, publish
from goldilocks_core.inputs.hpc import Hardware, HpcProfile, Partition
from goldilocks_core.inputs.structure import StructureInputError
from goldilocks_core.resolution import Blocked, Unavailable, records_document
from goldilocks_core.service import (
    AdviceIncomplete,
    RunOverrides,
    SystemOverrides,
    advise,
    advise_dos,
    advise_relax,
    check,
    generate,
    render_submission,
    to_bundle_input,
)
from goldilocks_core.service._pseudo import upf_projectors
from goldilocks_core.set_overrides import build_overrides
from goldilocks_core.steps import default_shared_context


@pytest.fixture
def silicon() -> Structure:
    return Structure(Lattice.cubic(5.43), ["Si", "Si"], [[0, 0, 0], [0.25, 0.25, 0.25]])


@pytest.fixture
def hpc() -> HpcProfile:
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


@pytest.fixture
def installed_table(tmp_path, monkeypatch):
    spec, registry_table = _sssp_table_spec(tmp_path / "sources")
    store = AssetStore(tmp_path / "store")
    store.install(spec, sssp_preparer(registry_table))
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *a, **kw: {registry_table.id: registry_table},
    )
    return store, registry_table


class TestAdviseEndToEnd:
    """The real, non-hand-built-fixture pipeline: a genuine AssetStore
    install, not a FieldState constructed by hand -- this is the test
    every prior epic's own docstring flagged as missing until this one."""

    def test_full_pipeline_produces_a_complete_bundle(
        self, silicon, hpc, installed_table, tmp_path
    ) -> None:
        store, _table = installed_table

        advice = advise(silicon, hpc=hpc, store=store)
        report = check(advice)
        assert report.ok, report.blocking

        steps = generate(advice, report)
        assert len(steps) == 1
        assert steps[0].name == "scf"
        assert "scf.in" in steps[0].files

        ctx = default_shared_context()
        script = render_submission(advice, hpc, "quantum_espresso", steps)
        assert "#SBATCH" in script
        assert "pw.x" in script

        bundle_input = to_bundle_input(
            advice,
            steps,
            script,
            ctx,
            code="quantum_espresso",
            hpc=hpc,
            assignments={},
            source=in_memory_source(silicon),
        )
        roles = {a["path"]: a["role"] for a in bundle_input.artifacts}
        assert roles["submit.sh"] == "submission_script"
        assert roles["pseudo/Si.upf"] == "pseudopotential"
        assert roles["licences/sssp-fixture.txt"] == "licence"

        destination = tmp_path / "out"
        publish(bundle_input, DirectoryOutput(destination))

        assert is_complete(destination)
        manifest = json.loads((destination / "goldilocks.json").read_text())
        assert manifest["records"]["functional"]["status"] == "resolved"
        assert manifest["records"]["functional"]["value"] == "PBEsol"
        assert manifest["records"]["pseudopotentials"]["status"] == "resolved"
        assert manifest["citations"] == ["Synthetic SSSP fixture, cite me."]
        # #176: a structure built in memory has no submitted text to hash.
        assert manifest["request"]["structure"] == {
            "name": "generated-structure",
            "format": "pymatgen",
            "sha256": None,
            "size_bytes": None,
        }
        assert (manifest["request"]["task"], manifest["request"]["hpc"]) == (
            "scf_single_point",
            "test-cluster",
        )
        assert (
            "results.\n\n- Synthetic SSSP fixture, cite me.\n\n## Licences\n"
            in (destination / "CITATIONS.md").read_text()
        )
        assert (destination / "pseudo" / "Si.upf").read_bytes() == _UPF
        assert (
            destination / "licences" / "sssp-fixture.txt"
        ).read_bytes() == b"SSSP fixture licence\n"
        assert (destination / "scf.in").exists()
        assert (destination / "submit.sh").exists()

    def test_bundle_refuses_a_pseudopotential_changed_since_it_was_verified(
        self, silicon, hpc, installed_table
    ) -> None:
        """#177: the bundle ships the bytes its pseudopotentials record
        names. A UPF rewritten in the store after the advice read it would
        put a file in ``goldilocks.json`` whose hash disagrees with its
        record, so assembly refuses it."""
        store, _table = installed_table
        advice = advise(silicon, hpc=hpc, store=store)
        steps = generate(advice, check(advice))
        script = render_submission(advice, hpc, "quantum_espresso", steps)
        (metadata,) = advice.system.pseudo.metadata.value
        Path(metadata.filepath).write_bytes(
            _UPF.replace(b'z_valence="4.0"', b'z_valence="4.5"')
        )

        with pytest.raises(
            AssetCorrupt,
            match=r"^pseudos/Si\.upf of pseudopotentials/sssp-fixture@1 "
            r"changed after its table was verified$",
        ):
            to_bundle_input(
                advice,
                steps,
                script,
                default_shared_context(),
                code="quantum_espresso",
                hpc=hpc,
                assignments={},
                source=in_memory_source(silicon),
            )

    def test_bundle_refuses_a_licence_changed_since_it_was_verified(
        self, silicon, hpc, installed_table
    ) -> None:
        """#157: the licence the bundle ships beside the UPFs is read
        through the table's verified inventory, like the UPFs: a LICENSE.txt
        rewritten after the advice resolved the table is refused."""
        store, _table = installed_table
        advice = advise(silicon, hpc=hpc, store=store)
        steps = generate(advice, check(advice))
        script = render_submission(advice, hpc, "quantum_espresso", steps)
        (metadata,) = advice.system.pseudo.metadata.value
        installation = Path(metadata.filepath).parents[1]
        (installation / "LICENSE.txt").write_text("Some other licence\n")

        with pytest.raises(
            AssetCorrupt,
            match=r"^LICENSE\.txt of pseudopotentials/sssp-fixture@1 "
            r"changed after its table was verified$",
        ):
            to_bundle_input(
                advice,
                steps,
                script,
                default_shared_context(),
                code="quantum_espresso",
                hpc=hpc,
                assignments={},
                source=in_memory_source(silicon),
            )

    def test_generate_renders_the_advised_steps_own_max_seconds_share(
        self, silicon, hpc, installed_table
    ) -> None:
        """#169: the share travels with the advised step, so ``purpose``
        only picks the writer; an scf advice rendered as nscf used to
        raise a bare KeyError looking up max_seconds_by_step['nscf']."""
        store, _table = installed_table
        advice = advise(silicon, hpc=hpc, store=store)
        report = check(advice)

        (nscf,) = generate(advice, report, purpose="nscf")

        share = advice.step.resources.job.value.max_seconds_by_step["scf"]
        assert advice.step.resources.max_seconds == share == 574560
        assert f"   max_seconds      = {share}" in nscf.files["nscf.in"].splitlines()

    def test_warnings_flattens_every_record_s_structured_warnings(
        self, silicon, hpc, installed_table
    ) -> None:
        store, _table = installed_table

        advice = advise(silicon, hpc=hpc, store=store)

        warnings = advice.warnings()
        assert warnings  # scarf's own missing-walltime warning always fires
        assert all(
            warning.keys() == {"code", "level", "category", "message", "record"}
            for warning in warnings
        )
        assert any(
            (warning["code"], warning["record"]) == ("job.walltime_defaulted", "job")
            for warning in warnings
        )

    def test_npool_not_dividing_ntasks_blocks_end_to_end(
        self, silicon, hpc, installed_table
    ) -> None:
        """Regression for #52, exercised through the real advise()/
        check() pipeline (test_checks.py already covers checks.check_all
        directly) -- npool=7 never divides scarf's 64 ntasks."""
        store, _table = installed_table
        overrides = build_overrides({"npool": 7}, task="scf_single_point")

        advice = advise(silicon, hpc=hpc, overrides=overrides, store=store)
        assert advice.step.resources.job.value.ntasks == 64
        report = check(advice)

        (finding,) = report.blocking
        assert finding.code == "parallelisation.npool_does_not_divide_ntasks"
        assert finding.message.startswith("npool=7 does not divide ntasks=64")

    @pytest.mark.parametrize(
        "setting", [{"nbnd": 2}, {"extra_bands": -6}], ids=["nbnd", "extra_bands"]
    )
    def test_a_human_band_count_below_the_electron_count_is_refused(
        self, silicon, hpc, installed_table, setting
    ) -> None:
        """#131: 2 bands, set outright or as the 8-band default less 6,
        cannot hold the fixture cell's 8 electrons, and pw.x stops in setup
        with 'too few bands'; check() refuses it before generation
        instead."""
        store, _ = installed_table
        overrides = build_overrides(setting, task="scf_single_point")

        advice = advise(silicon, hpc=hpc, overrides=overrides, store=store)
        assert advice.step.kpoints.nbnd.value.nbnd == 2
        report = check(advice)

        (finding,) = report.blocking
        assert finding.code == "nbnd.too_few_bands"
        assert "'too few bands'" in finding.message

    def test_human_overrides_flow_through_to_generated_input(
        self, silicon, hpc, installed_table
    ) -> None:
        from goldilocks_core.advisors.functional import FunctionalHumanInput

        store, _ = installed_table
        overrides = RunOverrides(
            system=SystemOverrides(functional=FunctionalHumanInput(functional="PBE"))
        )

        advice = advise(silicon, hpc=hpc, store=store, overrides=overrides)

        assert advice.system.functional.ok
        assert advice.system.functional.value == "PBE"
        assert advice.system.functional.source == "human"
        # PBE pseudopotentials aren't in the fixture table (PBEsol only),
        # so downstream table selection correctly can't find a match --
        # proving the override actually reached pseudo_requirements().
        assert not advice.system.pseudo.table.ok

    def test_human_override_of_an_analysis_fact_flows_through(
        self, silicon, hpc, installed_table
    ) -> None:
        """`capabilities()` advertises the four analysis facts as
        overridable (v2 epic 8, #8) -- confirm `advise()`'s own end of
        that promise, not just that `set_overrides.build_overrides` can
        construct the ``RunOverrides`` (``test_set_overrides.py`` covers
        that half)."""
        from goldilocks_core.analysis.is_metal import IsMetalHumanInput
        from goldilocks_core.service._analysis import AnalysisOverrides

        store, _ = installed_table
        overrides = RunOverrides(
            analysis=AnalysisOverrides(is_metal=IsMetalHumanInput(is_metal="metal"))
        )

        advice = advise(silicon, hpc=hpc, store=store, overrides=overrides)

        assert advice.analysis.is_metal.ok
        assert advice.analysis.is_metal.value == "metal"
        assert advice.analysis.is_metal.source == "human"


def _si_upf(header: str) -> bytes:
    return (
        '<UPF version="2.0.1">\n'
        f'<PP_HEADER element="Si" functional="PBEsol" z_valence="4.0" {header}/>\n'
        "</UPF>\n"
    ).encode()


def _store_with(
    upf: bytes, tmp_path, monkeypatch, *, relativistic: str = "scalar"
) -> AssetStore:
    """The offline fixture table with ``upf`` as its Si file."""
    import support

    monkeypatch.setattr(support, "SSSP_FIXTURE_UPF", upf)
    spec, registry_table = _sssp_table_spec(tmp_path / "sources")
    registry_table = dataclasses.replace(registry_table, relativistic=relativistic)
    store = AssetStore(tmp_path / "store")
    store.install(spec, sssp_preparer(registry_table))
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *a, **kw: {registry_table.id: registry_table},
    )
    return store


def _per_process_mb(
    advice,
    species: Species,
    *,
    npol: int = 1,
    nspin: int = 1,
    nspin_mag: int = 1,
    variable_cell: bool = False,
) -> float:
    """pw.x's figure for the advised SCF-loop step of diamond Si, at the
    advised layout, with the estimate inputs a test names."""
    assert advice.step.kpoints.convergence.value.mixing_mode == "plain"
    cutoffs = advice.system.cutoffs.value
    nbnd = advice.step.kpoints.nbnd.value.nbnd
    estimate = resource_estimate(
        advice.system.magnetic.value.cell.lattice,
        (species,),
        ecutwfc_ry=cutoffs.ecutwfc_ry,
        ecutrho_ry=cutoffs.ecutrho_ry,
        nbnd=nbnd,
        n_kpoint_spin=advice.step.kpoints.n_irr_k.value,
        nspin=nspin,
        npol=npol,
        nspin_mag=nspin_mag,
        scf_loop=True,
        variable_cell=variable_cell,
        local_tf_mixing=False,
    )
    job = advice.step.resources.job.value
    parallel = advice.step.resources.parallelisation.value
    side = diag_grid_side(parallel.ndiag, job.ntasks // parallel.npool, nbnd)
    memory = memory_estimate(
        estimate, ntasks=job.ntasks, npool=parallel.npool, diag_side=side
    )
    return round(memory.per_process_mb, 2)


class TestJobMemory:
    """#148: the job is sized on pw.x's estimated memory, which reads the
    projector counts from each pseudopotential's own UPF header."""

    def test_projector_counts_come_from_a_upf_v1_text_header(self, tmp_path) -> None:
        """120 installed SSSP files (GBRV, old pslibrary) give the counts
        as text-header lines, not attributes; these are SSSP's
        Co_pbe_v1.2.uspp.F.UPF lines verbatim."""
        path = tmp_path / "Co_pbe_v1.2.uspp.F.UPF"
        path.write_text(
            "<PP_INFO>\n"
            "    1        The Pseudo was generated with a Scalar-Relativistic "
            "Calculation\n"
            "</PP_INFO>\n"
            "<PP_HEADER>\n"
            "   0                   Version Number\n"
            "  Co                   Element\n"
            "   US                  Ultrasoft pseudopotential\n"
            "SLA  PW   PBE  PBE     PBE  Exchange-Correlation functional\n"
            "   17.00000000000      Z valence\n"
            "    2                  Max angular momentum component\n"
            "    5    6             Number of Wavefunctions, Number of Projectors\n"
            "</PP_HEADER>\n"
        )

        assert upf_projectors((parse_upf_metadata(path),)) == {"Co": (6, 2)}

    def test_ultrasoft_species_and_u_projectors_reach_the_estimate(
        self, diamond_silicon, hpc, tmp_path, monkeypatch
    ) -> None:
        """The written species' pseudo_type and the HUBBARD card's
        manifold, here U on an ultrasoft Si's 3p (l = 1)."""
        upf = _si_upf(
            'pseudo_type="US" relativistic="scalar" number_of_wfc="2" '
            'number_of_proj="4" l_max="1"'
        )
        store = _store_with(upf, tmp_path, monkeypatch)
        overrides = build_overrides(
            {"u_by_element": {"Si": 4.0}}, task="scf_single_point"
        )

        advice = advise(diamond_silicon, hpc=hpc, overrides=overrides, store=store)

        species = Species(atoms=2, projectors=4, l_max=1, ultrasoft=True, hubbard_l=1)
        job = advice.step.resources.job.value
        assert job.memory_per_process_mb == _per_process_mb(advice, species)

    def test_a_non_magnetic_spin_orbit_run_has_one_magnetization_component(
        self, diamond_silicon, hpc, tmp_path, monkeypatch
    ) -> None:
        """Spin-orbit runs nspin=4 spinors, but without a starting
        magnetization only one magnetization component, which sizes the
        ultrasoft scratch (``parallelisation.qe_spin_layout``); on one
        task that scratch is the largest block."""
        upf = _si_upf(
            'pseudo_type="US" relativistic="full" number_of_wfc="2" '
            'number_of_proj="4" l_max="1"'
        )
        store = _store_with(upf, tmp_path, monkeypatch, relativistic="full")
        overrides = build_overrides(
            {"spin_orbit_coupling": True, "ntasks": 1}, task="scf_single_point"
        )

        advice = advise(diamond_silicon, hpc=hpc, overrides=overrides, store=store)

        magnetic = advice.system.magnetic.value
        assert magnetic.spin_orbit_enabled and not magnetic.spin_polarized
        species = Species(atoms=2, projectors=4, l_max=1, ultrasoft=True)
        job = advice.step.resources.job.value
        assert job.ntasks == 1
        assert job.memory_per_process_mb == _per_process_mb(
            advice, species, npol=2, nspin=4, nspin_mag=1
        )

    def test_a_vc_relax_estimate_holds_the_variable_cell_arrays(
        self, diamond_silicon, hpc, installed_table
    ) -> None:
        store, _table = installed_table

        relax = advise_relax(
            diamond_silicon, calculation="vc-relax", hpc=hpc, store=store
        )

        species = Species(atoms=2, projectors=4, l_max=1, ultrasoft=False)
        job = relax.advice.step.resources.job.value
        assert job.memory_per_process_mb == _per_process_mb(
            relax.advice, species, variable_cell=True
        )

    def test_a_header_without_projector_counts_makes_the_job_unavailable(
        self, silicon, hpc, tmp_path, monkeypatch
    ) -> None:
        upf = _si_upf('pseudo_type="NC" relativistic="scalar"')
        store = _store_with(upf, tmp_path, monkeypatch)

        advice = advise(silicon, hpc=hpc, store=store)

        job = advice.step.resources.job
        assert isinstance(job, Unavailable)
        assert "Si.upf" in job.reason
        assert "number_of_proj" in job.reason
        report = check(advice)
        assert any("Si.upf" in finding.message for finding in report.blocking)


class TestPoolsShareKpointSpinPairs:
    """#168: pw.x splits k-point/spin pairs over pools, two per k-point
    with collinear spin. ``k_grid=[3,3,3]`` gives the fixture cell
    n_irr_k 6, on the test cluster's 64 tasks."""

    @staticmethod
    def _parallelisation(silicon, hpc, store, **settings):
        overrides = build_overrides(
            {"k_grid": [3, 3, 3], **settings}, task="scf_single_point"
        )
        advice = advise(silicon, hpc=hpc, overrides=overrides, store=store)
        assert advice.step.kpoints.n_irr_k.value == 6
        assert advice.step.resources.job.value.ntasks == 64
        assert check(advice).ok
        return advice.step.resources.parallelisation.value

    @staticmethod
    def _codes(parallel) -> list[str]:
        return [warning.code for warning in parallel.warnings]

    def test_spin_polarized_run_pools_twelve_pairs_evenly(
        self, silicon, hpc, installed_table
    ) -> None:
        store, _table = installed_table

        parallel = self._parallelisation(silicon, hpc, store, spin_polarized=True)

        assert parallel.npool == 4
        assert self._codes(parallel) == []
        assert parallel.kpoint_spin_pairs == 12

    def test_spinless_run_takes_two_pools_for_six_k_points(
        self, silicon, hpc, installed_table
    ) -> None:
        store, _table = installed_table

        parallel = self._parallelisation(silicon, hpc, store)

        assert parallel.npool == 2
        assert self._codes(parallel) == []
        assert parallel.kpoint_spin_pairs == 6

    def test_user_npool_within_the_spin_pairs_is_not_called_idle(
        self, silicon, hpc, installed_table
    ) -> None:
        store, _table = installed_table

        parallel = self._parallelisation(
            silicon, hpc, store, spin_polarized=True, npool=8
        )

        assert parallel.npool == 8
        assert self._codes(parallel) == []
        assert parallel.kpoint_spin_pairs == 12


class TestUnresolvedStepInputBlocksTheJob:
    """#169: the job is sized from each step's ``nbnd`` and ``n_irr_k``,
    so operator input that leaves either unresolved blocks the job and
    the step's parallelisation, with that input as the root cause."""

    @pytest.mark.parametrize(
        ("settings", "cause"),
        [
            pytest.param({"extra_bands": -100}, "extra_bands=-100", id="nbnd"),
            pytest.param({"k_index": 99999}, "k_index=99999", id="n_irr_k"),
        ],
    )
    def test_advise_returns_a_blocked_job_that_check_refuses(
        self, diamond_silicon, hpc, installed_table, settings, cause
    ) -> None:
        store, _table = installed_table
        overrides = build_overrides(settings, task="scf_single_point")

        advice = advise(diamond_silicon, hpc=hpc, overrides=overrides, store=store)

        resources = advice.step.resources
        assert isinstance(resources.job, Blocked)
        assert isinstance(resources.parallelisation, Blocked)
        assert cause in resources.job.root_cause()
        assert cause in resources.parallelisation.root_cause()
        assert resources.max_seconds is None
        assert not check(advice).ok


class TestAdviseDegradation:
    """No asset store or network involved -- these exercise Blocked/
    Unavailable propagation through advise() using an explicit,
    guaranteed-missing table id, per the tri-state "never fake a value"
    contract."""

    def test_unknown_table_id_degrades_the_whole_pseudopotential_chain(
        self, silicon, hpc
    ) -> None:
        overrides = RunOverrides(
            system=SystemOverrides(pseudo_table_id="does-not-exist")
        )

        advice = advise(silicon, hpc=hpc, overrides=overrides)

        assert isinstance(advice.system.pseudo.table, Unavailable)
        assert isinstance(advice.system.pseudo.metadata, Blocked)
        assert isinstance(advice.system.pseudo.relativistic, Blocked)
        assert isinstance(advice.system.magnetic, Blocked)
        assert isinstance(advice.system.cutoffs, Blocked)
        assert isinstance(advice.system.electron_count, Blocked)
        assert isinstance(advice.step.kpoints.nbnd, Blocked)
        assert isinstance(advice.step.resources.job, Blocked)
        assert isinstance(advice.step.resources.parallelisation, Blocked)
        # Unrelated facts/advisors are unaffected. (is_metal is correctly
        # Unavailable for silicon regardless -- a semiconductor, not a
        # metal -- so it is not asserted here; see is_metal.py's own
        # docstring on why composition alone never confirms "non_metal".)
        assert advice.analysis.composition.ok
        assert advice.system.functional.ok
        assert advice.step.kpoints.k_sampling.ok

    def test_soc_on_a_lanthanide_blocks_the_whole_relativistic_chain(self, hpc) -> None:
        """v2 epic 9 (#9)'s "SOC on Ce" acceptance scenario: SSSP is the
        only table lanthanides are allowed to use (``requires_sssp``), but
        no SSSP table is fully relativistic -- so requesting spin-orbit
        coupling on a lanthanide can never be satisfied by any table in
        the registry, real or synthetic, no asset store needed to prove
        it (table *selection* fails before any file is ever touched)."""
        cerium = Structure(Lattice.cubic(5.16), ["Ce"], [[0.0, 0.0, 0.0]])
        overrides = RunOverrides(
            system=SystemOverrides(
                magnetic=MagneticConfigHumanInput(spin_orbit_coupling=True)
            )
        )

        advice = advise(cerium, hpc=hpc, overrides=overrides)

        assert isinstance(advice.system.pseudo.table, Unavailable)
        reason = advice.system.pseudo.table.reason
        assert (
            "pseudodojo-pbesol-efficiency-fr: lanthanide and actinide elements "
            "require an SSSP table and missing elements Ce; "
        ) in reason
        assert reason.endswith(
            "sssp-pbesol-efficiency-sr: relativistic treatment is scalar, "
            "requested full"
        )
        assert isinstance(advice.system.pseudo.metadata, Blocked)
        assert isinstance(advice.system.pseudo.relativistic, Blocked)
        assert isinstance(advice.system.magnetic, Blocked)
        assert isinstance(advice.system.cutoffs, Blocked)
        # Genuinely unrelated decisions -- never fed pseudo/magnetic data
        # at all -- still resolve normally.
        assert advice.system.functional.ok
        assert advice.step.kpoints.k_sampling.ok
        assert advice.step.kpoints.occupations.ok
        assert advice.system.boundary.ok

    @pytest.mark.parametrize(
        ("structure", "functional", "notice"),
        [
            (hcp_gadolinium(), "PBEsol", "magnetic.soc_unavailable"),
            (fcc_lead(), "PBEsol", "magnetic.soc_suggested"),
            (fcc_lead(), "LDA", "magnetic.soc_unavailable"),
        ],
        ids=["Gd-PBEsol", "Pb-PBEsol", "Pb-LDA"],
    )
    def test_the_soc_notice_follows_the_selection_soc_would_make(
        self, hpc, structure, functional, notice
    ) -> None:
        """#181: the spin-orbit notice of a run without SOC comes from the
        table selection the same request makes with spin_orbit_coupling:
        soc_suggested names the table it selects, soc_unavailable carries
        the reason it refuses. hcp Gd used to be told to enable SOC, which
        then left pseudo_table unavailable."""
        settings = {"functional": functional}
        without = advise(
            structure,
            hpc=hpc,
            overrides=build_overrides(settings, task="scf_single_point"),
        )
        with_soc = advise(
            structure,
            hpc=hpc,
            overrides=build_overrides(
                {**settings, "spin_orbit_coupling": True}, task="scf_single_point"
            ),
        )

        notices = {
            warning.code: warning.message
            for warning in without.system.magnetic.value.warnings
            if warning.code in {"magnetic.soc_suggested", "magnetic.soc_unavailable"}
        }
        assert notices.keys() == {notice}
        table = with_soc.system.pseudo.table
        if notice == "magnetic.soc_suggested":
            assert notices[notice].endswith(f" table {table.value.id}.")
        else:
            assert notices[notice].endswith(f"pseudopotential tables: {table.reason}")

    @pytest.mark.parametrize(
        "settings", [{}, {"spin_polarized": False}], ids=["default", "unpolarized"]
    )
    def test_a_disordered_structure_is_refused_before_any_record(
        self, hpc, settings
    ) -> None:
        """#224: no input file describes a partially occupied site, so advice
        refuses the structure up front, whatever the settings, instead of
        reaching the ML tiers, which raised AttributeError on ``site.specie``,
        or blocking records one by one (#142)."""
        disordered = Structure(
            Lattice.cubic(2.86),
            [{"Fe": 0.5, "Co": 0.5}, {"Fe": 0.5, "Co": 0.5}],
            [[0, 0, 0], [0.5, 0.5, 0.5]],
        )

        with pytest.raises(
            StructureInputError,
            match=r"site 1 \(Fe0\.5 Co0\.5\), site 2 \(Fe0\.5 Co0\.5\)\. Order it",
        ):
            advise(
                disordered,
                hpc=hpc,
                overrides=build_overrides(settings, task="scf_single_point"),
            )

    def test_blocked_root_cause_is_reachable_from_a_downstream_field(
        self, silicon, hpc
    ) -> None:
        overrides = RunOverrides(
            system=SystemOverrides(pseudo_table_id="does-not-exist")
        )

        advice = advise(silicon, hpc=hpc, overrides=overrides)

        assert "does-not-exist" in advice.step.resources.job.root_cause() or (
            "does-not-exist" in advice.system.pseudo.table.reason
        )

    def test_check_reports_blocking_and_generate_refuses(self, silicon, hpc) -> None:
        overrides = RunOverrides(
            system=SystemOverrides(pseudo_table_id="does-not-exist")
        )
        advice = advise(silicon, hpc=hpc, overrides=overrides)

        report = check(advice)

        assert not report.ok
        assert report.blocking

        with pytest.raises(AdviceIncomplete) as excinfo:
            generate(advice, report)
        assert excinfo.value.report is report

    def test_one_root_cause_is_one_finding_and_said_once(self, silicon, hpc) -> None:
        """Many fields share the one pseudo_table_id failure here; the
        report holds it once (#151), as advice.blocked without a remedy,
        and the exception message says it once."""
        overrides = RunOverrides(
            system=SystemOverrides(pseudo_table_id="does-not-exist")
        )
        advice = advise(silicon, hpc=hpc, overrides=overrides)
        blocked = [
            state for state in advice.field_states() if isinstance(state, Blocked)
        ]
        report = check(advice)
        assert len(blocked) > 1, "test assumes multiple fields share one cause"

        with pytest.raises(AdviceIncomplete) as excinfo:
            generate(advice, report)

        (finding,) = report.blocking
        assert (finding.code, finding.remedies) == ("advice.blocked", ())
        assert str(excinfo.value).count("unknown pseudopotential table") == 1

    def test_fetch_missing_false_degrades_without_raising(
        self, silicon, hpc, tmp_path, monkeypatch
    ) -> None:
        _spec, registry_table = _sssp_table_spec(tmp_path / "sources")
        monkeypatch.setattr(
            "goldilocks_core.service._pseudo.load_tables",
            lambda *a, **kw: {registry_table.id: registry_table},
        )
        empty_store = AssetStore(tmp_path / "empty-store")

        advice = advise(silicon, hpc=hpc, store=empty_store, fetch_missing=False)

        assert isinstance(advice.system.pseudo.metadata, Unavailable)
        assert "not installed" in advice.system.pseudo.metadata.reason
        assert isinstance(advice.system.cutoffs, Blocked)
        # A table *was* selected (only the asset isn't downloaded yet) --
        # ``relativistic`` is already confirmed, and magnetic still
        # resolves, seeded at the flat default fractions because the table
        # is not installed, rather than blocking:
        # this is an ordinary preview-without-download run, not a chain
        # failure (contrast the SOC-on-a-lanthanide test above, where no
        # table can ever be selected at all).
        assert advice.system.pseudo.relativistic.ok
        assert advice.system.magnetic.ok

    def test_fetch_missing_true_installs_then_succeeds(
        self, silicon, hpc, tmp_path, monkeypatch
    ) -> None:
        spec, registry_table = _sssp_table_spec(tmp_path / "sources")
        monkeypatch.setattr(
            "goldilocks_core.service._pseudo.load_tables",
            lambda *a, **kw: {registry_table.id: registry_table},
        )
        empty_store = AssetStore(tmp_path / "empty-store")
        prepare = sssp_preparer(registry_table)
        monkeypatch.setattr(
            "goldilocks_core.service._pseudo.install_assets",
            lambda name, *, store: (store.install(spec, prepare),),
        )

        advice = advise(silicon, hpc=hpc, store=empty_store, fetch_missing=True)

        assert advice.system.pseudo.metadata.ok
        assert advice.system.cutoffs.ok


def test_forced_spin_polarization_survives_generation_on_a_labeled_structure(
    hpc, installed_table
) -> None:
    """Regression for #32 (v2 epic 9, #9): the plain, non-AFM path used
    to crash inside generate() with a bare KeyError whenever the
    structure's own per-site labels differ from its element symbols --
    true for every bundled example structure (pymatgen's own CIF
    writer/reader default), not something specific to AFM relabeling.
    Uses the silicon-covering installed_table fixture (real Fe pseudo
    coverage isn't fixtured) with spin_polarized forced on -- the
    crash reproduces for any spin-polarized, label-carrying structure,
    not only genuinely magnetic elements.

    Both sites get the identical heuristic-default fraction (no AFM, no
    per-site override) -- generation collapses ``Si0``/``Si1`` back to
    one ``Si`` species with one shared ``starting_magnetization(1))``,
    not two redundant, identically-valued species (the #32-era fix kept
    them split only to avoid the crash, not because physics needed two)."""
    store, _table = installed_table
    two_silicon_sites = Structure(
        Lattice.cubic(5.43),
        ["Si", "Si"],
        [[0.0, 0.0, 0.0], [0.25, 0.25, 0.25]],
        labels=["Si0", "Si1"],
    )
    overrides = RunOverrides(
        system=SystemOverrides(magnetic=MagneticConfigHumanInput(spin_polarized=True))
    )

    advice = advise(two_silicon_sites, hpc=hpc, overrides=overrides, store=store)
    report = check(advice)

    assert report.ok, report.blocking
    steps = generate(advice, report, ctx=default_shared_context())
    content = steps[0].files["scf.in"]
    assert "ntyp             = 1" in content
    assert "starting_magnetization(1)" in content
    assert "starting_magnetization(2)" not in content


@pytest.mark.skipif(
    not enumlib_installed(),
    reason="needs the enumlib executables (enum.x, makeStr.py) on PATH",
)
class TestAfmRelabeling:
    """v2 epic 9 (#9)'s AFM acceptance scenario, through the real
    ``advise()`` orchestrator -- not just ``magnetic_cell()`` in
    isolation (that half is ``test_advisors_magnetic_config.py``'s job).
    No asset store needed: table *selection* (which is all AFM relabeling
    itself depends on) works off the bundled registry data alone."""

    def test_afm_ordering_produces_a_split_cell_and_a_different_symmetry_eff(
        self, hpc
    ) -> None:
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
        cell = advice.system.cell.value.structure
        assert advice.system.magnetic.value.cell is cell
        assert len(set(cell.species)) > len(set(rock_salt_feo.species))

        assert advice.analysis.symmetry.ok
        assert advice.system.symmetry_eff.ok
        assert advice.system.symmetry_eff.value != advice.analysis.symmetry.value

        # k_sampling/n_irr_k consumed the split (bigger) cell, not the
        # original one, and did not crash doing it.
        assert advice.step.kpoints.k_sampling.ok
        assert advice.step.kpoints.n_irr_k.ok

    def test_fm_default_keeps_symmetry_eff_identical_to_symmetry(self, hpc) -> None:
        rock_salt_feo = Structure(
            Lattice.cubic(4.3), ["Fe", "O"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]
        )

        advice = advise(rock_salt_feo, hpc=hpc)

        assert advice.system.magnetic.ok
        cell = advice.system.magnetic.value.cell
        assert [site.label for site in cell] == ["Fe", "O"]
        assert cell.frac_coords.tolist() == rock_salt_feo.frac_coords.tolist()
        assert advice.system.symmetry_eff.value == advice.analysis.symmetry.value


@pytest.fixture
def correlated_store(tmp_path, monkeypatch) -> AssetStore:
    """A synthetic table covering NiO, ThO2 and UN."""
    spec, registry_table = _sssp_table_spec(
        tmp_path / "sources", {"N": 5.0, "Ni": 18.0, "O": 6.0, "Th": 12.0, "U": 14.0}
    )
    store = AssetStore(tmp_path / "store")
    store.install(spec, sssp_preparer(registry_table))
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *a, **kw: {registry_table.id: registry_table},
    )
    return store


def _rock_salt_nio() -> Structure:
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(4.17), ["Ni", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    ).get_primitive_structure()


def _rock_salt_un() -> Structure:
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(4.89), ["U", "N"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    ).get_primitive_structure()


def _fluorite_tho2() -> Structure:
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(5.60), ["Th", "O"], [[0, 0, 0], [0.25, 0.25, 0.25]]
    ).get_primitive_structure()


def test_hubbard_record_lists_each_applied_u_with_its_source(
    hpc, correlated_store
) -> None:
    """#135: records.hubbard (explain --json, /explain, goldilocks.json)
    carries one entry per element that gets +U, with where its value came
    from, instead of a plan name and a bare element-to-U map."""
    advice = advise(_rock_salt_nio(), hpc=hpc, store=correlated_store)

    record = records_document(advice.records())["hubbard"]
    assert record["status"] == "resolved"
    (entry,) = record["value"]["u_values"]
    assert set(record["value"]) == {"u_values", "projectors", "warnings"}
    assert record["value"]["projectors"] == "ortho-atomic"
    assert record["field_sources"]["hubbard_projectors"] == "heuristic"
    assert {key: entry[key] for key in ("element", "manifold", "u_ev")} == {
        "element": "Ni",
        "manifold": "3d",
        "u_ev": 6.2,
    }
    assert entry["value_source"] == "table"
    assert "Materials Project" in entry["citation"]
    assert entry["doi"] == "10.1038/s41598-021-94550-5"
    codes = {warning["code"] for warning in advice.warnings()}
    assert "hubbard.projector_mismatch" in codes


def test_user_u_by_element_reaches_the_generated_card(hpc, correlated_store) -> None:
    overrides = build_overrides({"u_by_element": {"Ni": 5.0}}, task="scf_single_point")

    advice = advise(
        _rock_salt_nio(), hpc=hpc, overrides=overrides, store=correlated_store
    )
    report = check(advice)

    assert report.ok, report.blocking
    (entry,) = advice.records()["hubbard"].value.u_values
    assert (entry.value_source, entry.citation, entry.doi) == (
        "human",
        None,
        None,
    )
    content = generate(advice, report)[0].files["scf.in"]
    assert "HUBBARD (ortho-atomic)\n  U  Ni-3d  5\n" in content


@pytest.mark.parametrize(
    ("overrides", "hubbard_codes"),
    [
        pytest.param(
            {},
            ["hubbard.projector_mismatch", "hubbard.starting_ns_eigenvalue_missing"],
            id="table",
        ),
        pytest.param(
            {"u_by_element": {"Ni": 6.2}},
            ["hubbard.starting_ns_eigenvalue_missing"],
            id="user-equal-to-table",
        ),
    ],
)
def test_hubbard_warnings_reach_the_top_level_list_for_table_and_user_u(
    hpc, correlated_store, overrides, hubbard_codes
) -> None:
    """#167: the table and u_by_element={"Ni": 6.2} give NiO the same U, but
    the user run used to carry no Hubbard warning, so none reached
    ``Advice.warnings()``."""
    advice = advise(
        _rock_salt_nio(),
        hpc=hpc,
        overrides=build_overrides(overrides, task="scf_single_point"),
        store=correlated_store,
    )

    codes = [
        item["code"] for item in advice.warnings() if item["category"] == "hubbard"
    ]
    assert codes == hubbard_codes


@pytest.mark.parametrize(
    ("structure", "overrides", "needs_correlation", "applies_u"),
    [
        pytest.param(_rock_salt_nio, {}, True, True, id="NiO-table-U"),
        pytest.param(
            _rock_salt_un, {"u_by_element": {"U": 4.0}}, False, True, id="UN-user-U"
        ),
        pytest.param(
            _fluorite_tho2,
            {"hubbard_needs_correlation": False},
            True,
            False,
            id="ThO2-no-U",
        ),
    ],
)
def test_frozen_ns_warning_follows_the_hubbard_decision_not_needs_correlation(
    hpc, correlated_store, structure, overrides, needs_correlation, applies_u
) -> None:
    """#166: +U-specific convergence output keys on the resolved Hubbard
    decision (the one that renders the HUBBARD card), not on the
    needs_correlation fact, which is false for the nitride UN given a user U
    and true for ThO2 with +U switched off."""
    advice = advise(
        structure(),
        hpc=hpc,
        overrides=build_overrides(
            {**overrides, "mixing_fixed_ns": 50}, task="scf_single_point"
        ),
        store=correlated_store,
    )

    assert advice.analysis.needs_correlation.value is needs_correlation
    assert bool(advice.system.hubbard.value.u_values) is applies_u
    assert advice.step.kpoints.convergence.value.mixing_fixed_ns == 50
    codes = {item["code"] for item in advice.warnings()}
    frozen_ns = "convergence.mixing_fixed_ns_freezes_hubbard_occupations"
    assert (frozen_ns in codes) is applies_u


def test_a_blocked_cell_blocks_every_count_made_on_it(
    silicon, hpc, installed_table
) -> None:
    """#128: k-points, convergence, the electron count and bands describe
    the simulated cell. When it cannot be decided -- a starting_magnetization
    label the cell does not have -- they block on that reason instead of
    describing the uploaded structure."""
    store, _table = installed_table

    advice = advise(
        silicon,
        hpc=hpc,
        overrides=build_overrides(
            {"starting_magnetization": {"Si9": 0.5}}, task="scf_single_point"
        ),
        store=store,
    )

    kpoints = advice.step.kpoints
    for state in (
        kpoints.k_sampling,
        kpoints.n_irr_k,
        kpoints.convergence,
        kpoints.nbnd,
        advice.step.resources.job,
        advice.system.electron_count,
        advice.system.symmetry_eff,
        advice.system.magnetic,
        advice.system.cell,
    ):
        assert isinstance(state, Blocked)
        assert "Si9" in state.root_cause()
    assert not check(advice).ok


def test_table_selection_reads_the_simulated_cell_s_spin_orbit_switch(
    silicon, hpc, installed_table
) -> None:
    """The cell step decides spin-orbit coupling before any table is
    chosen, and selection reads it (#128): the scalar-relativistic
    fixture table serves the plain run and cannot serve a spin-orbit one.
    The seeds that need the table's z_valence come after it, so nothing
    runs twice."""
    store, table = installed_table

    plain = advise(silicon, hpc=hpc, store=store)
    spin_orbit = advise(
        silicon,
        hpc=hpc,
        overrides=build_overrides(
            {"spin_orbit_coupling": True}, task="scf_single_point"
        ),
        store=store,
    )

    assert plain.system.magnetic.ok
    assert plain.system.pseudo.table.value.id == table.id
    assert spin_orbit.system.cell.value.spin_orbit_enabled is True
    assert not spin_orbit.system.pseudo.table.ok


def _afm_rock_salt(structure: Structure) -> Structure:
    """A spin-decorated 4-site cell of a 2-site rock-salt input, Ni up and
    down along the doubled c -- the shape ``MagneticStructureEnumerator``
    returns a candidate in."""
    supercell = structure * (1, 1, 2)
    spins = iter((5.0, -5.0))
    return Structure(
        supercell.lattice,
        [
            SpinSpecies("Ni", spin=next(spins))
            if site.specie.symbol == "Ni"
            else site.specie
            for site in supercell
        ],
        supercell.frac_coords,
    )


@pytest.fixture
def counted_enumerations(monkeypatch) -> list[Structure]:
    """Every structure handed to enumlib's enumeration, which returns one
    4-site antiferromagnetic candidate -- stubbed on the module that calls
    it, because the real enumerator runs in a worker process a
    monkeypatch cannot reach."""
    calls: list[Structure] = []

    def enumerate_orderings(structure: Structure, **_kwargs: object):
        calls.append(structure)
        return ((_afm_rock_salt(structure), "afm"),)

    monkeypatch.setattr(magnetic_config_module, "enumlib_installed", lambda: True)
    monkeypatch.setattr(
        magnetic_config_module, "enumerate_orderings", enumerate_orderings
    )
    return calls


@pytest.mark.parametrize(
    ("advise_task", "task"),
    [
        pytest.param(advise, "scf_single_point", id="advise"),
        pytest.param(advise_dos, "dos", id="advise_dos"),
        pytest.param(
            functools.partial(advise_relax, calculation="relax"), "relax", id="relax"
        ),
    ],
)
def test_an_afm_task_enumerates_its_orderings_once(
    hpc, correlated_store, counted_enumerations, advise_task, task
) -> None:
    """#184 (part A), #128: the simulated cell is resolved once per task.
    The two-pass magnetic decision used to enumerate before pseudopotential
    selection and again after it, about a second of enumlib each."""
    advise_task(
        _rock_salt_nio(),
        hpc=hpc,
        overrides=build_overrides({"magnetic_ordering": "afm"}, task=task),
        store=correlated_store,
    )

    assert len(counted_enumerations) == 1


def test_the_written_cell_is_seeded_once_from_the_selected_table(
    hpc, correlated_store, counted_enumerations, tmp_path
) -> None:
    """#128: the starting moments are set once, on the written cell, after
    table selection -- Ni's 5 Bohr magneton target over the table's
    z_valence of 18, opposite on the two Ni sublattices, with O off the
    sublattice at 0 (#170). A table that is not installed yet leaves
    aiida's flat 0.1."""
    overrides = build_overrides({"magnetic_ordering": "afm"}, task="scf_single_point")

    installed = advise(
        _rock_salt_nio(), hpc=hpc, overrides=overrides, store=correlated_store
    )
    not_installed = advise(
        _rock_salt_nio(), hpc=hpc, overrides=overrides, store=AssetStore(tmp_path)
    )

    assert installed.system.magnetic.value.starting_magnetization == {
        "Ni1": 5.0 / 18.0,
        "Ni2": -5.0 / 18.0,
        "O": 0.0,
    }
    assert isinstance(not_installed.system.pseudo.metadata, Unavailable)
    assert not_installed.system.magnetic.value.starting_magnetization == {
        "Ni1": 0.1,
        "Ni2": -0.1,
        "O": 0.0,
    }


@pytest.mark.parametrize(
    ("settings", "cell", "ordering", "compensated"),
    [
        pytest.param(
            {},
            {"formula": "Ni1 O1", "nat": 2},
            {
                "requested": None,
                "applied": "fm",
                "criterion": "identity",
                "alternatives": [],
            },
            False,
            id="unset",
        ),
        pytest.param(
            {"magnetic_ordering": "fm"},
            {"formula": "Ni1 O1", "nat": 2},
            {
                "requested": "fm",
                "applied": "fm",
                "criterion": "identity",
                "alternatives": [],
            },
            False,
            id="fm",
        ),
        pytest.param(
            {"magnetic_ordering": "afm"},
            {"formula": "Ni2 O2", "nat": 4},
            {
                "requested": "afm",
                "applied": "afm-1",
                "criterion": "smallest_cell",
                "alternatives": [],
            },
            True,
            id="afm",
        ),
    ],
)
def test_the_magnetic_record_shows_the_written_cell_and_its_ordering(
    hpc, correlated_store, counted_enumerations, settings, cell, ordering, compensated
) -> None:
    """#128: goldilocks.json records the cell the input is written for, as
    its formula and atom count (any Structure in a record projects to
    those, never to host-specific or bulky data), next to the ordering
    asked for (none when unset, unlike an explicit fm, which is a spin
    request), the one applied, why it was applied and the other candidates
    of its size (#144), and whether its seeds are compensated (#138, #185)."""
    advice = advise(
        _rock_salt_nio(),
        hpc=hpc,
        overrides=build_overrides(settings, task="scf_single_point"),
        store=correlated_store,
    )

    record = records_document(advice.records())["magnetic"]["value"]
    assert record["cell"] == cell
    assert record["ordering"] == ordering
    assert record["compensated"] is compensated
    assert json.loads(json.dumps(record))["cell"] == cell


def test_the_magnetic_record_shows_the_frame_the_cell_is_written_in(hpc) -> None:
    """#140: diamond Si's primitive cell as MC3D serves it (c along z) shows
    pw.x 4 of its 48 operations, so it is written turned into cubic axes:
    the record carries the rotation, the notice names it, and every count
    reads the turned cell."""
    advice = advise(mc3d_42058_silicon(), hpc=hpc)

    record = records_document(advice.records())["magnetic"]["value"]
    frame = json.loads(json.dumps(record))["frame"]
    (notice,) = [
        warning["message"]
        for warning in advice.warnings()
        if warning["code"] == "magnetic.cell_framed"
    ]
    assert frame == {
        "rotated": True,
        "rotation": [
            [0.816496580928, 0.57735026919, 0.0],
            [-0.408248290464, 0.57735026919, 0.707106781187],
            [0.408248290464, -0.57735026919, 0.707106781187],
        ],
        "origin_shift": [0.0, 0.0, 0.0],
        "max_displacement_angstrom": 0.0,
        "operations": 48,
    }
    assert notice.startswith(
        "the cell is written rotated by 56.6003 degrees about "
        "[-0.7693, -0.2445, -0.5903]; pw.x"
    )
    assert "keeps 48 symmetry operations" in notice
    assert "Cartesian cell_dofree masks would not" in notice
    assert advice.system.cell.value.structure is advice.system.magnetic.value.cell
    assert advice.system.symmetry_eff.value.space_group_number == 227


def test_a_cell_already_in_pw_x_s_frame_is_written_unturned_without_a_notice(
    hpc,
) -> None:
    """#140: the frame is always recorded; the notice fires only when the
    cell is turned, its origin moves or an atom moves 1e-4 A or more."""
    cubic = Structure.from_spacegroup(
        "Fd-3m", Lattice.cubic(5.431), ["Si"], [[0.0, 0.0, 0.0]]
    )

    advice = advise(cubic, hpc=hpc)

    frame = advice.records()["magnetic"].value.frame
    assert frame.rotated is False
    assert frame.operations == 24
    assert "magnetic.cell_framed" not in {
        warning["code"] for warning in advice.warnings()
    }


def test_advise_reduces_only_the_chosen_mesh_by_symmetry(hpc, monkeypatch) -> None:
    """Regression for #155: labelling the chosen mesh with its ``k_index``
    rebuilt the whole ladder with one spglib reduction per rung -- 73
    reductions for this cell, seconds of them on a low-symmetry one.
    ``n_irr_k`` is the one reduction left, of the mesh the step uses, by
    the operations pw.x keeps (#140). Counted at spglib's two mesh
    reductions as the ``spglib`` module holds them when called, which is
    how ``pw_symmetry`` calls ``get_stabilized_reciprocal_mesh`` and
    pymatgen's ``SpacegroupAnalyzer`` calls ``get_ir_reciprocal_mesh``: a
    per-rung reduction through either is seen, whatever module makes it."""
    bcc_iron = Structure(
        Lattice.cubic(2.87), ["Fe", "Fe"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]
    )
    reduced_meshes = []

    def counting(reduce):
        def counted_reduce(mesh, *args, **kwargs):
            reduced_meshes.append(tuple(int(n) for n in mesh))
            return reduce(mesh, *args, **kwargs)

        return counted_reduce

    for name in ("get_stabilized_reciprocal_mesh", "get_ir_reciprocal_mesh"):
        monkeypatch.setattr(spglib, name, counting(getattr(spglib, name)))

    advice = advise(bcc_iron, hpc=hpc)

    k_sampling = advice.step.kpoints.k_sampling
    assert k_sampling.ok
    assert k_sampling.value.k_index is not None
    assert reduced_meshes == [k_sampling.value.mesh]
    assert advice.step.kpoints.n_irr_k.ok
