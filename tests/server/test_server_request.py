from __future__ import annotations

import errno
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    JobMode,
)
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.server.request import (
    ConfinedAccessFailure,
    RequestError,
    parse_core_job_request,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _bounded_call(func: "Callable[[], object]", timeout: float = 5.0) -> object:
    """Run ``func`` in a daemon thread and fail if it does not return in time.

    Guards against a FIFO/special file blocking the worker: a correct confined
    walk returns immediately, while a blocking ``os.open`` would hang the
    thread past ``timeout``.
    """
    box: dict[str, object] = {}

    def runner() -> None:
        try:
            box["result"] = func()
        except BaseException as error:  # noqa: BLE001 - re-raised in caller
            box["error"] = error

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise AssertionError(
            f"confined walk did not complete within {timeout}s (blocked on a FIFO?)"
        )
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["result"]


def _si_pseudo() -> PseudoMetadata:
    """Return a minimal Si pseudopotential metadata instance."""
    return PseudoMetadata(
        filepath="/pseudo/Si.UPF",
        filename="Si.UPF",
        header_format="attr",
        element="Si",
        pseudo_type="NC",
        functional="PBE",
        relativistic="scalar",
        sssp_recommended_cutoff={"ecutwfc_ry": 30.0, "ecutrho_ry": 120.0},
    )


def _si_structure() -> Structure:
    """Return a small Si structure."""
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def test_parse_inline_cif_content_into_core_job_request() -> None:
    """Inline CIF text is parsed into a Structure on the request."""
    structure = _si_structure()
    cif = structure.to(fmt="cif")
    body = {
        "structure": {"content": cif, "format": "cif"},
        "hints": {"k_grid": [3, 3, 3]},
    }

    request = parse_core_job_request(
        body, mode="recommend", structure_root=None, bundle_root=Path("/tmp/bundles")
    )

    assert isinstance(request, CoreJobRequest)
    assert request.mode == "recommend"
    assert request.structure.reduced_formula == "Si"
    assert request.hints.k_grid == (3, 3, 3)
    assert request.pseudo_metadata == ()


def test_parse_inline_poscar_without_format_auto_detects() -> None:
    """Inline POSCAR without an explicit format is still parsed."""
    poscar = _si_structure().to(fmt="poscar")
    body = {"structure": {"content": poscar}}

    request = parse_core_job_request(
        body, mode="recommend", structure_root=None, bundle_root=Path("/tmp/bundles")
    )

    assert request.structure.reduced_formula == "Si"


def test_parse_intent_and_hints_delegate_to_from_dict() -> None:
    """Intent and hints are built through the shared contract constructors."""
    body = {
        "structure": {"content": _si_structure().to(fmt="cif"), "format": "cif"},
        "intent": {"functional": "PBEsol", "pseudo_mode": "precision"},
        "hints": {"k_grid": [4, 4, 4], "use_vdw": True, "vdw_method": "d3bj"},
    }

    request = parse_core_job_request(
        body, mode="recommend", structure_root=None, bundle_root=Path("/tmp/bundles")
    )

    assert request.intent == CalculationIntent(
        functional="PBEsol", pseudo_mode="precision"
    )
    assert request.hints == CalculationHints(
        k_grid=(4, 4, 4), use_vdw=True, vdw_method="d3bj"
    )


def test_parse_per_request_pseudo_metadata_overrides_default() -> None:
    """Per-request pseudo_metadata replaces the configured default."""
    body = {
        "structure": {"content": _si_structure().to(fmt="cif"), "format": "cif"},
        "pseudo_metadata": [_si_pseudo().to_dict()],
    }

    request = parse_core_job_request(
        body,
        mode="recommend",
        structure_root=None,
        bundle_root=Path("/tmp/bundles"),
        default_pseudo_metadata=("placeholder",),  # type: ignore[arg-type]
    )

    assert len(request.pseudo_metadata) == 1
    assert request.pseudo_metadata[0].filename == "Si.UPF"


def test_parse_falls_back_to_default_pseudo_metadata_when_absent() -> None:
    """Missing pseudo_metadata uses the configured default tuple."""
    default = (_si_pseudo(),)
    body = {
        "structure": {"content": _si_structure().to(fmt="cif"), "format": "cif"},
    }

    request = parse_core_job_request(
        body,
        mode="recommend",
        structure_root=None,
        bundle_root=Path("/tmp/bundles"),
        default_pseudo_metadata=default,
    )

    assert request.pseudo_metadata == default


def test_parse_structure_path_resolves_under_allowlisted_root(
    structure_root: Path,
) -> None:
    """A server-side structure path resolves against the configured root."""
    body = {"structure": {"path": "Si.cif"}, "hints": {"k_grid": [3, 3, 3]}}

    request = parse_core_job_request(
        body,
        mode="recommend",
        structure_root=structure_root,
        bundle_root=Path("/tmp/bundles"),
    )

    assert request.structure.reduced_formula == "Si"


def test_parse_rejects_non_dict_body() -> None:
    """A non-object body maps to invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            [], mode="recommend", structure_root=None, bundle_root=Path("/x")
        )  # type: ignore[arg-type]
    assert error.value.kind == "invalid_request"


def test_parse_rejects_missing_structure() -> None:
    """A body without a structure field maps to invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {"hints": {}}, mode="recommend", structure_root=None, bundle_root=Path("/x")
        )
    assert error.value.kind == "invalid_request"


def test_parse_rejects_structure_without_content_or_path() -> None:
    """A structure object missing both keys maps to invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {"structure": {}},
            mode="recommend",
            structure_root=None,
            bundle_root=Path("/x"),
        )
    assert error.value.kind == "invalid_request"


def test_parse_rejects_non_object_structure() -> None:
    """A bare string structure maps to invalid_request (ambiguous)."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {"structure": "Si.cif"},
            mode="recommend",
            structure_root=None,
            bundle_root=Path("/x"),
        )
    assert error.value.kind == "invalid_request"


def test_parse_rejects_unparseable_inline_content() -> None:
    """Garbage inline content maps to invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {"structure": {"content": "not a structure", "format": "cif"}},
            mode="recommend",
            structure_root=None,
            bundle_root=Path("/x"),
        )
    assert error.value.kind == "invalid_request"


def test_parse_rejects_unknown_structure_format() -> None:
    """An unsupported structure format hint maps to invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {"structure": {"content": "x", "format": "xyz"}},
            mode="recommend",
            structure_root=None,
            bundle_root=Path("/x"),
        )
    assert error.value.kind == "invalid_request"


def test_parse_rejects_absolute_structure_path() -> None:
    """An absolute structure path maps to invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {"structure": {"path": "/etc/passwd"}},
            mode="recommend",
            structure_root=Path("/tmp/structures"),
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"


@pytest.mark.parametrize(
    "path", ["../escape", "sub/../../escape", "foo/..", "a/b/../../c"]
)
def test_parse_rejects_traversal_structure_path(path: str) -> None:
    """Traversal in a structure path maps to invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {"structure": {"path": path}},
            mode="recommend",
            structure_root=Path("/tmp/structures"),
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"


def test_parse_rejects_structure_path_without_configured_root() -> None:
    """A server-side path with no configured root maps to invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {"structure": {"path": "Si.cif"}},
            mode="recommend",
            structure_root=None,
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"


def test_parse_missing_structure_file_maps_to_not_found(structure_root: Path) -> None:
    """A structure path that does not exist maps to not_found (404)."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {"structure": {"path": "missing.cif"}},
            mode="recommend",
            structure_root=structure_root,
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "not_found"


def test_parse_rejects_unknown_intent_key() -> None:
    """Unknown intent keys surface as invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {
                "structure": {
                    "content": _si_structure().to(fmt="cif"),
                    "format": "cif",
                },
                "intent": {"code": "quantum_espresso", "bogus": 1},
            },
            mode="recommend",
            structure_root=None,
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"
    assert "bogus" in error.value.message


def test_parse_rejects_unknown_hints_key() -> None:
    """Unknown hints keys surface as invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {
                "structure": {
                    "content": _si_structure().to(fmt="cif"),
                    "format": "cif",
                },
                "hints": {"bogus": 1},
            },
            mode="recommend",
            structure_root=None,
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"


def test_parse_rejects_unsupported_code() -> None:
    """An unsupported DFT code maps to invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {
                "structure": {
                    "content": _si_structure().to(fmt="cif"),
                    "format": "cif",
                },
                "intent": {"code": "vasp"},
            },
            mode="recommend",
            structure_root=None,
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"


def test_parse_rejects_unsupported_task() -> None:
    """An unsupported calculation task maps to invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {
                "structure": {
                    "content": _si_structure().to(fmt="cif"),
                    "format": "cif",
                },
                "intent": {"task": "relax"},
            },
            mode="recommend",
            structure_root=None,
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"


def test_parse_rejects_bad_hint_value() -> None:
    """A hint value that fails contract validation maps to invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {
                "structure": {
                    "content": _si_structure().to(fmt="cif"),
                    "format": "cif",
                },
                "hints": {"k_grid": [0, 0, 0]},
            },
            mode="recommend",
            structure_root=None,
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"


def test_parse_bundle_resolves_output_dir_under_bundle_root(tmp_path: Path) -> None:
    """Bundle output_dir is resolved against the configured bundle root."""
    bundle_root = tmp_path / "bundles"
    body = {
        "structure": {"content": _si_structure().to(fmt="cif"), "format": "cif"},
        "hints": {"k_grid": [3, 3, 3]},
        "pseudo_metadata": [_si_pseudo().to_dict()],
        "output_dir": "run-001",
    }

    request = parse_core_job_request(
        body, mode="bundle", structure_root=None, bundle_root=bundle_root
    )

    assert request.mode == "bundle"
    assert request.output_dir is not None
    assert str(bundle_root) in request.output_dir
    assert request.output_dir.endswith("run-001")


def test_parse_bundle_requires_output_dir() -> None:
    """Bundle mode without output_dir maps to invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {
                "structure": {
                    "content": _si_structure().to(fmt="cif"),
                    "format": "cif",
                },
                "hints": {"k_grid": [3, 3, 3]},
            },
            mode="bundle",
            structure_root=None,
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"


def test_parse_bundle_rejects_traversal_output_dir() -> None:
    """A traversal output_dir maps to invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {
                "structure": {
                    "content": _si_structure().to(fmt="cif"),
                    "format": "cif",
                },
                "output_dir": "../../etc",
            },
            mode="bundle",
            structure_root=None,
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"


def test_parse_bundle_rejects_absolute_output_dir() -> None:
    """An absolute output_dir maps to invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {
                "structure": {
                    "content": _si_structure().to(fmt="cif"),
                    "format": "cif",
                },
                "output_dir": "/etc",
            },
            mode="bundle",
            structure_root=None,
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"


@pytest.mark.parametrize("mode", ["recommend", "generate", "bundle"])
def test_parse_rejects_mode_in_body(mode: JobMode) -> None:
    """The body must not carry ``mode``; the transport selects it."""
    body = {
        "structure": {"content": _si_structure().to(fmt="cif"), "format": "cif"},
        "hints": {"k_grid": [3, 3, 3]},
        "mode": "recommend",
    }
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            body,
            mode=mode,
            structure_root=None,
            bundle_root=Path("/tmp/bundles") if mode == "bundle" else None,
        )
    assert error.value.kind == "invalid_request"
    assert "mode" in error.value.message


@pytest.mark.parametrize("mode", ["recommend", "generate"])
def test_parse_rejects_output_dir_on_non_bundle(mode: JobMode) -> None:
    """``output_dir`` is rejected on non-bundle endpoints."""
    body = {
        "structure": {"content": _si_structure().to(fmt="cif"), "format": "cif"},
        "hints": {"k_grid": [3, 3, 3]},
        "output_dir": "run-001",
    }
    with pytest.raises(RequestError) as error:
        parse_core_job_request(body, mode=mode, structure_root=None, bundle_root=None)
    assert error.value.kind == "invalid_request"
    assert "output_dir" in error.value.message


def test_parse_rejects_unknown_top_level_field() -> None:
    """Unknown top-level fields map to invalid_request, not silent acceptance."""
    body = {
        "structure": {"content": _si_structure().to(fmt="cif"), "format": "cif"},
        "hints": {"k_grid": [3, 3, 3]},
        "bogus": 1,
    }
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            body, mode="recommend", structure_root=None, bundle_root=None
        )
    assert error.value.kind == "invalid_request"
    assert "bogus" in error.value.message


def test_parse_bundle_accepts_output_dir_and_selects_mode() -> None:
    """Bundle mode accepts output_dir; the transport mode governs the request."""
    body = {
        "structure": {"content": _si_structure().to(fmt="cif"), "format": "cif"},
        "hints": {"k_grid": [3, 3, 3]},
        "pseudo_metadata": [_si_pseudo().to_dict()],
        "output_dir": "run-001",
    }

    request = parse_core_job_request(
        body,
        mode="bundle",
        structure_root=None,
        bundle_root=Path("/tmp/bundles"),
        default_pseudo_metadata=(),
    )

    assert request.mode == "bundle"
    assert request.output_dir is not None


def test_parse_rejects_non_list_pseudo_metadata() -> None:
    """A non-list pseudo_metadata maps to invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {
                "structure": {
                    "content": _si_structure().to(fmt="cif"),
                    "format": "cif",
                },
                "pseudo_metadata": {"filename": "Si.UPF"},  # type: ignore[dict-item]
            },
            mode="recommend",
            structure_root=None,
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"


# --- Reviewer probe regressions (issue #44): symlink confinement --------------


def test_parse_structure_path_rejects_symlink_component(
    structure_root: Path, tmp_path: Path
) -> None:
    """A symlink component inside the structure root is rejected, not followed."""
    outside = tmp_path / "outside.cif"
    outside.write_text(_si_structure().to(fmt="cif"))
    (structure_root / "link.cif").symlink_to(outside)

    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {"structure": {"path": "link.cif"}, "hints": {"k_grid": [3, 3, 3]}},
            mode="recommend",
            structure_root=structure_root,
            bundle_root=Path("/tmp/bundles"),
        )

    assert error.value.kind == "invalid_request"
    assert "symlink" in error.value.message


def test_parse_bundle_output_dir_rejects_symlink_component(
    bundle_root: Path, tmp_path: Path
) -> None:
    """A symlink component in output_dir cannot resolve outside the bundle root."""
    outside_root = tmp_path / "outside-bundles"
    outside_root.mkdir()
    (bundle_root / "link").symlink_to(outside_root)

    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {
                "structure": {
                    "content": _si_structure().to(fmt="cif"),
                    "format": "cif",
                },
                "hints": {"k_grid": [3, 3, 3]},
                "output_dir": "link/run-001",
            },
            mode="bundle",
            structure_root=None,
            bundle_root=bundle_root,
        )

    assert error.value.kind == "invalid_request"
    assert "symlink" in error.value.message
    assert not any(outside_root.iterdir())


# --- Reviewer probe regressions (issue #44 final): FIFO/special-file confinement ---


def test_parse_rejects_fifo_structure_file_without_blocking(
    structure_root: Path, tmp_path: Path
) -> None:
    """A FIFO as the final structure file is rejected, not read-blocked on."""
    fifo = structure_root / "fifo.cif"
    os.mkfifo(fifo)

    def call() -> object:
        return parse_core_job_request(
            {"structure": {"path": "fifo.cif"}, "hints": {"k_grid": [3, 3, 3]}},
            mode="recommend",
            structure_root=structure_root,
            bundle_root=tmp_path / "bundles",
        )

    with pytest.raises(RequestError) as error:
        _bounded_call(call)
    assert error.value.kind == "invalid_request"
    assert "regular file" in error.value.message


def test_parse_rejects_fifo_intermediate_structure_component_without_blocking(
    structure_root: Path, tmp_path: Path
) -> None:
    """A FIFO as an intermediate component is rejected without blocking."""
    fifo_dir = structure_root / "blocked"
    os.mkfifo(fifo_dir)  # an intermediate component that is a FIFO, not a dir

    def call() -> object:
        return parse_core_job_request(
            {"structure": {"path": "blocked/Si.cif"}, "hints": {"k_grid": [3, 3, 3]}},
            mode="recommend",
            structure_root=structure_root,
            bundle_root=tmp_path / "bundles",
        )

    with pytest.raises(RequestError) as error:
        _bounded_call(call)
    assert error.value.kind == "invalid_request"
    assert "non-directory" in error.value.message


def test_parse_rejects_socket_structure_file(
    structure_root: Path, tmp_path: Path
) -> None:
    """A Unix socket as the final structure file is rejected as non-regular."""
    import socket

    sock_path = structure_root / "sock.cif"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(str(sock_path))

        def call() -> object:
            return parse_core_job_request(
                {"structure": {"path": "sock.cif"}, "hints": {"k_grid": [3, 3, 3]}},
                mode="recommend",
                structure_root=structure_root,
                bundle_root=tmp_path / "bundles",
            )

        with pytest.raises(RequestError) as error:
            _bounded_call(call)
    finally:
        sock.close()
        sock_path.unlink(missing_ok=True)
    assert error.value.kind == "invalid_request"
    assert "regular file" in error.value.message


def test_parse_rejects_fifo_intermediate_bundle_output_dir_without_blocking(
    bundle_root: Path, tmp_path: Path
) -> None:
    """A FIFO as an intermediate output_dir component is rejected without blocking."""
    fifo = bundle_root / "blocked"
    os.mkfifo(fifo)

    def call() -> object:
        return parse_core_job_request(
            {
                "structure": {
                    "content": _si_structure().to(fmt="cif"),
                    "format": "cif",
                },
                "hints": {"k_grid": [3, 3, 3]},
                "output_dir": "blocked/run-001",
            },
            mode="bundle",
            structure_root=None,
            bundle_root=bundle_root,
        )

    with pytest.raises(RequestError) as error:
        _bounded_call(call)
    assert error.value.kind == "invalid_request"


# --- Reviewer probe regressions (issue #44 final): strict structure sub-schema ---


def test_parse_rejects_unknown_structure_key() -> None:
    """Unknown structure sub-keys map to invalid_request, not silent acceptance."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {"structure": {"bogus": 1}},
            mode="recommend",
            structure_root=None,
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"
    assert "bogus" in error.value.message


def test_parse_rejects_both_content_and_path() -> None:
    """Specifying both content and path maps to invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {
                "structure": {
                    "content": _si_structure().to(fmt="cif"),
                    "path": "Si.cif",
                }
            },
            mode="recommend",
            structure_root=Path("/tmp/structures"),
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"
    assert "exactly one" in error.value.message


def test_parse_rejects_format_with_path() -> None:
    """A non-null format alongside path maps to invalid_request."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {"structure": {"path": "Si.cif", "format": "cif"}},
            mode="recommend",
            structure_root=Path("/tmp/structures"),
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"
    assert "format" in error.value.message


def test_parse_accepts_null_format_with_path(structure_root: Path) -> None:
    """An explicit null format with path is accepted (the suffix governs)."""
    request = parse_core_job_request(
        {
            "structure": {"path": "Si.cif", "format": None},
            "hints": {"k_grid": [3, 3, 3]},
        },
        mode="recommend",
        structure_root=structure_root,
        bundle_root=Path("/tmp/bundles"),
    )
    assert request.structure.reduced_formula == "Si"


# --- Reviewer probe regressions (issue #44 final): malformed path strings ---


@pytest.mark.parametrize(
    "path", ["Si\x00.cif", "Si\u0000.cif", "Si\n.cif", "Si\x01.cif", "Si\x7f.cif"]
)
def test_parse_rejects_control_chars_in_structure_path(path: str) -> None:
    """Embedded NUL/control characters in structure.path map to 422, not 400."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {"structure": {"path": path}, "hints": {"k_grid": [3, 3, 3]}},
            mode="recommend",
            structure_root=Path("/tmp/structures"),
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"
    assert "control" in error.value.message


@pytest.mark.parametrize("path", ["run\x00-001", "run\n-001"])
def test_parse_rejects_control_chars_in_output_dir(path: str) -> None:
    """Embedded NUL/control characters in output_dir map to 422."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {
                "structure": {
                    "content": _si_structure().to(fmt="cif"),
                    "format": "cif",
                },
                "output_dir": path,
            },
            mode="bundle",
            structure_root=None,
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"
    assert "control" in error.value.message


# --- Reviewer probe regressions (issue #44 final): redacted 500 mapping ---


def test_parse_unreadable_structure_file_maps_to_confined_failure(
    structure_root: Path, tmp_path: Path
) -> None:
    """EACCES on a structure file is a redacted 500, not a 422 invalid_request."""
    secret = structure_root / "secret.cif"
    secret.write_text(_si_structure().to(fmt="cif"))
    secret.chmod(0o000)
    try:
        with pytest.raises(ConfinedAccessFailure) as error:
            parse_core_job_request(
                {"structure": {"path": "secret.cif"}, "hints": {"k_grid": [3, 3, 3]}},
                mode="recommend",
                structure_root=structure_root,
                bundle_root=tmp_path / "bundles",
            )
    finally:
        secret.chmod(0o600)
    # The host path must not leak into the exception text the 500 handler echoes.
    assert str(structure_root) not in str(error.value)
    assert str(secret) not in str(error.value)


@pytest.mark.parametrize("err", [errno.EACCES, errno.EMFILE, errno.EIO])
def test_raise_confined_oserror_maps_server_failures_to_redacted_500(err: int) -> None:
    """Genuine server filesystem failures raise ConfinedAccessFailure (500)."""
    from goldilocks_core.server.request import _raise_confined_oserror

    with pytest.raises(ConfinedAccessFailure):
        _raise_confined_oserror(
            OSError(err, os.strerror(err), "/host/path/secret"),
            field_name="structure.path",
            display="secret.cif",
        )


@pytest.mark.parametrize(
    "err,kind", [(errno.ENOENT, "not_found"), (errno.ELOOP, "invalid_request")]
)
def test_raise_confined_oserror_maps_client_conditions_to_4xx(
    err: int, kind: str
) -> None:
    """Client path conditions map to deterministic RequestError kinds."""
    from goldilocks_core.server.request import _raise_confined_oserror

    with pytest.raises(RequestError) as error:
        _raise_confined_oserror(
            OSError(err, os.strerror(err)),
            field_name="structure.path",
            display="Si.cif",
        )
    assert error.value.kind == kind


def test_read_confined_file_closes_final_descriptor_when_fstat_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The final descriptor is closed even if ``fstat`` raises after ``open``.

    Regression for the descriptor-cleanup hole: a child opened successfully
    must be closed when the post-open ``fstat`` raises, rather than leaked.
    """
    root = tmp_path / "root"
    root.mkdir()
    (root / "Si.cif").write_text(_si_structure().to(fmt="cif"))

    opened_fds: list[int] = []
    real_fstat = os.fstat
    real_open = os.open

    def raising_fstat(fd: int) -> os.stat_result:
        if fd in opened_fds:
            raise OSError(errno.EIO, "simulated fstat failure")
        return real_fstat(fd)

    def tracking_open(path: str, flags: int, dir_fd: int | None = None) -> int:
        fd = (
            real_open(path, flags, dir_fd=dir_fd)
            if dir_fd is not None
            else real_open(path, flags)
        )
        if dir_fd is not None:
            opened_fds.append(fd)
        return fd

    monkeypatch.setattr(os, "fstat", raising_fstat)
    monkeypatch.setattr(os, "open", tracking_open)
    with pytest.raises(OSError):
        parse_core_job_request(
            {"structure": {"path": "Si.cif"}, "hints": {"k_grid": [3, 3, 3]}},
            mode="recommend",
            structure_root=root,
            bundle_root=tmp_path / "bundles",
        )
    monkeypatch.undo()
    for fd in opened_fds:
        with pytest.raises(OSError, match="Bad file descriptor"):
            real_fstat(fd)


def test_read_confined_file_closes_intermediate_descriptor_when_fstat_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An intermediate descriptor is closed when ``fstat`` raises after ``open``."""
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "Si.cif").write_text(_si_structure().to(fmt="cif"))

    opened_fds: list[int] = []
    real_fstat = os.fstat
    real_open = os.open

    def raising_fstat(fd: int) -> os.stat_result:
        if fd in opened_fds:
            raise OSError(errno.EIO, "simulated fstat failure")
        return real_fstat(fd)

    def tracking_open(path: str, flags: int, dir_fd: int | None = None) -> int:
        fd = (
            real_open(path, flags, dir_fd=dir_fd)
            if dir_fd is not None
            else real_open(path, flags)
        )
        if dir_fd is not None:
            opened_fds.append(fd)
        return fd

    monkeypatch.setattr(os, "fstat", raising_fstat)
    monkeypatch.setattr(os, "open", tracking_open)
    with pytest.raises(OSError):
        parse_core_job_request(
            {"structure": {"path": "sub/Si.cif"}, "hints": {"k_grid": [3, 3, 3]}},
            mode="recommend",
            structure_root=root,
            bundle_root=tmp_path / "bundles",
        )
    monkeypatch.undo()
    for fd in opened_fds:
        with pytest.raises(OSError, match="Bad file descriptor"):
            real_fstat(fd)


# --- Reviewer probe regressions (issue #44 final-2): Unicode path characters ---


@pytest.mark.parametrize(
    "path",
    [
        "run\u0085x",  # C1 NEXT LINE (Cc)
        "run\u00ad-x",  # SOFT HYPHEN (Cf)
        "a\u200bb",  # ZERO WIDTH SPACE (Cf)
        "a\u200db",  # ZERO WIDTH JOINER (Cf)
        "a\ufeffb",  # BOM / ZERO WIDTH NO-BREAK SPACE (Cf)
        "a\u200eb",  # LEFT-TO-RIGHT MARK (Cf)
        "Si\ud800.cif",  # lone surrogate (Cs)
        "Si\udfff.cif",  # lone surrogate (Cs)
    ],
)
def test_parse_rejects_unicode_control_format_surrogate_in_structure_path(
    path: str, structure_root: Path
) -> None:
    """Unicode control/format/surrogate code points in structure.path are 422."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {"structure": {"path": path}, "hints": {"k_grid": [3, 3, 3]}},
            mode="recommend",
            structure_root=structure_root,
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"
    assert "control, format, or surrogate" in error.value.message


@pytest.mark.parametrize(
    "path",
    [
        "run\u0085x",
        "run\u00ad-x",
        "a\u200bb",
        "a\u200db",
        "a\ufeffb",
        "a\u200eb",
        "a\ud800b",
        "a\udfffb",
    ],
)
def test_parse_rejects_unicode_control_format_surrogate_in_output_dir(
    path: str,
) -> None:
    """Unicode control/format/surrogate code points in output_dir are 422."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {
                "structure": {
                    "content": _si_structure().to(fmt="cif"),
                    "format": "cif",
                },
                "output_dir": path,
            },
            mode="bundle",
            structure_root=None,
            bundle_root=Path("/tmp/bundles"),
        )
    assert error.value.kind == "invalid_request"
    assert "control, format, or surrogate" in error.value.message


def test_parse_rejects_lone_surrogate_in_structure_path_before_os_open(
    structure_root: Path, tmp_path: Path
) -> None:
    """A lone surrogate surfaces as a 422 boundary error, never UnicodeEncodeError."""
    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {"structure": {"path": "Si\ud800.cif"}, "hints": {"k_grid": [3, 3, 3]}},
            mode="recommend",
            structure_root=structure_root,
            bundle_root=tmp_path / "bundles",
        )
    assert error.value.kind == "invalid_request"
    # The cause chain must not carry a UnicodeEncodeError from os.open.
    assert not isinstance(error.value.__cause__, UnicodeEncodeError)


# --- Reviewer probe regressions (issue #44 final-2): O_DIRECTORY intermediate opens ---


def test_read_confined_file_opens_intermediate_with_o_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Intermediate confined components are opened with O_DIRECTORY + O_NOFOLLOW.

    The kernel refuses a non-directory (FIFO/device/socket/regular file) with
    ``ENOTDIR`` before any driver ``open`` runs. The leaf regular file is opened
    WITHOUT ``O_DIRECTORY``. Asserted via captured open flags so no special file
    has to be created.
    """
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "Si.cif").write_text(_si_structure().to(fmt="cif"))

    captured: list[tuple[str, int]] = []
    real_open = os.open

    def capturing_open(path: object, flags: int, dir_fd: int | None = None) -> int:
        if dir_fd is not None:
            captured.append((str(path), flags))
        return (
            real_open(path, flags, dir_fd=dir_fd)
            if dir_fd is not None
            else real_open(path, flags)
        )

    monkeypatch.setattr(os, "open", capturing_open)
    parse_core_job_request(
        {"structure": {"path": "sub/Si.cif"}, "hints": {"k_grid": [3, 3, 3]}},
        mode="recommend",
        structure_root=root,
        bundle_root=tmp_path / "bundles",
    )
    monkeypatch.undo()

    flags_by_name = dict(captured)
    assert "sub" in flags_by_name
    assert flags_by_name["sub"] & os.O_DIRECTORY, "intermediate must use O_DIRECTORY"
    assert flags_by_name["sub"] & os.O_NOFOLLOW, "intermediate must use O_NOFOLLOW"
    assert "Si.cif" in flags_by_name
    assert not (flags_by_name["Si.cif"] & os.O_DIRECTORY), (
        "leaf regular file must not use O_DIRECTORY"
    )
    assert flags_by_name["Si.cif"] & os.O_NOFOLLOW, "leaf must use O_NOFOLLOW"


def test_confined_destination_path_opens_intermediate_with_o_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Intermediate bundle-path components are opened with O_DIRECTORY + O_NOFOLLOW."""
    bundle_root = tmp_path / "bundles"
    (bundle_root / "preexisting").mkdir(parents=True)

    captured: list[tuple[str, int]] = []
    real_open = os.open

    def capturing_open(path: object, flags: int, dir_fd: int | None = None) -> int:
        if dir_fd is not None:
            captured.append((str(path), flags))
        return (
            real_open(path, flags, dir_fd=dir_fd)
            if dir_fd is not None
            else real_open(path, flags)
        )

    monkeypatch.setattr(os, "open", capturing_open)
    parse_core_job_request(
        {
            "structure": {
                "content": _si_structure().to(fmt="cif"),
                "format": "cif",
            },
            "output_dir": "preexisting/run-001",
        },
        mode="bundle",
        structure_root=None,
        bundle_root=bundle_root,
    )
    monkeypatch.undo()

    flags_by_name = dict(captured)
    assert "preexisting" in flags_by_name
    assert flags_by_name["preexisting"] & os.O_DIRECTORY
    assert flags_by_name["preexisting"] & os.O_NOFOLLOW
    # The non-existent leaf is also opened O_DIRECTORY (it must be a directory);
    # the bundle stage creates it under the verified parent.
    assert "run-001" in flags_by_name
    assert flags_by_name["run-001"] & os.O_DIRECTORY


def test_confined_destination_path_rejects_intermediate_regular_file(
    tmp_path: Path,
) -> None:
    """An intermediate regular file in output_dir is rejected via kernel ENOTDIR."""
    bundle_root = tmp_path / "bundles"
    bundle_root.mkdir()
    (bundle_root / "file").write_text("not a dir")

    with pytest.raises(RequestError) as error:
        parse_core_job_request(
            {
                "structure": {
                    "content": _si_structure().to(fmt="cif"),
                    "format": "cif",
                },
                "output_dir": "file/run-001",
            },
            mode="bundle",
            structure_root=None,
            bundle_root=bundle_root,
        )
    assert error.value.kind == "invalid_request"
    assert "non-directory" in error.value.message


def test_parse_rejects_socket_intermediate_structure_component_without_blocking(
    structure_root: Path, tmp_path: Path
) -> None:
    """A Unix socket as an intermediate component is rejected without blocking.

    With ``O_DIRECTORY`` the kernel refuses the socket (a non-directory) with
    ``ENOTDIR`` before invoking its driver ``open``, so the worker never blocks.
    """
    import socket

    sock_path = structure_root / "blocked"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(str(sock_path))

        def call() -> object:
            return parse_core_job_request(
                {
                    "structure": {"path": "blocked/Si.cif"},
                    "hints": {"k_grid": [3, 3, 3]},
                },
                mode="recommend",
                structure_root=structure_root,
                bundle_root=tmp_path / "bundles",
            )

        with pytest.raises(RequestError) as error:
            _bounded_call(call)
    finally:
        sock.close()
        sock_path.unlink(missing_ok=True)
    assert error.value.kind == "invalid_request"
    assert "non-directory" in error.value.message


def test_raise_confined_oserror_enotdir_symlink_classifies_as_symlink(
    tmp_path: Path,
) -> None:
    """ENOTDIR from an O_DIRECTORY open of a symlink keeps the symlink message."""
    from goldilocks_core.server.request import _raise_confined_oserror

    parent = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    try:
        with pytest.raises(RequestError) as error:
            _raise_confined_oserror(
                OSError(errno.ENOTDIR, os.strerror(errno.ENOTDIR)),
                field_name="output_dir",
                display="link/run-001",
                parent_fd=parent,
                part="link",
            )
    finally:
        os.close(parent)
    assert error.value.kind == "invalid_request"
    assert "symlink" in error.value.message


def test_raise_confined_oserror_enotdir_regular_file_classifies_as_non_directory(
    tmp_path: Path,
) -> None:
    """ENOTDIR from an O_DIRECTORY open of a regular file is a non-directory."""
    from goldilocks_core.server.request import _raise_confined_oserror

    parent = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    regular = tmp_path / "file"
    regular.write_text("x")
    try:
        with pytest.raises(RequestError) as error:
            _raise_confined_oserror(
                OSError(errno.ENOTDIR, os.strerror(errno.ENOTDIR)),
                field_name="output_dir",
                display="file/run-001",
                parent_fd=parent,
                part="file",
            )
    finally:
        os.close(parent)
    assert error.value.kind == "invalid_request"
    assert "non-directory" in error.value.message
