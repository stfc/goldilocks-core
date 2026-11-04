"""Tests for goldilocks_core.server.http (v2 epic 8, #8).

Deliberately thin on business-logic scenarios (test_handlers.py already
covers those, transport-agnostically) -- this file is about what's
actually HTTP-specific: status codes, the error envelope shape, routing,
and the archive response mode.
"""

from __future__ import annotations

import io
import json
import math
import re
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient
from pymatgen.core import Lattice, Structure
from support import silicon_dimer_in_a_box, strict_json

from goldilocks_core.server.http import create_app

_GAMMA_ONLY = {"k_grid": [1, 1, 1]}
_SILICON_GAMMA_INTERVAL = [round(2 * math.pi / 5.431, 8), None]
"""Rung 1 of the bundled Si.cif's ladder (cubic, a = 5.431 A): every
k-distance above |b| = 2 pi / a, with no upper bound."""


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


class TestWorkbenchStaticMount:
    """v2 epic 12 (#12): the frontend is served off the same origin as
    the API, gated behind an env var so plain API use (every other test
    in this file) never needs a frontend build lying around."""

    def test_root_is_a_404_when_the_env_var_is_unset(self, client: TestClient) -> None:
        response = client.get("/")

        assert response.status_code == 404

    def test_root_serves_the_built_frontend_when_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "index.html").write_text("<!doctype html><title>Workbench</title>")
        monkeypatch.setenv("GOLDILOCKS_WORKBENCH_STATIC_ROOT", str(tmp_path))

        client = TestClient(create_app())
        response = client.get("/")

        assert response.status_code == 200
        assert "Workbench" in response.text

    def test_api_routes_still_win_over_the_mount(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "index.html").write_text("<!doctype html><title>Workbench</title>")
        monkeypatch.setenv("GOLDILOCKS_WORKBENCH_STATIC_ROOT", str(tmp_path))

        client = TestClient(create_app())
        response = client.get("/capabilities")

        assert response.status_code == 200
        assert response.json()["vocabulary_version"]

    def test_a_missing_static_root_fails_fast_at_startup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "GOLDILOCKS_WORKBENCH_STATIC_ROOT", str(tmp_path / "does-not-exist")
        )

        with pytest.raises(RuntimeError, match="does not exist"):
            create_app()

    def test_the_static_root_parameter_works_without_the_env_var(
        self, tmp_path: Path
    ) -> None:
        """#59: the CLI's ``--static-root`` flag reaches here as this
        explicit parameter, not by mutating the env var."""
        (tmp_path / "index.html").write_text("<!doctype html><title>Workbench</title>")

        client = TestClient(create_app(static_root=tmp_path))
        response = client.get("/")

        assert response.status_code == 200
        assert "Workbench" in response.text

    def test_the_static_root_parameter_wins_over_the_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_root = tmp_path / "from-env"
        env_root.mkdir()
        (env_root / "index.html").write_text("<!doctype html><title>Env</title>")
        param_root = tmp_path / "from-param"
        param_root.mkdir()
        (param_root / "index.html").write_text("<!doctype html><title>Param</title>")
        monkeypatch.setenv("GOLDILOCKS_WORKBENCH_STATIC_ROOT", str(env_root))

        client = TestClient(create_app(static_root=param_root))
        response = client.get("/")

        assert "Param" in response.text

    def test_a_relative_static_root_keeps_serving_after_the_cwd_changes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#136: ``poe stage`` passes ``--static-root web/dist``; resolving
        it against whatever the cwd is at request time made every static
        GET a 404 once something moved the server's cwd."""
        launch_directory = tmp_path / "launch"
        (launch_directory / "dist").mkdir(parents=True)
        (launch_directory / "dist" / "index.html").write_text(
            "<!doctype html><title>Workbench</title>"
        )
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(launch_directory)
        client = TestClient(create_app(static_root="dist"))
        assert client.get("/").status_code == 200

        monkeypatch.chdir(elsewhere)
        response = client.get("/")

        assert response.status_code == 200
        assert "Workbench" in response.text

    def test_root_serves_the_bundled_frontend_when_one_ships_with_this_install(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#122: a release build copies web/dist into src/goldilocks_core/
        webapp/ before packaging -- neither the explicit parameter nor the
        env var is involved, so this is the only tier left once both are
        unset."""
        (tmp_path / "index.html").write_text("<!doctype html><title>Bundled</title>")
        monkeypatch.setattr(
            "goldilocks_core.server.http._bundled_static_root", lambda: tmp_path
        )

        client = TestClient(create_app())
        response = client.get("/")

        assert response.status_code == 200
        assert "Bundled" in response.text

    def test_the_env_var_wins_over_the_bundled_frontend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundled_root = tmp_path / "bundled"
        bundled_root.mkdir()
        (bundled_root / "index.html").write_text(
            "<!doctype html><title>Bundled</title>"
        )
        env_root = tmp_path / "from-env"
        env_root.mkdir()
        (env_root / "index.html").write_text("<!doctype html><title>Env</title>")
        monkeypatch.setattr(
            "goldilocks_core.server.http._bundled_static_root", lambda: bundled_root
        )
        monkeypatch.setenv("GOLDILOCKS_WORKBENCH_STATIC_ROOT", str(env_root))

        client = TestClient(create_app())
        response = client.get("/")

        assert "Env" in response.text

    def test_no_bundled_frontend_ships_with_a_plain_source_install(self) -> None:
        """The whole point of #122's design: a dev/source install (this
        test suite's own environment) never has anything under
        src/goldilocks_core/webapp/, so this must resolve to None here --
        not mocked, the real function against the real installed package."""
        from goldilocks_core.server.http import _bundled_static_root

        assert _bundled_static_root() is None


class TestOperationalRoutes:
    def test_health(self, client: TestClient) -> None:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_ready_matches_the_readiness_checker_directly(
        self, client: TestClient
    ) -> None:
        """Not gated on ``real_assets``: ``/ready`` checks the *workbench*
        profile (every pseudopotential table *and* every ml model), a
        stricter bar than the ``default`` profile ``real_assets``
        guarantees -- this machine has the pseudopotentials but was
        deliberately not given the ml models, so asserting a specific
        ready/not-ready value here would depend on machine state this
        test doesn't control. Assert the response is *consistent* and
        well-shaped instead."""
        from goldilocks_core.server._handlers import build_readiness

        expected = build_readiness().check()

        response = client.get("/ready")

        if expected.ready:
            assert response.status_code == 200
            assert response.json() == {
                "status": "ready",
                "asset_count": expected.asset_count,
            }
        else:
            assert response.status_code == 503
            error = response.json()["error"]
            assert error["kind"] == "assets_unavailable"
            assert error["details"]["asset_id"] == expected.asset_id


class TestOpenAPISchema:
    def test_openapi_builds_without_raising(self, client: TestClient) -> None:
        """Regression test for #31: the ``/run`` route's ``-> Response``
        return annotation is a string under ``from __future__ import
        annotations``, and FastAPI/pydantic resolve it against
        ``server/http.py``'s module globals when building the schema --
        not against whatever was imported inside ``create_app()``. This
        is also what ``scripts/export_workbench_openapi.py`` runs during
        the Docker build stage, so a regression here breaks the image."""
        schema = client.app.openapi()

        assert set(schema["paths"]) == {
            "/health",
            "/ready",
            "/capabilities",
            "/inspect",
            "/explain",
            "/run",
            "/magnetic-orderings",
        }


class TestCapabilities:
    def test_returns_the_same_shape_capabilities_py_builds(
        self, client: TestClient
    ) -> None:
        from goldilocks_core.capabilities import capabilities

        response = client.get("/capabilities")

        assert response.status_code == 200
        assert response.json() == capabilities()

    def test_cell_dofree_advertises_only_values_valid_under_ibrav_0(
        self, client: TestClient
    ) -> None:
        """#153: 'volume' and the 21 'ibrav' forms were offered, though the
        written input always has ibrav = 0."""
        settings = client.get("/capabilities").json()["settings"]

        (cell_dofree,) = (s for s in settings if s["key"] == "cell_dofree")
        assert len(cell_dofree["enum"]) == 20
        assert "volume" not in cell_dofree["enum"]
        assert not [value for value in cell_dofree["enum"] if "ibrav" in value]


class TestInspect:
    def test_returns_200_for_real_structure_text(
        self, client: TestClient, silicon_cif: str
    ) -> None:
        response = client.post("/inspect", json={"structure_content": silicon_cif})

        assert response.status_code == 200
        assert response.json()["structure"]["reduced_formula"] == "Si"

    def test_rejects_a_path_shaped_value_as_422(self, client: TestClient) -> None:
        response = client.post("/inspect", json={"structure_content": "/etc/passwd"})

        assert response.status_code == 422
        body = response.json()
        assert body["error"]["kind"] == "invalid_request"
        # No raw exception object anywhere in the sanitized body.
        json.dumps(body)


class TestDisorderedStructures:
    def test_explain_run_and_orderings_refuse_it_as_422_and_inspect_reads_it(
        self, client: TestClient
    ) -> None:
        """#224: explain and run returned 500 when the ML tiers raised on a
        partially occupied site; every route that advises now refuses it with
        the sites named, and inspect still reads the file."""
        content = Structure.from_spacegroup(
            "Fm-3m",
            Lattice.cubic(4.2),
            [{"Fe": 0.5, "Ni": 0.5}, "O"],
            [[0, 0, 0], [0.5, 0, 0]],
        ).to(fmt="cif")

        for route, body in (
            ("/explain", {"structure_content": content, "hpc": "scarf"}),
            ("/run", {"structure_content": content, "hpc": "scarf"}),
            ("/magnetic-orderings", {"structure_content": content}),
        ):
            response = client.post(route, json=body)

            assert response.status_code == 422, route
            error = response.json()["error"]
            assert error["kind"] == "invalid_structure", route
            assert "site 1 (Fe0.5 Ni0.5)" in error["message"], route

        inspected = client.post("/inspect", json={"structure_content": content})
        assert inspected.status_code == 200


class TestMagneticOrderings:
    def test_returns_the_fm_candidate_unranked_by_default(
        self, client: TestClient, silicon_cif: str
    ) -> None:
        response = client.post(
            "/magnetic-orderings", json={"structure_content": silicon_cif}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ranked"] is False
        assert [c["label"] for c in body["candidates"]] == ["fm"]
        assert body["candidates"][0]["energy_per_atom_ev"] is None

    def test_rank_with_mmace_degrades_with_a_warning_when_unconfigured(
        self, client: TestClient, silicon_cif: str, monkeypatch
    ) -> None:
        monkeypatch.delenv("GOLDILOCKS_MACE_BACKBONE", raising=False)

        response = client.post(
            "/magnetic-orderings",
            json={"structure_content": silicon_cif, "rank_with_mmace": True},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ranked"] is False
        assert len(body["warnings"]) == 1
        assert body["warnings"][0]["code"] == "magnetic.ordering_ranking_unavailable"

    def test_rejects_a_path_shaped_value_as_422(self, client: TestClient) -> None:
        response = client.post(
            "/magnetic-orderings", json={"structure_content": "/etc/passwd"}
        )

        assert response.status_code == 422


class TestExplain:
    def test_returns_records_and_warnings(
        self, client: TestClient, real_assets, silicon_cif: str
    ) -> None:
        response = client.post(
            "/explain", json={"structure_content": silicon_cif, "hpc": "scarf"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["records"]["functional"]["value"] == "PBEsol"
        assert "warnings" in body
        assert body["blocking"] == []

    @pytest.mark.parametrize(
        "task",
        [
            "scf_single_point",
            "dos",
            "band",
            "phonon",
            "relax-phonon",
            "vc-relax-phonon",
        ],
    )
    def test_blocking_lists_the_reasons_run_refuses_with(
        self, client: TestClient, silicon_cif: str, task: str
    ) -> None:
        """#165: no real assets, so the isolated asset root's uninstalled
        default table blocks both routes; /explain still answers 200 and
        names the reason /run's 422 gives. Si is set to a non-metal, which a
        phonon task needs on smearing without a model to decide it."""
        body = {
            "structure_content": silicon_cif,
            "hpc": "scarf",
            "task": task,
            "overrides": {"is_metal": "non_metal"},
        }

        explained = client.post("/explain", json=body)
        refused = client.post("/run", json=body)

        assert explained.status_code == 200
        blocking = explained.json()["blocking"]
        assert len(blocking) == 1
        assert blocking[0]["code"] == "advice.blocked"
        assert "is not installed" in blocking[0]["message"]
        assert refused.status_code == 422
        error = refused.json()["error"]
        assert error["details"] == {"findings": blocking}
        assert error["message"] == (
            "cannot generate a runnable input: " + blocking[0]["message"]
        )

    def test_a_refused_run_returns_each_finding_with_its_remedies(
        self, client: TestClient, silicon_cif: str
    ) -> None:
        """#151: the 422 names the setting each finding concerns and the
        override patches that resolve it, in error.details.findings and in
        the message. No real assets: the uninstalled table is a finding
        without a remedy."""
        response = client.post(
            "/run",
            json={
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "task": "vc-relax",
                "overrides": {"ion_dynamics": "damp"},
            },
        )

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["kind"] == "advice_incomplete"
        table, ion_dynamics = error["details"]["findings"]
        assert table["code"] == "advice.blocked"
        assert (table["fields"], table["remedies"]) == ([], [])
        assert ion_dynamics == {
            "code": "relax.vc_relax_needs_bfgs",
            "fields": ["ion_dynamics"],
            "message": ion_dynamics["message"],
            "remedies": [{"ion_dynamics": "bfgs"}],
            "summary": "vc-relax is generated only with ion_dynamics=bfgs: set "
            "ion_dynamics to bfgs.",
        }
        assert ion_dynamics["message"].startswith(
            "vc-relax is generated only with ion_dynamics=bfgs, not damp:"
        )
        assert error["message"].endswith(
            f'{ion_dynamics["message"]} Remedy overrides: {{"ion_dynamics": "bfgs"}}.'
        )

    def test_dos_task_returns_nscf_prefixed_records_and_a_dos_record(
        self, client: TestClient, real_assets, silicon_cif: str
    ) -> None:
        """v2 epic 9 (#9, #28): task='dos' used to be silently accepted
        and ignored -- this confirms it actually routes to advise_dos,
        not the scf-only pipeline, through the real HTTP transport."""
        response = client.post(
            "/explain",
            json={"structure_content": silicon_cif, "hpc": "scarf", "task": "dos"},
        )

        assert response.status_code == 200
        records = response.json()["records"]
        # v2 epic 11 (#11): the real, installed CGCNN classifier now
        # resolves Si confidently non-metal (source=ml), so the scf
        # step's own occupations correctly follows the non-metal branch
        # -- unlike nscf_occupations below, which dos's own advisor
        # always pins to tetrahedra_opt regardless of metallicity.
        assert records["occupations"]["value"]["occupations"] == "fixed"
        assert records["nscf_occupations"]["value"]["occupations"] == ("tetrahedra_opt")
        assert records["dos"]["value"]["delta_e"] == 0.01

    def test_dos_nscf_protocol_values_read_heuristic_not_your_override(
        self, client: TestClient, silicon_cif: str
    ) -> None:
        """#174: with no overrides the dos task's nscf protocol values read
        'heuristic', naming the protocol in source_note; the same values set
        in the request read 'human'. Both used to read 'human'."""

        def nscf_records(overrides: dict[str, object]) -> list[dict]:
            response = client.post(
                "/explain",
                json={
                    "structure_content": silicon_cif,
                    "hpc": "scarf",
                    "task": "dos",
                    "overrides": overrides,
                },
            )
            assert response.status_code == 200
            records = response.json()["records"]
            return [records["nscf_k_sampling"], records["nscf_occupations"]]

        defaults = nscf_records({})
        requested = nscf_records({"k_distance": 0.1, "occupations": "tetrahedra_opt"})

        assert [record["value"] for record in defaults] == [
            record["value"] for record in requested
        ]
        assert defaults[0]["value"]["k_distance"] == 0.1
        assert defaults[1]["value"]["occupations"] == "tetrahedra_opt"
        for record in defaults:
            assert record["source"] == "heuristic"
            assert record["source_note"] == (
                "Protocol default for the dos task's nscf step: "
                "aiida-quantumespresso's pdos.yaml, balanced."
            )
        for record in requested:
            assert record["source"] == "human"
            assert record["source_note"] is None

    def test_band_task_returns_bands_prefixed_records(
        self, client: TestClient, real_assets, silicon_cif: str
    ) -> None:
        """#118: task='band' routes to advise_band through the real HTTP
        transport: the bands step's path as k_path and its other decisions
        under bands_ names, laid out under its own step."""
        response = client.post(
            "/explain",
            json={"structure_content": silicon_cif, "hpc": "scarf", "task": "band"},
        )

        assert response.status_code == 200
        body = response.json()
        records = body["records"]
        assert records["k_path"]["value"]["lattice_type"] == "FCC"
        assert (
            records["bands_occupations"]["value"]["occupations"]
            == (records["occupations"]["value"]["occupations"])
        )
        assert body["layout"]["steps"][1]["name"] == "bands"
        assert body["blocking"] == []

    @pytest.mark.parametrize(
        ("task", "first_step"),
        [("phonon", "scf"), ("relax-phonon", "relax"), ("vc-relax-phonon", "vc-relax")],
    )
    def test_a_phonon_task_returns_its_steps_records(
        self,
        client: TestClient,
        silicon_fixture_table,
        silicon_cif: str,
        task: str,
        first_step: str,
    ) -> None:
        """#215: each phonon task routes to advise_phonon through the real HTTP
        transport: the first pw.x step's records under its own name, then the
        ph step's q-mesh and ph.x settings, q2r.x's and matdyn.x's, the
        dispersion's path as k_path. Si is set to a non-metal, which a phonon
        task needs on smearing without a model to decide it."""
        response = client.post(
            "/explain",
            json={
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "task": task,
                "overrides": {"is_metal": "non_metal"},
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["blocking"] == []
        assert body["layout"]["steps"][1:] == [
            {"name": "ph", "records": ["q_sampling", "phonon"]},
            {"name": "q2r", "records": ["q2r"]},
            {"name": "phonon_dos", "records": ["phonon_dos"]},
            {"name": "dispersion", "records": ["k_path"]},
        ]
        assert body["layout"]["steps"][0]["name"] == first_step
        records = body["records"]
        assert records["q_sampling"]["value"]["q_distance"] == 0.3
        assert records["phonon"]["value"]["tr2_ph"] == 1e-18
        assert ("relax" in records) is (first_step != "scf")

    def test_relax_task_returns_a_relax_record(
        self, client: TestClient, real_assets, silicon_cif: str
    ) -> None:
        """v2 epic 10 (#10): confirms task='relax' actually routes to
        advise_relax through the real HTTP transport, the same
        end-to-end check #28 added for task='dos'."""
        response = client.post(
            "/explain",
            json={"structure_content": silicon_cif, "hpc": "scarf", "task": "relax"},
        )

        assert response.status_code == 200
        records = response.json()["records"]
        assert records["relax"]["value"]["ion_dynamics"] == "bfgs"

    def test_unknown_task_is_a_422_not_a_silent_fallback(
        self, client: TestClient, silicon_cif: str
    ) -> None:
        response = client.post(
            "/explain",
            json={
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "task": "no_such_task",
            },
        )

        assert response.status_code == 422

    def test_a_gamma_only_mesh_answers_with_strict_json(
        self, client: TestClient, silicon_cif: str
    ) -> None:
        """Rung 1's open k-distance bound is null (#137)."""
        response = client.post(
            "/explain",
            json={
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "overrides": _GAMMA_ONLY,
            },
        )

        assert response.status_code == 200
        k_sampling = strict_json(response.text)["records"]["k_sampling"]["value"]
        assert k_sampling["k_index"] == 1
        assert k_sampling["k_distance_interval"] == _SILICON_GAMMA_INTERVAL

    def test_metallicity_and_magnetism_overrides_take_the_advertised_labels(
        self, client: TestClient, silicon_cif: str
    ) -> None:
        """#139: /capabilities advertises metal/non_metal and
        magnetic/non_magnetic; each was a 422 bool_parsing."""
        response = client.post(
            "/explain",
            json={
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "overrides": {"is_metal": "non_metal", "is_magnetic": "magnetic"},
            },
        )

        assert response.status_code == 200
        records = response.json()["records"]
        assert (records["is_metal"]["value"], records["is_metal"]["source"]) == (
            "non_metal",
            "human",
        )
        assert (
            records["is_magnetic"]["value"],
            records["is_magnetic"]["source"],
        ) == ("magnetic", "human")

    def test_a_boolean_metallicity_override_is_a_422(
        self, client: TestClient, silicon_cif: str
    ) -> None:
        """#139: no boolean alias for the advertised labels."""
        response = client.post(
            "/explain",
            json={
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "overrides": {"is_metal": False},
            },
        )

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["kind"] == "invalid_setting"
        assert "'metal' or 'non_metal'" in error["message"]

    def test_a_non_finite_override_is_a_422(
        self, client: TestClient, silicon_cif: str
    ) -> None:
        """The request body parser reads the JSON number 1e999 as inf: an
        invalid setting, not a k-distance (#137)."""
        body = json.dumps(
            {
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "overrides": {"k_distance": "__non_finite__"},
            }
        ).replace('"__non_finite__"', "1e999")

        response = client.post(
            "/explain", content=body, headers={"content-type": "application/json"}
        )

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["kind"] == "invalid_setting"
        assert "finite number" in error["message"]


class TestPerStepOverrides:
    """#154 over HTTP: `steps.nscf.k_grid` was a 422 "unknown setting",
    dos.x keys were unknown, and a key no step of the task reads (press on
    an scf) answered 200 and was dropped. No real assets needed: /explain
    reports every record either way."""

    def _explain(
        self, client: TestClient, silicon_cif: str, task: str, overrides: dict
    ) -> object:
        return client.post(
            "/explain",
            json={
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "task": task,
                "overrides": overrides,
            },
        )

    def test_steps_nscf_k_grid_changes_only_the_nscf_mesh(
        self, client: TestClient, silicon_cif: str
    ) -> None:
        default = self._explain(client, silicon_cif, "dos", {}).json()["records"]
        response = self._explain(
            client, silicon_cif, "dos", {"steps.nscf.k_grid": [30, 30, 30]}
        )

        assert response.status_code == 200
        records = response.json()["records"]
        assert records["nscf_k_sampling"]["value"]["mesh"] == [30, 30, 30]
        assert records["k_sampling"] == default["k_sampling"]

    def test_a_shift_keeps_the_protocol_nscf_mesh(
        self, client: TestClient, silicon_cif: str
    ) -> None:
        default = self._explain(client, silicon_cif, "dos", {}).json()["records"]
        response = self._explain(client, silicon_cif, "dos", {"shift": [1, 1, 1]})

        assert response.status_code == 200
        nscf = response.json()["records"]["nscf_k_sampling"]["value"]
        assert nscf["mesh"] == default["nscf_k_sampling"]["value"]["mesh"]
        assert (nscf["k_distance"], nscf["shift"]) == (0.1, [1, 1, 1])

    def test_a_dos_x_setting_reaches_the_dos_record(
        self, client: TestClient, silicon_cif: str
    ) -> None:
        response = self._explain(client, silicon_cif, "dos", {"delta_e": 0.05})

        assert response.status_code == 200
        dos = response.json()["records"]["dos"]
        assert dos["value"]["delta_e"] == 0.05
        assert dos["source"] == "human"

    def test_a_flat_k_grid_on_dos_answers_with_the_routing_notice(
        self, client: TestClient, silicon_cif: str
    ) -> None:
        response = self._explain(client, silicon_cif, "dos", {"k_grid": [4, 4, 4]})

        assert response.status_code == 200
        notices = [
            warning
            for warning in response.json()["warnings"]
            if warning["code"] == "overrides.applies_to_multiple_steps"
        ]
        assert [(n["record"], n["level"]) for n in notices] == [("overrides", "info")]

    def test_a_mixing_beta_on_dos_sets_the_scf_step_only(
        self, client: TestClient, silicon_cif: str
    ) -> None:
        """The nscf step runs no SCF loop, yet nscf_convergence read human for
        a mixing_beta pw.x ignores there, with a notice naming both steps."""
        response = self._explain(client, silicon_cif, "dos", {"mixing_beta": 0.3})

        assert response.status_code == 200
        body = response.json()
        scf = body["records"]["convergence"]
        nscf = body["records"]["nscf_convergence"]
        assert (scf["value"]["mixing_beta"], scf["field_sources"]["mixing_beta"]) == (
            0.3,
            "human",
        )
        assert (nscf["value"]["mixing_beta"], nscf["source"]) == (0.4, "heuristic")
        assert "overrides.applies_to_multiple_steps" not in {
            warning["code"] for warning in body["warnings"]
        }

    @pytest.mark.parametrize(
        ("task", "overrides", "message"),
        [
            (
                "scf_single_point",
                {"press": 10},
                "'press' does not apply to task 'scf_single_point'; "
                "it applies to tasks vc-relax, vc-relax-phonon",
            ),
            (
                "relax",
                {"cell_dofree": "2Dxy", "press": 5},
                "'cell_dofree' does not apply to task 'relax'; "
                "it applies to tasks vc-relax, vc-relax-phonon",
            ),
            (
                "relax-phonon",
                {"steps.scf.k_grid": [4, 4, 4]},
                "unknown step 'scf' in 'steps.scf.k_grid'; "
                "task 'relax-phonon' has steps: relax, ph, q2r, phonon_dos, "
                "dispersion",
            ),
            (
                "scf_single_point",
                {"delta_e": 0.05},
                "'delta_e' does not apply to task 'scf_single_point'; "
                "it applies to task dos",
            ),
            (
                "dos",
                {"steps.nscf.mixing_beta": 0.3},
                "'mixing_beta' does not apply to step 'nscf' "
                "(in 'steps.nscf.mixing_beta'); it applies to steps scf, relax, "
                "vc-relax",
            ),
        ],
    )
    def test_a_setting_no_step_of_the_task_reads_is_a_422(
        self,
        client: TestClient,
        silicon_cif: str,
        task: str,
        overrides: dict,
        message: str,
    ) -> None:
        for route in ("/explain", "/run"):
            response = client.post(
                route,
                json={
                    "structure_content": silicon_cif,
                    "hpc": "scarf",
                    "task": task,
                    "overrides": overrides,
                },
            )

            assert response.status_code == 422, route
            error = response.json()["error"]
            assert (error["kind"], error["message"]) == ("invalid_setting", message)

    def test_delta_e_reaches_dos_in_and_steps_nscf_only_nscf_in(
        self, client: TestClient, silicon_fixture_table, silicon_cif: str
    ) -> None:
        response = client.post(
            "/run",
            json={
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "task": "dos",
                "respond_with": "archive",
                "overrides": {"delta_e": 0.05, "steps.nscf.k_grid": [12, 12, 12]},
            },
        )

        assert response.status_code == 200
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        dos_in = archive.read(_archive_member(archive, "dos.in")).decode()
        assert "deltae           = 0.05" in dos_in
        nscf_in = archive.read(_archive_member(archive, "nscf.in")).decode()
        scf_in = archive.read(_archive_member(archive, "scf.in")).decode()
        assert "K_POINTS automatic\n  12  12  12  0  0  0" in nscf_in
        assert "K_POINTS automatic\n  12  12  12" not in scf_in


def _archive_member(archive: zipfile.ZipFile, name: str) -> str:
    return next(
        member for member in archive.namelist() if member.rpartition("/")[2] == name
    )


class TestRun:
    def test_json_mode_lists_the_published_files(
        self, client: TestClient, real_assets, silicon_cif: str
    ) -> None:
        response = client.post(
            "/run", json={"structure_content": silicon_cif, "hpc": "scarf"}
        )

        assert response.status_code == 200
        body = response.json()
        assert "scf.in" in body["files"]
        assert "submit.sh" in body["files"]

    def test_archive_mode_returns_a_real_zip(
        self, client: TestClient, real_assets, silicon_cif: str
    ) -> None:
        response = client.post(
            "/run",
            json={
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "respond_with": "archive",
            },
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"

    def test_json_mode_answers_a_gamma_only_mesh_with_strict_json(
        self, client: TestClient, silicon_fixture_table, silicon_cif: str
    ) -> None:
        """Rung 1's open k-distance bound is null; as inf it made the
        response encoder raise, so every Gamma-only /run was a 500 (#137)."""
        response = client.post(
            "/run",
            json={
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "overrides": _GAMMA_ONLY,
            },
        )

        assert response.status_code == 200
        records = strict_json(response.text)["records"]
        interval = records["k_sampling"]["value"]["k_distance_interval"]
        assert interval == _SILICON_GAMMA_INTERVAL

    def test_a_metal_override_reaches_the_generated_occupations(
        self, client: TestClient, silicon_fixture_table, silicon_cif: str
    ) -> None:
        """#139: the advertised label, not a boolean, now corrects the
        classification, and the input follows it: smearing for a metal."""
        response = client.post(
            "/run",
            json={
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "overrides": {"is_metal": "metal"},
                "respond_with": "archive",
            },
        )

        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            manifest = strict_json(archive.read("goldilocks.json"))
            scf_in = archive.read("scf.in").decode()
        assert manifest["records"]["is_metal"]["value"] == "metal"
        assert manifest["records"]["is_metal"]["source"] == "human"
        assert re.search(r"occupations\s*=\s*'smearing'", scf_in)

    def test_archive_manifest_is_strict_json_for_a_gamma_only_mesh(
        self, client: TestClient, silicon_fixture_table, silicon_cif: str
    ) -> None:
        """goldilocks.json carried a bare Infinity token here (#137)."""
        response = client.post(
            "/run",
            json={
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "overrides": _GAMMA_ONLY,
                "respond_with": "archive",
            },
        )

        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            manifest = strict_json(archive.read("goldilocks.json"))
        interval = manifest["records"]["k_sampling"]["value"]["k_distance_interval"]
        assert interval == _SILICON_GAMMA_INTERVAL

    def test_an_isolated_molecule_runs_at_gamma_only_by_default(
        self, client: TestClient, silicon_fixture_table
    ) -> None:
        """#159: a molecule in a box, vacuum along a, b and c, gets the
        Gamma-only mesh without any k-point override, and its open-ended
        interval reaches the response as strict JSON (#137)."""
        response = client.post(
            "/run",
            json={
                "structure_content": silicon_dimer_in_a_box().to(fmt="cif"),
                "structure_format": "cif",
                "hpc": "scarf",
            },
        )

        assert response.status_code == 200
        k_sampling = strict_json(response.text)["records"]["k_sampling"]["value"]
        assert k_sampling["mesh"] == [1, 1, 1]
        assert k_sampling["k_distance_interval"] == [0.0, None]

    def test_dos_task_generates_all_three_steps(
        self, client: TestClient, real_assets, silicon_cif: str
    ) -> None:
        response = client.post(
            "/run",
            json={"structure_content": silicon_cif, "hpc": "scarf", "task": "dos"},
        )

        assert response.status_code == 200
        files = response.json()["files"]
        assert "scf.in" in files
        assert "nscf.in" in files
        assert "dos.in" in files
        assert "submit.sh" in files

    def test_band_task_generates_every_step(
        self, client: TestClient, real_assets, silicon_cif: str
    ) -> None:
        response = client.post(
            "/run",
            json={"structure_content": silicon_cif, "hpc": "scarf", "task": "band"},
        )

        assert response.status_code == 200
        files = response.json()["files"]
        for name in ("scf.in", "bands.in", "bands_x.in", "submit.sh"):
            assert name in files, name

    @pytest.mark.parametrize(
        ("task", "first_step"),
        [("phonon", "scf"), ("relax-phonon", "relax"), ("vc-relax-phonon", "vc-relax")],
    )
    def test_a_phonon_task_generates_every_step(
        self,
        client: TestClient,
        silicon_fixture_table,
        silicon_cif: str,
        task: str,
        first_step: str,
    ) -> None:
        """Si set to a non-metal, which a phonon task needs on smearing without
        a model to decide it."""
        response = client.post(
            "/run",
            json={
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "task": task,
                "overrides": {"is_metal": "non_metal"},
            },
        )

        assert response.status_code == 200
        files = response.json()["files"]
        for name in (
            f"{first_step}.in",
            "ph.in",
            "q2r.in",
            "phonon_dos.in",
            "dispersion.in",
            "submit.sh",
        ):
            assert name in files, name
        assert "d3hess.in" not in files

    def test_relax_task_generates_relax_in(
        self, client: TestClient, real_assets, silicon_cif: str
    ) -> None:
        response = client.post(
            "/run",
            json={"structure_content": silicon_cif, "hpc": "scarf", "task": "relax"},
        )

        assert response.status_code == 200
        files = response.json()["files"]
        assert "relax.in" in files
        assert "submit.sh" in files

    def test_vc_relax_task_generates_vc_relax_in_with_a_set_override(
        self, client: TestClient, real_assets, silicon_cif: str
    ) -> None:
        response = client.post(
            "/run",
            json={
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "task": "vc-relax",
                "overrides": {"cell_factor": 3.0},
            },
        )

        assert response.status_code == 200
        files = response.json()["files"]
        assert "vc-relax.in" in files

    @pytest.mark.parametrize("cell_dofree", ["volume", "ibrav+volume", "ibrav+2Dxy"])
    def test_a_cell_dofree_invalid_under_ibrav_0_is_a_422(
        self, client: TestClient, silicon_cif: str, cell_dofree: str
    ) -> None:
        """#153: cell_dofree='volume' returned 200 and a vc-relax.in with
        ibrav = 0, where pw.x stops while reading it."""
        response = client.post(
            "/run",
            json={
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "task": "vc-relax",
                "overrides": {"cell_dofree": cell_dofree},
            },
        )

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["kind"] == "invalid_setting"
        assert "cell_dofree" in error["message"]

    def test_unknown_setting_is_a_422_with_did_you_mean(
        self, client: TestClient, real_assets, silicon_cif: str
    ) -> None:
        response = client.post(
            "/run",
            json={
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "overrides": {"ecutwf_ry": 30},
            },
        )

        assert response.status_code == 422
        assert "did you mean: ecutwfc_ry" in response.json()["error"]["message"]

    def test_blocked_pipeline_is_a_422_with_deduplicated_message(
        self, client: TestClient, silicon_cif: str
    ) -> None:
        response = client.post(
            "/run",
            json={
                "structure_content": silicon_cif,
                "hpc": "scarf",
                "overrides": {"pseudo_table_id": "does-not-exist"},
            },
        )

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["message"].count("unknown pseudopotential table") == 1
        (finding,) = error["details"]["findings"]
        assert finding["code"] == "advice.blocked"
        assert "does-not-exist" in finding["message"]

    def test_unknown_hpc_profile_is_a_422(
        self, client: TestClient, silicon_cif: str
    ) -> None:
        response = client.post(
            "/run",
            json={"structure_content": silicon_cif, "hpc": "does-not-exist"},
        )

        assert response.status_code == 422
        assert response.json()["error"]["kind"] == "invalid_hpc_profile"

    def test_rejects_unknown_top_level_fields(
        self, client: TestClient, silicon_cif: str
    ) -> None:
        response = client.post(
            "/run",
            json={"structure_content": silicon_cif, "structure_path": "/tmp/x.cif"},
        )

        assert response.status_code == 422
