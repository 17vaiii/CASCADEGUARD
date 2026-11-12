"""Small Windows desktop launcher for the existing local CascadeGuard dashboard."""

from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

APP_URL = "http://127.0.0.1:8501"
CORE_MODULES = ("numpy", "pandas", "pandapower", "torch", "sklearn", "yaml", "joblib", "pyarrow")
DASHBOARD_MODULES = ("streamlit", "plotly", "ortools")


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def runtime_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    path = base / "CascadeGuard"
    path.mkdir(parents=True, exist_ok=True)
    return path


def hidden_startup() -> subprocess.STARTUPINFO:
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0
    return info


def python_launcher() -> tuple[str, ...]:
    py = shutil.which("py")
    if py:
        probe = subprocess.run([py, "-3.12", "-c", "import sys; print(sys.executable)"],
                               capture_output=True, text=True, startupinfo=hidden_startup())
        if probe.returncode == 0 and probe.stdout.strip():
            return (py, "-3.12")
    python = shutil.which("python")
    if python:
        probe = subprocess.run([python, "-c", "import sys; print(sys.version_info[:2]); print(sys.executable)"],
                               capture_output=True, text=True, startupinfo=hidden_startup())
        if probe.returncode == 0 and "(3, 12)" in probe.stdout:
            return (python,)
    raise RuntimeError("Python 3.12 was not found. Install Python 3.12, then open CascadeGuard.exe again.")


def imports_available(python: Path, modules: tuple[str, ...]) -> bool:
    return not missing_modules(python, modules)


def dashboard_versions_supported(python: Path) -> bool:
    """Check versions as well as imports; old dashboard packages can import but fail at runtime."""
    code = (
        "from importlib.metadata import version; import sys; "
        "parts=lambda name: tuple(int(p) for p in version(name).split('.')[:2]); "
        "ok=(parts('streamlit') >= (1, 51) and parts('streamlit') < (2, 0) "
        "and parts('plotly') >= (5, 24) and parts('plotly') < (7, 0)); "
        "sys.exit(0 if ok else 1)"
    )
    result = subprocess.run([str(python), "-c", code], capture_output=True, text=True,
                            startupinfo=hidden_startup())
    return result.returncode == 0


def missing_modules(python: Path, modules: tuple[str, ...]) -> list[str]:
    code = "import importlib.util,sys; missing=[m for m in sys.argv[1:] if importlib.util.find_spec(m) is None]; print('\\n'.join(missing)); sys.exit(bool(missing))"
    result = subprocess.run([str(python), "-c", code, *modules], capture_output=True, text=True,
                            startupinfo=hidden_startup())
    return result.stdout.splitlines() if result.returncode else []


def run_pip(python: Path, args: list[str], status) -> None:
    command = [str(python), "-m", "pip", "install", "--disable-pip-version-check", *args]
    log_path = runtime_dir() / "launcher.log"
    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        log.write("\n> " + subprocess.list2cmdline(command) + "\n")
        proc = subprocess.Popen(command, cwd=project_root(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", startupinfo=hidden_startup())
        assert proc.stdout is not None
        for line in proc.stdout:
            log.write(line)
        code = proc.wait()
    if code:
        raise RuntimeError(f"Dependency setup failed (exit code {code}). See {log_path} for details.")


def prepare_python(status) -> Path:
    root = project_root()
    venv_python = root / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        status("Preparing the project’s local Python environment…")
        launcher = python_launcher()
        subprocess.run([*launcher, "-m", "venv", "--system-site-packages", str(root / ".venv")],
                       check=True, cwd=root, startupinfo=hidden_startup())

    if not imports_available(venv_python, CORE_MODULES):
        status("Installing the project’s declared local dependencies (first launch may take a while)…")
        run_pip(venv_python, ["-r", str(root / "requirements.txt"), "-r", str(root / "requirements-p5.txt")], status)
    elif (not imports_available(venv_python, DASHBOARD_MODULES)
          or not dashboard_versions_supported(venv_python)):
        status("Installing the dashboard packages into the project environment…")
        run_pip(venv_python, ["-r", str(root / "requirements-p5.txt")], status)

    missing = missing_modules(venv_python, (*CORE_MODULES, *DASHBOARD_MODULES))
    if missing:
        raise RuntimeError("Missing Python packages after setup: " + ", ".join(missing))
    return venv_python


def dashboard_healthy() -> bool:
    try:
        with urllib.request.urlopen(APP_URL + "/_stcore/health", timeout=1.5) as response:
            if response.status != 200 or response.read(32).strip() != b"ok":
                return False
        with urllib.request.urlopen(APP_URL, timeout=1.5) as response:
            return response.status == 200 and b"CascadeGuard" in response.read(512_000)
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def port_is_busy() -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", 8501)) == 0


class Launcher:
    def __init__(self) -> None:
        self.root = project_root()
        self.app = self.root / "src" / "cascadeguard" / "dashboard" / "app.py"
        self.pid_path = runtime_dir() / "dashboard.pid"
        self.window = tk.Tk()
        self.window.title("CascadeGuard")
        self.window.geometry("470x235")
        self.window.resizable(False, False)
        self.window.configure(bg="#0b1220")

        tk.Label(self.window, text="CASCADEGUARD", bg="#0b1220", fg="#7dd3fc",
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=24, pady=(20, 2))
        tk.Label(self.window, text="Local Grid Intelligence", bg="#0b1220", fg="#f8fafc",
                 font=("Segoe UI Semibold", 18)).pack(anchor="w", padx=24)
        self.status = tk.StringVar(value="Ready to start the local dashboard.")
        tk.Label(self.window, textvariable=self.status, bg="#0b1220", fg="#cbd5e1",
                 font=("Segoe UI", 10), wraplength=420, justify="left").pack(anchor="w", padx=24, pady=(12, 18))

        row = tk.Frame(self.window, bg="#0b1220")
        row.pack(fill="x", padx=24)
        self.start_button = tk.Button(row, text="Start dashboard", command=self.start,
            bg="#4f46e5", fg="white", activebackground="#4338ca", relief="flat", padx=14, pady=8)
        self.start_button.pack(side="left")
        self.open_button = tk.Button(row, text="Open dashboard", command=self.open_dashboard,
            bg="#172235", fg="#e2e8f0", activebackground="#24334a", relief="flat", padx=14, pady=8)
        self.open_button.pack(side="left", padx=8)
        self.stop_button = tk.Button(row, text="Stop", command=self.stop_dashboard,
            bg="#172235", fg="#e2e8f0", activebackground="#24334a", relief="flat", padx=14, pady=8)
        self.stop_button.pack(side="right")
        tk.Label(self.window, text="The dashboard runs on this PC only.", bg="#0b1220", fg="#64748b",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=24, pady=(14, 0))
        self.window.after(250, self.start)

    def set_status(self, value: str) -> None:
        self.window.after(0, self.status.set, value)

    def start(self) -> None:
        self.start_button.configure(state="disabled")
        threading.Thread(target=self._start_worker, daemon=True).start()

    def _start_worker(self) -> None:
        try:
            if dashboard_healthy():
                self.set_status("Dashboard is already running. Opening it in your browser…")
                self.window.after(0, self.open_dashboard)
                return
            if port_is_busy():
                raise RuntimeError("Port 8501 is already in use by another application. Close it and try again.")
            if not self.app.exists():
                raise RuntimeError("CascadeGuard project files were not found beside CascadeGuard.exe. Keep the EXE in the project root.")

            python = prepare_python(self.set_status)
            self.set_status("Starting the local dashboard…")
            log_path = runtime_dir() / "launcher.log"
            env = os.environ.copy()
            env["PYTHONPATH"] = str(self.root / "src") + os.pathsep + env.get("PYTHONPATH", "")
            command = [str(python), "-m", "streamlit", "run", str(self.app),
                "--server.address", "127.0.0.1", "--server.port", "8501",
                "--global.developmentMode", "false", "--server.fileWatcherType", "none",
                "--browser.gatherUsageStats", "false"]
            flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            with log_path.open("a", encoding="utf-8", errors="replace") as log:
                process = subprocess.Popen(command, cwd=self.root, env=env, stdin=subprocess.PIPE,
                    stdout=log, stderr=subprocess.STDOUT, creationflags=flags, startupinfo=hidden_startup(),
                    close_fds=True)
            if process.stdin is not None:
                process.stdin.write(b"\n")
                process.stdin.close()
            self.pid_path.write_text(str(process.pid), encoding="ascii")

            for _ in range(120):
                if dashboard_healthy():
                    self.set_status("CascadeGuard is running locally. Opening the dashboard…")
                    self.window.after(0, self.open_dashboard)
                    return
                if process.poll() is not None:
                    break
                time.sleep(.5)
            log_tail = ""
            try:
                log_tail = "\n\n" + "".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines(True)[-12:])
            except OSError:
                pass
            raise RuntimeError(f"The dashboard did not start. See {log_path}.{log_tail}")
        except Exception as exc:
            self.set_status("Could not start the dashboard.")
            error = str(exc)
            self.window.after(0, lambda: messagebox.showerror("CascadeGuard startup", error, parent=self.window))
        finally:
            self.window.after(0, lambda: self.start_button.configure(state="normal"))

    def open_dashboard(self) -> None:
        webbrowser.open(APP_URL, new=2)
        self.status.set("Dashboard is open at 127.0.0.1:8501.")

    def stop_dashboard(self) -> None:
        try:
            pid = int(self.pid_path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            self.status.set("No launcher-started dashboard is recorded.")
            return
        result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                                text=True, startupinfo=hidden_startup())
        if result.returncode == 0:
            self.pid_path.unlink(missing_ok=True)
            self.status.set("Dashboard stopped.")
        elif not dashboard_healthy():
            self.pid_path.unlink(missing_ok=True)
            self.status.set("Dashboard is already stopped.")
        else:
            messagebox.showerror("CascadeGuard", "Could not stop the dashboard process.", parent=self.window)

    def run(self) -> None:
        self.window.mainloop()


if __name__ == "__main__":
    Launcher().run()

