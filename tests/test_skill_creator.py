"""
Tests de agent_core/skill_creator.py — el pipeline propose/approve/
reject de una Skill nueva propuesta por el agente.

Usa directorios aislados (tmp_path) para staging/skills/keys, nunca los
reales del proyecto (data/proposed_skills/, skills/, data/keys/) —
mismo criterio que tests/test_self_modification.py con su
`fake_project`.
"""
from __future__ import annotations

import pytest
import yaml

from agent_core.skill_creator import SkillCreatorManager, SkillProposalRejectedError
from kernel.registry.skill_signing import verify_skill_signature

_VALID_CODE = (
    "from sdk.skill import Tool\n"
    "from sdk.artifacts import Artifact\n\n\n"
    "class WebScraperTool(Tool):\n"
    "    def execute(self, **kwargs):\n"
    "        return Artifact(modality='text', uri='', metadata={'summary': 'ok'})\n"
)


@pytest.fixture
def manager(tmp_path):
    return SkillCreatorManager(
        staging_root=tmp_path / "proposed_skills",
        skills_root=tmp_path / "skills",
        key_dir=tmp_path / "keys",
    )


def _propose(manager, **overrides):
    kwargs = {
        "name": "web_scraper",
        "description": "Descarga y extrae texto de una URL",
        "class_name": "WebScraperTool",
        "code": _VALID_CODE,
        "justification": "Se pidió esto varias veces en la conversación",
    }
    kwargs.update(overrides)
    return manager.propose(**kwargs)


# --- propose() ---


def test_propose_creates_staging_dir_with_manifest_and_code(manager):
    proposal = _propose(manager)

    staging_dir = manager.staging_root / proposal.id
    assert staging_dir.exists()
    assert (staging_dir / "tool.py").read_text(encoding="utf-8") == _VALID_CODE

    manifest = yaml.safe_load((staging_dir / "skill.yaml").read_text(encoding="utf-8"))
    assert manifest["name"] == "web_scraper"
    assert manifest["entry_point"] == "tool:WebScraperTool"
    assert manifest["enabled"] is False  # nunca true al proponer, bajo ninguna circunstancia


def test_propose_status_is_pending_human_approval(manager):
    proposal = _propose(manager)
    assert proposal.status == "pending_human_approval"


def test_propose_rejects_invalid_name(manager):
    for bad_name in ("WebScraper", "web-scraper", "../etc", "1_web_scraper", ""):
        with pytest.raises(SkillProposalRejectedError):
            _propose(manager, name=bad_name)


def test_propose_rejects_name_colliding_with_an_existing_real_skill(manager):
    (manager.skills_root / "web_scraper").mkdir(parents=True)
    with pytest.raises(SkillProposalRejectedError, match="Ya existe una skill instalada"):
        _propose(manager)


def test_propose_rejects_a_duplicate_pending_proposal_name(manager):
    _propose(manager)
    with pytest.raises(SkillProposalRejectedError, match="Ya hay una propuesta pendiente"):
        _propose(manager)


def test_propose_allows_reusing_a_name_after_the_first_proposal_is_rejected(manager):
    first = _propose(manager)
    manager.reject(first.id)
    # No debería quedar bloqueado — la propuesta anterior ya no está pendiente.
    second = _propose(manager)
    assert second.name == "web_scraper"


def test_propose_rejects_invalid_class_name(manager):
    with pytest.raises(SkillProposalRejectedError):
        _propose(manager, class_name="not a valid identifier")


def test_propose_rejects_syntactically_invalid_code(manager):
    with pytest.raises(SkillProposalRejectedError, match="no es Python válido"):
        _propose(manager, code="def foo(:\n    pass")


def test_propose_rejects_an_invalid_permission(manager):
    with pytest.raises(SkillProposalRejectedError, match="Permiso inválido"):
        _propose(manager, permissions=["network", "root_access"])


def test_propose_accepts_a_valid_known_permission(manager):
    proposal = _propose(manager, permissions=["network"])
    assert proposal.permissions == ["network"]


def test_propose_is_audited(manager):
    from audit.audit_log import audit_log

    _propose(manager)
    entries = audit_log.tail(5)
    assert any(e["event_type"] == "skill_proposed" and e["outcome"] == "pending" for e in entries)


# --- approve() ---


def test_approve_installs_into_skills_root_and_removes_staging(manager):
    proposal = _propose(manager)
    manager.approve(proposal.id, approved_by="kalin")

    final_dir = manager.skills_root / "web_scraper"
    assert final_dir.exists()
    assert (final_dir / "tool.py").exists()
    assert not (manager.staging_root / proposal.id).exists()


def test_approve_signs_the_installed_skill(manager):
    proposal = _propose(manager)
    manager.approve(proposal.id, approved_by="kalin")

    final_dir = manager.skills_root / "web_scraper"
    assert verify_skill_signature(final_dir) == "verified"


def test_approve_keeps_enabled_false(manager):
    proposal = _propose(manager)
    manager.approve(proposal.id, approved_by="kalin")

    final_dir = manager.skills_root / "web_scraper"
    manifest = yaml.safe_load((final_dir / "skill.yaml").read_text(encoding="utf-8"))
    assert manifest["enabled"] is False


def test_approve_sets_status_and_returns_it(manager):
    proposal = _propose(manager)
    approved = manager.approve(proposal.id, approved_by="kalin")
    assert approved.status == "approved"


def test_approve_unknown_id_raises(manager):
    with pytest.raises(ValueError, match="No existe"):
        manager.approve("no-existe", approved_by="kalin")


def test_approve_twice_raises(manager):
    proposal = _propose(manager)
    manager.approve(proposal.id, approved_by="kalin")
    with pytest.raises(ValueError, match="no está pendiente"):
        manager.approve(proposal.id, approved_by="kalin")


def test_approve_fails_if_a_real_skill_with_the_same_name_appeared_meanwhile(manager):
    proposal = _propose(manager)
    # Simula que, entre proponer y aprobar, alguien instaló a mano (o vía
    # market) una skill real con el mismo nombre.
    (manager.skills_root / "web_scraper").mkdir(parents=True)
    with pytest.raises(ValueError, match="no se puede aprobar sin conflicto"):
        manager.approve(proposal.id, approved_by="kalin")


def test_approve_is_audited_as_success(manager):
    from audit.audit_log import audit_log

    proposal = _propose(manager)
    manager.approve(proposal.id, approved_by="kalin")
    entries = audit_log.tail(5)
    assert any(
        e["event_type"] == "skill_proposed" and e["outcome"] == "success"
        and e["context"].get("approved_by") == "kalin"
        for e in entries
    )


# --- reject() ---


def test_reject_removes_staging_dir_without_touching_skills_root(manager):
    proposal = _propose(manager)
    manager.reject(proposal.id, reason="no hace falta")

    assert not (manager.staging_root / proposal.id).exists()
    assert not (manager.skills_root / "web_scraper").exists()


def test_reject_sets_status_and_detail(manager):
    proposal = _propose(manager)
    rejected = manager.reject(proposal.id, reason="ya existe algo parecido")
    assert rejected.status == "rejected"
    assert rejected.detail == "ya existe algo parecido"


def test_reject_unknown_id_raises(manager):
    with pytest.raises(ValueError, match="No existe"):
        manager.reject("no-existe")


def test_reject_is_audited_as_failure(manager):
    from audit.audit_log import audit_log

    proposal = _propose(manager)
    manager.reject(proposal.id, reason="motivo de prueba")
    entries = audit_log.tail(5)
    assert any(
        e["event_type"] == "skill_proposed" and e["outcome"] == "failure"
        and e["context"].get("reason") == "motivo de prueba"
        for e in entries
    )


# --- list_proposals() / get() ---


def test_list_proposals_most_recent_first(manager):
    first = _propose(manager)
    second = _propose(manager, name="another_skill")
    listed = manager.list_proposals()
    assert [p.id for p in listed] == [second.id, first.id]


def test_get_returns_none_for_unknown_id(manager):
    assert manager.get("no-existe") is None


def test_get_returns_the_proposal(manager):
    proposal = _propose(manager)
    assert manager.get(proposal.id) is proposal


# --- Punta a punta con el loader real de skills ---


def test_an_approved_proposal_is_seen_by_the_real_skill_loader_as_disabled(manager):
    """
    No alcanza con que approve() no explote — la prueba real es que
    kernel/registry/skills.py::load_skills() (el mismo loader que usa
    kal en producción) vea la skill instalada exactamente como
    cualquier otra skill deshabilitada: ni una línea de su código se
    importa, y load_skills() ni siquiera llega a verificar la firma
    (se corta antes, por enabled=False) — eso es justamente lo que
    garantiza que aprobar una propuesta no la active sola.
    """
    from kernel.registry.registry import ToolRegistry
    from kernel.registry.skills import load_skills

    proposal = _propose(manager)
    manager.approve(proposal.id, approved_by="kalin")

    registry = ToolRegistry()
    statuses = load_skills(registry, manager.skills_root)

    web_scraper_status = next(s for s in statuses if s.manifest and s.manifest.name == "web_scraper")
    assert web_scraper_status.status == "disabled"
    assert web_scraper_status.manifest.enabled is False
    assert "web_scraper" not in [t["name"] for t in registry.list_active()]


def test_habilitarla_aparte_recien_ahi_la_deja_cargar_con_firma_verificada(manager):
    """
    Cierra el ciclo completo: aprobar SOLO instala y firma — un segundo
    gate independiente (set_skill_enabled(), lo mismo que hace
    scripts/enable_skill.py a mano) es el que de verdad la activa. Solo
    ENTONCES load_skills() llega a verificar la firma.
    """
    from kernel.registry.registry import ToolRegistry
    from kernel.registry.skills import load_skills, set_skill_enabled

    proposal = _propose(manager)
    manager.approve(proposal.id, approved_by="kalin")
    final_dir = manager.skills_root / "web_scraper"

    set_skill_enabled(final_dir, True)

    registry = ToolRegistry()
    statuses = load_skills(registry, manager.skills_root)
    web_scraper_status = next(s for s in statuses if s.manifest and s.manifest.name == "web_scraper")

    assert web_scraper_status.status == "loaded"
    assert web_scraper_status.signature_status == "verified"
    assert "web_scraper" in [t["name"] for t in registry.list_active()]
