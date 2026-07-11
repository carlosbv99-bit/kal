"""
Tests del historial de versiones generalizado de
agent_core/self_modification.py (list_versions/rollback_to), que
complementa a apply()/rollback() (ver test_self_modification.py) para
poder volver a una versión específica del historial, no solo a la
última aplicada.

Misma estrategia de proyecto sintético (`fake_project`) que
test_self_modification.py, para no correr el test suite real de kal/
dos veces por test.
"""
from __future__ import annotations

import pytest

from agent_core.self_modification import SelfModificationManager
from utils.config import settings


@pytest.fixture(autouse=True)
def _enabled_by_default(monkeypatch):
    """Ver test_self_modification.py: self_modification.enabled default es False."""
    monkeypatch.setattr(settings.self_modification, "enabled", True)


@pytest.fixture
def fake_project(tmp_path):
    (tmp_path / "mymodule.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "test_mymodule.py").write_text(
        "from mymodule import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def manager(fake_project):
    return SelfModificationManager(project_root=fake_project)


def _propose_and_apply(manager, source: str, justification: str = "cambio"):
    proposal = manager.propose(target_path="mymodule.py", proposed_source=source, justification=justification)
    assert proposal.status == "pending_human_approval"
    manager.apply(proposal.id, approved_by="kalin")
    return proposal


def test_no_versions_before_any_apply(manager):
    assert manager.list_versions("mymodule.py") == []


def test_each_apply_appends_a_version(manager):
    _propose_and_apply(manager, "def add(a, b):\n    return a + b  # v2\n")
    _propose_and_apply(manager, "def add(a, b):\n    return a + b  # v3\n")

    versions = manager.list_versions("mymodule.py")
    assert [v["version"] for v in versions] == [1, 2]


def test_rollback_to_restores_content_of_that_version(manager, fake_project):
    original_content = (fake_project / "mymodule.py").read_text(encoding="utf-8")

    _propose_and_apply(manager, "def add(a, b):\n    return a + b  # v2\n")
    _propose_and_apply(manager, "def add(a, b):\n    return a + b  # v3\n")

    # version 1 = backup tomado ANTES del primer apply, es decir el
    # contenido original del archivo.
    manager.rollback_to("mymodule.py", version=1, reason="volver al original")

    real_file = fake_project / "mymodule.py"
    assert real_file.read_text(encoding="utf-8") == original_content


def test_rollback_to_unknown_version_raises(manager):
    _propose_and_apply(manager, "def add(a, b):\n    return a + b  # v2\n")

    with pytest.raises(ValueError):
        manager.rollback_to("mymodule.py", version=99, reason="no existe")


def test_version_history_is_isolated_per_target_path(manager, fake_project):
    (fake_project / "othermodule.py").write_text("VALUE = 1\n", encoding="utf-8")

    _propose_and_apply(manager, "def add(a, b):\n    return a + b  # v2\n")

    other_proposal = manager.propose(
        target_path="othermodule.py", proposed_source="VALUE = 2\n", justification="cambio"
    )
    manager.apply(other_proposal.id, approved_by="kalin")

    assert len(manager.list_versions("mymodule.py")) == 1
    assert len(manager.list_versions("othermodule.py")) == 1
