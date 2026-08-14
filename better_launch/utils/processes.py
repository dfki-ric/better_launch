import os
import sys
import re
import signal
import ctypes
import subprocess
import psutil


# Use this instead of signal.SIGKILL, as it doesn't exist on windows and we use 
# SIGTERM as a graceful shutdown.
FORCE_KILL = getattr(signal, "SIGKILL", -9)


# TODO documentation


def _spawn_node_process_linux(
    cmd: list[str], niceness: int = 0, **kwargs
) -> subprocess.Popen:
    def setup_process():
        # Make the process its own process group so ctrl-c doesn't hit it directly
        os.setpgrp()
        os.setpriority(os.PRIO_PROCESS, 0, niceness)

        # Tell the kernel the process should be killed if our root process dies
        PR_SET_PDEATHSIG = 1
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)

    return subprocess.Popen(cmd, preexec_fn=setup_process, **kwargs)


def _spawn_node_process_windows(
    cmd: list[str], niceness: int = 0, **kwargs
) -> subprocess.Popen:
    if niceness > 10:
        priority = subprocess.IDLE_PRIORITY_CLASS
    elif niceness > 5:
        priority = subprocess.BELOW_NORMAL_PRIORITY_CLASS
    elif niceness == 0:
        priority = subprocess.NORMAL_PRIORITY_CLASS
    elif niceness > -6:
        priority = subprocess.ABOVE_NORMAL_PRIORITY_CLASS
    elif niceness > -11:
        priority = subprocess.HIGH_PRIORITY_CLASS
    else:
        priority = subprocess.REALTIME_PRIORITY_CLASS

    # preexec_fn is not supported on windows
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | priority
    proc = subprocess.Popen(cmd, creationflags=flags, **kwargs)

    # Setup a windows kernel job that will kill the child when it dies. This
    # will be alive for as long as our process is running
    kernel32 = ctypes.windll.kernel32
    job = kernel32.CreateJobObject(None, None)

    # JOBOBJECT_BASIC_LIMIT_INFORMATION struct
    # We only care about the LimitFlags field, rest remains unnamed
    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("_a", ctypes.c_int64),
            ("_b", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("_c", ctypes.c_size_t),
            ("_d", ctypes.c_size_t),
            ("_e", ctypes.c_uint32),
            ("_f", ctypes.c_size_t),
            ("_g", ctypes.c_uint32),
            ("_h", ctypes.c_uint32),
        ]

    # JOBOBJECT_EXTENDED_LIMIT_INFORMATION struct
    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("Basic", BasicLimits),
            ("_io", ctypes.c_byte * 48),
            ("_i", ctypes.c_size_t),
            ("_j", ctypes.c_size_t),
            ("_k", ctypes.c_size_t),
            ("_l", ctypes.c_size_t),
        ]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

    # Create a limits object, set the kill-on-close flag, then associate our
    # child process handle with the job object
    info = ExtendedLimits()
    info.Basic.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    kernel32.SetInformationJobObject(
        job,
        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    kernel32.AssignProcessToJobObject(job, proc._handle)


def spawn_node_process(cmd: list[str], niceness: int = 0, **kwargs) -> subprocess.Popen:
    if sys.platform == "win32":
        return _spawn_node_process_windows(cmd, niceness, **kwargs)

    return _spawn_node_process_linux(cmd, niceness, **kwargs)


def send_signal_to_ptree(pid: int, signum: int) -> None:
    if sys.platform == "win32":
        if signum in {signal.SIGINT, signal.SIGTERM}:
            # SIGTERM on windows is a hard kill, this gives the process time 
            # to react via SIGBREAK
            os.kill(pid, signal.CTRL_BREAK_EVENT)
        else:
            # Kill the entire process tree; proc.kill would only kill the 
            # launch process itself
            subprocess.call(["taskkill", "/F", "/T", "/PID", str(pid)])
    else:
        os.killpg(pid, signum)


def shutdown_process(
    proc: subprocess.Popen, signum: int = signal.SIGTERM, timeout: float = None
) -> int:
    if not proc:
        return 0

    if proc.poll() is not None:
        return proc.returncode

    send_signal_to_ptree(proc.pid, signum)

    try:
        return proc.wait(timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait()


def find_ros2_node_processes() -> list[psutil.Process]:
    """Finds processes that seem to be ROS2 nodes.

    Unfortunately, ROS2 doesn't provide any means of discovering node internals other than by looking at the process command line. Lucky for us, there are a couple of distinct command line arguments that are somewhat unique to ROS. These are:
    - --ros-args for passing arguments
    - __ns:=<namespace>
    - __node:=<name>
    - __name:=<name>

    If any of these are present, the process will be added to the returned list.

    Returns
    -------
    list[psutil.Process]
        The processes that appear to be ROS2 nodes.
    """
    # NOTE we won't be able to discover nodes started by ros2 run this way, but there's really
    # nothing distinctive about those, e.g.:
    #
    # /usr/bin/python3 /opt/ros/humble/bin/ros2 run examples_rclpy_minimal_publisher publisher_local_function
    # /usr/bin/python3 /opt/ros/humble/lib/examples_rclpy_minimal_publisher/publisher_local_function
    ret = []

    for p in psutil.process_iter():
        try:
            cmd = p.cmdline()
            if p.is_running() and (
                "--ros-args" in cmd
                or "__ns:=" in cmd
                or "__node:=" in cmd
                or "__name:=" in cmd
            ):
                ret.append(p)
        except psutil.ZombieProcess:
            pass

    return ret


def find_process_for_node(namespace: str, name: str) -> list[psutil.Process]:
    """Find processes that look like ROS2 nodes which have been passed the specified namespace and name.

    Parameters
    ----------
    namespace : str
        The namespace to look for.
    name : str
        The node name to look for.

    Returns
    -------
    list[psutil.Process]
        A list processes that match the above criteria.
    """
    r_pkg = re.compile(rf"__ns:={namespace}")
    r_name = re.compile(rf"__(?:node|name):={name}")

    candidates = []

    for p in psutil.process_iter():
        pkg_match = False
        name_match = False

        try:
            cmd = p.cmdline()
            for arg in cmd:
                if r_pkg.match(arg):
                    pkg_match = True
                elif r_name.match(arg):
                    name_match = True

                if pkg_match and name_match:
                    candidates.append(p)
                    break
        except psutil.ZombieProcess:
            pass

    return candidates
