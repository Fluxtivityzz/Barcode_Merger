"""
应用配置常量与集中管理
"""

# ============ 应用基本信息 ============
APP_TITLE = "条码合并工具"
SKIP_KEYWORD = "前后规格不同，请不要贴错"

# ============ 窗口尺寸 ============
PANEL_WIDTH = 430
DESIGN_WINDOW_W = 1440
DESIGN_WINDOW_H = 900
MIN_WINDOW_W = 1100
MIN_WINDOW_H = 700
DEFAULT_WINDOW_W = 1280
DEFAULT_WINDOW_H = 820

# ============ 颜色方案 ============
COLORS = {
    'bg': '#111318',
    'panel': '#181B22',
    'panel_2': '#20242D',
    'input_bg': '#0F1117',
    'preview_bg': '#0E1015',
    'text': '#F2F4F8',
    'muted': '#AAB1C0',
    'accent': '#D6B46A',
    'border': '#303643',
    'log_text': '#D7DBE5',
}

# ============ 字体配置 ============
FONTS = {
    'default': ('Segoe UI', 10),
    'semibold': ('Segoe UI Semibold', 10),
    'title': ('Segoe UI Semibold', 15),
    'section': ('Segoe UI Semibold', 10),
    'status': ('Segoe UI', 9),
    'muted': ('Segoe UI', 9),
    'mono': ('Consolas', 9),
    'placeholder': ('Segoe UI', 13),
}

# ============ UI组件尺寸 ============
UI_PADDING = {
    'outer': 18,
    'inner': 14,
    'small': 8,
    'tiny': 4,
}

# ============ 参数范围与步长 ============
PARAM_RANGES = {
    'barcode_width_ratio': {
        'min': 0.01,
        'max': 2.00,
        'step': 0.01,
        'format': '%.2f',
    },
    'bottom_margin': {
        'min': -500,
        'max': 500,
        'step': 1,
        'format': '%.0f',
    },
    'max_barcode_height': {
        'min': 1,
        'max': 1000,
        'step': 1,
        'format': '%.0f',
    },
    'x_offset': {
        'min': -500,
        'max': 500,
        'step': 1,
        'format': '%.0f',
    },
    'y_offset': {
        'min': -500,
        'max': 500,
        'step': 1,
        'format': '%.0f',
    },
}

# ============ 参数显示名称 ============
PARAM_LABELS = {
    'barcode_width_ratio': '条码宽度比例',
    'bottom_margin': '底部边距',
    'max_barcode_height': '条码最大高度',
    'x_offset': '水平偏移',
    'y_offset': '垂直偏移',
}

# ============ 默认参数值 ============
DEFAULT_PARAMS = {
    'barcode_width_ratio': '0.60',
    'bottom_margin': '3',
    'max_barcode_height': '90',
    'x_offset': '0',
    'y_offset': '0',
    'skip_keyword': SKIP_KEYWORD,
    'reverse_save': '0',
    'feature_filter_keyword': '',
    'feature_filter_after_merge': '0',
    'feature_filter_inverse': '0',
    'pdf_filter_keyword': '',
    'pdf_filter_inverse': '0',
}

# ============ 配置文件 ============
CONFIG_FILENAME = 'settings.json'
CONFIG_DIR_NAME = 'BarcodeMergerPro'

# ============ 预览相关 ============
PREVIEW_ZOOM_MODES = ['适应整页', '适应宽度', '25%', '50%', '75%', '100%', '150%', '200%', '300%']
PREVIEW_UPDATE_DELAY = 350  # ms
SETTINGS_SAVE_DELAY = 300  # ms
PREVIEW_CACHE_MAX_SIZE = 2  # 最多缓存2个文档对

# ============ 合并处理 ============
PDF_COMPRESSION = {
    'garbage': 4,
    'deflate': True,
}

# ============ 日志输出 ============
LOG_HEIGHT = 10  # 行数

# ============ 参数说明文本 ============
PARAM_HINTS = """条码宽度比例步长：0.01
底部边距 / 最大高度 / 偏移步长：1
底部边距越大，条码越靠上
垂直偏移为正，条码向下移动
水平偏移为正，条码向右移动"""
