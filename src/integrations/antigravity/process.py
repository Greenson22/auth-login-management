"""Pengelolaan proses sesi agy pada Linux (/proc).

Modul ini mendeteksi proses agy yang berjalan, membaca state dari /proc/<pid>/stat,
dan menghentikannya menggunakan urutan sinyal yang aman (SIGCONT -> SIGTERM -> SIGKILL)
dengan polling dan verifikasi cmdline ulang untuk mencegah race PID reuse.
"""

from __future__ import annotations

import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# State definitions:
# R (running), S (sleeping), D (disk sleep) -> ALIVE
# T (stopped by job control), t (tracing stop) -> STOPPED (considered ALIVE, needs SIGCONT)
# Z (zombie) -> ZOMBIE (not considered ALIVE, does not block apply)
ALIVE_STATES = {"R", "S", "D"}
STOPPED_STATES = {"T", "t"}
ZOMBIE_STATES = {"Z"}


class ProcessError(Exception):
  """Base error untuk pengelolaan proses."""


class ProcUnreadableError(ProcessError):
  """/proc tidak dapat dibaca (misalnya Flatpak atau sandbox)."""


@dataclass(frozen=True)
class AgySession:
  """Representasi sesi proses agy."""

  pid: int
  cmdline: List[str]
  state: str  # R, S, D, T, t, Z, etc.
  is_remote_control: bool = False
  command_str: str = ""

  @property
  def is_alive(self) -> bool:
    """True bila proses masih aktif/hidup (R, S, D, T, t)."""
    return self.state in ALIVE_STATES or self.state in STOPPED_STATES

  @property
  def is_stopped(self) -> bool:
    """True bila proses berstatus stopped (T, t)."""
    return self.state in STOPPED_STATES

  @property
  def is_zombie(self) -> bool:
    """True bila proses berstatus zombie (Z)."""
    return self.state in ZOMBIE_STATES

  @property
  def state_label(self) -> str:
    """Label ramah pengguna untuk status proses."""
    if self.is_remote_control:
      suffix = " (remote-control)"
    else:
      suffix = ""

    if self.state in ALIVE_STATES:
      return f"Running ({self.state}){suffix}"
    elif self.is_stopped:
      return f"Stopped ({self.state}){suffix}"
    elif self.is_zombie:
      return f"Zombie ({self.state}){suffix}"
    return f"{self.state}{suffix}"


def is_agy_binary(arg0: str) -> bool:
  """Mencocokkan persis basename argumen pertama dengan 'agy'.

  Nama 'antigravity' atau binary lain tidak cocok.
  """
  if not arg0:
    return False
  basename = os.path.basename(arg0.strip())
  return basename == "agy"


def read_proc_cmdline(proc_path: Path, pid: int) -> Optional[List[str]]:
  """Membaca /proc/<pid>/cmdline dan memisahkannya berdasarkan null byte."""
  cmdline_file = proc_path / str(pid) / "cmdline"
  try:
    data = cmdline_file.read_bytes()
    if not data:
      return []
    parts = [part.decode("utf-8", errors="replace") for part in data.split(b"\x00")]
    if parts and parts[-1] == "":
      parts.pop()
    return parts
  except (ProcessLookupError, FileNotFoundError):
    return None
  except PermissionError:
    return None
  except Exception as exc:
    logger.debug("Gagal membaca cmdline untuk pid %s: %s", pid, exc)
    return None


def read_proc_stat(proc_path: Path, pid: int) -> Optional[str]:
  """Membaca /proc/<pid>/stat dan mengambil kolom state (karakter ke-3)."""
  stat_file = proc_path / str(pid) / "stat"
  try:
    content = stat_file.read_text(encoding="utf-8", errors="replace").strip()
    if not content:
      return None
    # /proc/<pid>/stat format: pid (comm) state ppid ...
    # comm bisa memuat spasi atau kurung tutup, jadi ambil setelah rfind(')')
    idx = content.rfind(")")
    if idx == -1:
      return None
    rest = content[idx + 1:].strip().split()
    if not rest:
      return None
    return rest[0]
  except (ProcessLookupError, FileNotFoundError):
    return None
  except PermissionError:
    return None
  except Exception as exc:
    logger.debug("Gagal membaca stat untuk pid %s: %s", pid, exc)
    return None


class LinuxProcessManager:
  """Pengelola proses agy berbasis pembacaan /proc."""

  def __init__(
      self,
      proc_path: Optional[Path] = None,
      signal_sender: Optional[Callable[[int, int], None]] = None,
      clock: Optional[Any] = None,
      excluded_pids: Optional[Tuple[int, ...]] = None,
  ):
    self.proc_path = proc_path or Path("/proc")
    self.signal_sender = signal_sender or os.kill
    self.clock = clock
    if excluded_pids is not None:
      self.excluded_pids = set(excluded_pids)
    else:
      self.excluded_pids = {os.getpid(), os.getppid()}

  def _sleep(self, seconds: float) -> None:
    if self.clock is not None and hasattr(self.clock, "sleep"):
      self.clock.sleep(seconds)
    else:
      import time
      time.sleep(seconds)

  def detect_sessions(self) -> List[AgySession]:
    """Mendeteksi semua sesi agy yang berjalan di sistem milik pengguna.

    Raises:
      ProcUnreadableError: bila direktori /proc tidak ada atau tidak dapat dibaca.
    """
    if not self.proc_path.exists() or not self.proc_path.is_dir():
      raise ProcUnreadableError("Direktori /proc tidak ditemukan atau tidak dapat diakses.")

    try:
      entries = list(self.proc_path.iterdir())
    except (PermissionError, OSError) as exc:
      raise ProcUnreadableError(f"Tidak dapat membaca /proc: {exc}") from exc

    current_uid = os.getuid() if hasattr(os, "getuid") else None
    sessions: List[AgySession] = []

    for entry in entries:
      name = entry.name
      if not name.isdigit():
        continue
      pid = int(name)
      if pid in self.excluded_pids:
        continue

      # Cek kepemilikan UID jika memungkinkan (jangan sentuh proses milik user lain)
      if current_uid is not None:
        try:
          stat_info = entry.stat()
          if stat_info.st_uid != current_uid:
            continue
        except (FileNotFoundError, ProcessLookupError, PermissionError):
          continue

      cmdline = read_proc_cmdline(self.proc_path, pid)
      if not cmdline:
        continue

      arg0 = cmdline[0]
      if not is_agy_binary(arg0):
        continue

      state = read_proc_stat(self.proc_path, pid)
      if state is None:
        continue

      is_remote_control = len(cmdline) > 1 and cmdline[1] == "remote-control"
      command_str = " ".join(cmdline)

      sessions.append(
          AgySession(
              pid=pid,
              cmdline=cmdline,
              state=state,
              is_remote_control=is_remote_control,
              command_str=command_str,
          )
      )

    return sorted(sessions, key=lambda s: s.pid)

  def verify_pid(self, pid: int) -> Optional[AgySession]:
    """Memverifikasi ulang apakah PID masih ada dan cmdline-nya masih proses agy.

    Menutup race condition PID reuse.
    """
    cmdline = read_proc_cmdline(self.proc_path, pid)
    if not cmdline:
      return None
    if not is_agy_binary(cmdline[0]):
      return None
    state = read_proc_stat(self.proc_path, pid)
    if state is None:
      return None
    is_remote_control = len(cmdline) > 1 and cmdline[1] == "remote-control"
    command_str = " ".join(cmdline)
    return AgySession(
        pid=pid,
        cmdline=cmdline,
        state=state,
        is_remote_control=is_remote_control,
        command_str=command_str,
    )

  def summarize_sessions(self, sessions: Optional[List[AgySession]] = None) -> Dict[str, int]:
    """Menghitung ringkasan jumlah sesi: alive, stopped, zombie."""
    if sessions is None:
      try:
        sessions = self.detect_sessions()
      except Exception:
        return {"alive": 0, "stopped": 0, "zombie": 0}

    alive_count = 0
    stopped_count = 0
    zombie_count = 0

    for s in sessions:
      if s.is_zombie:
        zombie_count += 1
      elif s.is_stopped:
        stopped_count += 1
        alive_count += 1
      elif s.is_alive:
        alive_count += 1

    return {
        "alive": alive_count,
        "stopped": stopped_count,
        "zombie": zombie_count,
    }

  def terminate_sessions(
      self,
      sessions: List[AgySession],
      *,
      on_progress: Optional[Callable[[str], None]] = None,
      is_cancelled: Optional[Callable[[], bool]] = None,
  ) -> Tuple[bool, List[int], str]:
    """Menghentikan sesi agy sesuai alur:

    1. Cek sesi hidup (R, S, D, T, t). Abaikan zombie.
    2. Jika stopped (T, t) -> kirim SIGCONT lalu SIGTERM.
    3. Jika hidup lainnya -> kirim SIGTERM.
    4. Polling 100ms hingga max 3000ms (3.0s).
    5. Jika masih hidup -> kirim SIGKILL.
    6. Polling 100ms hingga max 2000ms (2.0s).
    7. Periksa apakah masih ada sesi hidup.

    Returns:
      (success: bool, failed_pids: List[int], error_message: str)
    """
    alive_targets = [s for s in sessions if s.is_alive]
    if not alive_targets:
      return True, [], ""

    # Kumpulkan target PID yang perlu dihentikan
    pids_to_kill = [s.pid for s in alive_targets]
    permission_failed_pids: List[int] = []

    if on_progress:
      on_progress(f"Mengirim sinyal penghentian ke {len(pids_to_kill)} proses agy...")

    # Langkah 1 & 2: Kirim SIGCONT (jika stopped) lalu SIGTERM
    for s in alive_targets:
      if is_cancelled and is_cancelled():
        return False, pids_to_kill, "Penghentian sesi dibatalkan oleh pengguna."

      # Verifikasi ulang cmdline sebelum mengirim sinyal
      current_session = self.verify_pid(s.pid)
      if current_session is None or not current_session.is_alive:
        continue

      try:
        if current_session.is_stopped:
          logger.info("Mengirim SIGCONT ke PID %d (stopped)", s.pid)
          self.signal_sender(s.pid, signal.SIGCONT)

        logger.info("Mengirim SIGTERM ke PID %d", s.pid)
        self.signal_sender(s.pid, signal.SIGTERM)
      except ProcessLookupError:
        # Proses sudah mati
        pass
      except PermissionError:
        logger.warning("PermissionError saat mengirim sinyal ke PID %d", s.pid)
        permission_failed_pids.append(s.pid)
      except Exception as exc:
        logger.warning("Gagal mengirim sinyal ke PID %d: %s", s.pid, exc)
        permission_failed_pids.append(s.pid)

    # Polling SIGTERM: 100ms per iterasi, max 3000ms (30 iterasi)
    term_poll_max = 30
    term_poll_interval = 0.1
    for _ in range(term_poll_max):
      if is_cancelled and is_cancelled():
        return False, pids_to_kill, "Penghentian sesi dibatalkan oleh pengguna."

      remaining = [
          pid for pid in pids_to_kill
          if self._is_pid_still_alive(pid)
      ]
      if not remaining:
        break
      self._sleep(term_poll_interval)

    # Periksa apakah ada yang masih hidup setelah SIGTERM
    still_alive_after_term = [
        pid for pid in pids_to_kill
        if self._is_pid_still_alive(pid)
    ]

    # Langkah 5: SIGKILL untuk sisa yang masih hidup
    if still_alive_after_term:
      if on_progress:
        on_progress(f"Mengirim SIGKILL ke {len(still_alive_after_term)} proses yang belum berhenti...")

      for pid in still_alive_after_term:
        if is_cancelled and is_cancelled():
          return False, still_alive_after_term, "Penghentian sesi dibatalkan oleh pengguna."

        current_session = self.verify_pid(pid)
        if current_session is None or not current_session.is_alive:
          continue

        try:
          logger.info("Mengirim SIGKILL ke PID %d", pid)
          self.signal_sender(pid, signal.SIGKILL)
        except ProcessLookupError:
          pass
        except PermissionError:
          permission_failed_pids.append(pid)
        except Exception as exc:
          logger.warning("Gagal mengirim SIGKILL ke PID %d: %s", pid, exc)
          permission_failed_pids.append(pid)

      # Polling SIGKILL: 100ms per iterasi, max 2000ms (20 iterasi)
      kill_poll_max = 20
      kill_poll_interval = 0.1
      for _ in range(kill_poll_max):
        if is_cancelled and is_cancelled():
          return False, still_alive_after_term, "Penghentian sesi dibatalkan oleh pengguna."

        remaining = [
            pid for pid in still_alive_after_term
            if self._is_pid_still_alive(pid)
        ]
        if not remaining:
          break
        self._sleep(kill_poll_interval)

    # Cek akhir: apakah ada PID yang masih hidup
    final_alive = [
        pid for pid in pids_to_kill
        if self._is_pid_still_alive(pid)
    ]

    if final_alive:
      pids_str = ", ".join(str(p) for p in final_alive)
      err_msg = (
          f"Gagal menghentikan sesi agy pada PID: {pids_str}.\n"
          f"Tutup manual dengan perintah: pkill -9 -x agy\n"
          f"Tidak ada perubahan kredensial yang ditulis."
      )
      return False, final_alive, err_msg

    return True, [], ""

  def _is_pid_still_alive(self, pid: int) -> bool:
    """True jika PID masih ada, cmdline masih agy, dan stat masih alive (bukan Z)."""
    session = self.verify_pid(pid)
    if session is None:
      return False
    return session.is_alive
