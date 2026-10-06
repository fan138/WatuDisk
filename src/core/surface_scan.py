# -*- coding: utf-8 -*-
"""盘面扫描（坏道扫描）：只读逐块读取物理盘，抓 SMART 尚未记录的读失败。

按键名与报告里一律称「盘面扫描」——扫的是磁盘盘面（盘片表面）的可读性与
响应速度，「表面扫描」听着像扫外壳或扫文件系统，容易被误解。

为什么需要（坛友反馈 #3 / #4）：
- 「检测全绿但盘实际不稳」——SMART 是硬盘自己记账的，故障还没被它记上时，
  SMART 一片绿是常态，这正是挖兔要补的盲区。
- 「希望对比 HD Tune 的错误扫描」。

与 chkdsk /r 的区别（本项目铁律：全程只读、不写入任何数据）：
- chkdsk /r 会**写**（把可读数据搬到别处、把坏簇标记进位图），需要卷空闲、
  系统盘还得重启才能跑，与「只读检测」的承诺冲突，本模块一律不做。
- 本模块只做一件事：按顺序 ReadFile 读原始扇区，读不出来 = 该处读失败。
  不写、不标记、不修复。

两档扫描（读写速度差异巨大，实测本机 NVMe 约 1900MB/s、HDD 约 80MB/s）：
- quick（默认）：把盘面切成 20×20 = 400 个区间，每个区间抽查 1 块
  （共 400 块 ≈ 1.6GB），约 1 分钟出结果，适合日常体检。
  注意：抽样可能漏掉局部坏道，属设计取舍，UI 与报告都会如实写明。
- full：全盘逐块读完，能覆盖整块盘，但 1TB 机械盘可能需要 3 小时以上，
  必须由用户显式选择，UI 要预先告知预计耗时。

盘面地图（v1.2 格子热力图）：
- 把盘面按物理位置切成 20×20 = 400 个区间，一格一个颜色，扫到哪亮到哪，
  让「小而强悍」看得见：普通用户也能一眼看出坏块集中在盘的哪一段。
- **两档共用同一套区间划分**，所以快速档热力图与全盘档可以直接对比，
  不会出现「两张图含义不同」的误解。
- 快速档每区间只抽查 1 块，所以「绿」只代表「这一格抽到的那一块读得快」，
  **不等于这一格整段都扫过**——UI 必须标注抽查密度，这是防误导的底线。
- 颜色不只看「读没读出来」，还看**读得多慢**：坏道在彻底读不出之前，
  往往先表现为「这块特别慢」（磁头反复重试）。这是专业坏块工具的核心维度，
  也是本模块此前最大的短板，补上它能提前发现正在劣化的区域。
- 慢/很快的阈值用**相对值**（以本次扫描成功块的中位数为基准），
  因为机械盘天然几十毫秒、NVMe 几毫秒，用绝对毫秒会把两种盘的语义搞反。

安全约束：
-仅 GENERIC_READ 打开，绝不申请 GENERIC_WRITE。
- 共享读+写（FILE_SHARE_READ|FILE_SHARE_WRITE），不独占磁盘，系统照常可用。
- 采用 OVERLAPPED 异步读+ 事件等待，单块最长 _READ_TIMEOUT_MS 毫秒，
  超时即判失败。坏道会让硬盘内部反复重试，不设上限可能卡死几十分钟。
  （不能用 SetFileTimeOut——该API 并非所有 Windows 的 kernel32 都导出。）
- 支持随时中止（progress 回调返回 False；超时的块会被 CancelIoEx取消）。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes as wt

# ---------------------------------------------------------------- 常量

CHUNK_SIZE = 4 * 1024 * 1024  # 4MB 一块：太小的系统调用开销高，太大进度更新不及时
QUICK_TARGET_BYTES = 2 * 1024 * 1024 * 1024  # 快速档目标读取量上限 2GB
MAX_QUICK_CHUNKS = 512  # 快速档最多读多少块（2GB / 4MB = 512）
MAX_RECORDED_BAD = 50  # 最多保留多少个坏点明细，防止报告被刷屏

# ---- 盘面地图（20×20 格子热力图）----
# 400 格：够密（能看出坏块集中在盘的哪一段），又够疏（4MB×400 ≈ 1.6GB，
# 快速档 1 分钟内跑完，机械盘也不会让人等到不耐烦）。
GRID_COLS = 20
GRID_ROWS = 20
GRID_CELLS = GRID_COLS * GRID_ROWS  # 400

# 格子状态（顺序即严重程度，颜色沿用主界面已有的六档健康色，口径统一）
CELL_PENDING = 0      # 还没扫到
CELL_OK = 1           # 正常（读得快）
CELL_SLOW = 2         # 偏慢（≥3 倍基准）
CELL_VERY_SLOW = 3    # 很慢（≥10 倍基准）
CELL_FAILED = 4       # 读失败
CELL_FAILED_RUN = 5   # 连续读失败（最危险）

# 慢的判定倍数：以本次扫描「成功块耗时的中位数」为基准。
# 3 倍是「明显不对劲」，10 倍基本可以确认这块在反复重试。
SLOW_FACTOR = 3.0
VERY_SLOW_FACTOR = 10.0

_MAX_TIMING_SAMPLES = 4096  # 算基准最多采样多少块（全盘档可能几十万块）

# 格子颜色与图例文案：core 里统一定义，UI 与 HTML 报告共用一份，
# 避免两处各写一套颜色导致「界面上一个色、报告里另一个色」。
CELL_COLORS = {
    CELL_PENDING: "#E5E7EB",
    CELL_OK: "#67C23A",
    CELL_SLOW: "#D99A0B",
    CELL_VERY_SLOW: "#DD6B1D",
    CELL_FAILED: "#C93A3A",
    CELL_FAILED_RUN: "#8A1E1E",
}
CELL_LABELS = {
    CELL_PENDING: "未扫描",
    CELL_OK: "正常",
    CELL_SLOW: "偏慢",
    CELL_VERY_SLOW: "很慢",
    CELL_FAILED: "读失败",
    CELL_FAILED_RUN: "连续读失败",
}

# 单块读取最长等待时间：坏道会触发硬盘内部多次重试，不设上限会卡死
_READ_TIMEOUT_MS = 5000
_POLL_SLICE_MS = 120  # 中止检查的轮询粒度（要短，中止才感觉及时）

MODE_QUICK = "quick"
MODE_FULL = "full"

# Windows API 常量
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = wt.HANDLE(-1).value
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
ERROR_IO_PENDING = 997
ERROR_OPERATION_ABORTED = 995

# IOCTL_DISK_GET_LENGTH_INFO = CTL_CODE(FILE_DEVICE_DISK=0x7, 0x17, METHOD_BUFFERED, FILE_ANY_ACCESS)
#   注意 IOCTL 码算错会返回 err=1（ERROR_INVALID_FUNCTION），不是 0，
#   容易误判成「设备不支持」——实测 0x0007405C 才是长度查询。
IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C


class _OVERLAPPED(ctypes.Structure):
    """OVERLAPPED 结构（wintypes 里没有 ULONG_PTR，按指针宽度自己定义）。"""

    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", wt.DWORD),
        ("OffsetHigh", wt.DWORD),
        ("hEvent", wt.HANDLE),
    ]


class SurfaceScanUnavailable(RuntimeError):
    """无法打开该物理盘（权限不足、盘被独占等）。"""


# ---------------------------------------------------------------- ctypes 绑定

def _load_kernel32():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wt.HANDLE
    k32.CreateFileW.argtypes = [
        wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE,
    ]
    k32.ReadFile.restype = wt.BOOL
    k32.ReadFile.argtypes = [
        wt.HANDLE, wt.LPVOID, wt.DWORD, wt.LPDWORD, ctypes.POINTER(_OVERLAPPED),
    ]
    k32.GetOverlappedResult.restype = wt.BOOL
    k32.GetOverlappedResult.argtypes = [
        wt.HANDLE, ctypes.POINTER(_OVERLAPPED), wt.LPDWORD, wt.BOOL,
    ]
    k32.CreateEventW.restype = wt.HANDLE
    k32.CreateEventW.argtypes = [wt.LPVOID, wt.BOOL, wt.BOOL, wt.LPCWSTR]
    k32.WaitForSingleObject.restype = wt.DWORD
    k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    k32.CancelIoEx.restype = wt.BOOL
    k32.CancelIoEx.argtypes = [wt.HANDLE, ctypes.POINTER(_OVERLAPPED)]
    k32.CloseHandle.restype = wt.BOOL
    k32.CloseHandle.argtypes = [wt.HANDLE]
    k32.DeviceIoControl.restype = wt.BOOL
    k32.DeviceIoControl.argtypes = [
        wt.HANDLE, wt.DWORD, wt.LPVOID, wt.DWORD, wt.LPVOID, wt.DWORD,
        wt.LPDWORD, wt.LPVOID,
    ]
    return k32


def _physical_drive_path(device_id: object) -> str:
    """device_id 转 \\\\?\\PhysicalDriveN 路径。

    全代码库把 device_id 当纯数字字符串用（#12 枚举兜底也守住了这个不变量），
    这里只容忍纯数字；其它一律拒绝，避免拼出错误路径去读别的盘。
    """
    text = str(device_id if device_id is not None else "").strip()
    if not text.isdigit():
        raise SurfaceScanUnavailable(f"无法识别的磁盘编号：{device_id!r}")
    return f"\\\\.\\PhysicalDrive{text}"


def _query_length(k32, handle) -> int:
    """用 IOCTL_DISK_GET_LENGTH_INFO 取物理盘真实字节数。

    该 IOCTL 的输出结构是 GET_LENGTH_INFORMATION（长度 + 有效标志）。
    实测本机 NVMe 会返回正确的 Length 但 LengthValid=0，所以判断依据是
    「Length 是否为正」，而不是 LengthValid——只看后者会把所有盘都判成
    「容量未知」，扫描直接跑不起来。
    """
    class _GET_LENGTH_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("Length", ctypes.c_longlong),
            ("LengthValid", wt.DWORD),
        ]

    info = _GET_LENGTH_INFORMATION()
    returned = wt.DWORD(0)
    ok = k32.DeviceIoControl(
        handle, IOCTL_DISK_GET_LENGTH_INFO, None, 0,
        ctypes.byref(info), ctypes.sizeof(info),
        ctypes.byref(returned), None,
    )
    if not ok or info.Length <= 0:
        return 0
    return int(info.Length)


def _plan_offsets(total_bytes: int, mode: str) -> list[int]:
    """规划要读取的块起始偏移列表。

    quick：沿盘面均匀抽样（覆盖头、中、尾）。抽样块数**刻意取 400**——
    正好等于盘面地图的格子数，保证每个区间都被抽到 1 块，扫完即填满热力图，
    不会出现「图上一片灰、但扫描其实已经结束」的观感。
    full：每CHUNK_SIZE 一个块，覆盖全盘。
    """
    if total_bytes <= 0:
        return []
    chunk = CHUNK_SIZE
    max_offset = total_bytes - chunk
    if max_offset <= 0:
        return [0]

    if mode == MODE_FULL:
        count = total_bytes // chunk
        return [i * chunk for i in range(count)]

    # quick：一个区间抽一块（400 格 = 400 块），再被上限与总目标量夹住
    want = min(GRID_CELLS, MAX_QUICK_CHUNKS, QUICK_TARGET_BYTES // chunk)
    want = max(want, 8)  # 至少读 8 块，样本太少的结论没有意义
    if total_bytes <= want * chunk:
        # 盘很小，直接全读
        return [i * chunk for i in range(total_bytes // chunk)]
    step = max_offset / (want - 1)
    return [int(i * step) for i in range(want)]


# ---------------------------------------------------------------- 盘面地图

def cell_of_index(index: int, total_blocks: int) -> int:
    """第 index 块落在哪个盘面格子（0..399）。

    按**物理位置比例**映射，所以快速档（400 块）是「一块一格」的一一对应，
    全盘档（几十万块）也能正确聚合到同一个区间——两档共用同一套划分，
    这是「快速档与全盘档热力图可以直接对比」的前提。
    """
    if total_blocks <= 0:
        return 0
    cell = index * GRID_CELLS // total_blocks
    if cell < 0:
        return 0
    return min(cell, GRID_CELLS - 1)


def timing_step_for(total_blocks: int) -> int:
    """基准采样间隔：全盘档有几十万块，全部留样既没必要也占内存。

    等距取最多 _MAX_TIMING_SAMPLES 个样本即可——顺序覆盖整个盘面，
    中位数足够有代表性，不会出现「只采了盘头」的偏差。
    """
    if total_blocks <= 0:
        return 1
    return max(total_blocks // _MAX_TIMING_SAMPLES, 1)


def _median(values: list[float]) -> float:
    """中位数（自己实现，不引入 statistics 依赖）。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def classify_cell(blocks: int, failed: int, max_run: int, avg_ms: float, baseline_ms: float) -> int:
    """判定单个格子的状态（纯函数，方便测试各种组合）。

    Args:
        blocks: 这一格一共读过几块。
        failed: 其中读失败几块。
        max_run: 这一格内「连续读失败」的最长长度（≥2 说明是成片坏区）。
        avg_ms: 成功块的平均耗时（毫秒）。
        baseline_ms: 本次扫描成功块耗时的中位数（基准）。<=0 时无法判慢，
                     只按「读没读出来」判定，绝不乱标黄橙——宁可漏标不可误标。
    """
    if blocks <= 0:
        return CELL_PENDING
    if failed > 0:
        return CELL_FAILED_RUN if max_run >= 2 else CELL_FAILED
    if baseline_ms <= 0 or avg_ms <= 0:
        return CELL_OK
    ratio = avg_ms / baseline_ms
    if ratio >= VERY_SLOW_FACTOR:
        return CELL_VERY_SLOW
    if ratio >= SLOW_FACTOR:
        return CELL_SLOW
    return CELL_OK


def live_cell_state(failed: bool, current_run: int) -> int:
    """扫描途中的暂定状态（此时还算不出基准，只能判读没读出来）。

    实时刷新靠它：扫一块亮一格，让用户看见进度。扫完会用 classify_cell
    重新着色（补上黄/橙），所以这里标绿不代表最终颜色。
    """
    if not failed:
        return CELL_OK
    return CELL_FAILED_RUN if current_run >= 2 else CELL_FAILED


def cell_counts(cells: object) -> dict[int, int]:
    """统计各状态的格子数，供图例显示「正常 396 格 · 偏慢 3 格 · 读失败 1 格」。"""
    counts = {state: 0 for state in CELL_LABELS}
    if not isinstance(cells, (list, tuple)):
        return counts
    for state in cells:
        try:
            key = int(state)
        except (TypeError, ValueError):
            continue
        if key in counts:
            counts[key] += 1
    return counts


def encode_cells(cells: object) -> str:
    """400 个格子状态压成一个 400 字符的字符串，方便存进 JSON/报告。

    直接存 400 个数字的列表会让 JSON 又长又占地方，一个字符一格刚好。
    """
    if not isinstance(cells, (list, tuple)) or len(cells) != GRID_CELLS:
        return ""
    out = []
    for state in cells:
        try:
            value = int(state)
        except (TypeError, ValueError):
            value = CELL_PENDING
        if value < CELL_PENDING or value > CELL_FAILED_RUN:
            value = CELL_PENDING
        out.append(str(value))
    return "".join(out)


def decode_cells(text: object) -> list[int]:
    """encode_cells 的逆运算；数据异常时返回全「未扫描」，不让界面崩。"""
    if not isinstance(text, str) or len(text) != GRID_CELLS:
        return [CELL_PENDING] * GRID_CELLS
    out = []
    for char in text:
        if not char.isdigit():
            return [CELL_PENDING] * GRID_CELLS
        value = int(char)
        if value < CELL_PENDING or value > CELL_FAILED_RUN:
            value = CELL_PENDING
        out.append(value)
    return out


def cell_color(state: object) -> str:
    """格子状态取颜色；未知状态按「未扫描」处理。"""
    try:
        key = int(state)
    except (TypeError, ValueError):
        return CELL_COLORS[CELL_PENDING]
    return CELL_COLORS.get(key, CELL_COLORS[CELL_PENDING])


# ---------------------------------------------------------------- 主入口

def _read_chunk(k32, handle, event, buffer, overlapped, should_abort) -> tuple[int, bool]:
    """异步读一个块，带超时与中止。

    Returns:
        (实读字节数, 是否读失败)。
    """
    overlapped.Internal = 0
    overlapped.InternalHigh = 0
    overlapped.Offset = 0
    overlapped.OffsetHigh = 0
    overlapped.hEvent = event
    ctypes.memset(buffer, 0, 1)  # 复位标志位，让本轮的完成状态可判别

    read_bytes = wt.DWORD(0)
    ok = k32.ReadFile(handle, buffer, CHUNK_SIZE, ctypes.byref(read_bytes), ctypes.byref(overlapped))
    err = ctypes.get_last_error()

    # err=ERROR_IO_PENDING 表示已排队；否则代表已同步完成（或直接失败）
    if not ok and err != ERROR_IO_PENDING:
        return 0, True

    # 轮询等待事件，超时或用户中止就取消这次 I/O
    waited = 0
    while True:
        if should_abort is not None and should_abort():
            k32.CancelIoEx(handle, ctypes.byref(overlapped))
            return 0, True
        slice_ms = _POLL_SLICE_MS
        if waited + slice_ms > _READ_TIMEOUT_MS:
            slice_ms = max(_READ_TIMEOUT_MS - waited, 1)
        rc = k32.WaitForSingleObject(event, slice_ms)
        waited += slice_ms
        if rc == WAIT_OBJECT_0:
            break
        if rc == WAIT_TIMEOUT:
            if waited >= _READ_TIMEOUT_MS:
                k32.CancelIoEx(handle, ctypes.byref(overlapped))
                return 0, True
            continue
        # WAIT_FAILED 或其它：判失败，不在这里抛异常打断整轮扫描
        k32.CancelIoEx(handle, ctypes.byref(overlapped))
        return 0, True

    completed = wt.DWORD(0)
    got_ok = k32.GetOverlappedResult(
        handle, ctypes.byref(overlapped), ctypes.byref(completed), False
    )
    if not got_ok:
        return 0, True
    actual = completed.value
    if actual != CHUNK_SIZE:
        # 短读：这块有问题（坏道通常表现为读不满或直接报错）
        return actual, True
    return actual, False


def scan_surface(
    device_id: object,
    total_bytes: int,
    mode: str = MODE_QUICK,
    progress=None,
    is_aborted=None,
    on_cell=None,
) -> dict:
    """只读扫描一块物理盘的表面，记录读失败的块与每块的读取耗时。

    Args:
        device_id: 物理盘编号（纯数字字符串或整数）。
        total_bytes: 盘容量，用于规划读取块；<=0 时会自己查。
        mode: MODE_QUICK（抽样，默认）或 MODE_FULL（全盘）。
        progress: 可选回调 progress(done_bytes, total_to_scan, bad_chunks)
                  返回 False 表示用户中止。
        is_aborted: 可选回调 is_aborted() -> bool，供 UI 在读盘阻塞期间
                    检查「已中止」按钮（progress 只在块间隙才有机会被调用）。
        on_cell: 可选回调 on_cell(cell_index, state)，每读完一块就回调一次，
                 供界面实时把那一格点亮。此时还算不出「慢」的基准，
                 所以状态只可能是 正常/读失败/连续读失败，扫完会整体重算。

    Returns:
        结果字典（见 _empty_result）。
        打不开盘时抛 SurfaceScanUnavailable。
    """
    if mode not in (MODE_QUICK, MODE_FULL):
        raise ValueError(f"未知扫描档位：{mode!r}")

    k32 = _load_kernel32()
    path = _physical_drive_path(device_id)

    # 只读 + 共享读/写：不独占磁盘，系统和其他程序照常使用该盘
    handle = k32.CreateFileW(
        path,
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OVERLAPPED,
        None,
    )
    if handle == INVALID_HANDLE_VALUE or handle is None:
        err = ctypes.get_last_error()
        if err == 5:
            raise SurfaceScanUnavailable("需要管理员权限才能读取物理盘")
        if err == 32:
            raise SurfaceScanUnavailable("磁盘正被其他程序独占，无法读取")
        raise SurfaceScanUnavailable(f"无法打开磁盘（错误码 {err}）")

    event = k32.CreateEventW(None, True, False, None)
    if not event:
        k32.CloseHandle(handle)
        raise SurfaceScanUnavailable("无法创建等待事件（系统资源不足）")

    try:
        if not total_bytes or total_bytes <= 0:
            total_bytes = _query_length(k32, handle)
        offsets = _plan_offsets(total_bytes, mode)
        result = _empty_result(device_id, mode, total_bytes, len(offsets))

        if not offsets:
            result["error"] = "无法确定磁盘容量"
            return result

        buffer = ctypes.create_string_buffer(CHUNK_SIZE)
        overlapped = _OVERLAPPED()
        planned = len(offsets) * CHUNK_SIZE
        started = time.time()

        # 盘面地图的逐格聚合数据
        cell_blocks = [0] * GRID_CELLS
        cell_failed = [0] * GRID_CELLS
        cell_ms = [0.0] * GRID_CELLS
        cell_run = [0] * GRID_CELLS      # 这一格内连续读失败的最长长度
        cell_cur_run = [0] * GRID_CELLS  # 这一格内当前的连续失败长度
        timings: list[float] = []
        # 全盘档可能几十万块，等距抽样取基准即可（顺序覆盖全盘，中位数有代表性）
        timing_step = timing_step_for(len(offsets))

        for index, offset in enumerate(offsets):
            one_start = time.perf_counter()
            got, failed = _read_chunk(k32, handle, event, buffer, overlapped, is_aborted)
            cost_ms = (time.perf_counter() - one_start) * 1000.0

            cell = cell_of_index(index, len(offsets))
            cell_blocks[cell] += 1

            if failed:
                result["chunks_failed"] += 1
                result["bad_sectors"] += max(1, got // 512) if got else CHUNK_SIZE // 512
                if len(result["bad_positions"]) < MAX_RECORDED_BAD:
                    result["bad_positions"].append(
                        {"offset_bytes": offset, "block": index, "cell": cell}
                    )
                cell_failed[cell] += 1
                cell_cur_run[cell] += 1
                if cell_cur_run[cell] > cell_run[cell]:
                    cell_run[cell] = cell_cur_run[cell]
            else:
                result["chunks_ok"] += 1
                result["bytes_scanned"] += got
                cell_cur_run[cell] = 0
                cell_ms[cell] += cost_ms
                if index % timing_step == 0:
                    timings.append(cost_ms)

            if on_cell is not None:
                try:
                    on_cell(cell, live_cell_state(bool(failed), cell_cur_run[cell]))
                except Exception:
                    pass  # 界面回调出错不能影响扫描本身

            done = (index + 1) * CHUNK_SIZE
            if progress is not None and progress(done, planned, result["chunks_failed"]) is False:
                result["cancelled"] = True
                break
            if is_aborted is not None and is_aborted():
                result["cancelled"] = True
                break

        result["elapsed_sec"] = time.time() - started
        if result["elapsed_sec"] > 0:
            result["speed_mb_s"] = (result["bytes_scanned"] / 1048576) / result["elapsed_sec"]
        _finalize_cells(result, cell_blocks, cell_failed, cell_ms, cell_run, timings)
        result["finished"] = True
        return result
    finally:
        k32.CloseHandle(event)
        k32.CloseHandle(handle)


def _finalize_cells(
    result: dict,
    blocks: list[int],
    failed: list[int],
    ms: list[float],
    run: list[int],
    timings: list[float],
) -> None:
    """扫描结束后统一给 400 个格子定色。

    必须等扫完再定色：「慢」的基准（成功块耗时中位数）要拿全盘样本才算得准。
    扫描途中界面上那版颜色只是暂定的（见 live_cell_state），这里才是最终结论。
    """
    baseline = _median(timings)
    result["baseline_ms"] = round(baseline, 3)
    result["timings_sampled"] = len(timings)

    cells: list[int] = []
    for i in range(GRID_CELLS):
        ok_blocks = blocks[i] - failed[i]
        avg = (ms[i] / ok_blocks) if ok_blocks > 0 else 0.0
        cells.append(classify_cell(blocks[i], failed[i], run[i], avg, baseline))
    result["cells"] = cells

    counts = cell_counts(cells)
    result["cells_scanned"] = GRID_CELLS - counts[CELL_PENDING]
    result["slow_cells"] = counts[CELL_SLOW] + counts[CELL_VERY_SLOW]
    result["very_slow_cells"] = counts[CELL_VERY_SLOW]
    result["bad_cells"] = counts[CELL_FAILED] + counts[CELL_FAILED_RUN]
    result["cells_code"] = encode_cells(cells)


def _empty_result(device_id: object, mode: str, total_bytes: int, planned_chunks: int) -> dict:
    return {
        "device_id": str(device_id),
        "mode": mode,
        "total_bytes": int(total_bytes or 0),
        "planned_chunks": int(planned_chunks),
        "bytes_scanned": 0,
        "chunks_ok": 0,
        "chunks_failed": 0,
        "bad_sectors": 0,
        "bad_positions": [],
        "elapsed_sec": 0.0,
        "speed_mb_s": 0.0,
        "cancelled": False,
        "finished": False,
        "error": "",
        # 盘面地图（20×20 格子热力图）
        "cells": [CELL_PENDING] * GRID_CELLS,
        "cells_code": "",
        "baseline_ms": 0.0,
        "timings_sampled": 0,
        "cells_scanned": 0,
        "slow_cells": 0,
        "very_slow_cells": 0,
        "bad_cells": 0,
    }


# ---------------------------------------------------------------- 结果解读

def interpret(result: dict) -> tuple[str, str]:
    """把扫描结果翻成 (等级, 一句话结论)。

    等级：good（干净）/ warn（有零星读失败）/ bad（多处读失败）/
    unknown（未完成或不可用）。
    """
    if not isinstance(result, dict) or not result:
        return "unknown", "未进行盘面扫描"
    if result.get("error"):
        return "unknown", str(result["error"])

    # 中止必须优先判定（放在 finished 之前）：
    # 扫描随时可被用户按停，此时 finished 也是 True，若先看 finished 就会
    # 输出「未发现读失败区域」这种假阴性结论——用户会误以为盘没问题，
    # 而实际只扫了前几块。这是最危险的一种误报，宁可说「不知道」。
    if result.get("cancelled"):
        done = int(result.get("chunks_ok") or 0)
        bad = int(result.get("chunks_failed") or 0)
        read_text = format_size(result.get("bytes_scanned"))
        if bad:
            return "warn", f"扫描已中止（读到{read_text}，其中 {bad} 块读失败，未扫完）"
        return "unknown", f"扫描已被中止，只读到 {read_text}，未能扫完整块硬盘，不能作为「无故障」的依据"

    if not result.get("finished"):
        return "unknown", "扫描未完成"

    bad = int(result.get("chunks_failed") or 0)
    scanned = result.get("bytes_scanned") or 0

    # 「读得慢」的补充提示：坏道在彻底读不出来之前，往往先表现为明显变慢，
    # 这是提前预警，值得说一句。但不改变等级——慢也可能是盘内圈/外圈速度差、
    # SMR 叠瓦盘、USB 桥接等正常原因，直接判警告又会变成新的「吓人」投诉。
    slow_tail = ""
    slow = int(result.get("slow_cells") or 0)
    if slow > 0:
        slow_tail = f"；另有 {slow} 个区域读取明显偏慢（尚未读失败，建议留意）"

    if bad == 0:
        scope = "抽样" if result.get("mode") == MODE_QUICK else "全盘"
        return "good", f"{scope}读取 {format_size(scanned)}，未发现读失败区域{slow_tail}"
    ratio = bad / max(result.get("planned_chunks") or 1, 1)
    if ratio >= 0.05:
        return "bad", f"发现 {bad} 块区域完全读不出来，硬盘存在严重读故障，请立即备份数据"
    if ratio >= 0.005:
        return "bad", f"发现 {bad} 块区域读失败（占比 {ratio * 100:.2f}%），建议尽快备份并考虑更换"
    return "warn", f"发现 {bad} 块区域偶发读失败，可能是磁头或盘面出现劣化迹象，建议关注"


def format_size(num: object) -> str:
    """字节数转可读文本（1024 进制）。"""
    try:
        value = float(num or 0)
    except (TypeError, ValueError):
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024.0
        index += 1
    if index == 0:
        return f"{int(value)} {units[index]}"
    return f"{value:.2f} {units[index]}"


def estimate_full_scan_time(total_bytes: int, speed_mb_s: float) -> str:
    """按实测速度估算全盘扫描耗时，用于扫描前告知用户。

    Args:
        total_bytes: 盘容量。
        speed_mb_s: 实测读取速度（MB/s），<=0 时给不出可信估算，返回空串。
    """
    if not speed_mb_s or speed_mb_s <= 0 or not total_bytes:
        return ""
    seconds = (total_bytes / 1048576) / speed_mb_s
    if seconds < 60:
        return "不到 1 分钟"
    if seconds < 3600:
        return f"约 {seconds / 60:.0f} 分钟"
    if seconds < 86400:
        return f"约 {seconds / 3600:.1f} 小时"
    return f"约 {seconds / 86400:.1f} 天"