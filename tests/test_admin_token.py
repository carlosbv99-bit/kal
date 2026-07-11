from __future__ import annotations

import stat

from utils.admin_token import get_or_create_admin_token


def test_creates_a_token_file_if_missing(tmp_path):
    token_path = tmp_path / "keys" / "admin_token"
    token = get_or_create_admin_token(token_path)

    assert token_path.exists()
    assert token_path.read_text(encoding="utf-8").strip() == token
    assert len(token) > 20


def test_reuses_the_same_token_on_subsequent_calls(tmp_path):
    token_path = tmp_path / "admin_token"

    first = get_or_create_admin_token(token_path)
    second = get_or_create_admin_token(token_path)

    assert first == second


def test_token_file_is_only_readable_by_owner(tmp_path):
    token_path = tmp_path / "admin_token"
    get_or_create_admin_token(token_path)

    mode = stat.S_IMODE(token_path.stat().st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR
