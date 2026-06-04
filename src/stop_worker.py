import os
import signal
import sys
from pathlib import Path


PID_FILE = Path("logs") / "cognitor-worker.pid"


def main() -> None:
    if not PID_FILE.exists():
        print("No PID file found. Is the worker running in daemon mode?")
        sys.exit(1)

    pid_text = PID_FILE.read_text().strip()
    try:
        pid = int(pid_text)
    except ValueError:
        print(f"Invalid PID in file: {pid_text!r}")
        PID_FILE.unlink(missing_ok=True)
        sys.exit(1)

    try:
        if os.name == "nt":
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(1, False, pid)
            ctypes.windll.kernel32.TerminateProcess(handle, 0)
            ctypes.windll.kernel32.CloseHandle(handle)
        else:
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print(f"No process with PID {pid}. It may have already stopped.")
    except PermissionError:
        print(f"Permission denied to stop process {pid}.")
        sys.exit(1)
    else:
        print(f"Sent stop signal to Cognitor worker (PID {pid}).")
    finally:
        PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
