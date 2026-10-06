# Linux Process Management System

A Linux-based process monitoring and control system that provides a graphical interface for viewing running processes, monitoring CPU and memory usage, inspecting process details, and performing basic process-control operations such as pause, resume, and termination.

---

## Team Members

| S. No. | Name | ID Number |
|--------|------|-----------|
| 1 | P. Ruhitha | 2520080053 |
| 2 | M. Ananya | 2520080069 |
| 3 | CH. Madhulika | 2520090056 |

### Supervisor

**Dr. Raghupathi Manthena**

---

## Project Status

**Status: Completed**

The project has been implemented, tested, and integrated into a functional Linux desktop application.

---

## Abstract

Modern operating systems manage multiple processes simultaneously, making process monitoring and control an important operating-system functionality. This project presents a Linux-based Process Management System that allows users to view information about currently running processes and perform basic process-control operations through a graphical interface.

The application is implemented using Python and Linux/POSIX mechanisms. It obtains process information directly from the Linux `/proc` pseudo-filesystem, including Process ID (PID), process name, process state, parent process ID, username, CPU usage, memory usage, runtime, and command-line information.

The system also provides basic process-control operations using Linux signals. Users can explicitly select a process and pause, resume, or terminate it. The application uses `SIGSTOP` for pausing, `SIGCONT` for resuming, and `SIGTERM` for requesting process termination. Safety measures such as process selection requirements and confirmation before termination are included.

The project demonstrates important Operating Systems concepts including process management, the Linux `/proc` filesystem, process states, CPU and memory monitoring, POSIX signals, system calls, and interaction between user-space applications and the Linux kernel.

---

## 1. Project Objective

The main objective of this project is to develop a simple and practical Linux process monitoring and control application.

The system aims to:

- Display information about currently running processes.
- Show Process ID (PID), process name, process state, parent PID, and username.
- Monitor CPU and memory usage.
- Display process runtime and command-line information.
- Allow users to search for processes.
- Allow users to view detailed information about a selected process.
- Provide process-control operations such as:
  - Pause
  - Resume
  - Terminate
- Demonstrate the use of the Linux `/proc` filesystem.
- Demonstrate POSIX signals and Linux process-control mechanisms.
- Provide a practical understanding of how user-space applications interact with the Linux kernel.

---

## 2. Key Features

### Process Monitoring

The application displays:

- Process ID (PID)
- Process name
- Username
- Process state
- Parent Process ID (PPID)
- CPU usage percentage
- Memory usage percentage
- Runtime

### Process Search

Users can search for processes using:

- PID
- Process name
- Username

### Process Details

A selected process can be opened in a separate details window showing:

- PID
- Process name
- State
- User
- Parent PID
- CPU usage
- Memory usage
- Runtime
- Full command line

### Process Control

The system supports:

- **Pause** → `SIGSTOP`
- **Resume** → `SIGCONT`
- **Terminate** → `SIGTERM`

### Safety Features

- A process must be explicitly selected before an operation can be performed.
- Termination requires user confirmation.
- The application does not use `SIGKILL`.
- Invalid or unavailable PIDs are handled safely.
- Permission errors are reported to the user.
- Processes that disappear while being monitored are handled gracefully.

---

## 3. Technologies Used

| Technology | Purpose |
|------------|---------|
| Python 3.8+ | Main programming language |
| Tkinter / ttk | Graphical user interface |
| Linux `/proc` | Process information and system statistics |
| POSIX Signals | Process control |
| `os.kill()` | Sending signals to processes |
| `pwd` module | Converting user IDs to usernames |
| `unittest` | Automated testing |
| `unittest.mock` | Mocking system interactions during testing |
| Git / GitHub | Version control and project repository |

### External Dependencies

The project does not require third-party Python packages.

It uses Python's standard library and Linux system interfaces.

---

## 4. System Requirements

The project is intended to run on Linux.

### Required

- Linux operating system
- Python 3.8 or newer
- `/proc` filesystem
- Tkinter
- Graphical desktop environment

### Ubuntu / Debian

Install Python and Tkinter if required:

```bash
sudo apt update
sudo apt install python3 python3-tk
