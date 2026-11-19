"""Integration test opt-in: jalur sinyal proses nyata.

Memastikan lingkungan host mendukung ``SIGCONT`` → ``SIGTERM`` untuk proses
yang sedang di-``SIGSTOP``. Tidak berjalan di suite default.
"""

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _process_state(pid: int) -> str:
  stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
  return stat.rsplit(")", 1)[1].split()[0]


def test_stopped_sleep_process_can_be_terminated():
  if not os.path.isdir("/proc"):
    pytest.skip("/proc tidak tersedia")

  process = subprocess.Popen(["sleep", "30"])
  try:
    process.send_signal(signal.SIGSTOP)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
      if _process_state(process.pid) in ("T", "t"):
        break
      time.sleep(0.02)
    assert _process_state(process.pid) in ("T", "t")

    os.kill(process.pid, signal.SIGCONT)
    process.terminate()

    try:
      process.wait(timeout=3)
    except subprocess.TimeoutExpired:
      process.kill()
      process.wait(timeout=2)
      pytest.fail("sleep tidak berhenti setelah SIGCONT → SIGTERM")

    assert process.poll() is not None
  finally:
    if process.poll() is None:
      process.kill()
      process.wait(timeout=2)
