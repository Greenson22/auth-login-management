"""Bukti bahwa modul aplikasi memakai database sementara saat dites."""

import hashlib
from pathlib import Path

from src.database import AccountDatabase


def _digest(path: Path) -> str | None:
  if not path.exists():
    return None
  return hashlib.sha256(path.read_bytes()).hexdigest()


def test_account_database_default_path_stays_in_fake_root(fake_root):
  repo_root = Path(__file__).resolve().parent.parent
  repo_db = repo_root / "accounts_manager.db"
  before = _digest(repo_db)

  db = AccountDatabase()
  summaries = db.fetch_accounts_summary()

  assert summaries == []
  assert Path(db.db_path).resolve() == fake_root.database_file.resolve()
  assert fake_root.database_file.exists()
  assert _digest(repo_db) == before
  assert not fake_root.gemini_dir.exists()
  assert not fake_root.opencode_config_dir.exists()
