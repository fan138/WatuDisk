# -*- coding: utf-8 -*-
"""原型验证 v2：严格 ctypes 原型，直读 NVMe 健康日志页（0x02）。只读操作。"""
import ctypes
from ctypes import wintypes as wt
import json
import struct

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.restype = wt.HANDLE
k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p,
                            wt.DWORD, wt.DWORD, wt.HANDLE]
k32.DeviceIoControl.restype = wt.BOOL
k32.DeviceIoControl.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_void_p, wt.DWORD,
                                ctypes.c_void_p, wt.DWORD,
                                ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
k32.CloseHandle.restype = wt.BOOL
k32.CloseHandle.argtypes = [wt.HANDLE]

IOCTL_STORAGE_QUERY_PROPERTY = 0x2D1400
INVALID_HANDLE_VALUE = wt.HANDLE(-1).value

def query_nvme_health(drive_number: int):
    path = f"\\\\.\\PhysicalDrive{drive_number}"
    h = k32.CreateFileW(path, 0x80000000 | 0x40000000, 1 | 2, None, 3, 0, None)
    if h == INVALID_HANDLE_VALUE or not h:
        return None, f"CreateFileW err={ctypes.get_last_error()}"
    try:
        # STORAGE_PROPERTY_QUERY(8) + STORAGE_PROTOCOL_SPECIFIC_DATA(40) + 512 payload
        PROTO_SPEC_SIZE = 40
        INPUT_SIZE = 8 + PROTO_SPEC_SIZE + 512
        buf = ctypes.create_string_buffer(INPUT_SIZE)
        struct.pack_into("<II", buf, 0, 50, 0)          # PropertyId=50(DeviceProtocolSpecific) QueryType=0
        struct.pack_into("<IIIIIII3I".replace("3I", "III"), buf, 8,
                         3, 2, 2, 0,                     # ProtocolType=Nvme, DataType=LogPage, RequestValue=health(2), SubValue=0
                         PROTO_SPEC_SIZE, 512, 0, 0, 0, 0)  # Offset, Length, FixedReturn, Reserved*3
        ret = wt.DWORD(0)
        ok = k32.DeviceIoControl(h, IOCTL_STORAGE_QUERY_PROPERTY, buf, INPUT_SIZE,
                                 buf, INPUT_SIZE, ctypes.byref(ret), None)
        if not ok:
            return None, f"DeviceIoControl err={ctypes.get_last_error()}"
        data = bytes(buf[8 + PROTO_SPEC_SIZE: 8 + PROTO_SPEC_SIZE + 512])
        crit_warn, temp_k, spare, spare_thresh, pct_used = struct.unpack_from("<BHBBB", data, 0)
        # 128-bit 计数字段：取低 64 位（NVMe 1.3/1.4 Health Log 标准布局）
        u64 = lambda off: struct.unpack_from("<Q", data, off)[0]
        dur_read = u64(8)      # Data Units Read
        dur_write = u64(24)    # Data Units Written
        power_cycles = u64(88)
        power_on_hours = u64(104)
        unsafe_shutdowns = u64(120)
        media_errors = u64(136)
        err_entries = u64(152)
        return {
            "critical_warning": crit_warn,
            "temperature_c": temp_k - 273,
            "available_spare_pct": spare,
            "spare_threshold": spare_thresh,
            "percentage_used": pct_used,
            "data_units_read": dur_read,
            "data_units_written": dur_write,
            "power_cycles": power_cycles,
            "power_on_hours": power_on_hours,
            "unsafe_shutdowns": unsafe_shutdowns,
            "media_errors": media_errors,
            "error_log_entries": err_entries,
        }, None
    finally:
        k32.CloseHandle(h)

if __name__ == "__main__":
    for n in (0, 1):
        r, err = query_nvme_health(n)
        print(f"== PhysicalDrive{n} ==")
        if err:
            print("  FAIL:", err)
        else:
            w = r.pop("data_units_written"); rd = r.pop("data_units_read")
            r["total_written"] = f"{w * 512000 / 1024**3:.1f} GB"
            r["total_read"] = f"{rd * 512000 / 1024**3:.1f} GB"
            print(json.dumps(r, indent=2))
