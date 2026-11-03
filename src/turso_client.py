import base64
import json
from typing import Any, List, Optional, Tuple
import urllib.error
import urllib.request


class TursoClient:
  """Client ringan zero-dependency untuk berkomunikasi dengan database Turso / libSQL melalui HTTP Pipeline API v2."""

  def __init__(self, url: str, auth_token: str, timeout: int = 10):
    self.url = self.clean_url(url)
    self.auth_token = (auth_token or "").strip()
    self.timeout = timeout

  @staticmethod
  def clean_url(url: str) -> str:
    """Mengubah libsql:// atau turso:// menjadi https:// dan memastikan endpoint pipeline."""
    if not url:
      return ""
    clean = url.strip()
    if clean.startswith("libsql://"):
      clean = "https://" + clean[len("libsql://") :]
    elif clean.startswith("turso://"):
      clean = "https://" + clean[len("turso://") :]
    elif not clean.startswith("http://") and not clean.startswith("https://"):
      clean = "https://" + clean

    clean = clean.rstrip("/")
    if not clean.endswith("/v2/pipeline"):
      clean = clean + "/v2/pipeline"
    return clean

  @staticmethod
  def extract_db_name(url: str) -> str:
    """Mengekstrak nama database dari URL Turso untuk tampilan UI ringkas."""
    if not url:
      return ""
    clean = url.strip()
    for prefix in ("libsql://", "turso://", "https://", "http://"):
      if clean.startswith(prefix):
        clean = clean[len(prefix) :]
        break
    clean = clean.split("/")[0]
    return clean.split(".")[0] if "." in clean else clean

  @staticmethod
  def _serialize_arg(val: Any) -> dict:
    """Mengonversi nilai Python ke format tipe data Hrana/Turso JSON."""
    if val is None:
      return {"type": "null"}
    elif isinstance(val, bool):
      return {"type": "integer", "value": "1" if val else "0"}
    elif isinstance(val, int):
      return {"type": "integer", "value": str(val)}
    elif isinstance(val, float):
      return {"type": "float", "value": val}
    elif isinstance(val, bytes):
      return {"type": "blob", "base64": base64.b64encode(val).decode("utf-8")}
    else:
      return {"type": "text", "value": str(val)}

  @staticmethod
  def _parse_row(row_raw: list) -> list:
    """Mengonversi row dari format Hrana/Turso ke tuple/list Python biasa."""
    parsed = []
    for col in row_raw:
      if not isinstance(col, dict):
        parsed.append(col)
        continue
      c_type = col.get("type")
      if c_type == "null":
        parsed.append(None)
      elif c_type == "integer":
        v = col.get("value")
        parsed.append(int(v) if v is not None else None)
      elif c_type == "float":
        v = col.get("value")
        parsed.append(float(v) if v is not None else None)
      elif c_type == "text":
        parsed.append(col.get("value"))
      elif c_type == "blob":
        b64 = col.get("base64", "")
        parsed.append(base64.b64decode(b64) if b64 else b"")
      else:
        parsed.append(col.get("value"))
    return parsed

  def _send_request(self, payload: dict) -> dict:
    """Mengirim POST request ke endpoint Turso menggunakan modul bawaan urllib."""
    headers = {
        "Authorization": f"Bearer {self.auth_token}",
        "Content-Type": "application/json",
        "User-Agent": "AccountManager-TursoClient/1.0",
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        self.url, data=data_bytes, headers=headers, method="POST"
    )

    try:
      with urllib.request.urlopen(req, timeout=self.timeout) as resp:
        res_data = resp.read().decode("utf-8")
        return json.loads(res_data)
    except urllib.error.HTTPError as e:
      body_err = ""
      try:
        body_err = e.read().decode("utf-8")
      except Exception:
        pass
      if e.code in (401, 403):
        raise PermissionError(
            f"Autentikasi gagal (HTTP {e.code})! Periksa kembali Turso Auth Token."
        )
      raise RuntimeError(f"Turso HTTP {e.code} Error: {body_err[:200]}")
    except urllib.error.URLError as e:
      raise ConnectionError(f"Gagal terhubung ke host Turso: {e.reason}")

  def test_connection(self) -> Tuple[bool, str]:
    """Menguji koneksi ke Turso dengan SELECT 1."""
    if not self.url:
      return False, "URL Database Turso belum diisi."
    if not self.auth_token:
      return False, "Auth Token Turso belum diisi."

    try:
      payload = {
          "requests": [
              {"type": "execute", "stmt": {"sql": "SELECT 1;"}},
              {"type": "close"},
          ]
      }
      data = self._send_request(payload)
      results = data.get("results", [])
      if not results:
        return False, "Respons server Turso kosong."

      first_res = results[0]
      if first_res.get("type") == "error":
        err_msg = first_res.get("error", {}).get("message", "Unknown error")
        return False, f"Turso Error: {err_msg}"

      return True, "Koneksi ke Turso berhasil terhubung!"
    except PermissionError as e:
      return False, str(e)
    except ConnectionError as e:
      return (
          False,
          f"{str(e)}. Periksa kembali URL dan koneksi internet Anda.",
      )
    except TimeoutError:
      return False, "Koneksi ke Turso timeout (melebihi batas waktu 10 detik)."
    except Exception as e:
      return False, f"Terjadi kesalahan saat menghubungkan ke Turso: {str(e)}"

  def execute(
      self, sql: str, args: Optional[List[Any]] = None
  ) -> Tuple[List[List[Any]], int]:
    """Mengeksekusi sebuah query ke Turso. Mengembalikan (rows, affected_rows)."""
    stmt = {"sql": sql}
    if args:
      stmt["args"] = [self._serialize_arg(a) for a in args]

    payload = {"requests": [{"type": "execute", "stmt": stmt}, {"type": "close"}]}
    data = self._send_request(payload)

    results = data.get("results", [])
    if not results:
      return [], 0

    first_res = results[0]
    if first_res.get("type") == "error":
      err = first_res.get("error", {})
      raise RuntimeError(
          f"Turso Query Error: {err.get('message', 'Unknown error')}"
      )

    res_data = first_res.get("response", {}).get("result", {})
    raw_rows = res_data.get("rows", [])
    parsed_rows = [self._parse_row(r) for r in raw_rows]
    affected = res_data.get("affected_row_count", 0)
    return parsed_rows, affected

  def execute_pipeline(self, statements: List[Tuple[str, Optional[List[Any]]]]):
    """Mengeksekusi sekumpulan statement secara berurutan dalam satu pipeline call."""
    if not statements:
      return []

    requests_list = []
    for sql, args in statements:
      stmt = {"sql": sql}
      if args:
        stmt["args"] = [self._serialize_arg(a) for a in args]
      requests_list.append({"type": "execute", "stmt": stmt})

    requests_list.append({"type": "close"})
    payload = {"requests": requests_list}
    data = self._send_request(payload)

    results = data.get("results", [])
    parsed_results = []
    for res in results:
      if res.get("type") == "error":
        err = res.get("error", {})
        raise RuntimeError(
            f"Turso Pipeline Query Error: {err.get('message', 'Unknown error')}"
        )
      if res.get("type") == "ok" and "result" in res.get("response", {}):
        res_data = res.get("response", {}).get("result", {})
        raw_rows = res_data.get("rows", [])
        parsed_results.append(
            ([self._parse_row(r) for r in raw_rows], res_data.get("affected_row_count", 0))
        )
    return parsed_results
