# -*- coding: utf-8 -*-
r"""NVMe 健康日志直读（v1.2 新增）。

背景：部分平台（如 Storage Spaces + 特定 NVMe 固件组合）上
Get-StorageReliabilityCounter 只返回温度 / Wear，PowerOnHours、
PowerCycleCount、读写错误等全为 null（OS 通道限制）。本模块改走
IOCTL_STORAGE_QUERY_PROPERTY 直读 NVMe Health Information Log Page（0x02），
拿到完整的健康数据。

实现要点（经真机验证的原型，勿随意改动）：
- ctypes 严格原型：CreateFileW / DeviceIoControl / CloseHandle 必须设置
  restype / argtypes，否则 64 位句柄被截断（DeviceIoControl 报 err=6）；
- 打开 \\.\PhysicalDrive{n}（只读查询，但仍需 GENERIC_READ|GENERIC_WRITE
  权限组合与管理员身份）；失败一律返回 None 降级，绝不抛异常；
- 输入缓冲：STORAGE_PROPERTY_QUERY(8) + STORAGE_PROTOCOL_SPECIFIC_DATA(40)
  + 512 字节负载区；返回缓冲的 512 字节即 NVMe 健康日志页。

固件布局怪癖（自适应解析）：标准 NVMe 1.3/1.4 布局中 Data Units Read 在
偏移 8、Written 在 24；某些盘固件整体后移 24 字节（Read@32、Written@48…）。
策略：先按标准布局解析；若 Read+Written 均为 0 且 +24 偏移处非零，则改用
+24 偏移布局。头部字段（critical_warning / 温度 / 备用空间 / 使用率）两种
布局固定在标准偏移。

约束：ctypes 仅用于 DeviceIoControl 只读查询；不写盘、不联网、不写注册表。
"""
from __future__ import annotations

import ctypes
import struct
from ctypes import wintypes as wt

# ---- Windows API 常量 ----
IOCTL_STORAGE_QUERY_PROPERTY = 0x2D1400
INVALID_HANDLE_VALUE = wt.HANDLE(-1).value

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ_WRITE = 1 | 2
_OPEN_EXISTING = 3

# ---- STORAGE_PROPERTY_QUERY: PropertyId = StorageDeviceProtocolSpecificProperty
_PROPERTY_ID_PROTOCOL_SPECIFIC = 50
_QUERY_TYPE_STANDARD = 0
# ---- STORAGE_PROTOCOL_SPECIFIC_DATA
_PROTOCOL_TYPE_NVME = 3        # ProtocolType = ProtocolTypeNvme
_DATA_TYPE_LOG_PAGE = 2        # DataType = NVMeDataTypeLogPage（与真机调通的原型一致）
_NVME_LOG_PAGE_HEALTH_INFO = 2  # ProtocolDataRequestValue = Log Page 0x02（健康日志）

_PROTO_SPEC_SIZE = 40          # sizeof(STORAGE_PROTOCOL_SPECIFIC_DATA)
_HEALTH_LOG_SIZE = 512         # NVMe 健康日志页长度
_INPUT_SIZE = 8 + _PROTO_SPEC_SIZE + _HEALTH_LOG_SIZE

# 健康日志解析所需的最小长度（最后一个字段 ErrLogEntries@176+8 = 184）
_MIN_LOG_SIZE = 184

# 标准布局：128 位小端计数字段的低 64 位偏移
_LAYOUT_STD = {
    "data_units_read": 8,
    "data_units_written": 24,
    "power_cycles": 88,
    "power_on_hours": 104,
    "unsafe_shutdowns": 120,
    "media_errors": 136,
    "error_log_entries": 152,
}
# 固件怪癖布局：整体 +24 偏移
_LAYOUT_SHIFTED = {key: off + 24 for key, off in _LAYOUT_STD.items()}


def _load_kernel32():
    """加载 kernel32 并设置严格原型（64 位下句柄 / 指针不能截断）。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wt.HANDLE
    k32.CreateFileW.argtypes = [
        wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p,
        wt.DWORD, wt.DWORD, wt.HANDLE,
    ]
    k32.DeviceIoControl.restype = wt.BOOL
    k32.DeviceIoControl.argtypes = [
        wt.HANDLE, wt.DWORD, ctypes.c_void_p, wt.DWORD,
        ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p,
    ]
    k32.CloseHandle.restype = wt.BOOL
    k32.CloseHandle.argtypes = [wt.HANDLE]
    return k32


def _build_query_buffer() -> ctypes.Array:
    """构造 IOCTL 输入缓冲：PropertyQuery + ProtocolSpecificData + 512 负载区。"""
    buf = ctypes.create_string_buffer(_INPUT_SIZE)
    struct.pack_into("<II", buf, 0, _PROPERTY_ID_PROTOCOL_SPECIFIC, _QUERY_TYPE_STANDARD)
    struct.pack_into(
        "<IIIIIIII", buf, 8,
        _PROTOCOL_TYPE_NVME,            # ProtocolType
        _DATA_TYPE_LOG_PAGE,            # DataType
        _NVME_LOG_PAGE_HEALTH_INFO,     # ProtocolDataRequestValue（健康日志页 0x02）
        0,                              # ProtocolDataRequestSubValue
        _PROTO_SPEC_SIZE,               # ProtocolDataOffset（相对返回缓冲头部）
        _HEALTH_LOG_SIZE,               # ProtocolDataLength
        0, 0,                           # FixedProtocolReturnData + 保留
    )
    return buf


def _u64_at(data: bytes, offset: int) -> int:
    """取 128 位小端计数字段的低 64 位。"""
    return struct.unpack_from("<Q", data, offset)[0]


def parse_health_log(data: bytes) -> dict | None:
    """解析 512 字节 NVMe 健康日志页（自适应标准 / +24 偏移两种布局）。

    Args:
        data: DeviceIoControl 返回的健康日志页原始字节。

    Returns:
        健康字段字典；数据过短或非法返回 None。纯函数，供自检复用。
    """
    if not data or len(data) < _MIN_LOG_SIZE:
        return None

    # 头部字段两种布局固定在标准偏移：
    # critical_warning@0(u8) / composite_temp@1(u16, 开尔文) /
    # available_spare@3(u8) / spare_threshold@4(u8) / percentage_used@5(u8)
    crit_warn, temp_k, spare, spare_thr, pct_used = struct.unpack_from("<BHBBB", data, 0)

    layout = _LAYOUT_STD
    du_read = _u64_at(data, layout["data_units_read"])
    du_written = _u64_at(data, layout["data_units_written"])
    # 自适应：标准布局读写字计数全 0，而 +24 偏移处非零 -> 采用偏移布局
    if du_read + du_written == 0:
        alt_read = _u64_at(data, _LAYOUT_SHIFTED["data_units_read"])
        alt_written = _u64_at(data, _LAYOUT_SHIFTED["data_units_written"])
        if alt_read + alt_written > 0:
            layout = _LAYOUT_SHIFTED
            du_read, du_written = alt_read, alt_written

    return {
        "critical_warning": crit_warn,
        "temperature_c": (temp_k - 273) if temp_k > 0 else None,
        "available_spare_pct": spare,
        "spare_threshold": spare_thr,
        "percentage_used": pct_used,
        "data_units_read": du_read,
        "data_units_written": du_written,
        "power_cycles": _u64_at(data, layout["power_cycles"]),
        "power_on_hours": _u64_at(data, layout["power_on_hours"]),
        "unsafe_shutdowns": _u64_at(data, layout["unsafe_shutdowns"]),
        "media_errors": _u64_at(data, layout["media_errors"]),
        "error_log_entries": _u64_at(data, layout["error_log_entries"]),
    }


def query_nvme_health(drive_number: int) -> dict | None:
    """直读指定物理盘的 NVMe 健康日志页。

    Args:
        drive_number: 物理盘编号（PhysicalDrive{n}，与 Get-PhysicalDisk
            的 DeviceId 一致）。

    Returns:
        parse_health_log 的解析结果；非 NVMe 盘 / 无权限 / 查询失败 /
        解析失败一律返回 None（调用方优雅降级），绝不抛异常。
    """
    if not isinstance(drive_number, int) or isinstance(drive_number, bool) or drive_number < 0:
        return None
    try:
        k32 = _load_kernel32()
        path = f"\\\\.\\PhysicalDrive{drive_number}"
        handle = k32.CreateFileW(
            path,
            _GENERIC_READ | _GENERIC_WRITE,
            _FILE_SHARE_READ_WRITE,
            None,
            _OPEN_EXISTING,
            0,
            None,
        )
        if handle == INVALID_HANDLE_VALUE or not handle:
            return None  # 无管理员权限或设备不存在
        try:
            buf = _build_query_buffer()
            bytes_returned = wt.DWORD(0)
            ok = k32.DeviceIoControl(
                handle,
                IOCTL_STORAGE_QUERY_PROPERTY,
                buf,
                _INPUT_SIZE,
                buf,
                _INPUT_SIZE,
                ctypes.byref(bytes_returned),
                None,
            )
            if not ok:
                return None
            start = 8 + _PROTO_SPEC_SIZE
            data = bytes(buf[start:start + _HEALTH_LOG_SIZE])
            return parse_health_log(data)
        finally:
            k32.CloseHandle(handle)
    except Exception:
        # 任何异常（驱动不支持 / 权限 / 内存）都降级为「读不到」
        return None


def format_data_units(data_units: object) -> str | None:
    """把 NVMe Data Units 计数格式化为人类可读容量（1 DU = 512,000 字节）。

    Returns:
        如「21.7 TB」「850 GB」；None / 非法值返回 None（界面显示「—」）。
    """
    if data_units is None or isinstance(data_units, bool):
        return None
    try:
        du = int(data_units)
    except (TypeError, ValueError):
        return None
    if du < 0:
        return None
    total_bytes = du * 512_000
    gb = total_bytes / (1024 ** 3)
    if gb >= 1024:
        return f"{gb / 1024:.1f} TB"
    return f"{gb:.0f} GB"
