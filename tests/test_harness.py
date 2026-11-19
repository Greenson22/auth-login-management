import os
from pathlib import Path
import signal

import pytest

from tests.fakes import (
    INTEGRATION_ENV_VAR,
    KeyringLockedError,
    KeyringUnavailableError,
    OAuthErrorStub,
    ProcTableUnreadableError,
    decode_id_token_email,
    integration_enabled,
)


def test_fake_root_isolates_home_cwd_and_xdg(fake_root):
  assert Path.home() == fake_root.home
  assert Path.cwd() == fake_root.work
  assert os.environ["XDG_CONFIG_HOME"] == str(fake_root.config)
  assert os.environ["XDG_STATE_HOME"] == str(fake_root.state)
  assert not fake_root.gemini_dir.exists()
  assert not fake_root.database_file.exists()


def test_default_repo_database_is_never_used(fake_root):
  """Path relatif default harus jatuh di cwd sementara, bukan repo."""
  default_db = Path("accounts_manager.db").resolve()

  assert default_db.is_relative_to(fake_root.work)
  assert not default_db.exists()


def test_fake_keyring_roundtrip_and_failure_modes(fake_keyring):
  assert fake_keyring.read("gemini", "antigravity") is None

  fake_keyring.write("gemini", "antigravity", b'{"email":"a@example.com"}')

  assert fake_keyring.read("gemini", "antigravity") == b'{"email":"a@example.com"}'
  assert fake_keyring.writes == [
      ("gemini", "antigravity", b'{"email":"a@example.com"}')
  ]

  fake_keyring.delete("gemini", "antigravity")
  assert fake_keyring.read("gemini", "antigravity") is None

  fake_keyring.locked = True

  with pytest.raises(KeyringLockedError):
    fake_keyring.read("gemini", "antigravity")

  fake_keyring.locked = False
  fake_keyring.available = False

  with pytest.raises(KeyringUnavailableError):
    fake_keyring.write("gemini", "antigravity", b"x")


def test_fake_proc_table_reads_cmdline_state_and_unreadable(fake_proc):
  fake_proc.add(4242, ["/usr/bin/agy", "remote-control"], state="T")

  assert fake_proc.pids() == [4242]
  assert fake_proc.read_cmdline(4242) == ["/usr/bin/agy", "remote-control"]
  assert fake_proc.read_state(4242) == "T"

  fake_proc.readable = False

  with pytest.raises(ProcTableUnreadableError):
    fake_proc.read_cmdline(4242)


def test_fake_proc_table_materializes_a_fake_proc_tree(fake_root, fake_proc):
  fake_proc.add(7, ["/usr/bin/agy"], state="R")

  fake_proc.write_to(fake_root.proc)

  cmdline = (fake_root.proc / "7" / "cmdline").read_bytes()
  assert cmdline == b"/usr/bin/agy\0"
  assert " R " in (fake_root.proc / "7" / "stat").read_text(encoding="utf-8")


def test_fake_signals_follow_stopped_process_state(fake_proc, fake_signals):
  fake_proc.add(99, ["/usr/bin/agy"], state="T")

  fake_signals.send(99, signal.SIGCONT)
  assert fake_proc.read_state(99) == "S"

  fake_signals.send(99, signal.SIGTERM)
  assert fake_proc.read_state(99) == "Z"
  assert fake_signals.sent == [
      (99, signal.SIGCONT),
      (99, signal.SIGTERM),
  ]


def test_fake_oauth_returns_matching_email_and_records_call(fake_oauth):
  fake_oauth.respond_for("user@example.com", refresh_token="new-refresh")

  response = fake_oauth.exchange_refresh_token("old-refresh")

  assert response.access_token == "ya29.fake-access-token"
  assert response.refresh_token == "new-refresh"
  assert decode_id_token_email(response.id_token) == "user@example.com"
  assert fake_oauth.calls == [{"refresh_token": "old-refresh"}]


def test_fake_oauth_can_emit_google_error(fake_oauth):
  fake_oauth.fail_with("invalid_grant", "Token has been revoked")

  with pytest.raises(OAuthErrorStub) as exc_info:
    fake_oauth.exchange_refresh_token("dead-refresh")

  assert exc_info.value.code == "invalid_grant"


def test_fake_clock_only_moves_when_advanced(fake_clock):
  start_wall = fake_clock.now()
  start_monotonic = fake_clock.monotonic()

  fake_clock.sleep(0.1)

  assert fake_clock.now() == pytest.approx(start_wall + 0.1)
  assert fake_clock.monotonic() == pytest.approx(start_monotonic + 0.1)


def test_integration_marker_is_registered(pytestconfig):
  markers = "\n".join(pytestconfig.getini("markers"))
  assert "integration:" in markers


def test_integration_flag_requires_explicit_env(monkeypatch):
  monkeypatch.delenv(INTEGRATION_ENV_VAR, raising=False)
  assert integration_enabled() is False

  monkeypatch.setenv(INTEGRATION_ENV_VAR, "1")
  assert integration_enabled() is True
