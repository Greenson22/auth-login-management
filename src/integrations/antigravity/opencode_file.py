"""Implementasi nyata adaptor OpenCode file."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


class RealOpenCodeFilePort:
  """Adaptor pembaca/penulis file antigravity-accounts.json nyata."""

  def __init__(self, folder_provider):
    # folder_provider adalah callable () -> str atau path statis
    self._folder_provider = folder_provider

  def get_file_path(self) -> Optional[Path]:
    folder = self._folder_provider() if callable(self._folder_provider) else self._folder_provider
    if not folder:
      return None
    return Path(folder) / "antigravity-accounts.json"

  def read_accounts_data(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    file_path = self.get_file_path()
    if file_path is None or not file_path.exists():
      return None, "invalid_file"
    if file_path.is_symlink():
      return None, "invalid_file"

    try:
      content = file_path.read_text(encoding="utf-8")
      data = json.loads(content)
      if not isinstance(data, dict):
        return None, "invalid_file"
      return data, None
    except Exception:
      return None, "invalid_file"

  def write_accounts_data(self, data: Dict[str, Any]) -> None:
    file_path = self.get_file_path()
    if file_path is None:
      raise FileNotFoundError("Folder target belum ditentukan")

    if file_path.is_symlink():
      raise PermissionError("File OpenCode adalah symlink, penulisan dibatalkan")

    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = file_path.with_name(f"{file_path.name}.tmp")
    content = json.dumps(data, indent=2)
    # Tulis atomic: buka fd dengan os.O_WRONLY | os.O_CREAT | os.O_TRUNC dan mode 0600
    fd = os.open(temp_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with open(fd, "w", encoding="utf-8") as f:
      f.write(content)
    try:
      os.chmod(temp_file, 0o600)
    except Exception:
      pass
    os.replace(temp_file, file_path)
