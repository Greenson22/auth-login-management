"""Pengelolaan snapshot dan backup untuk OpenCode dan Antigravity CLI."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_backups_base_dir() -> Path:
  """Mengembalikan base direktori backup (~/.local/state/auth-login-management/backups)."""
  xdg_state = os.environ.get("XDG_STATE_HOME")
  if xdg_state:
    base = Path(xdg_state) / "auth-login-management" / "backups"
  else:
    base = Path.home() / ".local" / "state" / "auth-login-management" / "backups"
  return base


def create_opencode_backup(
    file_path: Path,
    email: str,
    clock_now: float,
    version: str = "1.0",
) -> Path:
  """Membuat snapshot backup sebelum penulisan file OpenCode.
  
  Direktori backup mode 0700, file mode 0600.
  """
  timestamp_str = str(int(clock_now))
  base_dir = get_backups_base_dir()
  backup_dir = base_dir / timestamp_str

  # Buat direktori dengan mode 0700
  backup_dir.mkdir(parents=True, exist_ok=True)
  try:
    os.chmod(backup_dir, 0o700)
  except Exception:
    pass

  artifacts = {}

  # Salin file jika ada
  if file_path.exists() and not file_path.is_symlink():
    dest_file = backup_dir / "antigravity-accounts.json"
    shutil.copy2(file_path, dest_file)
    try:
      os.chmod(dest_file, 0o600)
    except Exception:
      pass
    artifacts["antigravity-accounts.json"] = "present"
  else:
    artifacts["antigravity-accounts.json"] = "absent"

  meta = {
      "target": "opencode",
      "email": email,
      "timestamp": int(clock_now),
      "app_version": version,
      "stopped_pids": [],
      "artifacts": artifacts,
  }

  meta_file = backup_dir / "meta.json"
  meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
  try:
    os.chmod(meta_file, 0o600)
  except Exception:
    pass

  return backup_dir


def cleanup_old_backups(max_keep: int = 30) -> None:
  """Membersihkan backup lama, menyisakan `max_keep` terbaru."""
  base_dir = get_backups_base_dir()
  if not base_dir.exists():
    return

  entries = []
  for p in base_dir.iterdir():
    if p.is_dir():
      try:
        entries.append((p.stat().st_mtime, p))
      except Exception:
        pass

  entries.sort(key=lambda x: x[0], reverse=True)
  for _, old_dir in entries[max_keep:]:
    try:
      shutil.rmtree(old_dir, ignore_errors=True)
    except Exception:
      pass
