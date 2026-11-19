import os

# Harus diset sebelum QApplication pertama dibuat. Test widget tidak boleh
# membutuhkan display nyata.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest

from tests.fakes import (
    INTEGRATION_ENV_VAR,
    FakeClock,
    FakeKeyring,
    FakeOAuth,
    FakeProcTable,
    FakeRoot,
    FakeSignalSender,
    integration_enabled,
)


@pytest.fixture(autouse=True)
def fake_root(tmp_path, monkeypatch) -> FakeRoot:
  """Root filesystem sementara; mengganti home, XDG, dan cwd proses test."""
  root = tmp_path / "sandbox"
  fake = FakeRoot(
      root=root,
      home=root / "home",
      config=root / "config",
      state=root / "state",
      data=root / "data",
      cache=root / "cache",
      runtime=root / "runtime",
      work=root / "work",
      proc=root / "proc",
  )
  fake.make_dirs()

  monkeypatch.setenv("HOME", str(fake.home))
  monkeypatch.setenv("XDG_CONFIG_HOME", str(fake.config))
  monkeypatch.setenv("XDG_STATE_HOME", str(fake.state))
  monkeypatch.setenv("XDG_DATA_HOME", str(fake.data))
  monkeypatch.setenv("XDG_CACHE_HOME", str(fake.cache))
  monkeypatch.setenv("XDG_RUNTIME_DIR", str(fake.runtime))
  monkeypatch.chdir(fake.work)
  return fake


@pytest.fixture
def fake_clock() -> FakeClock:
  return FakeClock()


@pytest.fixture
def fake_keyring() -> FakeKeyring:
  return FakeKeyring()


@pytest.fixture
def fake_proc() -> FakeProcTable:
  return FakeProcTable()


@pytest.fixture
def fake_signals(fake_proc: FakeProcTable) -> FakeSignalSender:
  return FakeSignalSender(fake_proc)


@pytest.fixture
def fake_oauth(fake_clock: FakeClock) -> FakeOAuth:
  return FakeOAuth(fake_clock)


def pytest_collection_modifyitems(config, items):
  """Skip test ``integration`` kecuali diaktifkan lewat environment variable."""
  if integration_enabled():
    return
  skip_marker = pytest.mark.skip(
      reason=(
          "Test integration di-skip. Set "
          f"{INTEGRATION_ENV_VAR}=1 untuk menjalankannya."
      )
  )
  for item in items:
    if "integration" in item.keywords:
      item.add_marker(skip_marker)
