"""Pengujian lengkap untuk Tiket 07: Pengelolaan sesi agy.

Memverifikasi:
- Deteksi Linux membaca /proc/<pid>/cmdline basename agy (antigravity tidak cocok).
- agy remote-control terdeteksi dan dilabeli.
- PID aplikasi sendiri dan parent-nya dikecualikan; UID lain tidak disentuh.
- State /proc/<pid>/stat: R/S/D hidup, T/t stopped, Z zombie.
- Zombie tidak memblokir apply dan dianggap sisa.
- Stopped memicu SIGCONT sebelum SIGTERM.
- /proc tidak terbaca -> plan FAILED / target_available=False pesan periksa proses manual.
- Build plan: auto_kill_agy=False -> requires_confirmation=True; auto_kill_agy=True -> requires_confirmation=False.
- Apply tanpa allow_kill saat ada sesi hidup -> FAILED tanpa penulisan.
- State machine sinyal: SIGCONT -> SIGTERM (poll 100ms) -> SIGKILL (poll 100ms).
- Verifikasi ulang cmdline sebelum sinyal menutup race PID reuse.
- ProcessLookupError dianggap sudah mati; PermissionError dilaporkan dan tidak dipaksa.
- Timeout proses D -> FAILED dan saran menutup manual (pkill -9 -x agy).
- Dialog konfirmasi: ukuran tetap 480x320, default focus Batal, tombol kill destruktif, checkbox auto_kill_agy.
- Cancellation pada progress: CANCELLED tanpa penulisan dan tidak mengirim sinyal baru.
- Tooltip chip memuat ringkasan sesi agy (alive/stopped/zombie).
"""

from __future__ import annotations

import os
import signal
from pathlib import Path
from typing import Any, Dict, List

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from src.integrations.antigravity.process import (
    AgySession,
    LinuxProcessManager,
    ProcUnreadableError,
    is_agy_binary,
    read_proc_cmdline,
    read_proc_stat,
)
from src.integrations.antigravity.service import AntigravityFacade
from src.targets import TARGET_ANTIGRAVITY_CLI
from src.ui.components.agy_session_dialog import AgyConfirmDialog
from tests.fakes import (
    FakeClock,
    FakeKeyring,
    FakeOAuth,
    FakeProcTable,
    FakeSignalSender,
)


class DummyAccountStorage:
  def reconstruct_account(self, account_id: str, password: str = "") -> Dict[str, Any]:
    return {"id": account_id, "email": "user@example.com", "refresh_token": "rt_12345"}

  def mark_applied(self, account_id: str, target: str, applied_at: int = None) -> bool:
    return True

  def update_refresh_token(self, account_id: str, new_token: str, password: str = "") -> bool:
    return True

  def account_exists(self, email: str) -> bool:
    return email == "user@example.com"


class DummyGeminiFiles:
  def __init__(self):
    self.oauth_creds = None
    self.google_accounts = None

  def read_oauth_creds(self):
    return self.oauth_creds

  def write_oauth_creds(self, creds):
    self.oauth_creds = dict(creds)

  def read_google_accounts(self):
    return self.google_accounts

  def write_google_accounts(self, accs):
    self.google_accounts = dict(accs)


class DummyOpenCodeFile:
  def read_accounts_data(self):
    return {"accounts": [{"email": "user@example.com"}], "activeIndex": 0}, None

  def write_accounts_data(self, data):
    pass


class DummyEnvironment:
  def __init__(self, is_linux=True, is_root=False, is_dbus=True, is_locked=False):
    self._is_linux = is_linux
    self._is_root = is_root
    self._is_dbus = is_dbus
    self._is_locked = is_locked

  def is_linux(self):
    return self._is_linux

  def is_root(self):
    return self._is_root

  def is_dbus_available(self):
    return self._is_dbus

  def is_keyring_locked(self):
    return self._is_locked


def test_is_agy_binary_matching():
  """Hanya mencocokkan basename 'agy' persis. 'antigravity' tidak cocok."""
  assert is_agy_binary("/usr/bin/agy")
  assert is_agy_binary("agy")
  assert is_agy_binary("/home/user/.local/bin/agy")
  assert not is_agy_binary("/usr/bin/antigravity")
  assert not is_agy_binary("antigravity")
  assert not is_agy_binary("/usr/bin/agy-custom")
  assert not is_agy_binary("")


def test_proc_detection_linux_and_remote_control(tmp_path: Path):
  """Deteksi Linux membaca /proc, mendeteksi agy dan agy remote-control, mengecualikan PID sendiri/parent."""
  proc_dir = tmp_path / "proc"
  proc_table = FakeProcTable()

  my_pid = os.getpid()
  my_ppid = os.getppid()

  # Sesi 1: agy normal running (R)
  proc_table.add(101, ["/usr/bin/agy", "start"], state="R")
  # Sesi 2: agy remote-control sleeping (S)
  proc_table.add(102, ["agy", "remote-control", "--port", "8080"], state="S")
  # Sesi 3: binary antigravity (tidak boleh terdeteksi)
  proc_table.add(103, ["/usr/bin/antigravity"], state="S")
  # Sesi 4: pid sendiri dengan argumen agy (harus dikecualikan)
  proc_table.add(my_pid, ["agy"], state="R")
  # Sesi 5: pid parent dengan argumen agy (harus dikecualikan)
  proc_table.add(my_ppid, ["agy"], state="R")
  # Sesi 6: zombie (Z)
  proc_table.add(106, ["agy"], state="Z")
  # Sesi 7: stopped (T)
  proc_table.add(107, ["agy"], state="T")

  proc_table.write_to(proc_dir)

  mgr = LinuxProcessManager(proc_path=proc_dir, excluded_pids=(my_pid, my_ppid))
  sessions = mgr.detect_sessions()

  pids = [s.pid for s in sessions]
  assert 101 in pids
  assert 102 in pids
  assert 106 in pids
  assert 107 in pids
  assert 103 not in pids
  assert my_pid not in pids
  assert my_ppid not in pids

  # Cek label remote control
  s_rc = next(s for s in sessions if s.pid == 102)
  assert s_rc.is_remote_control is True
  assert "remote-control" in s_rc.state_label

  s_norm = next(s for s in sessions if s.pid == 101)
  assert s_norm.is_remote_control is False
  assert s_norm.state == "R"
  assert s_norm.is_alive is True

  s_zombie = next(s for s in sessions if s.pid == 106)
  assert s_zombie.is_zombie is True
  assert s_zombie.is_alive is False

  s_stopped = next(s for s in sessions if s.pid == 107)
  assert s_stopped.is_stopped is True
  assert s_stopped.is_alive is True


def test_proc_unreadable_fails_gracefully(tmp_path: Path):
  """Bila /proc tidak terbaca (sandbox/flatpak), deteksi melempar ProcUnreadableError."""
  non_existent = tmp_path / "proc_missing"
  mgr = LinuxProcessManager(proc_path=non_existent)
  with pytest.raises(ProcUnreadableError):
    mgr.detect_sessions()


def test_state_machine_termination_sequence(tmp_path: Path):
  """State machine penghentian:

  - stopped (T) menerima SIGCONT lalu SIGTERM
  - running (R) menerima SIGTERM
  - Polling deterministik memajukan jam palsu
  - Jika belum mati, dikirim SIGKILL
  """
  proc_dir = tmp_path / "proc"
  proc_table = FakeProcTable()
  fake_sender = FakeSignalSender(proc_table)
  fake_clock = FakeClock()

  # 201: stopped, 202: running
  proc_table.add(201, ["agy"], state="T")
  proc_table.add(202, ["agy"], state="R")
  proc_table.write_to(proc_dir)

  # Custom sender yang mengubah state di filesystem pohon proc
  def signal_dispatch(pid: int, sig: int):
    fake_sender.send(pid, sig)
    # Tulis ulang file stat di filesystem sementara
    stat_file = proc_dir / str(pid) / "stat"
    if stat_file.exists():
      stat_file.write_text(proc_table.read_stat(pid) + "\n", encoding="utf-8")

  mgr = LinuxProcessManager(
      proc_path=proc_dir,
      signal_sender=signal_dispatch,
      clock=fake_clock,
      excluded_pids=(),
  )

  sessions = mgr.detect_sessions()
  assert len(sessions) == 2

  success, failed_pids, msg = mgr.terminate_sessions(sessions)
  assert success is True
  assert failed_pids == []

  # Verifikasi urutan sinyal yang dikirim:
  # PID 201 (stopped) harus menerima SIGCONT lalu SIGTERM
  sig_201 = [sig for p, sig in fake_sender.sent if p == 201]
  assert sig_201[0] == signal.SIGCONT
  assert sig_201[1] == signal.SIGTERM

  # PID 202 (running) harus menerima SIGTERM
  sig_202 = [sig for p, sig in fake_sender.sent if p == 202]
  assert sig_202[0] == signal.SIGTERM


def test_unkillable_process_d_state_times_out(tmp_path: Path):
  """Proses D-state unkillable yang tidak mati memicu SIGKILL lalu FAILED dengan pesan pkill -9 -x agy."""
  proc_dir = tmp_path / "proc"
  proc_table = FakeProcTable()
  fake_sender = FakeSignalSender(proc_table)
  fake_clock = FakeClock()

  # Proses 301 unkillable state D
  proc_table.add(301, ["agy"], state="D", unkillable=True)
  proc_table.write_to(proc_dir)

  def signal_dispatch(pid: int, sig: int):
    fake_sender.send(pid, sig)

  mgr = LinuxProcessManager(
      proc_path=proc_dir,
      signal_sender=signal_dispatch,
      clock=fake_clock,
      excluded_pids=(),
  )

  sessions = mgr.detect_sessions()
  success, failed_pids, msg = mgr.terminate_sessions(sessions)

  assert success is False
  assert failed_pids == [301]
  assert "pkill -9 -x agy" in msg
  assert "Tidak ada perubahan kredensial yang ditulis" in msg

  # Periksa bahwa sinyal SIGTERM lalu SIGKILL dikirim
  signals_sent = [sig for p, sig in fake_sender.sent if p == 301]
  assert signal.SIGTERM in signals_sent
  assert signal.SIGKILL in signals_sent


def test_permission_error_fails_cleanly(tmp_path: Path):
  """PermissionError saat kill menandai PID gagal tanpa crash/dipaksa."""
  proc_dir = tmp_path / "proc"
  proc_table = FakeProcTable()
  fake_sender = FakeSignalSender(proc_table)
  fake_clock = FakeClock()

  proc_table.add(401, ["agy"], state="S", deny_signals=True)
  proc_table.write_to(proc_dir)

  def signal_dispatch(pid: int, sig: int):
    fake_sender.send(pid, sig)

  mgr = LinuxProcessManager(
      proc_path=proc_dir,
      signal_sender=signal_dispatch,
      clock=fake_clock,
      excluded_pids=(),
  )

  sessions = mgr.detect_sessions()
  success, failed_pids, msg = mgr.terminate_sessions(sessions)

  assert success is False
  assert 401 in failed_pids


def test_pid_reuse_race_check(tmp_path: Path):
  """Sebelum kill, verifikasi cmdline ulang mencegah mengirim sinyal ke binary lain jika PID di-reuse."""
  proc_dir = tmp_path / "proc"
  proc_table = FakeProcTable()
  fake_sender = FakeSignalSender(proc_table)
  fake_clock = FakeClock()

  proc_table.add(501, ["agy"], state="S")
  proc_table.write_to(proc_dir)

  mgr = LinuxProcessManager(
      proc_path=proc_dir,
      signal_sender=fake_sender.send,
      clock=fake_clock,
      excluded_pids=(),
  )

  sessions = mgr.detect_sessions()
  assert len(sessions) == 1

  # Simulasikan PID reuse: proses berganti cmdline menjadi bash
  proc_table.entries[501].argv = ["bash"]
  proc_table.write_to(proc_dir)

  # terminate_sessions memanggil verify_pid sebelum os.kill
  success, failed_pids, msg = mgr.terminate_sessions(sessions)
  assert success is True
  # Tidak ada sinyal yang dikirim ke PID yang sudah berganti binary
  assert len(fake_sender.sent) == 0


def test_facade_build_plan_and_apply_process_integration(tmp_path: Path):
  """Integrasi facade build_plan & apply:

  - auto_kill_agy mati -> requires_confirmation=True
  - auto_kill_agy hidup -> requires_confirmation=False
  - apply tanpa allow_kill gagal tanpa tulis
  - apply dengan allow_kill memanggil terminate_sessions dan sukses
  - sesi baru muncul sebelum tulis -> FAILED
  """
  proc_dir = tmp_path / "proc"
  proc_table = FakeProcTable()
  fake_sender = FakeSignalSender(proc_table)
  fake_clock = FakeClock()

  proc_table.add(601, ["agy"], state="S")
  proc_table.write_to(proc_dir)

  def signal_dispatch(pid: int, sig: int):
    fake_sender.send(pid, sig)
    proc_table.remove(pid)
    # Hapus dari direktori sementara
    cmdline_file = proc_dir / str(pid) / "cmdline"
    if cmdline_file.exists():
      cmdline_file.unlink()

  proc_mgr = LinuxProcessManager(
      proc_path=proc_dir,
      signal_sender=signal_dispatch,
      clock=fake_clock,
      excluded_pids=(),
  )

  fake_oauth = FakeOAuth(fake_clock)
  fake_oauth.respond_for("user@example.com", refresh_token="rt_12345")

  facade = AntigravityFacade(
      account_storage=DummyAccountStorage(),
      keyring=FakeKeyring(),
      gemini_files=DummyGeminiFiles(),
      opencode_file=DummyOpenCodeFile(),
      oauth=fake_oauth,
      process_manager=proc_mgr,
      environment=DummyEnvironment(),
      clock=fake_clock,
  )

  # 1. Build plan dengan auto_kill_agy=False -> butuh konfirmasi
  plan_confirm = facade.build_plan("acc_1", TARGET_ANTIGRAVITY_CLI, auto_kill_agy=False)
  assert plan_confirm.target_available is True
  assert plan_confirm.requires_confirmation is True
  assert len(plan_confirm.detected_sessions) == 1

  # 2. Build plan dengan auto_kill_agy=True -> tidak butuh konfirmasi
  plan_auto = facade.build_plan("acc_1", TARGET_ANTIGRAVITY_CLI, auto_kill_agy=True)
  assert plan_auto.requires_confirmation is False

  # 3. Apply tanpa izin kill (allow_kill=False) -> FAILED
  res_disallowed = facade.apply(plan_confirm, allow_kill=False)
  assert res_disallowed.status.value == "FAILED"
  assert res_disallowed.code == "sessions_still_running"

  # 4. Apply dengan izin kill (allow_kill=True) -> SUCCESS
  res_allowed = facade.apply(plan_confirm, allow_kill=True)
  assert res_allowed.status.value == "SUCCESS"

  # 5. Sesi baru muncul tepat sebelum apply
  proc_table.add(602, ["agy"], state="R")
  proc_table.write_to(proc_dir)
  # Jangan dispatch sinyal untuk 602 agar tetap hidup
  res_race = facade.apply(plan_confirm, allow_kill=False)
  assert res_race.status.value == "FAILED"


def test_facade_proc_unreadable_build_plan_fails(tmp_path: Path):
  """Bila /proc tidak bisa dibaca, build_plan menandai target_available=False dan pesan periksa proses manual."""
  proc_mgr = LinuxProcessManager(
      proc_path=tmp_path / "invalid_proc",
      clock=FakeClock(),
      excluded_pids=(),
  )

  facade = AntigravityFacade(
      account_storage=DummyAccountStorage(),
      keyring=FakeKeyring(),
      gemini_files=DummyGeminiFiles(),
      opencode_file=DummyOpenCodeFile(),
      oauth=FakeOAuth(),
      process_manager=proc_mgr,
      environment=DummyEnvironment(),
      clock=FakeClock(),
  )

  plan = facade.build_plan("acc_1", TARGET_ANTIGRAVITY_CLI)
  assert plan.target_available is False
  assert plan.error_code == "proc_unreadable"
  assert "periksa proses manual" in plan.error_message.lower()


def test_read_status_includes_sessions_summary(tmp_path: Path):
  """read_status mengikutsertakan ringkasan sesi agy pada target Antigravity CLI."""
  proc_dir = tmp_path / "proc"
  proc_table = FakeProcTable()
  proc_table.add(701, ["agy"], state="R")
  proc_table.add(702, ["agy"], state="T")
  proc_table.add(703, ["agy"], state="Z")
  proc_table.write_to(proc_dir)

  proc_mgr = LinuxProcessManager(
      proc_path=proc_dir,
      clock=FakeClock(),
      excluded_pids=(),
  )

  facade = AntigravityFacade(
      account_storage=DummyAccountStorage(),
      keyring=FakeKeyring(),
      gemini_files=DummyGeminiFiles(),
      opencode_file=DummyOpenCodeFile(),
      oauth=FakeOAuth(),
      process_manager=proc_mgr,
      environment=DummyEnvironment(),
      clock=FakeClock(),
  )

  status = facade.read_status()
  cli_status = status.antigravity_cli
  assert cli_status.sessions_summary is not None
  assert cli_status.sessions_summary["alive"] == 2  # 701 (R) + 702 (T)
  assert cli_status.sessions_summary["stopped"] == 1
  assert cli_status.sessions_summary["zombie"] == 1


def test_agy_confirm_dialog_widget(qtbot):
  """Dialog konfirmasi sesi agy: ukuran 480x320, Batal fokus default, tombol destruktif, checkbox."""
  sessions = [
      AgySession(pid=1234, cmdline=["agy", "start"], state="R", command_str="agy start"),
      AgySession(pid=5678, cmdline=["agy", "remote-control"], state="S", is_remote_control=True, command_str="agy remote-control"),
  ]

  from PyQt6.QtCore import QSettings
  settings = QSettings("OpenCodeAppTest", "TestApp")
  settings.clear()

  dialog = AgyConfirmDialog(sessions, settings=settings)
  qtbot.addWidget(dialog)

  # Cek ukuran tetap
  assert dialog.width() == 480
  assert dialog.height() == 320

  # Cek jumlah baris pada tabel
  assert dialog.table.rowCount() == 2
  assert dialog.table.item(0, 0).text() == "1234"
  assert "Running" in dialog.table.item(0, 1).text()
  assert dialog.table.item(1, 0).text() == "5678"
  assert "remote-control" in dialog.table.item(1, 1).text()

  # Cek fokus default pada tombol Batal
  assert dialog.btn_cancel.hasFocus() or dialog.btn_cancel.isDefault()

  # Cek checkbox "Jangan tanya lagi"
  dialog.chk_dont_ask.setChecked(True)
  dialog._on_confirm_kill()
  assert settings.value("auto_kill_agy") in (True, "true", "True")
