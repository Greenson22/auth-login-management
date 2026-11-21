"""Pengelolaan snapshot, backup, rollback, dan restore untuk OpenCode dan Antigravity CLI."""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .constants import KEYRING_SERVICE, KEYRING_USERNAME

logger = logging.getLogger(__name__)


def get_backups_base_dir() -> Path:
  """Mengembalikan base direktori backup (~/.local/state/auth-login-management/backups)."""
  xdg_state = os.environ.get("XDG_STATE_HOME")
  if xdg_state:
    base = Path(xdg_state) / "auth-login-management" / "backups"
  else:
    base = Path.home() / ".local" / "state" / "auth-login-management" / "backups"
  return base


def _create_backup_dir(clock_now: float) -> Path:
  """Membuat direktori backup dengan timestamp integer dan mode 0700."""
  timestamp_str = str(int(clock_now))
  base_dir = get_backups_base_dir()
  backup_dir = base_dir / timestamp_str

  backup_dir.mkdir(parents=True, exist_ok=True)
  try:
    os.chmod(backup_dir, 0o700)
  except Exception:
    pass
  return backup_dir


def _write_secure_file(path: Path, content: str | bytes) -> None:
  """Menulis file secara aman dengan izin mode 0600."""
  path.parent.mkdir(parents=True, exist_ok=True)
  try:
    os.chmod(path.parent, 0o700)
  except Exception:
    pass

  if isinstance(content, str):
    data = content.encode("utf-8")
  else:
    data = content

  fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
  try:
    with open(fd, "wb") as f:
      f.write(data)
  finally:
    try:
      os.chmod(path, 0o600)
    except Exception:
      pass


def create_opencode_backup(
    file_path: Path,
    email: str,
    clock_now: float,
    version: str = "1.0",
) -> Path:
  """Membuat snapshot backup sebelum penulisan file OpenCode.
  
  Direktori backup mode 0700, file mode 0600.
  """
  backup_dir = _create_backup_dir(clock_now)
  artifacts: Dict[str, str] = {}

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
  _write_secure_file(meta_file, json.dumps(meta, indent=2))
  return backup_dir


def create_cli_backup(
    keyring_payload: Optional[bytes],
    gemini_dir: Optional[Path],
    email: str,
    clock_now: float,
    stopped_pids: Optional[List[int]] = None,
    version: str = "1.0",
) -> Path:
  """Membuat snapshot backup sebelum penulisan kredensial Antigravity CLI.

  Menyimpan snapshot item keyring (jika ada), oauth_creds.json, dan
  google_accounts.json beserta meta.json.
  Direktori backup mode 0700, file mode 0600.
  """
  backup_dir = _create_backup_dir(clock_now)
  artifacts: Dict[str, str] = {}

  # 1. Keyring payload
  if keyring_payload is not None:
    keyring_file = backup_dir / "keyring_item.bin"
    _write_secure_file(keyring_file, keyring_payload)
    artifacts["keyring_item"] = "present"
  else:
    artifacts["keyring_item"] = "absent"

  # 2. File ~/.gemini
  gemini_files = ["oauth_creds.json", "google_accounts.json"]
  for fname in gemini_files:
    if gemini_dir is not None:
      src_file = gemini_dir / fname
      if src_file.exists() and not src_file.is_symlink():
        dest_file = backup_dir / fname
        shutil.copy2(src_file, dest_file)
        try:
          os.chmod(dest_file, 0o600)
        except Exception:
          pass
        artifacts[fname] = "present"
      else:
        artifacts[fname] = "absent"
    else:
      artifacts[fname] = "absent"

  meta = {
      "target": "antigravity_cli",
      "email": email,
      "timestamp": int(clock_now),
      "app_version": version,
      "stopped_pids": list(stopped_pids or []),
      "artifacts": artifacts,
  }

  meta_file = backup_dir / "meta.json"
  _write_secure_file(meta_file, json.dumps(meta, indent=2))
  return backup_dir


def list_backups() -> List[Tuple[float, Path, Dict[str, Any]]]:
  """Mencari semua backup yang valid, diurutkan dari terbaru ke terlama."""
  base_dir = get_backups_base_dir()
  if not base_dir.exists():
    return []

  backups = []
  for p in base_dir.iterdir():
    if p.is_dir():
      meta_file = p / "meta.json"
      if meta_file.exists():
        try:
          meta = json.loads(meta_file.read_text(encoding="utf-8"))
          ts = float(meta.get("timestamp", p.stat().st_mtime))
          backups.append((ts, p, meta))
        except Exception:
          continue

  backups.sort(key=lambda x: x[0], reverse=True)
  return backups


def get_latest_backup() -> Optional[Tuple[Path, Dict[str, Any]]]:
  """Mengembalikan backup terbaru (backup_dir, meta), atau None jika tidak ada."""
  all_backups = list_backups()
  if not all_backups:
    return None
  ts, path, meta = all_backups[0]
  return path, meta


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


def rollback_from_backup(
    backup_dir: Path,
    keyring_port: Any,
    gemini_dir: Optional[Path],
    opencode_file_path: Optional[Path],
) -> None:
  """Mengembalikan kondisi artefak persis seperti snapshot backup.

  - Jika artefak sebelumnya ada ('present'), pulihkan isinya dengan mode 0600.
  - Jika artefak sebelumnya tidak ada ('absent'), hapus item keyring atau file tersebut.
  """
  meta_file = backup_dir / "meta.json"
  if not meta_file.exists():
    raise FileNotFoundError(f"meta.json tidak ditemukan di {backup_dir}")

  meta = json.loads(meta_file.read_text(encoding="utf-8"))
  artifacts = meta.get("artifacts", {})
  target = meta.get("target")

  if target == "opencode":
    acc_status = artifacts.get("antigravity-accounts.json")
    if opencode_file_path is not None:
      if acc_status == "present":
        src = backup_dir / "antigravity-accounts.json"
        if src.exists():
          shutil.copy2(src, opencode_file_path)
          try:
            os.chmod(opencode_file_path, 0o600)
          except Exception:
            pass
      elif acc_status == "absent":
        if opencode_file_path.exists():
          try:
            opencode_file_path.unlink()
          except Exception:
            pass

  elif target == "antigravity_cli":
    # 1. Keyring
    keyring_status = artifacts.get("keyring_item")
    if keyring_status == "present":
      keyring_file = backup_dir / "keyring_item.bin"
      if keyring_file.exists():
        raw_payload = keyring_file.read_bytes()
        keyring_port.write(KEYRING_SERVICE, KEYRING_USERNAME, raw_payload)
    elif keyring_status == "absent":
      try:
        keyring_port.delete(KEYRING_SERVICE, KEYRING_USERNAME)
      except Exception:
        pass

    # 2. Gemini files
    if gemini_dir is not None:
      for fname in ["oauth_creds.json", "google_accounts.json"]:
        f_status = artifacts.get(fname)
        target_f = gemini_dir / fname
        if f_status == "present":
          src_f = backup_dir / fname
          if src_f.exists():
            gemini_dir.mkdir(parents=True, exist_ok=True)
            try:
              os.chmod(gemini_dir, 0o700)
            except Exception:
              pass
            shutil.copy2(src_f, target_f)
            try:
              os.chmod(target_f, 0o600)
            except Exception:
              pass
        elif f_status == "absent":
          if target_f.exists():
            try:
              target_f.unlink()
            except Exception:
              pass
