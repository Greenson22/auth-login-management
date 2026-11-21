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

  def _get_file_path(self) -> Optional[Path]:
    folder = self._folder_provider() if callable(self._folder_provider) else self._folder_provider
    if not folder:
      return None
    return Path(folder) / "antigravity-accounts.json"

  def read_accounts_data(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    file_path = self._get_file_path()
    if file_path is None or not file_path.exists():
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
    file_path = self._get_file_path()
    if file_path is None:
      raise FileNotFoundError("Folder target belum ditentukan")

    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = file_path.with_name(f"{file_path.name}.tmp")
    content = json.dumps(data, indent=2)
    temp_file.write_text(content, encoding="utf-8")
    try:
      os.chmod(temp_file, 0o600)
    except Exception:
      pass
    temp_file.replace(file_path)
