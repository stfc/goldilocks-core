from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from pymatgen.core import Structure

from goldilocks_core.assets import AssetStore
from goldilocks_core.contracts.registry import RECORD_TYPE_IDS
from goldilocks_core.examples import structure
from goldilocks_core.pseudo.registry import load_tables
from goldilocks_core.runtime import (
    GraphHandler,
    Preset,
    Runtime,
    Service,
    Stage,
    TaskGraph,
)


@dataclass(frozen=True, slots=True)
class CustomSummary:
    value: str


@pytest.fixture
def installed_pseudo_metadata() -> tuple[PseudoMetadata, ...]:
    """Return metadata sufficient to render a silicon QE input."""
    return (
        PseudoMetadata(
            filepath="/pseudo/Si.UPF",
            filename="Si.UPF",
            header_format="attr",
            element="Si",
            pseudo_type="NC",
            functional="PBEsol",
            relativistic="scalar",
            z_valence=4.0,
            cutoffs=PseudoCutoffs(ecutwfc_ry=30.0, ecutrho_ry=120.0),
        ),
    )


@pytest.fixture(autouse=True)
def installed_pseudos(
    monkeypatch: pytest.MonkeyPatch, installed_pseudo_metadata
) -> None:
    """Resolve the server's installed pseudo source without a real store."""
    monkeypatch.setattr(
        "goldilocks_core.runtime.scf.source_for_request",
        lambda request, *, store, registry_path: (
            lambda structure, requirements: installed_pseudo_metadata
        ),
    )


@pytest.fixture
def sample_structure_path() -> str:
    return str(structure("Si.cif"))


@pytest.fixture
def sample_structure_text(sample_structure_path: str) -> str:
    return Structure.from_file(sample_structure_path).to(fmt="cif")


@pytest.fixture
def pseudo_metadata(tmp_path) -> dict[str, object]:
    pseudo_path = tmp_path / "Si.UPF"
    content = b"<UPF version='2.0.1'>server fixture</UPF>\n"
    pseudo_path.write_bytes(content)
    return {
        "filepath": str(pseudo_path),
        "filename": "Si.UPF",
        "header_format": "attr",
        "provider": "sssp",
        "accuracy": "efficiency",
        "element": "Si",
        "pseudo_type": "NC",
        "functional": "PBEsol",
        "relativistic": "scalar",
        "z_valence": 4.0,
        "cutoffs": {
            "ecutwfc_ry": 30.0,
            "ecutrho_ry": 120.0,
        },
        "source_identifier": "synthetic/Si.UPF",
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "content_size_bytes": len(content),
        "pseudo_info": {
            "licence": "CC-BY-4.0",
            "licence_text": "Synthetic server fixture licence\n",
            "citation": "Synthetic server fixture pseudopotential.",
        },
    }


@pytest.fixture
def request_body(
    sample_structure_path: str, pseudo_metadata: dict[str, object]
) -> dict[str, object]:
    return {
        "structure": sample_structure_path,
        "hints": {"k_grid": [3, 3, 3]},
    }


@pytest.fixture
def test_service() -> Iterator[Service]:
    service = Service()
    yield service
    service.close()


@pytest.fixture
def custom_record_service() -> Iterator[Service]:
    registered = dict(RECORD_TYPE_IDS)
    handler = GraphHandler(
        spec=TaskGraph(
            task="custom_task",
            stages=(
                Stage(
                    CustomSummary,
                    (),
                    lambda *, ctx: CustomSummary("custom result"),
                    id="custom_summary",
                    name="Custom summary",
                ),
            ),
            presets=(Preset("summary", (CustomSummary,)),),
            selectable_outputs=(CustomSummary,),
            record_ids=((CustomSummary, "custom_summary"),),
        ),
        build_context=lambda request, normalized, runtime: None,
    )
    service = Service(task_handlers=(handler,))
    try:
        yield service
    finally:
        service.close()
        RECORD_TYPE_IDS.clear()
        RECORD_TYPE_IDS.update(registered)


@pytest.fixture
def publishable_service(tmp_path) -> Iterator[Service]:
    sources = tmp_path / "asset-sources"
    sources.mkdir()
    pseudo = sources / "Si.UPF"
    pseudo.write_bytes(b"<UPF version='2.0.1'>HTTP fixture</UPF>\n")
    licence = sources / "LICENSE.txt"
    licence.write_text("Fixture licence\n", encoding="utf-8")
    manifest = sources / "pseudo-table.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "fixture-table",
                "version": "1",
                "provider": "sssp",
                "functional": "PBEsol",
                "accuracy": "efficiency",
                "relativistic": "scalar",
                "licence": "Fixture-Licence",
                "citation": "Fixture pseudopotential citation.",
                "entries": [
                    {
                        "element": "Si",
                        "path": "pseudos/Si.UPF",
                        "md5": hashlib.md5(pseudo.read_bytes()).hexdigest(),
                        "header_format": "attr",
                        "pseudo_type": "NC",
                        "z_valence": 4.0,
                        "ecutwfc_ry": 30.0,
                        "ecutrho_ry": 120.0,
                        "source_identifier": "fixture/Si.UPF",
                        "frozen_4f_core": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = tmp_path / "pseudos.toml"
    registry.write_text(
        f'''[tables.fixture-table]
provider = "sssp"
upstream_table = "fixture"
version = "1"
functional = "PBEsol"
relativistic = "scalar"
accuracy = "efficiency"
licence = "Fixture-Licence"
citation = "Fixture pseudopotential citation."
elements = ["Si"]
default = true

[[tables.fixture-table.files]]
role = "pseudopotentials"
path = "pseudos/Si.UPF"
url = "{pseudo.as_uri()}"

[[tables.fixture-table.files]]
role = "metadata"
path = "pseudo-table.json"
url = "{manifest.as_uri()}"

[[tables.fixture-table.files]]
role = "licence"
path = "LICENSE.txt"
url = "{licence.as_uri()}"
''',
        encoding="utf-8",
    )
    store = AssetStore(tmp_path / "assets")
    store.install(load_tables(registry)["fixture-table"].asset)
    runtime = Runtime(asset_store=store, pseudo_registry_path=registry)
    service = Service(runtime)
    yield service
    service.close()
    runtime.close()
