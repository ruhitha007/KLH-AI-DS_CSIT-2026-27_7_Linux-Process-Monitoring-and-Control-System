"""Process control backend for Linux.

This module sends POSIX signals directly with :func:`os.kill`. It never runs
shell commands such as ``kill`` or ``pkill``, and it only ever acts on a PID
that the caller explicitly supplies, so no process is controlled implicitly.
"""

import errno
import os
import signal
import sys
from typing import Callable, Optional

# Only these three signals may be sent. More forceful options are deliberately
# not defined, so they cannot be triggered through this application.
# getattr keeps the module importable on platforms without the POSIX signals.
PAUSE_SIGNAL = getattr(signal, "SIGSTOP", None)
RESUME_SIGNAL = getattr(signal, "SIGCONT", None)
TERMINATE_SIGNAL = getattr(signal, "SIGTERM", None)


class ProcessControlError(Exception):
    """Application-level error describing why a control action failed."""

    def __init__(self, message: str, pid: object = None) -> None:
        super().__init__(message)
        self.pid = pid


class ProcessController:
    """Pause, resume, and terminate a process by PID using Linux signals."""

    def __init__(self, send_signal: Optional[Callable[[int, int], None]] = None) -> None:
        # The default sender is resolved at call time so os.kill stays the real
        # production path and can be replaced in tests.
        self._send_signal = send_signal
        self.pause_signal = PAUSE_SIGNAL
        self.resume_signal = RESUME_SIGNAL
        self.terminate_signal = TERMINATE_SIGNAL

    def pause_process(self, pid: int) -> None:
        """Suspend a process with SIGSTOP."""
        self._apply_signal(pid, self.pause_signal, "SIGSTOP", "pause")

    def resume_process(self, pid: int) -> None:
        """Continue a suspended process with SIGCONT."""
        self._apply_signal(pid, self.resume_signal, "SIGCONT", "resume")

    def terminate_process(self, pid: int) -> None:
        """Ask a process to exit with SIGTERM."""
        self._apply_signal(pid, self.terminate_signal, "SIGTERM", "terminate")

    def _apply_signal(
        self,
        pid: int,
        sig: Optional[int],
        signal_name: str,
        action: str,
    ) -> None:
        self._validate_pid(pid, action)

        if sig is None:
            raise ProcessControlError(
                f"{signal_name} is not available on {sys.platform}, so PID {pid} "
                "cannot be controlled here.",
                pid,
            )

        sender = self._send_signal if self._send_signal is not None else os.kill
        try:
            sender(pid, sig)
        except ProcessLookupError:
            raise ProcessControlError(
                f"PID {pid} no longer exists, so it cannot be "
                f"{self._completed_phrase(action)}.",
                pid,
            ) from None
        except PermissionError:
            raise ProcessControlError(
                f"Permission denied: PID {pid} is probably owned by another user "
                "or is a protected system process.",
                pid,
            ) from None
        except OSError as error:
            if error.errno == errno.ESRCH:
                raise ProcessControlError(
                    f"PID {pid} no longer exists, so it cannot be "
                    f"{self._completed_phrase(action)}.",
                    pid,
                ) from None
            reason = error.strerror or str(error)
            raise ProcessControlError(
                f"Could not {action} PID {pid}: {reason}.",
                pid,
            ) from None

    @staticmethod
    def _validate_pid(pid: int, action: str) -> None:
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise ProcessControlError(
                f"PID {pid!r} is not a valid process ID, so it cannot be "
                f"{ProcessController._completed_phrase(action)}.",
                pid,
            )

    @staticmethod
    def _completed_phrase(action: str) -> str:
        return {
            "pause": "paused",
            "resume": "resumed",
            "terminate": "terminated",
        }[action]
