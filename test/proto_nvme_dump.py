# -*- coding: utf-8 -*-
"""导出 NVMe 健康日志原始字节，定位真实字段偏移。只读。"""
import ctypes
import struct
from ctypes import wintypes as wt

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.restype = wt.HANDLE
k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p,
                            wt.DWORD, wt.DWORD, wt.HANDLE]
k32.DeviceIoControl.restype = wt.BOOL
k32.DeviceIoControl.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_void_p, wt.DWORD,
                                ctypes.c_void_p, wt.DWORD,
                                ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
k32.CloseHandle.argtypes = [wt.HANDLE]

PS = 40
IN_SIZE = 8 + PS + 512

for n in (0, 1):
    h = k32.CreateFileW(f"\\\\.\\PhysicalDrive{n}", 0xC0000000, 3, None, 3, 0, None)
    buf = ctypes.create_string_buffer(IN_SIZE)
    struct.pack_into("<II", buf, 0, 50, 0)
    struct.pack_into("<IIIIIIIII", buf, 8, 3, 2, 2, 0, PS, 512, 0, 0, 0)
    ret = wt.DWORD(0)
    ok = k32.DeviceIoControl(h, 0x2D1400, buf, IN_SIZE, buf, IN_SIZE,
                             ctypes.byref(ret), None)
    print(f"== PhysicalDrive{n} ok={bool(ok)} ret={ret.value}")
    if ok:
        data = bytes(buf[8 + PS: 8 + PS + 512])
        for off in range(0, 176, 16):
            chunk = data[off:off + 16]
            low = int.from_bytes(chunk[0:8], "little")
            print(f"{off:4d}: {chunk.hex(' ')}   u64@{off}={low}")
    k32.CloseHandle(h)
