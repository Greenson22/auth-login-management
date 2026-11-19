"""Integration test opt-in: keyring Linux asli.

Hanya berjalan bila ``AUTH_MANAGER_RUN_INTEGRATION=1``. Test memakai item
sementara ``service=selftest`` lewat ``secret-tool`` (dependensi sistem
opsional) dan tidak pernah menyentuh item ``gemini``.
"""

import shutil
import subprocess
import uuid

import pytest

pytestmark = pytest.mark.integration

SERVICE = "selftest"


def _secret_tool(*args: str, input_bytes: bytes | None = None) -> bytes:
  return subprocess.run(
      ["secret-tool", *args],
      input=input_bytes,
      check=True,
      capture_output=True,
  ).stdout


def test_real_keyring_selftest_item_roundtrip():
  if shutil.which("secret-tool") is None:
    pytest.skip("secret-tool tidak terpasang (dependensi sistem opsional)")

  username = f"selftest-{uuid.uuid4().hex}"
  attributes = ("service", SERVICE, "username", username)
  payload = b'{"ok":true}'
  stored = False

  try:
    try:
      _secret_tool(
          "store",
          "--label",
          f"auth-login-management selftest {username}",
          *attributes,
          input_bytes=payload,
      )
      stored = True
    except subprocess.CalledProcessError as exc:
      detail = exc.stderr.decode(errors="replace").strip()
      pytest.skip(f"Secret Service tidak tersedia/terkunci: {detail}")

    result = _secret_tool("lookup", *attributes)
    assert result == payload
  finally:
    if stored:
      subprocess.run(
          ["secret-tool", "clear", *attributes],
          check=False,
          capture_output=True,
      )
