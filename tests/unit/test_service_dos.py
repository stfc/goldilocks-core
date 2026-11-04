"""Tests for goldilocks_core.service._dos (v2 epic 9, #9)."""

from __future__ import annotations

import dataclasses

import pytest
from pymatgen.core import Lattice, Structure
from support import sssp_fixture_table_spec

from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.inputs.hpc import Hardware, HpcProfile, Partition
from goldilocks_core.resolution import Blocked, Provenance, Resolved, Warning
from goldilocks_core.service import (
    RunOverrides,
    advise,
    advise_dos,
    check,
    check_dos,
    generate_dos,
)
from goldilocks_core.set_overrides import build_overrides


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


def _diamond_silicon() -> Structure:
    """Diamond Si's two-atom primitive cell, as in the #169 reproduction."""
    a = 5.43
    lattice = Lattice([[0, a / 2, a / 2], [a / 2, 0, a / 2], [a / 2, a / 2, 0]])
    return Structure(lattice, ["Si", "Si"], [[0, 0, 0], [0.25, 0.25, 0.25]])


def _installed_store(tmp_path, monkeypatch) -> AssetStore:
    spec, registry_table = sssp_fixture_table_spec(tmp_path / "sources")
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *a, **kw: {registry_table.id: registry_table},
    )
    store = AssetStore(tmp_path / "store")
    store.install(spec, sssp_preparer(registry_table))
    return store


class TestAdviseDosDegradation:
    """No asset store needed: table *selection* alone (real registry
    data, no network) is enough to exercise the nscf protocol and the
    dos advisor -- same style as test_service_v2.py's own
    ``TestAdviseDegradation``."""

    def test_nscf_step_gets_a_denser_mesh_and_tetrahedra_opt_occupations(self) -> None:
        advice = advise_dos(_silicon(), hpc=_hpc())

        assert advice.scf.step.kpoints.occupations.value.occupations == "smearing"
        assert advice.nscf.step.kpoints.occupations.value.occupations == (
            "tetrahedra_opt"
        )
        scf_k_distance = advice.scf.step.kpoints.k_sampling.value.k_distance
        nscf_k_distance = advice.nscf.step.kpoints.k_sampling.value.k_distance
        assert nscf_k_distance == 0.10
        assert nscf_k_distance < scf_k_distance

    def test_explicit_k_grid_override_reaches_the_nscf_step_too(self) -> None:
        """Regression for #33 (v2 epic 9, #9): the nscf protocol's
        k_distance used to replace k_sampling unconditionally, silently
        discarding a caller's own explicit k_grid for the nscf step
        specifically (while the exact same override reached the scf step).
        A request value outranks the protocol (#174)."""
        overrides = build_overrides({"k_grid": (16, 16, 16)}, task="dos")

        advice = advise_dos(_silicon(), hpc=_hpc(), overrides=overrides)

        assert advice.scf.step.kpoints.k_sampling.value.mesh == (16, 16, 16)
        assert advice.nscf.step.kpoints.k_sampling.value.mesh == (16, 16, 16)

    def test_explicit_occupations_override_reaches_the_nscf_step_too(self) -> None:
        overrides = build_overrides({"occupations": "fixed"}, task="dos")

        advice = advise_dos(_silicon(), hpc=_hpc(), overrides=overrides)

        assert advice.scf.step.kpoints.occupations.value.occupations == "fixed"
        assert advice.nscf.step.kpoints.occupations.value.occupations == "fixed"

    def test_nscf_still_gets_its_own_default_when_only_scf_relevant_fields_are_unset(
        self,
    ) -> None:
        """A k_grid override for one field must not suppress the nscf
        protocol's value for a sibling field (occupations) that the caller
        left alone."""
        overrides = build_overrides({"k_grid": [4, 4, 4]}, task="dos")

        advice = advise_dos(_silicon(), hpc=_hpc(), overrides=overrides)

        assert advice.nscf.step.kpoints.k_sampling.value.mesh == (4, 4, 4)
        assert advice.nscf.step.kpoints.occupations.value.occupations == (
            "tetrahedra_opt"
        )

    def test_dos_settings_resolve_from_the_nscf_steps_own_occupations(self) -> None:
        advice = advise_dos(_silicon(), hpc=_hpc())

        assert advice.dos.ok
        # nscf used the protocol's tetrahedra_opt -- no smearing width
        # exists, so broadening is correctly left unset, not invented.
        assert advice.dos.value.broadening is None
        assert advice.dos.value.delta_e == 0.01
        assert advice.dos.value.ngauss == 0

    def test_both_pw_x_steps_share_one_analysis_and_system_advice(self) -> None:
        """The task runs analysis and system advice once (#169, #184 part
        B); the two pw.x steps differ only in their per-step advice."""
        advice = advise_dos(_diamond_silicon(), hpc=_hpc())

        assert advice.nscf.analysis is advice.scf.analysis
        assert advice.nscf.system is advice.scf.system

    def test_unknown_table_id_blocks_both_pw_steps_and_check_dos_reports_it(
        self,
    ) -> None:
        from goldilocks_core.service import SystemOverrides

        overrides = RunOverrides(
            system=SystemOverrides(pseudo_table_id="does-not-exist")
        )

        advice = advise_dos(_silicon(), hpc=_hpc(), overrides=overrides)

        assert isinstance(advice.scf.system.pseudo.metadata, Blocked)
        assert isinstance(advice.nscf.system.pseudo.metadata, Blocked)
        report = check_dos(advice)
        assert not report.ok
        (finding,) = report.blocking
        assert finding.code == "advice.blocked"
        assert "does-not-exist" in finding.message


class TestTheNscfProtocol:
    """#174: the dos task's nscf protocol (aiida-quantumespresso's pdos.yaml,
    balanced) is a tier of its own for the nscf step, below the request and
    above the ML tier, so its values read 'heuristic' with the protocol as
    their note. It used to be written into the request's override bag, so
    the records read 'human' ("Your override") for values nobody set."""

    _NOTE = (
        "Protocol default for the dos task's nscf step: "
        "aiida-quantumespresso's pdos.yaml, balanced."
    )

    def test_protocol_values_read_heuristic_with_the_protocol_as_their_note(
        self,
    ) -> None:
        records = advise_dos(_diamond_silicon(), hpc=_hpc()).records()

        k_sampling = records["nscf_k_sampling"]
        occupations = records["nscf_occupations"]
        assert (k_sampling.value.k_distance, k_sampling.value.mesh) == (
            0.10,
            (21, 21, 21),
        )
        assert occupations.value.occupations == "tetrahedra_opt"
        assert k_sampling.provenance == Provenance(
            source="heuristic",
            source_note=self._NOTE,
            field_sources={"k_distance": "heuristic", "shift": "heuristic"},
        )
        assert occupations.provenance == Provenance(
            source="heuristic",
            source_note=self._NOTE,
            field_sources={"occupations": "heuristic"},
        )

    def test_the_same_values_set_in_the_request_read_human(self) -> None:
        overrides = build_overrides(
            {"k_distance": 0.1, "occupations": "tetrahedra_opt"},
            task="dos",
        )
        defaults = advise_dos(_diamond_silicon(), hpc=_hpc()).records()

        records = advise_dos(
            _diamond_silicon(), hpc=_hpc(), overrides=overrides
        ).records()

        for name in ("nscf_k_sampling", "nscf_occupations"):
            assert records[name].value == defaults[name].value
        assert records["nscf_k_sampling"].provenance == Provenance(
            source="human",
            field_sources={"k_distance": "human", "shift": "heuristic"},
        )
        assert records["nscf_occupations"].provenance == Provenance(
            source="human", field_sources={"occupations": "human"}
        )

    def test_a_request_shift_keeps_the_protocol_mesh(self) -> None:
        """A shift alone used to displace the whole protocol k_distance,
        since the bag only filled an unset k_sampling input."""
        overrides = build_overrides({"shift": [1, 1, 1]}, task="dos")

        advice = advise_dos(_diamond_silicon(), hpc=_hpc(), overrides=overrides)

        nscf = advice.nscf.step.kpoints.k_sampling
        assert (nscf.value.k_distance, nscf.value.mesh) == (0.10, (21, 21, 21))
        assert nscf.value.shift == (1, 1, 1)
        assert nscf.provenance.field_sources == {
            "k_distance": "heuristic",
            "shift": "human",
        }
        assert nscf.provenance.source_note == self._NOTE
        assert advice.scf.step.kpoints.k_sampling.value.shift == (1, 1, 1)

    def test_a_request_degauss_keeps_tetrahedra_opt_and_applies_only_to_scf(
        self,
    ) -> None:
        """A smearing width alone used to displace the protocol's
        tetrahedra_opt. It is applied where smearing is (the scf step of a
        Si cell is_metal cannot classify), not under tetrahedra."""
        overrides = build_overrides({"degauss": 0.02}, task="dos")

        advice = advise_dos(_diamond_silicon(), hpc=_hpc(), overrides=overrides)

        nscf = advice.nscf.step.kpoints.occupations
        assert (nscf.value.occupations, nscf.value.degauss) == ("tetrahedra_opt", None)
        assert nscf.source == "heuristic"
        assert nscf.provenance.field_sources == {"occupations": "heuristic"}
        scf = advice.scf.step.kpoints.occupations
        assert (scf.value.occupations, scf.value.degauss) == ("smearing", 0.02)
        assert scf.provenance.field_sources["degauss"] == "human"

    def test_the_scf_step_gets_no_protocol(self) -> None:
        scf = advise_dos(_diamond_silicon(), hpc=_hpc()).scf.step.kpoints

        assert scf.k_sampling.value.k_distance == 0.15
        assert scf.occupations.value.occupations == "smearing"
        assert scf.k_sampling.provenance.source_note is None
        assert scf.occupations.provenance.source_note is None


class TestOneJobForTheTask:
    """#169: dos runs its steps in one allocation, so the task has one job,
    sized over both pw.x steps, that budgets each step's max_seconds."""

    def test_both_pw_x_steps_hold_the_tasks_one_job(
        self, tmp_path, monkeypatch
    ) -> None:
        store = _installed_store(tmp_path, monkeypatch)

        advice = advise_dos(_diamond_silicon(), hpc=_hpc(), store=store)

        job = advice.scf.step.resources.job
        assert advice.nscf.step.resources.job is job
        assert job.value.max_seconds_by_step.keys() == {"scf", "nscf"}
        for step in (advice.scf.step, advice.nscf.step):
            parallel = step.resources.parallelisation.value
            assert parallel.kpoint_spin_pairs == step.kpoints.n_irr_k.value
            assert job.value.ntasks % parallel.npool == 0

    def test_records_carry_one_job_and_no_nscf_copy(
        self, tmp_path, monkeypatch
    ) -> None:
        store = _installed_store(tmp_path, monkeypatch)

        records = advise_dos(_diamond_silicon(), hpc=_hpc(), store=store).records()

        assert "nscf_job" not in records
        assert records["job"].value.max_seconds_by_step.keys() == {"scf", "nscf"}
        assert "nscf_parallelisation" in records

    def test_warnings_list_the_nscf_step_s_own_notices(
        self, tmp_path, monkeypatch
    ) -> None:
        """#152: the nscf step's records reached ``records()`` as raw
        decisions next to the scf step's dict projections, and the
        dict-only collector skipped them, so the npool notice of the nscf
        step that ``submit.sh`` runs never reached ``warnings``. Every
        warning now names the record it came from."""
        store = _installed_store(tmp_path, monkeypatch)
        advice = advise_dos(_diamond_silicon(), hpc=_hpc(), store=store)
        notice = Warning(
            code="parallelisation.npool_load_imbalance",
            level="info",
            category="parallelisation",
            message="npool=64 does not divide the 286 k-point/spin pairs evenly.",
        )
        parallelisation = advice.nscf.step.resources.parallelisation
        resources = dataclasses.replace(
            advice.nscf.step.resources,
            parallelisation=Resolved(
                dataclasses.replace(parallelisation.value, warnings=(notice,)),
                parallelisation.provenance,
            ),
        )
        step = dataclasses.replace(advice.nscf.step, resources=resources)
        advice = dataclasses.replace(
            advice, nscf=dataclasses.replace(advice.nscf, step=step)
        )

        warnings = advice.warnings()

        assert notice.message in [warning["message"] for warning in warnings]
        assert {**notice.model_dump(), "record": "nscf_parallelisation"} in warnings


class TestGenerateDosEndToEnd:
    def test_generate_dos_produces_three_steps_sharing_one_context(
        self, tmp_path, monkeypatch
    ) -> None:
        store = _installed_store(tmp_path, monkeypatch)

        advice = advise_dos(_silicon(), hpc=_hpc(), store=store)
        report = check_dos(advice)
        assert report.ok, report.blocking

        steps = generate_dos(advice, report)

        assert [step.name for step in steps] == ["scf", "nscf", "dos"]
        assert [step.executable for step in steps] == ["pw.x", "pw.x", "dos.x"]
        scf_step, nscf_step, dos_step = steps
        assert "calculation      = 'scf'" in scf_step.files["scf.in"]
        assert "calculation      = 'nscf'" in nscf_step.files["nscf.in"]
        assert "occupations      = 'tetrahedra_opt'" in nscf_step.files["nscf.in"]
        assert "&DOS" in dos_step.files["dos.in"]
        assert "deltae           = 0.01" in dos_step.files["dos.in"]
        # All three steps share one prefix/outdir (SharedContext).
        for step in steps:
            content = next(iter(step.files.values()))
            assert "prefix           = 'pwscf'" in content
            assert "outdir           = './out'" in content


class TestPerStepOverrides:
    """#154: advise_dos gave its scf and nscf steps one shared StepOverrides
    and every caller left dos_human unset, so no override could reach one
    step only or dos.x at all. Overrides routed for the dos task carry one
    bag per step."""

    def test_a_steps_nscf_k_grid_moves_only_the_nscf_mesh(self) -> None:
        default = advise_dos(_diamond_silicon(), hpc=_hpc())
        overrides = build_overrides({"steps.nscf.k_grid": [30, 30, 30]}, task="dos")

        advice = advise_dos(_diamond_silicon(), hpc=_hpc(), overrides=overrides)

        assert advice.nscf.step.kpoints.k_sampling.value.mesh == (30, 30, 30)
        assert advice.scf.step.kpoints.k_sampling == (
            default.scf.step.kpoints.k_sampling
        )
        assert advice.scf.step.kpoints.n_irr_k == default.scf.step.kpoints.n_irr_k

    def test_dos_x_settings_reach_the_dos_record(self) -> None:
        overrides = build_overrides(
            {"delta_e": 0.05, "ngauss": -1, "broadening": 0.01}, task="dos"
        )

        dos = advise_dos(_diamond_silicon(), hpc=_hpc(), overrides=overrides).dos

        assert (dos.value.delta_e, dos.value.ngauss) == (0.05, -1)
        assert dos.provenance.field_sources["delta_e"] == "human"

    def test_an_ngauss_without_a_width_is_refused_on_the_protocol_nscf(
        self,
    ) -> None:
        """The dos protocol's tetrahedra_opt nscf gives dos.x no width, so
        dos.x would integrate with tetrahedra and ignore ngauss."""
        overrides = build_overrides({"ngauss": 1}, task="dos")

        advice = advise_dos(_diamond_silicon(), hpc=_hpc(), overrides=overrides)

        assert isinstance(advice.dos, Blocked)
        assert any(
            "nscf step's tetrahedra_opt occupations give none" in finding.message
            for finding in check_dos(advice).blocking
        )

    def test_the_routing_notice_reaches_the_task_s_warnings(self) -> None:
        overrides = build_overrides({"k_grid": [6, 6, 6]}, task="dos")

        warnings = advise_dos(
            _diamond_silicon(), hpc=_hpc(), overrides=overrides
        ).warnings()

        assert {
            **overrides.warnings[0].model_dump(),
            "record": "overrides",
        } in warnings

    def test_overrides_routed_for_dos_are_refused_by_the_scf_task(self) -> None:
        overrides = build_overrides({"steps.nscf.k_grid": [4, 4, 4]}, task="dos")

        with pytest.raises(ValueError, match="nscf"):
            advise(_diamond_silicon(), hpc=_hpc(), overrides=overrides)

    @pytest.mark.parametrize("unresolved", ["scf", "nscf"])
    def test_one_step_s_unresolved_bands_block_the_job_of_both_steps(
        self, unresolved, tmp_path, monkeypatch
    ) -> None:
        """The job covers every step, so one step's unresolved nbnd also
        blocks the other step's job."""
        store = _installed_store(tmp_path, monkeypatch)
        overrides = build_overrides(
            {f"steps.{unresolved}.extra_bands": -100}, task="dos"
        )

        advice = advise_dos(
            _diamond_silicon(), hpc=_hpc(), overrides=overrides, store=store
        )

        for purpose, step_advice in (("scf", advice.scf), ("nscf", advice.nscf)):
            assert step_advice.step.kpoints.nbnd.ok == (purpose != unresolved)
            resources = step_advice.step.resources
            assert isinstance(resources.job, Blocked)
            assert isinstance(resources.parallelisation, Blocked)
            assert "extra_bands=-100" in resources.job.root_cause()
            assert resources.max_seconds is None
            report = check(step_advice, purpose=purpose)
            assert any(
                "extra_bands=-100" in finding.message for finding in report.blocking
            )

    def test_delta_e_and_a_steps_nscf_mesh_reach_the_written_inputs(
        self, tmp_path, monkeypatch
    ) -> None:
        store = _installed_store(tmp_path, monkeypatch)
        overrides = build_overrides(
            {"delta_e": 0.05, "steps.nscf.k_grid": [12, 12, 12]}, task="dos"
        )
        advice = advise_dos(
            _diamond_silicon(), hpc=_hpc(), overrides=overrides, store=store
        )
        report = check_dos(advice)
        assert report.ok, report.blocking

        scf_step, nscf_step, dos_step = generate_dos(advice, report)

        assert "deltae           = 0.05" in dos_step.files["dos.in"]
        assert "K_POINTS automatic\n  12  12  12  0  0  0" in nscf_step.files["nscf.in"]
        assert "K_POINTS automatic\n  12  12  12" not in scf_step.files["scf.in"]
