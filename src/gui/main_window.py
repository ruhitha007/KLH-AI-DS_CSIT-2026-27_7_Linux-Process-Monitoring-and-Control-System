"""Tkinter interface for the Linux process monitor."""

import logging
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, List, Optional, Tuple

from backend.process_controller import ProcessControlError, ProcessController
from backend.process_manager import ProcessInfo, ProcessManager


APP_TITLE = "Linux Process Monitoring and Control System"
TABLE_COLUMNS = ("pid", "name", "user", "state", "cpu", "memory", "ppid")
SEARCH_DELAY_MS = 250
AUTO_REFRESH_INTERVAL_MS = 1500
PROCESS_STATE_NAMES = {
    "R": "Running",
    "S": "Sleeping",
    "D": "Waiting",
    "Z": "Zombie",
    "T": "Stopped",
    "I": "Idle",
}
LOGGER = logging.getLogger(__name__)


def format_percentage(value: Optional[float]) -> str:
    """Format an optional percentage for display."""
    return "N/A" if value is None else f"{value:.1f}"


def format_percent_value(value: Optional[float]) -> str:
    """Format an optional percentage with a percent sign for the details view."""
    return "N/A" if value is None else f"{value:.1f}%"


def format_runtime(seconds: Optional[float]) -> str:
    """Format a runtime in hours, minutes, and seconds."""
    if seconds is None or seconds < 0:
        return "N/A"
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}"


def format_state(state: str) -> str:
    """Return a readable description of a Linux process state code."""
    description = PROCESS_STATE_NAMES.get(state)
    return f"{description} ({state})" if description is not None else state


def process_matches_search(process: ProcessInfo, query: str) -> bool:
    """Match a process against PID, name, or username, ignoring case."""
    normalized_query = query.strip().casefold()
    if not normalized_query:
        return True

    searchable_values = (
        str(process.pid),
        process.name,
        process.username if process.username is not None else "",
    )
    return any(
        normalized_query in value.casefold() for value in searchable_values
    )


def format_process_row(process: ProcessInfo) -> Tuple[str, ...]:
    """Convert a backend record into values for the process table."""
    return (
        str(process.pid),
        process.name if process.name else "Unknown",
        process.username if process.username is not None else "Unknown",
        process.state,
        format_percentage(process.cpu_percent),
        format_percentage(process.memory_percent),
        str(process.ppid),
    )


class ProcessMonitorApp:
    """Main window that displays process data supplied by ProcessManager."""

    def __init__(
        self,
        root: tk.Tk,
        process_manager: Optional[ProcessManager] = None,
        process_controller: Optional[ProcessController] = None,
    ) -> None:
        self.root = root
        self.process_manager = (
            process_manager if process_manager is not None else ProcessManager()
        )
        self.process_controller = (
            process_controller
            if process_controller is not None
            else ProcessController()
        )
        self.selected_pid: Optional[int] = None
        self.cpu_sampling_available = True
        self._process_snapshot: List[ProcessInfo] = []
        self._unavailable_count = 0
        self._filtered_count = 0
        self._search_after_id: Optional[str] = None
        self._auto_refresh_after_id: Optional[str] = None
        self._refreshing = False
        self._updating = False
        self._selection_note = ""
        self._refresh_error_reported = False

        self.root.title(APP_TITLE)
        self.root.geometry("980x540")
        self.root.minsize(760, 360)

        self._build_interface()
        self._capture_cpu_baseline()
        self.refresh()
        self._schedule_auto_refresh()

    def _build_interface(self) -> None:
        header = ttk.Frame(self.root, padding=(12, 10))
        header.pack(fill=tk.X)
        ttk.Label(
            header,
            text=APP_TITLE,
            font=("TkDefaultFont", 15, "bold"),
        ).pack(side=tk.LEFT)

        toolbar = ttk.Frame(self.root, padding=(12, 0, 12, 8))
        toolbar.pack(fill=tk.X)

        action_frame = ttk.Frame(toolbar)
        action_frame.pack(side=tk.RIGHT)
        ttk.Button(action_frame, text="Refresh", command=self.refresh).pack(side=tk.LEFT)
        ttk.Button(
            action_frame,
            text="View Details",
            command=self._open_details_window,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            action_frame,
            text="Terminate",
            command=self._terminate_selected_process,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            action_frame,
            text="Resume",
            command=self._resume_selected_process,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            action_frame,
            text="Pause",
            command=self._pause_selected_process,
        ).pack(side=tk.LEFT, padx=(8, 0))

        search_frame = ttk.Frame(toolbar)
        search_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
        self.search_text = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_text)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        ttk.Button(search_frame, text="Clear", command=self._clear_search).pack(
            side=tk.LEFT
        )
        self.search_text.trace_add("write", self._schedule_search)

        table_frame = ttk.Frame(self.root, padding=(12, 0))
        table_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(
            table_frame,
            columns=TABLE_COLUMNS,
            show="headings",
            selectmode="browse",
        )
        column_settings = (
            ("pid", "PID", 80, tk.E),
            ("name", "Process Name", 240, tk.W),
            ("user", "User", 150, tk.W),
            ("state", "State", 70, tk.CENTER),
            ("cpu", "CPU %", 90, tk.E),
            ("memory", "Memory %", 100, tk.E),
            ("ppid", "Parent PID", 100, tk.E),
        )
        for column, heading, width, anchor in column_settings:
            self.tree.heading(column, text=heading)
            self.tree.column(
                column,
                width=width,
                minwidth=60,
                anchor=anchor,
                stretch=column == "name",
            )

        scrollbar = ttk.Scrollbar(
            table_frame,
            orient=tk.VERTICAL,
            command=self.tree.yview,
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._on_process_selected)
        self.tree.bind("<Return>", self._open_details_window)

        status_frame = ttk.Frame(self.root, padding=(12, 8))
        status_frame.pack(fill=tk.X)
        self.process_count_text = tk.StringVar(value="Processes: 0")
        self.selected_pid_text = tk.StringVar(value="Selected PID: None")
        self.status_note_text = tk.StringVar(value="")
        self.status_text = tk.StringVar(value="Status: Ready")
        self.updated_text = tk.StringVar(value="")

        ttk.Label(status_frame, textvariable=self.process_count_text).pack(side=tk.LEFT)
        ttk.Label(
            status_frame,
            textvariable=self.selected_pid_text,
        ).pack(side=tk.LEFT, padx=(20, 0))
        ttk.Label(
            status_frame,
            textvariable=self.status_note_text,
        ).pack(side=tk.LEFT, padx=(20, 0))
        ttk.Label(
            status_frame,
            textvariable=self.status_text,
        ).pack(side=tk.LEFT, padx=(20, 0))
        ttk.Label(status_frame, textvariable=self.updated_text).pack(side=tk.RIGHT)

    def _capture_cpu_baseline(self) -> None:
        # CPU percentage needs a baseline. The next refresh, automatic or
        # manual, supplies the second sample that produces the first value.
        try:
            self.process_manager.capture_cpu_baseline()
        except Exception:
            self.cpu_sampling_available = False
            LOGGER.exception("Could not capture the initial CPU baseline")

    def _schedule_auto_refresh(self) -> None:
        """Queue the next periodic refresh using Tkinter's after() callback.

        Using a single one-shot callback keeps the GUI responsive without a
        thread, a while loop, or a repeating call that could overlap.
        """
        self._cancel_auto_refresh()
        self._auto_refresh_after_id = self.root.after(
            AUTO_REFRESH_INTERVAL_MS, self._auto_refresh_tick
        )

    def _cancel_auto_refresh(self) -> None:
        if self._auto_refresh_after_id is None:
            return
        try:
            self.root.after_cancel(self._auto_refresh_after_id)
        except tk.TclError:
            pass
        self._auto_refresh_after_id = None

    def _auto_refresh_tick(self) -> None:
        self._auto_refresh_after_id = None
        try:
            self.refresh()
        finally:
            # Reschedule even if a refresh fails so monitoring keeps running.
            self._schedule_auto_refresh()

    def refresh(self) -> None:
        """Request current process data and update the table and status area."""
        if self._refreshing:
            return
        self._refreshing = True
        try:
            self._refresh_table()
        finally:
            self._refreshing = False

    def _refresh_table(self) -> None:
        previous_pid = self.selected_pid

        try:
            processes = self.process_manager.get_processes()
            snapshot: List[ProcessInfo] = []
            unavailable = 0

            for basic_process in processes:
                try:
                    process = self.process_manager.get_process_details(basic_process.pid)
                except Exception as error:
                    unavailable += 1
                    LOGGER.warning("Skipping PID %s: %s", basic_process.pid, error)
                    continue

                if process is None:
                    unavailable += 1
                    continue
                snapshot.append(process)
        except Exception:
            LOGGER.exception("Could not read process information")
            # Automatic refresh repeats on a timer, so report a failure once
            # instead of showing the same dialog on every interval.
            if not self._refresh_error_reported:
                self._refresh_error_reported = True
                messagebox.showerror(
                    "Refresh failed",
                    "Process information could not be read.\n\n"
                    "Check that the application is running on Linux with access "
                    "to /proc, then try again.",
                    parent=self.root,
                )
            return

        self._refresh_error_reported = False
        self._process_snapshot = snapshot
        self._unavailable_count = unavailable
        self._apply_search(previous_pid=previous_pid)

    def _on_process_selected(self, _event: Optional[tk.Event] = None) -> None:
        # Ignore events caused by the application restoring a selection itself.
        if self._updating:
            return

        selection = self.tree.selection()
        new_pid: Optional[int] = None
        if selection:
            try:
                new_pid = int(selection[0])
            except ValueError:
                new_pid = None

        # A status line about a previous action would be misleading once the
        # user moves to a different process.
        if new_pid != self.selected_pid:
            self.status_text.set("Status: Ready")
        self.selected_pid = new_pid
        self._selection_note = ""
        self._update_status()

    def _schedule_search(self, *_args: object) -> None:
        """Debounce typing so filtering runs once the user pauses."""
        self._cancel_scheduled_search()
        self._search_after_id = self.root.after(
            SEARCH_DELAY_MS, self._run_scheduled_search
        )

    def _run_scheduled_search(self) -> None:
        self._search_after_id = None
        self._apply_search()

    def _cancel_scheduled_search(self) -> None:
        if self._search_after_id is None:
            return
        try:
            self.root.after_cancel(self._search_after_id)
        except tk.TclError:
            pass
        self._search_after_id = None

    def _clear_search(self) -> None:
        self.search_text.set("")
        self._cancel_scheduled_search()
        self._apply_search()

    def _apply_search(self, previous_pid: Optional[int] = None) -> None:
        """Filter the cached snapshot and repopulate the table.

        Filtering only re-reads data already collected by refresh(), so typing
        never queries /proc; a refresh simply re-applies the current search.
        """
        if previous_pid is None:
            previous_pid = self.selected_pid

        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)

        query = self.search_text.get().strip()
        filtered = [
            process
            for process in self._process_snapshot
            if process_matches_search(process, query)
        ]

        self._filtered_count = len(filtered)
        for process in filtered:
            self.tree.insert(
                "", tk.END, iid=str(process.pid), values=format_process_row(process)
            )

        self._restore_selection(previous_pid)
        self._update_status()

    def _restore_selection(self, previous_pid: Optional[int]) -> None:
        """Keep a visible process selected and explain when it is filtered out."""
        self._updating = True
        try:
            if previous_pid is None:
                self.selected_pid = None
                self._selection_note = ""
                return

            row_id = str(previous_pid)
            if not self.tree.exists(row_id):
                self.selected_pid = None
                still_in_snapshot = any(
                    process.pid == previous_pid for process in self._process_snapshot
                )
                if still_in_snapshot:
                    self._selection_note = (
                        f"The selected process (PID {previous_pid}) is hidden by "
                        "the current search."
                    )
                else:
                    self._selection_note = (
                        "The selected process is no longer available."
                    )
                return

            self.selected_pid = previous_pid
            self.tree.selection_set(row_id)
            self.tree.focus(row_id)
            self._selection_note = ""
        finally:
            self._updating = False

    def _selected_process_record(self) -> Optional[ProcessInfo]:
        """Return the cached record for the selected PID, if it is displayed."""
        if self.selected_pid is None:
            return None
        for process in self._process_snapshot:
            if process.pid == self.selected_pid:
                return process
        return None

    def _pause_selected_process(self) -> None:
        self._run_control_action(
            self.process_controller.pause_process, "Pause", "paused"
        )

    def _resume_selected_process(self) -> None:
        self._run_control_action(
            self.process_controller.resume_process, "Resume", "resumed"
        )

    def _terminate_selected_process(self) -> None:
        """Ask the user to confirm, then send SIGTERM to the selected process."""
        record = self._selected_process_record()
        if record is None:
            self._show_no_selection_warning("Terminate")
            return

        name = record.name if record.name else "this process"
        confirmed = messagebox.askyesno(
            "Confirm terminate",
            f"Terminate {name} (PID {record.pid})?\n\n"
            "The process is asked to exit and may not be able to close cleanly.",
            parent=self.root,
        )
        if not confirmed:
            self.status_text.set(f"Status: Terminate cancelled for PID {record.pid}")
            return

        self._run_control_action(
            self.process_controller.terminate_process, "Terminate", "terminated"
        )

    def _show_no_selection_warning(self, action_label: str) -> None:
        messagebox.showwarning(
            "No process selected",
            f"Select a process in the table before choosing {action_label}.",
            parent=self.root,
        )
        self.status_text.set(f"Status: No process selected to {action_label.lower()}")

    def _run_control_action(
        self,
        action: Callable[[int], None],
        action_label: str,
        completed_label: str,
    ) -> None:
        """Send one control signal to the selected PID and report the result."""
        pid = self.selected_pid
        if pid is None:
            self._show_no_selection_warning(action_label)
            return

        try:
            action(pid)
        except ProcessControlError as error:
            LOGGER.warning(
                "Could not %s PID %s: %s", action_label.lower(), pid, error
            )
            messagebox.showerror(
                f"{action_label} failed",
                str(error),
                parent=self.root,
            )
            self.status_text.set(f"Status: {action_label} failed for PID {pid}")
            return
        except Exception:
            LOGGER.exception(
                "Unexpected error while trying to %s PID %s",
                action_label.lower(),
                pid,
            )
            messagebox.showerror(
                f"{action_label} failed",
                f"PID {pid} could not be {completed_label}.\n\n"
                "An unexpected error occurred. See the log for details.",
                parent=self.root,
            )
            self.status_text.set(f"Status: {action_label} failed for PID {pid}")
            return

        self.status_text.set(f"Status: {completed_label.capitalize()} PID {pid}")
        # Show the effect immediately, for example a stopped state or a row that
        # is gone after termination.
        self.refresh()

    def _open_details_window(self, *_args: object) -> Optional[tk.Toplevel]:
        """Show the selected process details in a separate window."""
        if self.selected_pid is None:
            messagebox.showwarning(
                "No process selected",
                "Select a process in the table before viewing its details.",
                parent=self.root,
            )
            return None

        pid = self.selected_pid
        try:
            process = self.process_manager.get_process_details(pid)
        except Exception:
            LOGGER.exception("Could not read details for PID %s", pid)
            messagebox.showerror(
                "Details unavailable",
                f"Details for PID {pid} could not be read.\n\n"
                "Refresh the table and try again.",
                parent=self.root,
            )
            return None

        if process is None:
            messagebox.showwarning(
                "Process unavailable",
                f"PID {pid} is no longer running, so its details are unavailable.\n\n"
                "Refresh the table to see the current processes.",
                parent=self.root,
            )
            return None

        return self._build_details_window(process)

    def _build_details_window(self, process: ProcessInfo) -> tk.Toplevel:
        """Create a read-only window describing one process."""
        window = tk.Toplevel(self.root)
        window.title(f"Process Details - PID {process.pid}")
        window.geometry("620x400")
        window.minsize(480, 320)
        window.transient(self.root)

        frame = ttk.Frame(window, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)

        fields = (
            ("PID", str(process.pid)),
            ("Process Name", process.name if process.name else "Unknown"),
            ("State", format_state(process.state)),
            ("User", process.username if process.username is not None else "Unknown"),
            ("Parent PID", str(process.ppid)),
            ("CPU Usage", format_percent_value(process.cpu_percent)),
            ("Memory Usage", format_percent_value(process.memory_percent)),
            ("Runtime", format_runtime(process.runtime_seconds)),
        )
        for row, (label, value) in enumerate(fields):
            ttk.Label(frame, text=f"{label}:", font=("TkDefaultFont", 10, "bold")).grid(
                row=row, column=0, sticky=tk.NW, padx=(0, 12), pady=3
            )
            ttk.Label(frame, text=value, wraplength=440, justify=tk.LEFT).grid(
                row=row, column=1, sticky=tk.NW, pady=3
            )

        command_row = len(fields) + 1
        ttk.Separator(frame).grid(
            row=command_row, column=0, columnspan=2, sticky=tk.EW, pady=10
        )
        ttk.Label(
            frame,
            text="Full Command:",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=command_row + 1, column=0, columnspan=2, sticky=tk.NW)
        ttk.Label(
            frame,
            text=(
                process.command_line
                if process.command_line
                else "Not available (kernel threads have no command line)."
            ),
            wraplength=580,
            justify=tk.LEFT,
        ).grid(
            row=command_row + 2, column=0, columnspan=2, sticky=tk.NW, pady=(4, 0)
        )

        ttk.Button(window, text="Close", command=window.destroy).pack(
            side=tk.BOTTOM, pady=(0, 12)
        )
        return window

    def _update_status(self) -> None:
        """Refresh the status bar from the current snapshot and search state."""
        process_count = len(self._process_snapshot)
        query = self.search_text.get().strip()
        notes: List[str] = []

        if query:
            count_text = (
                f"Showing: {self._filtered_count} of {process_count} "
                f"matching \"{query}\""
            )
        else:
            count_text = f"Processes: {process_count}"

        if process_count == 0:
            notes.append("No readable processes were found. Check access to /proc.")
        if self._unavailable_count:
            count_text += f" | Unavailable: {self._unavailable_count}"
            notes.append("Some processes exited or could not be read.")
        if not self.cpu_sampling_available:
            count_text += " | CPU sampling unavailable"
            notes.append("CPU usage could not be measured.")
        if self._selection_note:
            notes.append(self._selection_note)

        if self.selected_pid is None:
            self.selected_pid_text.set("Selected PID: None")
        else:
            self.selected_pid_text.set(f"Selected PID: {self.selected_pid}")

        self.process_count_text.set(count_text)
        self.status_note_text.set(" | ".join(notes))
        self.updated_text.set(f"Updated: {time.strftime('%H:%M:%S')}")


def run() -> None:
    """Create the Tkinter application and start its event loop."""
    logging.basicConfig(level=logging.INFO)
    root = tk.Tk()
    ProcessMonitorApp(root)
    root.mainloop()
