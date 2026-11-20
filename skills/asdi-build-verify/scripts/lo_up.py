"""Bring the loopback interface up inside the test sandbox's fresh network namespace.

Only loopback: the namespace still has no route out. Failure is silent so a host
where this is not permitted still runs the tests (they then see loopback down).
"""
import fcntl, socket, struct

try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    flags = struct.unpack("16sH", fcntl.ioctl(s, 0x8913, struct.pack("16sH", b"lo", 0)))[1]  # SIOCGIFFLAGS
    fcntl.ioctl(s, 0x8914, struct.pack("16sH", b"lo", flags | 0x1))  # SIOCSIFFLAGS, IFF_UP
except OSError:
    pass
