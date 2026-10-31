# Linux Process Monitoring and Control System

## 1. Team Details

**Team Members:**
1. M. Ananya – 2520080069
2. P. Ruhitha – 2520080053
3. CH. Madhulika – 2520090056

**Project Supervisor:** Dr. M. Raghupathi

## 2. Abstract

The Linux Process Monitoring and Control System is a Python-based application developed to monitor and manage processes in a Linux operating system. It provides a graphical interface using Tkinter to display process information such as PID, process name, username, process state, CPU usage, memory usage, and PPID.

The application retrieves information from the Linux `/proc` pseudo-filesystem and allows users to search, view details, pause, resume, and terminate processes using POSIX signals. The project demonstrates important Operating Systems concepts such as process management, resource monitoring, process states, and kernel interaction.

## 3. Technologies Used

- Python 3
- Tkinter
- Linux `/proc` filesystem
- Python `os` and `signal` modules
- `unittest` and `unittest.mock`

## 4. Key Features

- Displays running processes and their details.
- Monitors CPU and memory usage.
- Supports process search and automatic refresh.
- Provides detailed process information.
- Pauses processes using `SIGSTOP`.
- Resumes processes using `SIGCONT`.
- Terminates processes using `SIGTERM`.
- Includes error handling and termination confirmation.

## 5. Project Structure

```text
OS_Project/
├── main.py
├── backend/
│   ├── process_manager.py
│   └── process_controller.py
├── gui/
│   └── main_window.py
├── tests/
│   ├── test_process_manager.py
│   ├── test_process_controller.py
│   └── test_main_window.py
└── README.md
```

## 6. Setup and Execution Instructions

**Prerequisites:** Linux, Python 3.8 or later, and Tkinter.

**Step 1: Install dependencies**

```bash
sudo apt update
sudo apt install python3 python3-tk
```

**Step 2: Clone the repository**

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL>
```

**Step 3: Navigate to the project folder**

```bash
cd OS_Project
```

**Step 4: Run the application**

```bash
python3 main.py
```

**Optional – Run in console mode**

```bash
python3 main.py --console
```

**Step 5: Run automated tests**

```bash
python3 -m unittest discover -s tests -v
```

## 7. Testing

The project uses Python's `unittest` framework to test process monitoring, process-control operations, and GUI functionality.

Recorded test results:
- Total tests: 44
- Passed: 43
- Skipped: 1
- Failed: 0

## 8. Current Phase Status

**Project Status: COMPLETED**

- Project architecture and implementation completed.
- Process monitoring using `/proc` implemented.
- CPU and memory usage calculations implemented.
- Tkinter graphical interface developed.
- Pause, Resume, and Terminate operations implemented using POSIX signals.
- Error handling and safety checks incorporated.
- Automated test cases developed and executed.
- Project documentation completed.

## 9. Project Outcome

Developed a Python-based Linux application that enables users to monitor process information and control running processes through a graphical interface, demonstrating essential Operating Systems concepts.

## 10. References

- Linux `/proc` filesystem documentation.
- Linux process signals documentation.
- Python documentation: `os`, `signal`, `tkinter`, and `unittest` modules.
