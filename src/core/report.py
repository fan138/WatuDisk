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
APP_VERSION = "v1.0.0"

_STYLE = """
body { font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
       background: #F5F6F8; color: #1F2937; margin: 0; padding: 24px; }
.wrap { max-width: 860px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 4px; }
.meta { color: #6B7280; font-size: 13px; margin-bottom: 20px; }
.card { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 10px;
        padding: 16px; margin-bottom: 12px; }
.badge { display: inline-block; border-radius: 10px; padding: 3px 12px;
         font-size: 12px; font-weight: 700; margin-left: 8px; }
.ok   { background: #EAF3DE; color: #3E7B1F; }
.warn { background: #FCEBEB; color: #C0392B; }
.bad  { background: #F1948A; color: #FFFFFF; }
.model { font-size: 16px; font-weight: 700; }
.sub { color: #6B7280; font-size: 12px; margin: 4px 0 10px; }
ul { margin: 6px 0 0 18px; padding: 0; }
li { font-size: 13px; color: #4B5563; margin-bottom: 4px; line-height: 1.6; }
table { border-collapse: collapse; width: 100%; font-size: 12px; margin-top: 8px; }
th, td { border: 1px solid #EEF0F3; padding: 5px 8px; text-align: left; }
th { background: #F3F4F6; color: #6B7280; }
tr.bad-row td { color: #C0392B; font-weight: 600; }
h2 { font-size: 15px; margin: 14px 0 4px; }
.footer { color: #9CA3AF; font-size: 12px; margin-top: 20px; line-height: 1.7; }
"""


def _esc(text: object) -> str:
    """HTML 转义。"""
    return html.escape(str(text if text is not None else ""))


def _pill(level: str, level_text: str, score: int, verdict_data: dict | None = None) -> str:
    """六档配色徽章（v1.5）：与主界面/托盘完全同色。"""
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
    wear = counters.get("Wear")
    if wear is not None:
        metrics.append(f"剩余寿命 {max(0, 100 - int(wear))}%")
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
            lines.append(f"<div class='sub' style='color:#C0392B;font-weight:600'>分区 {letters} 已置位「损坏位」，建议尽快检查文件系统。</div>")
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
    parts.append(
        "<div class='footer'>本报告由「挖兔硬盘精灵」只读检测生成（全程离线、不写入硬盘任何数据）。"
        "报告内容仅供参考，不构成专业数据恢复或维修建议；如遇重要数据，请以备份为先。</div>"
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
