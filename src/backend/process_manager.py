
"""Read-only process monitoring backend for Linux."""

import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

try:
    import pwd
except ImportError:
    # The backend still imports on non-Linux systems so its tests can run there.
    pwd = None


@dataclass(frozen=True)
class ProcessInfo:
    """Information collected for one Linux process."""

    pid: int
    name: str
    state: str
    ppid: int
    username: Optional[str]
    command_line: Optional[str] = None
    cpu_percent: Optional[float] = None
    memory_percent: Optional[float] = None
    runtime_seconds: Optional[float] = None


@dataclass(frozen=True)
class _StatSnapshot:
    """The /proc/PID/stat values needed by the backend."""

    name: str
    state: str
    ppid: int
    cpu_ticks: Optional[int]
    start_time_ticks: Optional[int]


@dataclass(frozen=True)
class _CpuSample:
    """One point in a process's cumulative CPU-time measurement."""

    cpu_ticks: int
    start_time_ticks: Optional[int]
    timestamp: float


class ProcessManager:
    """Discover and monitor process information from a Linux /proc directory."""

    def __init__(
        self,
        proc_root: Union[str, Path] = "/proc",
        clock_ticks: Optional[int] = None,
        monotonic_time: Callable[[], float] = time.monotonic,
    ) -> None:
        self.proc_root = Path(proc_root)
        self._clock_ticks = (
            self._get_system_clock_ticks() if clock_ticks is None else clock_ticks
        )
        if self._clock_ticks is not None and self._clock_ticks <= 0:
            raise ValueError("clock_ticks must be a positive integer")

        self._monotonic_time = monotonic_time
        self._previous_cpu_samples: Dict[int, _CpuSample] = {}

    def get_processes(self) -> List[ProcessInfo]:
        """Return readable processes sorted by PID.

        A process may disappear between reading /proc and reading its files, so
        entries that cannot be read are skipped instead of stopping discovery.
        """
        try:
            entries = list(self.proc_root.iterdir())
        except OSError:
            return []

        processes = []
        for entry in entries:
            # Linux represents processes as numeric directories under /proc.
            if not entry.name.isdigit():
                continue

            pid = int(entry.name)
            if pid <= 0:
                continue

            process = self.get_process_info(pid)
            if process is not None:
                processes.append(process)

        return sorted(processes, key=lambda process: process.pid)

    def get_process_info(self, pid: int) -> Optional[ProcessInfo]:
        """Return information for one PID, or None if it cannot be read."""
        if self._is_invalid_pid(pid):
            return None

        stat = self._read_process_stat(pid)
        if stat is None:
            return None

        return self._build_process_record(pid, stat, include_resources=False)

    def capture_cpu_baseline(self) -> None:
        """Store the first CPU sample for all processes that can be read."""
        self._previous_cpu_samples = {}
        if self._clock_ticks is None:
            return

        timestamp = self._monotonic_time()
        try:
            entries = list(self.proc_root.iterdir())
        except OSError:
            return

        for entry in entries:
            if not entry.name.isdigit():
                continue

            pid = int(entry.name)
            if pid <= 0:
                continue

            stat = self._read_process_stat(pid)
            if stat is None or stat.cpu_ticks is None:
                continue

            self._previous_cpu_samples[pid] = _CpuSample(
                cpu_ticks=stat.cpu_ticks,
                start_time_ticks=stat.start_time_ticks,
                timestamp=timestamp,
            )

    def get_cpu_usage(self, pid: int) -> Optional[float]:
        """Return CPU usage percent since the previous sample for one PID.

        CPU usage requires two samples. Call capture_cpu_baseline(), allow an
        interval to pass, and then call this method. A result is unavailable on
        the first call or when either /proc sample cannot be read.
        """
        if self._is_invalid_pid(pid):
            return None

        stat = self._read_process_stat(pid)
        if stat is None:
            self._previous_cpu_samples.pop(pid, None)
            return None

        return self._cpu_percent_from_stat(pid, stat)

    def _cpu_percent_from_stat(self, pid: int, stat: _StatSnapshot) -> Optional[float]:
        """Compare one stat sample with the stored sample and keep the new one."""
        clock_ticks = self._clock_ticks
        if clock_ticks is None:
            return None
        if stat.cpu_ticks is None:
            self._previous_cpu_samples.pop(pid, None)
            return None

        current_sample = _CpuSample(
            cpu_ticks=stat.cpu_ticks,
            start_time_ticks=stat.start_time_ticks,
            timestamp=self._monotonic_time(),
        )
        previous_sample = self._previous_cpu_samples.get(pid)
        self._previous_cpu_samples[pid] = current_sample

        if previous_sample is None:
            return None

        # A different start time means the PID was reused for another process.
        if (
            previous_sample.start_time_ticks is not None
            and current_sample.start_time_ticks is not None
            and previous_sample.start_time_ticks != current_sample.start_time_ticks
        ):
            return None

        elapsed_seconds = current_sample.timestamp - previous_sample.timestamp
        elapsed_ticks = current_sample.cpu_ticks - previous_sample.cpu_ticks
        if elapsed_seconds <= 0 or elapsed_ticks < 0:
            return None

        # /proc reports cumulative CPU time in clock ticks, not seconds.
        cpu_seconds = elapsed_ticks / clock_ticks
        return (cpu_seconds / elapsed_seconds) * 100.0


    def get_memory_usage(self, pid: int) -> Optional[float]:
        """Return resident memory as a percentage of physical system memory."""
        if self._is_invalid_pid(pid):
            return None

        rss_kb = self._read_rss_kb(self.proc_root / str(pid) / "status")
        total_kb = self._read_total_memory_kb()
        if rss_kb is None or total_kb is None or total_kb <= 0:
            return None

        return (rss_kb / total_kb) * 100.0

    def get_command_line(self, pid: int) -> Optional[str]:
        """Return the command line from /proc/PID/cmdline when available."""
        if self._is_invalid_pid(pid):
            return None

        try:
            command_bytes = (self.proc_root / str(pid) / "cmdline").read_bytes()
        except OSError:
            return None

        # Linux separates command-line arguments with NUL bytes. Kernel threads
        # have an empty cmdline file, so they correctly return None here.
        arguments = [
            argument.decode("utf-8", errors="replace")
            for argument in command_bytes.split(b"\0")
            if argument
        ]
        if not arguments:
            return None
        return " ".join(arguments)

    def get_runtime_seconds(self, pid: int) -> Optional[float]:
        """Return elapsed wall-clock runtime from /proc uptime and starttime."""
        if self._is_invalid_pid(pid) or self._clock_ticks is None:
            return None

        stat = self._read_process_stat(pid)
        if stat is None:
            return None

        return self._runtime_from_stat(stat)

    def _runtime_from_stat(self, stat: _StatSnapshot) -> Optional[float]:
        """Return runtime from an already-read stat sample."""
        clock_ticks = self._clock_ticks
        if clock_ticks is None or stat.start_time_ticks is None:
            return None

        uptime_seconds = self._read_uptime_seconds()
        if uptime_seconds is None:
            return None

        runtime_seconds = uptime_seconds - stat.start_time_ticks / clock_ticks
        if runtime_seconds < 0:
            return None
        return runtime_seconds

    def get_process_details(self, pid: int) -> Optional[ProcessInfo]:
        """Return Part 1 fields together with available resource details."""
        if self._is_invalid_pid(pid):
            return None

        stat = self._read_process_stat(pid)
        if stat is None:
            return None

        return self._build_process_record(pid, stat, include_resources=True)

    def _build_process_record(
        self,
        pid: int,
        stat: _StatSnapshot,
        include_resources: bool,
    ) -> ProcessInfo:
        """Build one record, reusing a single stat read for every value.

        The CPU and runtime values are derived from the stat sample that was
        already read, so a details lookup does not re-read /proc/PID/stat once
        per value during a refresh.
        """
        process_dir = self.proc_root / str(pid)
        uid = self._read_uid(process_dir / "status")
        username = self._get_username(uid) if uid is not None else None

        if not include_resources:
            return ProcessInfo(
                pid=pid,
                name=stat.name,
                state=stat.state,
                ppid=stat.ppid,
                username=username,
            )

        return ProcessInfo(
            pid=pid,
            name=stat.name,
            state=stat.state,
            ppid=stat.ppid,
            username=username,
            command_line=self.get_command_line(pid),
            cpu_percent=self._cpu_percent_from_stat(pid, stat),
            memory_percent=self.get_memory_usage(pid),
            runtime_seconds=self._runtime_from_stat(stat),
        )

    def _read_process_stat(self, pid: int) -> Optional[_StatSnapshot]:
        """Read and parse one /proc/PID/stat file."""
        stat_path = self.proc_root / str(pid) / "stat"
        try:
            stat_text = stat_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            # The process may exit or become inaccessible between samples.
            return None
        return self._parse_stat(pid, stat_text)

    @staticmethod
    def _is_invalid_pid(pid: int) -> bool:
        return isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0

    @staticmethod
    def _parse_nonnegative_int(value: str) -> Optional[int]:
        try:
            number = int(value)
        except ValueError:
            return None
        return number if number >= 0 else None

    @staticmethod
    def _parse_stat(pid: int, stat_text: str) -> Optional[_StatSnapshot]:
        """Parse the values needed from /proc/PID/stat."""
        try:
            # The command name is enclosed in parentheses and may contain both
            # spaces and closing parentheses, so the final ')' is the delimiter.
            pid_and_name, fields_text = stat_text.rsplit(")", 1)
            reported_pid_text, name = pid_and_name.split("(", 1)
            fields = fields_text.split()
            reported_pid = int(reported_pid_text)
        except (IndexError, ValueError):
            return None

        if reported_pid != pid or len(fields) < 2 or len(fields[0]) != 1:
            return None

        ppid = ProcessManager._parse_nonnegative_int(fields[1])
        if ppid is None:
            return None

        cpu_ticks = None
        if len(fields) >= 13:
            user_ticks = ProcessManager._parse_nonnegative_int(fields[11])
            system_ticks = ProcessManager._parse_nonnegative_int(fields[12])
            if user_ticks is not None and system_ticks is not None:
                cpu_ticks = user_ticks + system_ticks

        start_time_ticks = None
        if len(fields) >= 20:
            start_time_ticks = ProcessManager._parse_nonnegative_int(fields[19])

        return _StatSnapshot(
            name=name,
            state=fields[0],
            ppid=ppid,
            cpu_ticks=cpu_ticks,
            start_time_ticks=start_time_ticks,
        )

    @staticmethod
    def _get_system_clock_ticks() -> Optional[int]:
        """Return the kernel's user/system CPU clock frequency."""
        try:
            ticks_per_second = os.sysconf("SC_CLK_TCK")
        except (AttributeError, OSError, ValueError):
            return None
        return ticks_per_second if ticks_per_second > 0 else None

    def _read_rss_kb(self, status_path: Path) -> Optional[int]:
        """Read VmRSS, the process's resident set size, from /proc/PID/status."""
        try:
            status_text = status_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        for line in status_text.splitlines():
            if line.startswith("VmRSS:"):
                fields = line.split()
                if len(fields) < 3 or fields[2] != "kB":
                    return None
                return self._parse_nonnegative_int(fields[1])
        return None

    def _read_total_memory_kb(self) -> Optional[int]:
        """Read total physical memory from /proc/meminfo."""
        try:
            meminfo_text = (self.proc_root / "meminfo").read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            return None

        for line in meminfo_text.splitlines():
            if line.startswith("MemTotal:"):
                fields = line.split()
                if len(fields) < 3 or fields[2] != "kB":
                    return None
                return self._parse_nonnegative_int(fields[1])
        return None

    def _read_uptime_seconds(self) -> Optional[float]:
        """Read system uptime from /proc/uptime."""
        try:
            uptime_text = (self.proc_root / "uptime").read_text(
                encoding="utf-8", errors="replace"
            )
            uptime_seconds = float(uptime_text.split()[0])
        except (IndexError, OSError, ValueError):
            return None

        if not math.isfinite(uptime_seconds) or uptime_seconds < 0:
            return None
        return uptime_seconds

    def _read_uid(self, status_path: Path) -> Optional[int]:
        """Read the real user ID from /proc/PID/status when available."""
        try:
            status_text = status_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            # User information is optional, so a vanished or restricted status
            # file does not prevent the rest of the process record being used.
            return None

        for line in status_text.splitlines():
            if line.startswith("Uid:"):
                fields = line.split()
                if len(fields) < 2:
                    return None
                try:
                    return int(fields[1])
                except ValueError:
                    return None

        return None

    @staticmethod
    def _get_username(uid: int) -> Optional[str]:
        """Translate a Linux user ID into a username when possible."""
        if pwd is None:
            return None

        try:
            return pwd.getpwuid(uid).pw_name
        except (KeyError, OSError, OverflowError):
            # The numeric ID is still useful when no passwd entry can be found.
            return str(uid)
