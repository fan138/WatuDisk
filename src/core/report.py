# -*- coding: utf-8 -*-
"""HTML 检测报告导出。

仅在用户点击「导出报告」并通过 QFileDialog 选择保存路径后才写文件；
其余任何情况下本模块不产生任何磁盘写入。报告为单文件内联 CSS 的 HTML。
"""
from __future__ import annotations

import html
from datetime import datetime

from core import metrics as metric_mod
from core.nvme_health import format_data_units
from core.verdict import GRADE_COLORS, GRADE_LABELS, grade_of_verdict

APP_NAME = "挖兔硬盘精灵"
APP_VERSION = "v1.2.0"

_STYLE = """
body { font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
       background: #F5F6F8; color: #1F2937; margin: 0; padding: 28px 24px 40px; }
.wrap { max-width: 880px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 6px; letter-spacing: .2px; }
.meta { color: #6B7280; font-size: 13px; margin-bottom: 20px; }
.card { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 12px;
        padding: 18px 20px; margin-bottom: 14px;
        box-shadow: 0 1px 2px rgba(16, 24, 40, .04); }
.badge { display: inline-block; border-radius: 10px; padding: 3px 12px;
         font-size: 12px; font-weight: 700; margin-left: 8px; }
.ok   { background: #EAF3DE; color: #3E7B1F; }
.warn { background: #FCEBEB; color: #C0392B; }
.bad  { background: #F1948A; color: #FFFFFF; }
.model { font-size: 16px; font-weight: 700; }
.sub { color: #6B7280; font-size: 12px; margin: 4px 0 10px; }
ul { margin: 6px 0 0 18px; padding: 0; }
li { font-size: 13px; color: #4B5563; margin-bottom: 4px; line-height: 1.6; }
table { border-collapse: collapse; width: 100%; font-size: 12px; margin-top: 8px;
        border-radius: 8px; overflow: hidden; }
th, td { border-bottom: 1px solid #EEF0F3; padding: 7px 10px; text-align: left; }
th { background: #F3F4F6; color: #6B7280; font-weight: 600; }
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover { background: #FAFBFC; }
tr.bad-row td { color: #C0392B; font-weight: 600; }
h2 { font-size: 15px; margin: 14px 0 6px; }
/* 盘面扫描结论配色：与主界面「健康/警告/危险」药丸同色 */
.scan-good { color: #16A34A; font-weight: 700; }
.scan-warn { color: #D97706; font-weight: 700; }
.scan-bad  { color: #C0392B; font-weight: 700; }
.scan-unknown { color: #9CA3AF; font-weight: 700; }
.scan-stat { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 4px; }
.scan-chip { background: #F7F8FA; border: 1px solid #E9EBEF; border-radius: 8px;
             padding: 6px 12px; font-size: 12px; color: #4B5563; }
.scan-chip b { color: #1F2937; font-weight: 700; }
/* 盘面地图：20×20 格子，颜色与软件界面完全同源（surface_scan.CELL_COLORS） */
.grid { display: grid; grid-template-columns: repeat(20, 13px); gap: 1px;
        margin: 8px 0 6px; width: max-content; }
.grid i { width: 13px; height: 13px; display: block; border-radius: 2px; }
.grid-note { color: #9CA3AF; font-size: 11px; margin: 2px 0 0; }
tr.grid-row td { background: #FCFCFD; padding: 4px 10px 10px; }
tr.grid-row:hover { background: #FCFCFD; }
/* 页脚：链接做低调处理，不抢正文视线，但确实可点 */
.footer { color: #9CA3AF; font-size: 12px; margin-top: 22px; line-height: 1.9;
          border-top: 1px solid #E5E7EB; padding-top: 14px; }
.footer a { color: #6B7280; text-decoration: none; border-bottom: 1px dotted #B9BEC7; }
.footer a:hover { color: #2563EB; border-bottom-color: #2563EB; }
"""

# 项目与反馈地址（v1.2：报告页脚要给出入口，但做得低调不张扬）
GITHUB_URL = "https://github.com/fan138/WatuDisk"
GITHUB_ISSUES_URL = GITHUB_URL + "/issues"


def _esc(text: object) -> str:
    """HTML 转义。"""
    return html.escape(str(text if text is not None else ""))


def _pill(level: str, level_text: str, score: int, verdict_data: dict | None = None) -> str:
    """六档配色徽章（v1.5）：与主界面/托盘完全同色。"""
    # v1.1.0：U 盘等无 SMART 通道的设备如实标注，不显示误导性满分
    if verdict_data and verdict_data.get("monitor_supported") is False:
        return '<span class="badge" style="background:#9AA0A6;color:#FFFFFF">不支持 · 无 SMART 数据</span>'
    if verdict_data:
        grade = grade_of_verdict(verdict_data)
        if grade != -1:
            color = GRADE_COLORS.get(grade, "#9AA0A6")
            label = GRADE_LABELS.get(grade, level_text)
            return (
                f'<span class="badge" style="background:{color};color:#FFFFFF">'
                f"{_esc(label)} · {score} 分</span>"
            )
    cls = {"healthy": "ok", "warning": "warn", "danger": "bad"}.get(level, "warn")
    return f'<span class="badge {cls}">{_esc(level_text)} · {score} 分</span>'


def _colored(text: str, level: int) -> str:
    """按 0-3 警示等级给数值着色（0 = 默认深色）。"""
    if level <= metric_mod.LEVEL_OK:
        return _esc(text)
    color = metric_mod.LEVEL_TEXT_COLORS.get(level, "")
    label = {1: "注意", 2: "警告", 3: "危险"}.get(level, "")
    return f'<span style="color:{color};font-weight:700">{_esc(text)}</span> <span style="color:{color};font-size:11px">{label}</span>'


def _fmt_int(value: object) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "—"


def _metrics_table(result: dict) -> str:
    """专业指标表（v1.5）：与主界面同源的指标项 + 四色警示 + 状态列。"""
    items = metric_mod.metric_items_for_result(result)
    level_labels = {0: "正常", 1: "注意", 2: "警告", 3: "危险"}
    rows = "".join(
        f"<tr><td>{_esc(item['label'])}</td>"
        f"<td>{_colored(item['text'], int(item.get('level') or 0))}</td>"
        f"<td style='color:{metric_mod.LEVEL_TEXT_COLORS.get(int(item.get('level') or 0), '#6B7280')};"
        f"font-size:11px'>{level_labels.get(int(item.get('level') or 0), '正常')}</td></tr>"
        for item in items
    )
    return (
        "<h2>专业指标</h2><table>"
        "<tr><th>指标</th><th>数值</th><th>状态</th></tr>"
        + rows
        + "</table>"
    )


def _format_bytes(num: object) -> str:
    """字节数转可读文本（报告里复用 core.surface_scan 的口径，避免两套算法）。"""
    try:
        from core.surface_scan import format_size

        return format_size(num)
    except Exception:  # 兜底：surface_scan 不可用时不要让报告生成失败
        return str(num or 0)


def _grid_map_html(cells_code: object) -> str:
    """盘面地图（20×20 格子）：报告里也画出来，和软件界面看到的同一份数据。

    报告是给别人看的（坛友求助、自己留档），有图比只有一行字直观得多：
    一眼就能看出坏块集中在盘的哪一段。颜色直接取 surface_scan.CELL_COLORS，
    不在这里再写一套，避免「界面一个色、报告另一个色」。
    """
    try:
        from core import surface_scan
    except Exception:  # 核心模块不可用时就不画图，绝不让报告生成失败
        return ""
    cells = surface_scan.decode_cells(cells_code)
    if not any(state != surface_scan.CELL_PENDING for state in cells):
        return ""  # 全是「未扫描」说明没画过，别放一张空图占地方
    blocks = "".join(
        f"<i style='background:{surface_scan.cell_color(state)}'></i>" for state in cells
    )
    return f"<div class='grid'>{blocks}</div>"


def _grid_legend_html() -> str:
    """盘面地图的六色图例（与软件界面顺序一致）。"""
    try:
        from core import surface_scan
    except Exception:
        return ""
    items = []
    for state in (
        surface_scan.CELL_OK,
        surface_scan.CELL_SLOW,
        surface_scan.CELL_VERY_SLOW,
        surface_scan.CELL_FAILED,
        surface_scan.CELL_FAILED_RUN,
        surface_scan.CELL_PENDING,
    ):
        color = surface_scan.cell_color(state)
        items.append(
            f"<span style='display:inline-block;width:9px;height:9px;"
            f"border-radius:2px;background:{color};margin-right:4px'></span>"
            f"{_esc(surface_scan.CELL_LABELS.get(state, ''))}"
        )
    return (
        "<div class='grid-note'>" + "　".join(items)
        + "　（格子从上到下、从左到右 = 盘的开头到末尾）</div>"
    )


def _surface_scan_section(results: list[dict]) -> str:
    """盘面扫描结果卡片（v1.2）：展示每块盘「最近一次扫描」的结论与盘面地图。

    用户反馈：导出的报告里看不到盘面扫描结果，等于扫了白扫——还得回软件里
    再看一遍。这里把最近一次结果直接写进报告，报告才是完整的。

    只展示真跑完的记录（store 只存finished 的），没扫过的盘不会出现在这里。
    """
    scans: dict[str, dict] = {}
    try:
        from core.store import get_store

        scans = get_store().all_surface_scans()
    except Exception:  # 读不到就当作没扫过，绝不让报告生成失败
        scans = {}

    if not scans:
        return ""

    rows: list[str] = []
    for result in results:
        # 报告的 result 结构是嵌套的（result["disk"] 里才是盘信息），
        # 但历史/测试里有摊平写法，两种都要兼容，否则这块会静默不出内容。
        disk = result.get("disk") or result
        device_id = str(disk.get("device_id") or "")
        record = scans.get(device_id)
        if not isinstance(record, dict):
            continue
        model = str(record.get("model") or disk.get("model") or "未知型号")
        mode = str(record.get("mode") or "")
        scope = "全盘逐块" if mode == "full" else "抽样"
        failed = int(record.get("chunks_failed") or 0)
        ok_chunks = int(record.get("chunks_ok") or 0)

        if failed == 0:
            level_class, level_text = "scan-good", "未发现读失败"
        elif failed >= 10:
            level_class, level_text = "scan-bad", "多处读失败"
        else:
            level_class, level_text = "scan-warn", "零星读失败"

        chips = [
            f"<div class='scan-chip'>扫描方式<b>{_esc(scope)}</b></div>",
            f"<div class='scan-chip'>已读<b>{_esc(_format_bytes(record.get('bytes_scanned')))}</b></div>",
            f"<div class='scan-chip'>正常读取<b>{_esc(ok_chunks)}</b> 块</div>",
            f"<div class='scan-chip'>用时<b>{_esc(record.get('elapsed_sec') or 0)}</b> 秒"
            f"（{_esc(record.get('speed_mb_s') or 0)} MB/s）</div>",
        ]
        if failed:
            chips.append(f"<div class='scan-chip'>读失败<b>{_esc(failed)}</b> 块</div>")

        slow_cells = int(record.get("slow_cells") or 0)
        bad_cells = int(record.get("bad_cells") or 0)
        if slow_cells:
            chips.append(f"<div class='scan-chip'>读取偏慢区域<b>{_esc(slow_cells)}</b> 格</div>")
        if bad_cells:
            chips.append(f"<div class='scan-chip'>读失败区域<b>{_esc(bad_cells)}</b> 格</div>")

        rows.append(
            "<tr><td>" + _esc(model)
            + f"</td><td class='{level_class}'>" + _esc(level_text)
            # 必须包一层 .scan-stat：它才是那个 flex 容器，
            # 直接把 chip 丢进 td 会变成块级元素一个一行，整行被拉得很高。
            + "</td><td><div class='scan-stat'>" + "".join(chips)
            + "</div></td><td>" + _esc(record.get("scanned_at") or "")
            + "</td></tr>"
        )

        # 盘面地图单独占一整行：塞进「扫描详情」那一列会被挤成细长条，
        # 图看不清等于没画。colspan 铺满整行才看得出坏块集中在盘的哪一段。
        grid_html = _grid_map_html(record.get("cells_code"))
        if grid_html:
            rows.append(
                "<tr class='grid-row'><td colspan='4'>" + grid_html
                + _grid_legend_html() + "</td></tr>"
            )

    if not rows:
        return ""

    return (
        "<div class='card'><h2 style='margin-top:0'>盘面扫描（最近一次）</h2>"
        "<div class='sub'>逐块只读读取盘面，检查有没有读不出来或读得特别慢的地方（坏道）。"
        "这是 SMART 之外的另一道检查——SMART 是硬盘自己记账的，故障还没被记上时它可能一片绿。"
        "<b>未发现读失败不代表 100% 无故障</b>：抽样方式可能漏掉局部坏道，"
        "对结论有疑问可跑一次全盘扫描复核。"
        "下面展示的是各盘<b>最近一次</b>扫描结果（已自动保存到本机），"
        "导出报告时无需为刷新结果而重新扫描；想更新数据请在软件内重跑一次盘面扫描。</div>"
        # 明确列宽：不加 colgroup 时「扫描详情」会被挤成窄条，
        # 里面的一排统计块只好竖着堆，整行被拉得很高又难读。
        "<table><colgroup><col style='width:24%'><col style='width:12%'>"
        "<col style='width:44%'><col style='width:20%'></colgroup>"
        "<tr><th>型号</th><th>结论</th><th>扫描详情</th><th>扫描时间</th></tr>"
        + "".join(rows) + "</table></div>"
    )


def _disk_section(result: dict) -> str:
    """生成单块磁盘的详情 HTML 片段。"""
    disk = result.get("disk") or {}
    verdict_data = result.get("verdict") or {}
    counters = result.get("counters") or {}
    attrs = result.get("smart_attrs") or []

    size_gb = None
    try:
        size_gb = int(disk.get("size") or 0) / (1024 ** 3)
    except (TypeError, ValueError):
        size_gb = None
    size_text = "未知容量" if not size_gb else (f"{size_gb / 1024:.2f} TB" if size_gb >= 1024 else f"{size_gb:.0f} GB")

    lines: list[str] = []
    lines.append(f"<div class='model'>{_esc(disk.get('model') or '未知型号')}{_pill(verdict_data.get('level', ''), verdict_data.get('level_text', '未知'), verdict_data.get('score', 0), verdict_data)}</div>")
    lines.append(
        f"<div class='sub'>接口 {_esc(disk.get('bus_type') or '未知')} · "
        f"类型 {_esc(disk.get('media_type') or '未知')} · 容量 {size_text} · "
        f"序列号 {_esc(disk.get('serial') or '无')} · 系统状态 {_esc(disk.get('health_status') or '未知')}</div>"
    )

    metrics: list[str] = []
    temp = counters.get("Temperature")
    if isinstance(temp, int) and temp > 0:
        metrics.append(f"温度 {temp}°C")
    # v1.2（#18）：早期 SATA SSD 无寿命数据时，Windows 会把 Wear 填成默认 100。
    # 若照单全收会在报告里显示「剩余寿命 0%」，与「0% 危险」的判读结论一样构成误报。
    # 与 verdict/metrics 保持同一口径：硬件告警全为零时标注「未提供」。
    _raw05 = _raw06 = _rawc5 = 0
    for _attr in attrs:
        try:
            _rid = int(_attr.get("id") or 0)
            _rraw = int(_attr.get("raw") or 0)
        except (TypeError, ValueError):
            continue
        if _rid == 0x05:
            _raw05 = _rraw
        elif _rid == 0xC5:
            _rawc5 = _rraw
        elif _rid == 0xC6:
            _raw06 = _rraw
    _hardware_clean = (_raw05 == 0 and _rawc5 == 0 and _raw06 == 0)
    wear = counters.get("Wear")
    if wear is not None:
        _wear_i = int(wear)
        _life = max(0, 100 - _wear_i)
        # 与 verdict / metrics 同口径：仅抑制 wear==100（无数据默认值）造成的 0% 误报
        if _life == 0 and _wear_i == 100 and _hardware_clean:
            metrics.append("剩余寿命 未提供（早期硬盘）")
        else:
            metrics.append(f"剩余寿命 {_life}%")
    hours = counters.get("PowerOnHours")
    if hours is not None:
        metrics.append(f"通电 {_fmt_int(hours)} 小时")
    lines.append(f"<div class='sub'>{' · '.join(metrics) if metrics else '关键指标：无法读取'}</div>")

    lines.append("<h2>大白话判读与建议</h2><ul>")
    for reason in verdict_data.get("reasons", []):
        lines.append(f"<li>{_esc(reason)}</li>")
    lines.append("</ul>")

    lines.append(_metrics_table(result))

    ev_count = result.get("event_count") or 0
    ev_recent = result.get("event_recent") or []
    lines.append(f"<h2>事件日志（最近 30 天）</h2><div class='sub'>相关错误/警告 {_fmt_int(ev_count)} 条</div>")
    if ev_recent:
        lines.append("<ul>")
        for event in ev_recent[:5]:
            lines.append(
                f"<li>[{_esc(event.get('time'))}] [{_esc(event.get('level_text'))}] "
                f"{_esc(event.get('provider'))}：{_esc(event.get('message'))}</li>"
            )
        lines.append("</ul>")

    all_vols = result.get("all_volumes") or []
    dirty_vols = result.get("dirty_volumes") or []
    lines.append("<h2>卷损坏位与剩余空间</h2>")
    if all_vols:
        if dirty_vols:
            letters = "、".join(str(v.get("drive") or "?") for v in dirty_vols)
            # v1.2（#13）：措辞对齐判读层——脏位是文件系统标志而非硬件损坏，
            # 故用橙色提醒（原红色报警）并给出 chkdsk 修复指引。
            lines.append(
                f"<div class='sub' style='color:#D99A0B;font-weight:600'>"
                f"分区 {letters} 的文件系统脏位（Dirty Bit）已置位，多为未安全弹出或跨系统使用所致，"
                f"不代表硬盘硬件损坏；如需清除可运行 <code>chkdsk /f</code>。</div>"
            )
        else:
            lines.append("<div class='sub'>该盘所有分区的损坏位标志均未置位。</div>")
        # 剩余空间（v1.5：按阈值着色）
        for volume in all_vols:
            pct = volume.get("free_pct")
            if not isinstance(pct, (int, float)):
                continue
            free_gb = (volume.get("free") or 0) / 1024 ** 3
            total_gb = (volume.get("size") or 0) / 1024 ** 3
            level = metric_mod.level_for("free_space", pct)
            drive_letter = str(volume.get("drive") or "")
            space_text = f"{drive_letter} 剩余 {pct:.1f}%（{free_gb:.0f} GB / 共 {total_gb:.0f} GB）"
            lines.append(f"<div class='sub'>{_colored(space_text, level)}</div>")
    else:
        lines.append("<div class='sub'>无法读取卷损坏标志（需要管理员权限）。</div>")

    nvme = result.get("nvme_health") or {}
    if nvme:
        lines.append("<h2>NVMe 健康数据（直读健康日志）</h2><table>"
                     "<tr><th>指标</th><th>数值</th></tr>")
        nvme_rows: list[tuple[str, str, int]] = []
        crit = nvme.get("critical_warning")
        if crit is not None:
            nvme_rows.append(("危险警告", "有（请立即备份）" if crit else "无", metric_mod.level_for("critical_warning", crit)))
        temp = nvme.get("temperature_c")
        if isinstance(temp, int) and temp > -100:
            nvme_rows.append(("复合温度", f"{temp}°C", metric_mod.level_for("current_temp", temp)))
        spare = nvme.get("available_spare_pct")
        if spare is not None:
            threshold = nvme.get("spare_threshold")
            nvme_rows.append(
                ("可用备用空间", f"{spare}%" + (f"（告警阈值 {threshold}%）" if threshold is not None else ""),
                 metric_mod.level_for("spare", spare, {"spare_threshold": threshold}))
            )
        pct = nvme.get("percentage_used")
        if pct is not None:
            nvme_rows.append(("使用率（NVMe Percentage Used）", f"{pct}%", metric_mod.level_for("pct_used", pct)))
        written = format_data_units(nvme.get("data_units_written"))
        if written:
            nvme_rows.append(("累计写入量", written, metric_mod.LEVEL_OK))
        read = format_data_units(nvme.get("data_units_read"))
        if read:
            nvme_rows.append(("累计读取量", read, metric_mod.LEVEL_OK))
        hours = nvme.get("power_on_hours")
        if hours is not None:
            nvme_rows.append(("通电时间", f"{_fmt_int(hours)} 小时", metric_mod.LEVEL_OK))
        cycles = nvme.get("power_cycles")
        if cycles is not None:
            nvme_rows.append(("通电次数", _fmt_int(cycles), metric_mod.LEVEL_OK))
        unsafe = nvme.get("unsafe_shutdowns")
        if unsafe is not None:
            nvme_rows.append(("不安全断电", f"{_fmt_int(unsafe)} 次", metric_mod.level_for("unsafe_shutdowns", unsafe)))
        media_errors = nvme.get("media_errors")
        if media_errors is not None:
            nvme_rows.append(("媒体错误", f"{_fmt_int(media_errors)} 个", metric_mod.level_for("media_errors", media_errors)))
        err_entries = nvme.get("error_log_entries")
        if err_entries is not None:
            nvme_rows.append(("错误日志条目", _fmt_int(err_entries), metric_mod.LEVEL_OK))
        lines += "".join(
            f"<tr><td>{_esc(k)}</td><td>{_colored(v, lvl)}</td></tr>" for k, v, lvl in nvme_rows
        )
        lines.append("</table>")

    if attrs:
        lines.append("<h2>SMART 属性明细</h2><table><tr><th>ID</th><th>属性名称</th><th>当前值</th><th>原始值</th></tr>")
        for attr in attrs:
            key_ids = (0x05, 0xC5, 0xC6, 0xC7)
            row_cls = ""
            try:
                if int(attr.get("id") or 0) in key_ids and int(attr.get("raw") or 0) > 0:
                    row_cls = " class='bad-row'"
            except (TypeError, ValueError):
                pass
            lines.append(
                f"<tr{row_cls}><td>{_esc(attr.get('hex'))}</td><td>{_esc(attr.get('name'))}</td>"
                f"<td>{_esc(attr.get('value'))}</td><td>{_esc(attr.get('raw'))}</td></tr>"
            )
        lines.append("</table>")
    else:
        lines.append("<div class='sub'>SMART 属性：此通道无法读取。</div>")

    return "<div class='card'>" + "".join(lines) + "</div>"


def build_report_html(results: list[dict], version: str = APP_VERSION) -> str:
    """把完整检测结果构建为 HTML 报告字符串（不写盘）。"""
    from core import verdict as verdict_module

    summary = verdict_module.summarize(results)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows: list[str] = []
    for result in results:
        disk = result.get("disk") or {}
        verdict_data = result.get("verdict") or {}
        grade = grade_of_verdict(verdict_data)
        level_color = GRADE_COLORS.get(grade, "#6B7280")
        level_text = GRADE_LABELS.get(grade, verdict_data.get("level_text", "未知"))
        rows.append(
            "<tr><td>" + _esc(disk.get("model") or "未知型号")
            + "</td><td>" + _esc(disk.get("bus_type") or "未知")
            + "</td><td>" + _esc(disk.get("media_type") or "未知")
            + "</td><td>" + _esc(verdict_data.get("score", 0))
            + "</td><td style='color:" + level_color + ";font-weight:700'>" + _esc(level_text)
            + "</td></tr>"
        )

    parts: list[str] = []
    parts.append("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    parts.append(f"<title>{_esc(APP_NAME)} 检测报告</title><style>{_STYLE}</style></head><body><div class='wrap'>")
    parts.append(f"<h1>{_esc(APP_NAME)} {_esc(version)} · 硬盘健康检测报告</h1>")
    parts.append(
        f"<div class='meta'>生成时间：{_esc(generated)} ｜ 共 {summary['total']} 块硬盘 ｜ "
        f"健康 {summary['healthy']} 块 ｜ 警告 {summary['warning']} 块 ｜ 危险 {summary['danger']} 块</div>"
    )
    if rows:
        parts.append(
            "<div class='card'><h2 style='margin-top:0'>总览</h2>"
            "<table><tr><th>型号</th><th>接口</th><th>类型</th><th>评分</th><th>结论</th></tr>"
            + "".join(rows) + "</table></div>"
        )
    parts.append("".join(_disk_section(result) for result in results))
    parts.append(_surface_scan_section(results))
    # v1.2（#5）：健康分口径说明——坛友反馈「和HardDiskSentinel 数值对不上」。
    # 根因是各家算法权重不同（读的是同一份硬件数据），属正常现象，不是准不准的问题。
    parts.append(
        "<div class='card'><h2 style='margin-top:0'>关于健康分（与其他工具为何不同）</h2>"
        "<div class='sub'>本软件与 HardDiskSentinel、CrystalDiskInfo 等工具的<b>硬件读数是一致的</b>"
        "（温度、通电时间、坏块、寿命等底层数据相同），"
        "但<b>健康分是各家自己定的算法</b>：同样一块盘，"
        "有的把「温度偏高」扣得重、有的扣得轻；有的对「少量坏块」立刻降级、有的要累积到一定量才提示。"
        "所以<b>分数高低不完全一致是正常的</b>，它只反映「按本软件的保守程度」的健康状况，"
        "不代表硬件的真实寿命百分比，也不代表谁更准。</div>"
        "<div class='sub'>判断硬盘是否真的要换，请以硬件硬指标为准："
        "<b>重映射扇区、待映射扇区、无法修正扇区</b>是否持续增长、"
        "<b>SMART 是否报 Unhealthy</b>、以及厂商自带的检测工具结论。"
        "这些是客观事实，不受各家评分算法影响。</div></div>"
    )
    parts.append(
        "<div class='footer'>本报告由「挖兔硬盘精灵」只读检测生成（全程离线、不写入硬盘任何数据）。"
        "报告内容仅供参考，不构成专业数据恢复或维修建议；如遇重要数据，请以备份为先。<br>"
        f"项目源码（开源、欢迎查看实现）：<a href='{GITHUB_URL}'>{GITHUB_URL}</a><br>"
        f"发现问题或建议（提Issue 最有效）：<a href='{GITHUB_ISSUES_URL}'>{GITHUB_ISSUES_URL}</a></div>"
    )
    parts.append("</div></body></html>")
    return "".join(parts)


def export_report(path: str, results: list[dict], version: str = APP_VERSION) -> tuple[bool, str]:
    """把报告写入用户指定路径。

    Returns:
        (是否成功, 失败原因)。成功时第二个元素为空字符串。
    """
    try:
        content = build_report_html(results, version=version)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return True, ""
    except OSError as exc:
        return False, str(exc)
