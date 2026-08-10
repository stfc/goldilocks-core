"""Tests for PseudoDojo table installation. No test here touches the network."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile

import pytest

from goldilocks_core.artifacts import cache, pseudodojo

TABLE = "nc-sr-04_pbesol_standard"
PSEUDOS = {"Si": b"UPF for silicon", "Ge": b"UPF for germanium"}


def _archive(members: dict[str, bytes]) -> bytes:
    """Build a .tgz in memory, as pseudo-dojo.org serves."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _reports(pseudos=None, hints=True, digest_key="md5_upf") -> dict[str, bytes]:
    """Build dojo reports describing ``pseudos``."""
    reports = {}
    for element, payload in (pseudos or PSEUDOS).items():
        report = {"symbol": element, "pseudo_type": "NC"}
        if digest_key:
            report[digest_key] = hashlib.md5(payload).hexdigest()
        if hints:
            report["hints"] = {
                "low": {"ecut": 14.0},
                "normal": {"ecut": 18.0},
                "high": {"ecut": 24.0},
            }
        reports[f"{element}.djrepo"] = json.dumps(report).encode()
    return reports


class _Response:
    def __init__(self, payload=b"", headers=None):
        self._payload = payload
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def iter_content(self, size):
        for start in range(0, len(self._payload), size):
            yield self._payload[start : start + size]

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _FakeSite:
    """Serves the two archives of one table, and records every call."""

    def __init__(self, upf_members=None, report_members=None):
        self.upf = _archive(upf_members if upf_members is not None else _upf_members())
        self.reports = _archive(
            report_members if report_members is not None else _reports()
        )
        self.urls: list[str] = []

    def get(self, url, **_kwargs):
        self.urls.append(url)
        return _Response(payload=self.reports if "_djrepo" in url else self.upf)

    def head(self, url, **_kwargs):
        self.urls.append(f"HEAD {url}")
        body = self.reports if "_djrepo" in url else self.upf
        return _Response(headers={"Content-Length": str(len(body))})


def _upf_members() -> dict[str, bytes]:
    return {f"{element}.upf": payload for element, payload in PSEUDOS.items()}


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch, tmp_path):
    monkeypatch.setenv(cache.CACHE_ENV, str(tmp_path / "cache"))


def test_both_archive_urls_derive_from_one_table_identifier():
    upf_url, djrepo_url = pseudodojo.archive_urls(TABLE)

    assert upf_url == f"{pseudodojo.PSEUDO_DOJO_BASE}/{TABLE}_upf.tgz"
    assert djrepo_url == f"{pseudodojo.PSEUDO_DOJO_BASE}/{TABLE}_djrepo.tgz"


def test_describe_reports_transfer_size_without_transferring():
    site = _FakeSite()

    described = pseudodojo.describe(TABLE, http=site)

    assert described.upf_bytes == len(site.upf)
    assert described.djrepo_bytes == len(site.reports)
    assert described.total_bytes == len(site.upf) + len(site.reports)
    assert all(url.startswith("HEAD ") for url in site.urls)


def test_install_uses_the_layout_selection_derives_from(tmp_path):
    site = _FakeSite()

    installed = pseudodojo.install(TABLE, http=site)

    assert installed.name == f"{TABLE}_upf"
    assert installed.parent.name == pseudodojo.LIBRARY
    assert sorted(p.name for p in installed.glob("*.upf")) == ["Ge.upf", "Si.upf"]
    assert (installed / "Si.upf").read_bytes() == PSEUDOS["Si"]


def test_install_keeps_the_dojo_reports_for_cutoff_extraction():
    site = _FakeSite()

    installed = pseudodojo.install(TABLE, http=site)
    reports = installed.parent / f"{TABLE}_djrepo"

    assert sorted(p.name for p in reports.glob("*.djrepo")) == [
        "Ge.djrepo",
        "Si.djrepo",
    ]
    assert (
        json.loads((reports / "Si.djrepo").read_text())["hints"]["normal"]["ecut"]
        == 18.0
    )


def test_install_fetches_the_reports_before_the_pseudopotentials():
    """Expected digests must be known before a single pseudopotential is written."""
    site = _FakeSite()

    pseudodojo.install(TABLE, http=site)

    assert "_djrepo" in site.urls[0]
    assert "_upf" in site.urls[1]


def test_install_rejects_a_pseudopotential_that_fails_its_published_digest():
    site = _FakeSite(upf_members={"Si.upf": b"tampered", "Ge.upf": PSEUDOS["Ge"]})

    with pytest.raises(cache.ChecksumMismatch, match="Si.upf"):
        pseudodojo.install(TABLE, http=site)


def test_install_rejects_a_table_missing_an_element_its_reports_describe():
    site = _FakeSite(upf_members={"Si.upf": PSEUDOS["Si"]})

    with pytest.raises(pseudodojo.TableIncomplete, match="Ge"):
        pseudodojo.install(TABLE, http=site)


def test_install_rejects_a_pseudopotential_with_no_report_to_verify_it():
    site = _FakeSite(report_members=_reports(pseudos={"Si": PSEUDOS["Si"]}))

    with pytest.raises(pseudodojo.TableIncomplete, match="no dojo report"):
        pseudodojo.install(TABLE, http=site)


def test_install_rejects_a_report_that_publishes_no_upf_digest():
    site = _FakeSite(report_members=_reports(digest_key=None))

    with pytest.raises(pseudodojo.TableIncomplete, match="md5_upf"):
        pseudodojo.install(TABLE, http=site)


def test_install_serves_an_installed_table_without_any_request():
    site = _FakeSite()
    pseudodojo.install(TABLE, http=site)
    calls_after_first_install = len(site.urls)

    again = pseudodojo.install(TABLE, http=site)

    assert sorted(p.name for p in again.glob("*.upf")) == ["Ge.upf", "Si.upf"]
    assert len(site.urls) == calls_after_first_install


def test_install_honours_an_explicit_root(tmp_path):
    site = _FakeSite()
    root = tmp_path / "shared-pseudos"

    installed = pseudodojo.install(TABLE, root=root, http=site)

    assert installed == root / pseudodojo.LIBRARY / f"{TABLE}_upf"


def test_install_writes_a_cutoff_sidecar_where_discovery_looks_for_it():
    """Selection finds `<source_set>.json` beside the UPF directory it names."""
    site = _FakeSite()

    installed = pseudodojo.install(TABLE, http=site)
    sidecar = installed.parent / f"{TABLE}_upf.json"

    assert sidecar.exists()


def test_the_sidecar_converts_hartree_to_rydberg_at_the_default_dual():
    site = _FakeSite()

    installed = pseudodojo.install(TABLE, http=site)
    sidecar = json.loads((installed.parent / f"{TABLE}_upf.json").read_text())

    assert sidecar["Si"]["cutoff_wfc"] == 24.0 * pseudodojo.HARTREE_TO_RYDBERG
    assert sidecar["Si"]["cutoff_rho"] == (
        24.0 * pseudodojo.HARTREE_TO_RYDBERG * pseudodojo.DEFAULT_DUAL
    )


def test_the_sidecar_takes_the_high_hint_not_normal_or_low():
    """Core always recommends the converged cutoff, not the cheapest that might do."""
    site = _FakeSite()

    installed = pseudodojo.install(TABLE, http=site)
    sidecar = json.loads((installed.parent / f"{TABLE}_upf.json").read_text())

    assert sidecar["Si"]["cutoff_wfc"] != 14.0 * pseudodojo.HARTREE_TO_RYDBERG
    assert sidecar["Si"]["cutoff_wfc"] != 18.0 * pseudodojo.HARTREE_TO_RYDBERG


def test_an_element_with_no_high_hint_is_omitted_rather_than_fabricated():
    """Missing from the sidecar reads as uncovered; a fabricated cutoff would not."""
    reports = _reports()
    without_high = json.loads(reports["Ge.djrepo"])
    del without_high["hints"]["high"]
    reports["Ge.djrepo"] = json.dumps(without_high).encode()
    site = _FakeSite(report_members=reports)

    installed = pseudodojo.install(TABLE, http=site)
    sidecar = json.loads((installed.parent / f"{TABLE}_upf.json").read_text())

    assert "Si" in sidecar
    assert "Ge" not in sidecar


def test_the_sidecar_makes_the_installed_table_generate_a_usable_input():
    """End-to-end: cutoff discovery reads what install() just wrote."""
    from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

    real_upf = (
        '<UPF><PP_HEADER element="Si" pseudo_type="NC" functional="PBEsol" '
        'relativistic="scalar" z_valence="4.0" /></UPF>'
    ).encode()
    by_element = {"Si": real_upf, "Ge": real_upf}
    upf_members = {f"{element}.upf": payload for element, payload in by_element.items()}
    site = _FakeSite(
        upf_members=upf_members, report_members=_reports(pseudos=by_element)
    )
    installed = pseudodojo.install(TABLE, http=site)

    metadata = load_pseudo_metadata(installed.parent.parent)
    si = next(m for m in metadata if m.element == "Si")

    assert si.is_sssp is False
    assert si.sssp_recommended_cutoff == {
        "ecutwfc_ry": 24.0 * pseudodojo.HARTREE_TO_RYDBERG,
        "ecutrho_ry": 24.0 * pseudodojo.HARTREE_TO_RYDBERG * pseudodojo.DEFAULT_DUAL,
    }
