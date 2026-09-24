# -*- coding: utf-8 -*-
"""集中管理 QSS 样式与配色常量。

设计基调：浅色主题、紧凑 SaaS 风格、圆角 8-12px、无粗黑外框、
药丸形按钮、Microsoft YaHei UI 字体。
"""
from __future__ import annotations

# ---- 配色常量 ----
COLOR_BG = "#F5F6F8"          # 页面背景（浅灰）
COLOR_CARD = "#FFFFFF"        # 卡片背景
COLOR_BORDER = "#E5E7EB"      # 卡片描边
COLOR_TEXT = "#1F2937"        # 主文字
COLOR_SUB = "#6B7280"         # 次要文字
COLOR_HINT = "#9CA3AF"        # 提示文字
COLOR_ACCENT = "#2563EB"      # 主色（蓝）
COLOR_ACCENT_DARK = "#1D4ED8"
COLOR_GREEN_BG = "#EAF3DE"    # 健康（浅绿）
COLOR_GREEN = "#3E7B1F"
COLOR_RED_BG = "#FCEBEB"      # 警告（浅红）
COLOR_RED = "#C0392B"
COLOR_GRAY_BG = "#F3F4F6"     # 中性（浅灰）

QSS = """
* {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    outline: none;
}
QMainWindow { background: #F5F6F8; }
QWidget#root { background: #F5F6F8; }

/* ---- 顶部标题栏 ---- */
QLabel#title { font-size: 17px; font-weight: 700; color: #1F2937; }
QLabel#badge { background: #EAF7EF; color: #1F9149; border-radius: 9px;
               padding: 3px 10px; font-size: 11px; font-weight: 600; }
QLabel#badgeGray { background: #EEF0F3; color: #6B7280; border-radius: 9px;
                   padding: 3px 10px; font-size: 11px; }
QLabel#badgeWarn { background: #FCEBEB; color: #C0392B; border-radius: 9px;
                   padding: 3px 10px; font-size: 11px; font-weight: 600; }
QLabel#warnTip { background: #FFF8E6; color: #9A6700; border: 1px solid #F5E2B8;
                 border-radius: 8px; padding: 8px 12px; font-size: 12px; }

/* ---- 概览指标卡 ---- */
QFrame#ovCardGray { background: #F3F4F6; border: 1px solid #E5E7EB; border-radius: 10px; }
QFrame#ovCardGreen { background: #EAF3DE; border: 1px solid #D9E7C6; border-radius: 10px; }
QFrame#ovCardRed { background: #FCEBEB; border: 1px solid #F1D4D4; border-radius: 10px; }
QLabel#ovNum { font-size: 22px; font-weight: 700; color: #1F2937; }
QLabel#ovNumGreen { font-size: 22px; font-weight: 700; color: #3E7B1F; }
QLabel#ovNumRed { font-size: 22px; font-weight: 700; color: #C0392B; }
QLabel#ovLabel { font-size: 12px; color: #6B7280; }

/* ---- 磁盘卡片 ---- */
QFrame#diskCard { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 10px; }
QFrame#diskCard:hover { border: 1px solid #C7D2FE; }
QFrame#diskCardDanger { background: #FFF7F6; border: 1.5px solid #E74C3C; border-radius: 10px; }
QLabel#diskName { font-size: 14px; font-weight: 600; color: #1F2937; }
QLabel#diskSub { font-size: 12px; color: #6B7280; }
QLabel#diskIconSSD { background: #EAF7EF; color: #2F9E4F; border-radius: 10px;
                     font-size: 13px; font-weight: 700; }
QLabel#diskIconHDD { background: #E8F0FE; color: #2563EB; border-radius: 10px;
                     font-size: 12px; font-weight: 700; }

/* ---- 状态药丸徽章（三档语义，v1.0 保留） ---- */
QLabel#pillHealthy { background: #EAF7EF; color: #2F9E4F; border-radius: 10px;
                     padding: 4px 12px; font-size: 12px; font-weight: 700; }
QLabel#pillWarning { background: #FCEBEB; color: #C0392B; border-radius: 10px;
                     padding: 4px 12px; font-size: 12px; font-weight: 700; }
QLabel#pillDanger { background: #F1948A; color: #FFFFFF; border-radius: 10px;
                    padding: 4px 12px; font-size: 12px; font-weight: 700; }
QLabel#pillGray { background: #EEF0F3; color: #6B7280; border-radius: 10px;
                  padding: 4px 12px; font-size: 12px; font-weight: 600; }

/* ---- 状态药丸徽章（v1.1 六档健康色：pillGrade5..pillGrade0，pillGrade-1=未检测） ---- */
QLabel#pillGrade5 { background: #1FAF52; color: #FFFFFF; border-radius: 10px;
                    padding: 4px 12px; font-size: 12px; font-weight: 700; }
QLabel#pillGrade4 { background: #67C23A; color: #FFFFFF; border-radius: 10px;
                    padding: 4px 12px; font-size: 12px; font-weight: 700; }
QLabel#pillGrade3 { background: #D99A0B; color: #FFFFFF; border-radius: 10px;
                    padding: 4px 12px; font-size: 12px; font-weight: 700; }
QLabel#pillGrade2 { background: #DD6B1D; color: #FFFFFF; border-radius: 10px;
                    padding: 4px 12px; font-size: 12px; font-weight: 700; }
QLabel#pillGrade1 { background: #C93A3A; color: #FFFFFF; border-radius: 10px;
                    padding: 4px 12px; font-size: 12px; font-weight: 700; }
QLabel#pillGrade0 { background: #8A1E1E; color: #FFFFFF; border-radius: 10px;
                    padding: 4px 12px; font-size: 12px; font-weight: 700; }
QLabel#pillGrade-1 { background: #EEF0F3; color: #6B7280; border-radius: 10px;
                     padding: 4px 12px; font-size: 12px; font-weight: 600; }

/* ---- 360 式体检步骤清单 ---- */
QFrame#stepsCard { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 10px; }
QLabel#stepRow { font-size: 12px; color: #9CA3AF; padding: 2px 4px; }
QLabel#stepRowRunning { font-size: 12px; color: #2563EB; font-weight: 700; padding: 2px 4px; }
QLabel#stepRowDone { font-size: 12px; color: #4B5563; padding: 2px 4px; }
QLabel#stepRowFailed { font-size: 12px; color: #DD6B1D; padding: 2px 4px; }
QLabel#stepSummary { font-size: 12px; color: #189B47; font-weight: 700; }

/* ---- 专业指标网格 ---- */
QFrame#metricsCard { background: #F8FAFC; border: 1px solid #EEF0F3; border-radius: 8px; }
QLabel#metricsTitle { font-size: 12px; font-weight: 700; color: #1F2937; }
QLabel#metricLabel { font-size: 12px; color: #6B7280; }
QLabel#metricValue { font-size: 12px; color: #1F2937; font-weight: 600; }

/* ---- 指标警示色（v1.3：异常数值文字变色） ---- */
QLabel#metricValueL1 { font-size: 12px; color: #B45309; font-weight: 700; }
QLabel#metricValueL2 { font-size: 12px; color: #DD6B1D; font-weight: 700; }
QLabel#metricValueL3 { font-size: 12px; color: #C93A3A; font-weight: 700; }
QLabel#metricValueIgnored { font-size: 12px; color: #1FAF52; font-weight: 600; }

/* ---- 忽略按钮（v1.3：异常项旁的小药丸） ---- */
QPushButton#ignoreBtn { background: #FFFFFF; color: #9CA3AF; border: 1px solid #E5E7EB;
                        border-radius: 9px; padding: 1px 8px; font-size: 11px; }
QPushButton#ignoreBtn:hover { color: #DD6B1D; border-color: #F0C4A0; background: #FFF8F2; }

/* ---- 体检记录面板（v1.3：健康痕迹，可折叠） ---- */
QFrame#historyCard { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 10px; }
QLabel#historyHeader { font-size: 13px; font-weight: 700; color: #1F2937; }
QPushButton#historyToggle { background: transparent; color: #6B7280; border: none;
                            font-size: 12px; padding: 2px 6px; }
QPushButton#historyToggle:hover { color: #2563EB; }
QLabel#historyRowOk { font-size: 12px; color: #1FAF52; padding: 1px 4px; }
QLabel#historyRowWarn { font-size: 12px; color: #B45309; padding: 1px 4px; }
QLabel#historyRowBad { font-size: 12px; color: #C93A3A; padding: 1px 4px; }
QLabel#historyEmpty { font-size: 12px; color: #9CA3AF; padding: 2px 4px; }
QLabel#historyDetail { font-size: 12px; color: #6B7280; padding: 1px 4px 3px 10px; }

/* ---- 提醒方案下拉框（v1.4） ---- */
QComboBox#profileCombo { background: #FFFFFF; color: #374151; border: 1px solid #E5E7EB;
                         border-radius: 9px; padding: 3px 10px; font-size: 12px; }
QComboBox#profileCombo:hover { border-color: #C7D2FE; }
QComboBox#profileCombo::drop-down { border: none; width: 18px; }
QComboBox#profileCombo QAbstractItemView { background: #FFFFFF; color: #374151;
                                           border: 1px solid #E5E7EB; selection-background-color: #EEF2FF;
                                           selection-color: #2563EB; }

/* ---- 设置行（开机启动 / 静默体检复选框） ---- */
QCheckBox#autostartCheck { font-size: 12px; color: #4B5563; spacing: 5px; }
QCheckBox#autostartCheck::indicator { width: 15px; height: 15px; border-radius: 4px;
                                      border: 1px solid #C7D2FE; background: #FFFFFF; }
QCheckBox#autostartCheck::indicator:checked { background: #2563EB;
                                               border: 1px solid #2563EB; }

/* ---- 卡片详情区 ---- */
QLabel#detailText { font-size: 12px; color: #4B5563; }
QLabel#detailTitle { font-size: 12px; font-weight: 700; color: #1F2937; }
QLabel#emptyTip { color: #9CA3AF; font-size: 13px; }

/* ---- 药丸按钮 ---- */
QPushButton#primary { background: #2563EB; color: #FFFFFF; border: none;
                      border-radius: 17px; padding: 8px 28px; font-size: 13px; font-weight: 600; }
QPushButton#primary:hover { background: #1D4ED8; }
QPushButton#primary:pressed { background: #1E40AF; }
QPushButton#primary:disabled { background: #B8C6E8; }
QPushButton#secondary { background: #FFFFFF; color: #2563EB; border: 1px solid #C7D2FE;
                        border-radius: 17px; padding: 7px 22px; font-size: 13px; font-weight: 600; }
QPushButton#secondary:hover { background: #EEF2FF; }
QPushButton#secondary:disabled { color: #9CA3AF; border-color: #E5E7EB; background: #FFFFFF; }

/* ---- 进度条 ---- */
QProgressBar { background: #E5E7EB; border: none; border-radius: 4px; }
QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                      stop:0 #3B82F6, stop:1 #2563EB); border-radius: 4px; }
QLabel#stageLabel { color: #6B7280; font-size: 12px; }
QLabel#note { color: #9CA3AF; font-size: 11px; }

/* ---- 表格 ---- */
QTableWidget { background: #FBFCFD; alternate-background-color: #F6F8FA;
               border: 1px solid #E5E7EB; border-radius: 8px;
               gridline-color: #EEF0F3; font-size: 12px; color: #374151; }
QHeaderView::section { background: #F3F4F6; color: #6B7280; border: none;
                       border-bottom: 1px solid #E5E7EB; padding: 5px 6px; font-size: 12px; }

/* ---- 滚动区域 / 滚动条 ---- */
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #D1D5DB; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QMessageBox { background: #FFFFFF; }
"""
