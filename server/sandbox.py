"""Chạy một tiến trình con với giới hạn tài nguyên, đo thời gian và bộ nhớ thật.

Đây là tầng nguy hiểm nhất của cả hệ thống: nó chạy mã do học sinh viết. Mọi
giới hạn dưới đây đều phải được đặt **trong tiến trình con, sau khi fork và
trước khi exec**, vì đó là khoảng thời gian duy nhất mà tiến trình cha còn kiểm
soát được thứ sẽ chạy.

Vì sao phải đo bằng ``os.wait4`` chứ không phải ``subprocess.run``:
``subprocess`` không trả về ``rusage``, nên không biết được đỉnh bộ nhớ thật của
tiến trình con. Cách duy nhất đúng là gọi ``os.wait4`` — nó vừa thu hồi tiến
trình con vừa trả về ``ru_maxrss`` (đỉnh RSS). Hệ quả: **không được gọi**
``Popen.wait()``/``poll()``/``communicate()`` trên tiến trình này, vì chúng sẽ
thu hồi tiến trình trước và ``os.wait4`` sẽ ném ``ChildProcessError``.

Vì sao tệp này chỉ được dùng từ tiến trình chấm riêng (``worker.py``) chứ không
phải từ tiến trình web: ``preexec_fn`` chạy giữa ``fork()`` và ``exec()``, và
tài liệu Python nói rõ nó **không an toàn khi tiến trình có nhiều luồng** — nếu
một luồng khác đang giữ khoá cấp phát bộ nhớ đúng lúc fork, tiến trình con sẽ
treo. Worker chấm bài là tiến trình đơn luồng nên ở đó mới an toàn.

--------------------------------------------------------------------------
HAI ĐƯỜNG CHẠY
--------------------------------------------------------------------------
**Linux là đường chạy tham chiếu.** Đó là hệ điều hành của máy chủ trường học,
và mọi cơ chế ở đây — ``RLIMIT_AS``, ``RLIMIT_CPU``, ``RLIMIT_NPROC``,
``os.setsid``, hạ quyền bằng ``setuid``, ``os.wait4`` — chỉ có trên POSIX.

**Windows là đường chạy để phát triển.** Không có ``resource`` trên Windows,
nên phần tương đương được dựng bằng Job Object của Windows: một đối tượng hạt
nhân gom nhóm tiến trình con và áp giới hạn lên cả nhóm. Đây là cơ chế chính
thức của Windows cho đúng việc này, không phải một mẹo.

Ba khác biệt phải biết khi chạy trên Windows, và lý do chúng chấp nhận được ở
đó nhưng **không** chấp nhận được trên máy chủ:

1. Không có ``RLIMIT_CPU``. Chỉ có trần thời gian thực, nên một chương trình
   ngốn CPU và một chương trình ngủ đều bị cắt như nhau. Trên máy chủ thì giới
   hạn CPU mới là thứ quyết định, còn trần thực chỉ để chặn trường hợp treo.
2. Bộ nhớ đo bằng đỉnh vùng nhớ đã cam kết của Job, không phải đỉnh RSS. Hai
   con số này gần nhau với chương trình C++ thông thường, nhưng không đồng nhất.
3. Không hạ được quyền: Windows không có ``setuid``. Mã học sinh chạy cùng tài
   khoản với worker. Trên máy chủ phải đặt ``SONGLO_JUDGE_RUNAS_UID``.
"""

from __future__ import annotations

import math
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

IS_POSIX = os.name == "posix"

if IS_POSIX:
    import resource

# Giới hạn kích thước tệp ghi ra. Một chương trình lặp vô hạn in ra sẽ làm đầy
# đĩa nếu không chặn; 64 MB là quá đủ cho mọi bộ dữ liệu của một đề thi cấp 2.
MAX_OUTPUT_BYTES = 64 * 1024 * 1024

# Hệ số nới cho giới hạn thời gian thực (wall clock) so với giới hạn CPU.
# Giới hạn CPU mới là thứ chặn vòng lặp tính toán; giới hạn thực tồn tại để chặn
# trường hợp chương trình ngủ hoặc chờ đọc dữ liệu vào — những trường hợp tiêu
# tốn ít CPU nhưng treo cả hàng đợi chấm.
WALL_FACTOR = 3.0
WALL_GRACE_S = 2.0

# Số tiến trình tối đa. Chặn "fork bomb" — chương trình con đệ quy gọi fork()
# cho tới khi cạn bảng tiến trình của hệ điều hành.
#
# Lưu ý quan trọng khi triển khai: RLIMIT_NPROC đếm theo **tài khoản**, và đếm
# theo **task** chứ không theo tiến trình — một tiến trình có 20 luồng bị tính
# là 20. Con số 64 rộng rãi cho một chương trình học sinh và cho cả `g++` (trình
# dịch tự nó sinh ra cc1plus, as, collect2, ld), nhưng lại nhỏ hơn số luồng mà
# một tài khoản dịch vụ thường đã có sẵn. Vì vậy giới hạn này chỉ được áp khi
# tiến trình con đã thật sự rời khỏi tài khoản của bộ chấm — xem chú thích
# trong `_apply_posix_limits`.
MAX_PROCESSES = int(os.environ.get("SONGLO_JUDGE_MAX_PROCS", "64"))

# Tuỳ chọn: hạ quyền tiến trình con xuống một tài khoản ít quyền trước khi exec.
#
# Đây là biện pháp bảo vệ mạnh nhất trong cả tệp này, nhưng chỉ dùng được khi
# worker chấm chạy bằng root. Cách dựng đúng: cho worker chạy bằng root, đặt
# SONGLO_JUDGE_RUNAS_UID/GID trỏ tới một tài khoản không có quyền gì
# (`nobody`), và mã của học sinh sẽ không bao giờ chạm được vào tệp của hệ
# thống. Nếu biến này không được đặt, mã học sinh chạy cùng quyền với worker —
# vẫn bị giới hạn tài nguyên, nhưng không được cách ly về quyền.
RUNAS_UID = os.environ.get("SONGLO_JUDGE_RUNAS_UID")
RUNAS_GID = os.environ.get("SONGLO_JUDGE_RUNAS_GID")


@dataclass
class RunResult:
    """Kết quả một lần chạy tiến trình con."""

    exit_code: int              # mã thoát, hoặc -1 nếu chết vì tín hiệu
    term_signal: int | None     # số tín hiệu đã giết tiến trình, None nếu thoát bình thường
    wall_ms: int                # thời gian thực, đo bằng đồng hồ đơn điệu
    cpu_ms: int                 # thời gian CPU (cả người dùng lẫn hệ thống)
    memory_kb: int              # đỉnh RSS
    killed_by_watchdog: bool    # True nếu chính chúng ta giết vì quá hạn thực

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.term_signal is None


def _child_env(cwd: Path, env_extra: dict[str, str] | None) -> dict[str, str]:
    """Môi trường tối thiểu cho tiến trình con.

    Truyền nguyên môi trường của worker xuống sẽ để lộ các biến cấu hình (khoá
    bí mật, đường dẫn CSDL) cho mã của học sinh, nên danh sách biến được viết
    thẳng ra đây thay vì kế thừa.

    Ngoại lệ có chủ ý: trên Windows, ``PATH`` được kế thừa nguyên vẹn. Trình
    biên dịch mingw liên kết động với ``libstdc++-6.dll`` và
    ``libgcc_s_seh-1.dll`` nằm cạnh nó, nên tệp thực thi sẽ không khởi động được
    nếu thiếu đường dẫn đó. ``PATH`` không phải thông tin mật, và mọi biến khác
    vẫn bị chặn.
    """
    env = {
        "HOME": str(cwd),
        "TMPDIR": str(cwd),
        "LANG": "C",
        "LC_ALL": "C",
    }
    if IS_POSIX:
        env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    else:
        env["PATH"] = os.environ.get("PATH", "")
        # Tên biến của Windows, không phải bản sao của TMPDIR ở trên.
        env["TEMP"] = str(cwd)
        env["TMP"] = str(cwd)
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        env.setdefault("SystemRoot", system_root)
    if env_extra:
        env.update(env_extra)
    return env


# ==========================================================================
# POSIX — đường chạy tham chiếu
# ==========================================================================
def _apply_posix_limits(cpu_seconds: int, memory_bytes: int) -> None:
    """Chạy trong tiến trình con, giữa fork và exec.

    Không được cấp phát bộ nhớ, không được ghi log, không được dùng bất kỳ thứ
    gì có thể lấy khoá ở đây. Chỉ gọi hệ thống.
    """
    # Tách khỏi nhóm tiến trình của cha để có thể giết cả cây tiến trình con
    # bằng một tín hiệu gửi tới -pgid.
    os.setsid()

    # Chặn tạo tệp core: một chương trình gặp lỗi phân đoạn sẽ đổ cả bộ nhớ ra
    # đĩa, và với bộ nhớ cho phép 256 MB thì mỗi bài sai là 256 MB rác.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    # Địa chỉ ảo tối đa. Đây là giới hạn bộ nhớ chính.
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))

    # CPU: mềm là mức gửi SIGXCPU, cứng là mức gửi SIGKILL. Đặt cứng cao hơn
    # mềm 1 giây để chương trình còn kịp thoát êm và in ra thông báo nếu muốn.
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))

    # Kích thước tệp ghi ra.
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES))

    # Hạ quyền. Thứ tự bắt buộc: setgid **trước** setuid, vì sau khi setuid
    # thì tiến trình không còn quyền đổi nhóm nữa.
    dropped = False
    if RUNAS_UID:
        try:
            if RUNAS_GID:
                os.setgid(int(RUNAS_GID))
                os.setgroups([])
            os.setuid(int(RUNAS_UID))
            dropped = True
        except OSError:
            # Không hạ được quyền (thường là vì worker không chạy bằng root).
            # Đã có giới hạn tài nguyên nên vẫn chấp nhận chạy tiếp; nuốt lỗi ở
            # đây là có chủ ý, vì ném ra sẽ làm mọi bài nộp đều lỗi hệ thống.
            pass

    # Số tiến trình tối đa — đặt **sau** khi hạ quyền, và chỉ khi đã hạ được.
    #
    # Hai lý do, cả hai đều đã quan sát được trên máy chủ thật chứ không phải
    # phòng ngừa suông:
    #
    # 1. Đặt sau: `setuid` trả EAGAIN nếu tài khoản đích đã có nhiều task hơn
    #    giới hạn. Đặt giới hạn trước rồi mới `setuid` nghĩa là một tài khoản
    #    đang bận làm `setuid` thất bại, và lỗi đó bị nuốt ngay trên — mã học
    #    sinh sẽ chạy bằng **root** mà không có dấu hiệu nào.
    # 2. Chỉ khi đã hạ được: giới hạn này đo bằng **task**, không phải tiến
    #    trình. Đo trên máy chủ đang chạy thật: uid 0 có 20 tiến trình nhưng 75
    #    luồng, nên `MAX_PROCESSES = 64` khiến `g++` không `fork` nổi và **mọi**
    #    bài nộp nhận CE với thông báo "vfork: Resource temporarily
    #    unavailable" — trong khi mã nguồn hoàn toàn đúng.
    #
    # Nếu không hạ được quyền thì cách ly vốn đã không có, và siết số tiến trình
    # chỉ còn tác dụng làm hỏng chính bộ chấm.
    if MAX_PROCESSES > 0 and dropped:
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (MAX_PROCESSES, MAX_PROCESSES))
        except (ValueError, OSError):
            # Một số hệ thống không cho đặt giới hạn này. Thiếu nó không làm
            # hỏng việc chấm, nên bỏ qua thay vì làm sập cả bài nộp.
            pass


def _run_posix(
    argv: list[str],
    cwd: Path,
    stdin_path: Path | None,
    stdout_path: Path,
    stderr_path: Path,
    time_limit_ms: int,
    memory_limit_mb: int,
    env_extra: dict[str, str] | None,
) -> RunResult:
    cpu_seconds = max(1, math.ceil(time_limit_ms / 1000))
    memory_bytes = memory_limit_mb * 1024 * 1024
    wall_seconds = time_limit_ms / 1000.0 * WALL_FACTOR + WALL_GRACE_S

    in_f = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
    out_f = open(stdout_path, "wb")
    err_f = open(stderr_path, "wb")

    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=_child_env(cwd, env_extra),
            stdin=in_f,
            stdout=out_f,
            stderr=err_f,
            close_fds=True,
            preexec_fn=lambda: _apply_posix_limits(cpu_seconds, memory_bytes),
        )
    except Exception:
        # `in_f` là `subprocess.DEVNULL` (một số nguyên) khi không có đầu vào,
        # nên chỉ đóng khi thật sự là tệp.
        if stdin_path:
            in_f.close()
        out_f.close()
        err_f.close()
        raise

    started = time.monotonic()

    # Đồng hồ canh giờ thực. Giết cả nhóm tiến trình (dấu trừ) vì chương trình
    # của học sinh có thể đã sinh ra tiến trình con.
    killed_by_watchdog = {"value": False}

    def _kill():
        killed_by_watchdog["value"] = True
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    watchdog = threading.Timer(wall_seconds, _kill)
    watchdog.daemon = True
    watchdog.start()

    try:
        # os.wait4 vừa thu hồi tiến trình con vừa trả về rusage. Không dùng
        # proc.wait() ở bất kỳ đâu trong nhánh này.
        _, status, usage = os.wait4(proc.pid, 0)
    finally:
        watchdog.cancel()
        if stdin_path:
            in_f.close()
        out_f.close()
        err_f.close()

    wall_ms = int((time.monotonic() - started) * 1000)

    # Giữ đối tượng Popen ở trạng thái nhất quán, nếu không nó sẽ cảnh báo
    # "subprocess still running" khi bị thu gom.
    if os.WIFSIGNALED(status):
        proc.returncode = -os.WTERMSIG(status)
        term_signal = os.WTERMSIG(status)
        exit_code = -1
    else:
        proc.returncode = os.WEXITSTATUS(status)
        term_signal = None
        exit_code = proc.returncode

    cpu_ms = int((usage.ru_utime + usage.ru_stime) * 1000)

    # ru_maxrss: KB trên Linux, byte trên macOS. Hệ thống chấm chạy trên Linux
    # nên quy đổi về KB; nếu giá trị lớn bất thường thì đang chạy trên hệ khác.
    maxrss = usage.ru_maxrss
    memory_kb = int(maxrss / 1024) if maxrss > (1 << 40) else int(maxrss)

    return RunResult(
        exit_code=exit_code,
        term_signal=term_signal,
        wall_ms=wall_ms,
        cpu_ms=cpu_ms,
        memory_kb=memory_kb,
        killed_by_watchdog=killed_by_watchdog["value"],
    )


# ==========================================================================
# Windows — đường chạy để phát triển
# ==========================================================================
if not IS_POSIX:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _psapi = ctypes.WinDLL("psapi", use_last_error=True)

    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_TERMINATE = 0x0001

    # Cờ giới hạn của Job Object. Tên và giá trị lấy từ winnt.h.
    _JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    _JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    _JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JobObjectExtendedLimitInformation = 9

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            # ULONG_PTR. Khai báo là c_size_t để ctypes tự căn đúng trên cả
            # bản 32 và 64 bit.
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.restype = wintypes.BOOL
    _k32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _k32.QueryInformationJobObject.restype = wintypes.BOOL
    _k32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    _k32.AssignProcessToJobObject.restype = wintypes.BOOL
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.TerminateJobObject.restype = wintypes.BOOL
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.CloseHandle.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]

    def _make_job(memory_bytes: int) -> int | None:
        """Tạo Job Object đã áp giới hạn bộ nhớ và số tiến trình."""
        job = _k32.CreateJobObjectW(None, None)
        if not job:
            return None

        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        flags = (_JOB_OBJECT_LIMIT_PROCESS_MEMORY
                 | _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                 | _JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION)
        if MAX_PROCESSES > 0:
            flags |= _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            info.BasicLimitInformation.ActiveProcessLimit = MAX_PROCESSES

        info.BasicLimitInformation.LimitFlags = flags
        info.ProcessMemoryLimit = memory_bytes

        ok = _k32.SetInformationJobObject(
            job, _JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            _k32.CloseHandle(job)
            return None
        return job

    def _job_peak_memory_kb(job: int) -> int:
        """Đỉnh bộ nhớ đã cam kết của mọi tiến trình trong Job.

        Đọc từ Job chứ không hỏi tiến trình con: tiến trình đã kết thúc vẫn còn
        số liệu trong đối tượng Job, còn hỏi thẳng tiến trình thì phải mở một
        luồng giám sát riêng và vẫn có thể trượt mất đỉnh của một chương trình
        chạy quá nhanh.
        """
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        returned = wintypes.DWORD(0)
        ok = _k32.QueryInformationJobObject(
            job, _JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(returned))
        if not ok:
            return 0
        return int(max(info.PeakProcessMemoryUsed, info.PeakJobMemoryUsed) // 1024)

    def _run_windows(
        argv: list[str],
        cwd: Path,
        stdin_path: Path | None,
        stdout_path: Path,
        stderr_path: Path,
        time_limit_ms: int,
        memory_limit_mb: int,
        env_extra: dict[str, str] | None,
    ) -> RunResult:
        memory_bytes = memory_limit_mb * 1024 * 1024
        wall_seconds = time_limit_ms / 1000.0 * WALL_FACTOR + WALL_GRACE_S

        job = _make_job(memory_bytes)

        in_f = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
        out_f = open(stdout_path, "wb")
        err_f = open(stderr_path, "wb")

        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(cwd),
                env=_child_env(cwd, env_extra),
                stdin=in_f,
                stdout=out_f,
                stderr=err_f,
                close_fds=True,
            )
        except Exception:
            if stdin_path:
                in_f.close()
            out_f.close()
            err_f.close()
            if job:
                _k32.CloseHandle(job)
            raise

        # Gán tiến trình con vào Job.
        #
        # Có một khe hở rất nhỏ giữa lúc CreateProcess trả về và lúc gán xong,
        # trong đó tiến trình con chưa bị giới hạn. Khe này không thể bịt bằng
        # cách tạo tiến trình ở trạng thái tạm dừng, vì `subprocess` không đưa
        # ra handle của luồng chính. Trên thực tế khe chỉ kéo dài vài chục
        # micro giây, trong khi riêng việc ghi 256 MB đã tốn hàng chục mili
        # giây, nên không có chương trình nào kịp vượt giới hạn ở đó.
        assigned = False
        if job:
            hproc = _k32.OpenProcess(
                _PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, proc.pid)
            if hproc:
                assigned = bool(_k32.AssignProcessToJobObject(job, hproc))
                _k32.CloseHandle(hproc)

        started = time.monotonic()
        killed_by_watchdog = {"value": False}

        def _kill():
            killed_by_watchdog["value"] = True
            # TerminateJobObject giết cả cây tiến trình con, tương đương
            # killpg trên POSIX.
            if job and assigned:
                _k32.TerminateJobObject(job, 1)
            try:
                proc.kill()
            except OSError:
                pass

        watchdog = threading.Timer(wall_seconds, _kill)
        watchdog.daemon = True
        watchdog.start()

        try:
            exit_code = proc.wait()
        finally:
            watchdog.cancel()
            if stdin_path:
                in_f.close()
            out_f.close()
            err_f.close()

        wall_ms = int((time.monotonic() - started) * 1000)

        # Phải đọc trước khi đóng Job: đóng Job với cờ KILL_ON_JOB_CLOSE sẽ
        # giải phóng luôn phần thống kê.
        memory_kb = _job_peak_memory_kb(job) if (job and assigned) else 0
        if job:
            _k32.CloseHandle(job)

        return RunResult(
            exit_code=exit_code,
            # Windows không có tín hiệu. Một chương trình C++ gặp lỗi truy cập
            # trả về mã thoát dạng 0xC0000005, và tầng phân loại xử lý nó qua
            # nhánh `exit_code != 0` -> RE, đúng như mong đợi.
            term_signal=None,
            wall_ms=wall_ms,
            # Không đo được thời gian CPU trên Windows. Trả 0 để tầng gọi tự
            # dùng thời gian thực; xem ghi chú đầu tệp.
            cpu_ms=0,
            memory_kb=memory_kb,
            killed_by_watchdog=killed_by_watchdog["value"],
        )


# ==========================================================================
# Cổng vào
# ==========================================================================
def prepare_workspace(path: Path) -> None:
    """Trao quyền sở hữu thư mục làm việc cho tài khoản chạy hạ quyền.

    Phải gọi ngay sau khi tạo thư mục và trước khi dịch.

    Vì sao cần: ``tempfile.mkdtemp`` tạo thư mục với quyền 0700 thuộc tài khoản
    gọi nó — tức là ``root`` khi tiến trình chấm chạy bằng root theo
    ``deploy/README.md``. Tiến trình con sau đó bị hạ xuống
    ``SONGLO_JUDGE_RUNAS_UID`` trước khi ``exec``, và tài khoản đó **không có
    quyền đi qua** thư mục 0700 của root.

    Hệ quả không phải một thông báo rõ ràng về quyền của bộ chấm, mà là thông
    báo của chính trình dịch, trỏ vào mã nguồn của học sinh::

        cc1plus: fatal error: main.cpp: Permission denied

    Đọc lên thì như lỗi ở bài làm, nhưng bài làm không liên quan gì: ``g++``
    không mở nổi tệp chỉ vì không có quyền tìm kiếm trên thư mục chứa nó. Kết
    quả là **mọi** bài nộp đều CE, kể cả bài đúng — và trên Windows, nơi không
    hạ quyền, thì không tái hiện được.

    Chỉ đổi chủ khi thật sự đang chạy bằng root và có cấu hình tài khoản hạ
    quyền; mọi trường hợp khác giữ nguyên hành vi cũ.
    """
    if not IS_POSIX or not RUNAS_UID or os.geteuid() != 0:
        return
    try:
        # -1 = "giữ nguyên" cho trường hợp chỉ cấu hình UID mà không có GID.
        os.chown(path, int(RUNAS_UID), int(RUNAS_GID) if RUNAS_GID else -1)
    except OSError:
        # Không đổi được chủ (hệ thống tệp không cho, hoặc tài khoản không tồn
        # tại). Ném ra ở đây sẽ biến mọi bài nộp thành lỗi hệ thống, nên bỏ qua;
        # nếu quyền thật sự thiếu thì chính trình dịch sẽ báo, kèm nhật ký.
        pass


def run_limited(
    argv: list[str],
    cwd: Path,
    stdin_path: Path | None,
    stdout_path: Path,
    stderr_path: Path,
    time_limit_ms: int,
    memory_limit_mb: int,
    env_extra: dict[str, str] | None = None,
) -> RunResult:
    """Chạy ``argv`` trong ``cwd`` với giới hạn, trả về số đo thật.

    Giới hạn thời gian thực được đặt rộng hơn giới hạn CPU (xem ``WALL_FACTOR``)
    để trong đa số trường hợp giới hạn CPU là thứ quyết định — nhưng vẫn có trần
    cho trường hợp chương trình không dùng CPU mà vẫn treo.
    """
    runner = _run_posix if IS_POSIX else _run_windows
    return runner(
        argv=argv,
        cwd=cwd,
        stdin_path=stdin_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        time_limit_ms=time_limit_ms,
        memory_limit_mb=memory_limit_mb,
        env_extra=env_extra,
    )


def read_capped(path: Path, limit: int = 64 * 1024) -> str:
    """Đọc tối đa ``limit`` byte và giải mã chịu lỗi.

    Đầu ra của một chương trình sai có thể là 64 MB nhị phân; đọc hết vào bộ nhớ
    để so sánh là không cần thiết và có thể làm worker hết bộ nhớ. Cắt ở 64 KB
    là quá đủ để kết luận sai, vì chỉ cần byte đầu tiên khác nhau là đã sai.
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read(limit)
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")
