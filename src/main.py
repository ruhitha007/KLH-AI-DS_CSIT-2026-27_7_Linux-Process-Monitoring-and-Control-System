import sys
import time

from backend.process_manager import ProcessManager


CPU_SAMPLE_INTERVAL_SECONDS = 1.0


def run_console() -> None:
    """Print one resource-monitored process list from /proc."""
    manager = ProcessManager()
    manager.capture_cpu_baseline()
    time.sleep(CPU_SAMPLE_INTERVAL_SECONDS)

    print(
        f"{'PID':>8} {'NAME':<20} {'USER':<16} {'STATE':<6} "
        f"{'PPID':>8} {'CPU %':>8} {'MEMORY %':>10}"
    )
    for basic_process in manager.get_processes():
        process = manager.get_process_details(basic_process.pid)
        if process is None:
            continue

        username = process.username if process.username is not None else "Unknown"
        cpu_percent = (
            f"{process.cpu_percent:.1f}" if process.cpu_percent is not None else "N/A"
        )
        memory_percent = (
            f"{process.memory_percent:.1f}"
            if process.memory_percent is not None
            else "N/A"
        )
        print(
            f"{process.pid:>8} {process.name:<20} {username:<16} "
            f"{process.state:<6} {process.ppid:>8} {cpu_percent:>8} "
            f"{memory_percent:>10}"
        )


def main() -> None:
    """Launch the GUI, with an optional console mode for terminal use."""
    if sys.argv[1:] == ["--console"]:
        run_console()
        return

    try:
        from gui.main_window import run
    except ImportError:
        raise SystemExit(
            "Tkinter is required. On Debian/Ubuntu, install it with: "
            "sudo apt install python3-tk"
        )
    run()


if __name__ == "__main__":
    main()
