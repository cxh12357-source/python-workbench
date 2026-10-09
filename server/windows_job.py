"""Own Windows child-process trees using a non-inheritable Job handle.

This is cleanup and resource containment, not a hostile-code sandbox.
"""

import ctypes
import os
import subprocess
from ctypes import wintypes


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class BASIC_LIMIT(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class EXTENDED_LIMIT(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", BASIC_LIMIT),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class WindowsJob:
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("This runner currently requires Windows Job Objects")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = EXTENDED_LIMIT()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits),
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process):
        # Popen's handle refers to this specific freshly created process.
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            if not self.kernel.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())


class JobPopen(subprocess.Popen):
    """Popen with atomic Windows Job attachment before any launcher executes.

    Windows venv python.exe may be a launcher. A stdin gate alone cannot stop
    that launcher creating an unassigned interpreter before job assignment.
    CREATE_SUSPENDED closes this race. Uses CPython's Windows Popen internals;
    subprocess I/O and process polling remain the standard implementations.
    """

    def __init__(self, *args, job, **kwargs):
        self._job = job
        super().__init__(*args, **kwargs)

    def _execute_child(self, args, executable, preexec_fn, close_fds,
                       pass_fds, cwd, env, startupinfo, creationflags, shell,
                       p2cread, p2cwrite, c2pread, c2pwrite, errread, errwrite,
                       *unused):
        import _winapi

        if shell or pass_fds or preexec_fn is not None or startupinfo is not None:
            raise ValueError("JobPopen only supports the runner's controlled launch")
        handles = [int(p2cread), int(c2pwrite), int(errwrite)]
        info = subprocess.STARTUPINFO()
        info.dwFlags |= _winapi.STARTF_USESTDHANDLES
        info.hStdInput, info.hStdOutput, info.hStdError = handles
        info.lpAttributeList = {"handle_list": handles}
        try:
            hp, ht, pid, _ = _winapi.CreateProcess(
                executable, subprocess.list2cmdline(args), None, None, True,
                creationflags | 0x00000004,  # CREATE_SUSPENDED
                env, cwd, info,
            )
        finally:
            self._close_pipe_fds(p2cread, p2cwrite, c2pread, c2pwrite, errread, errwrite)
        self._child_created = True
        self._handle = subprocess.Handle(hp)
        self.pid = pid
        try:
            self._job.assign(self)
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.ResumeThread.argtypes = [wintypes.HANDLE]
            kernel.ResumeThread.restype = wintypes.DWORD
            if kernel.ResumeThread(ht) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
        except Exception:
            _winapi.TerminateProcess(hp, 125)
            _winapi.WaitForSingleObject(hp, 3000)
            raise
        finally:
            _winapi.CloseHandle(ht)
