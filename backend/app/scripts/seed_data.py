"""数据库种子数据脚本 - 填充模板和素材

用法:
    python -m app.scripts.seed_data

填充内容:
    1. 初始管理员用户（需通过 SEED_ADMIN_* 环境变量显式提供）
    2. 模板素材 (5 个预设设计模板)
    3. 元素素材 (16 个 SVG 图标/装饰)
    4. 文字素材 (8 个预设文字样式)
    5. 背景素材 (8 个渐变/纯色背景)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from urllib.parse import quote

# 确保使用 SQLite 本地数据库（如果未配置 DATABASE_URL）
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./dev.db"

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select, func

from app.db.base import Base
from app.models.template import Template
from app.models.material import Material
from app.models.user import User
from app.core.security import hash_password


def get_local_session():
    """为本地种子脚本创建数据库会话"""
    db_url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")
    # SQLite 需要不同的连接参数
    if db_url.startswith("sqlite"):
        engine = create_async_engine(db_url, echo=False)
    else:
        engine = create_async_engine(db_url, echo=False, pool_size=5)
    return async_sessionmaker(engine, expire_on_commit=False)


# ============================================================
# 1. 模板素材 - 常见设计模板
# ============================================================

TEMPLATES = [
    {
        "name": "简约海报模板",
        "description": "适合活动宣传、演出海报的简约风格模板",
        "category": "poster",
        "tags": ["海报", "简约", "活动"],
        "fabric_json": json.dumps({
            "version": "5.3.0",
            "objects": [
                {"type": "rect", "left": 0, "top": 0, "width": 800, "height": 1200, "fill": "#1a1a2e", "selectable": False},
                {"type": "circle", "left": 600, "top": 200, "width": 300, "height": 300, "fill": "rgba(233,69,96,0.3)", "selectable": False},
                {"type": "circle", "left": 100, "top": 800, "width": 200, "height": 200, "fill": "rgba(0,168,150,0.3)", "selectable": False},
                {"type": "i-text", "left": 100, "top": 400, "width": 600, "text": "活动标题", "fontSize": 64, "fontWeight": "bold", "fill": "#ffffff", "fontFamily": "PingFang SC", "textAlign": "center", "selectable": True},
                {"type": "i-text", "left": 100, "top": 520, "width": 600, "text": "2026.04.25 | 地点名称", "fontSize": 24, "fill": "#e6e6e6", "fontFamily": "PingFang SC", "textAlign": "center", "selectable": True},
                {"type": "line", "x1": 300, "y1": 560, "x2": 500, "y2": 560, "stroke": "#e94560", "strokeWidth": 3, "selectable": False},
                {"type": "i-text", "left": 100, "top": 600, "width": 600, "text": "这里是副标题描述文字\n添加更多活动信息", "fontSize": 18, "fill": "#b3b3b3", "fontFamily": "PingFang SC", "textAlign": "center", "selectable": True},
            ],
            "width": 800, "height": 1200,
        }),
    },
    {
        "name": "社交媒体封面",
        "description": "微信公众号/小红书/微博封面图模板",
        "category": "social",
        "tags": ["社交媒体", "封面", "公众号"],
        "fabric_json": json.dumps({
            "version": "5.3.0",
            "objects": [
                {"type": "rect", "left": 0, "top": 0, "width": 1200, "height": 675, "fill": "#667eea", "selectable": False},
                {"type": "rect", "left": 0, "top": 0, "width": 600, "height": 675, "fill": "#764ba2", "selectable": False},
                {"type": "i-text", "left": 100, "top": 200, "width": 1000, "text": "封面标题", "fontSize": 72, "fontWeight": "bold", "fill": "#ffffff", "fontFamily": "PingFang SC", "selectable": True},
                {"type": "i-text", "left": 100, "top": 320, "text": "副标题描述文字", "fontSize": 28, "fill": "rgba(255,255,255,0.8)", "fontFamily": "PingFang SC", "selectable": True},
                {"type": "rect", "left": 100, "top": 400, "width": 100, "height": 6, "fill": "#ffffff", "selectable": False},
                {"type": "i-text", "left": 100, "top": 420, "text": "品牌名称 - 2026", "fontSize": 20, "fill": "rgba(255,255,255,0.6)", "fontFamily": "PingFang SC", "selectable": True},
            ],
            "width": 1200, "height": 675,
        }),
    },
    {
        "name": "商务名片模板",
        "description": "横版商务名片，简洁专业",
        "category": "card",
        "tags": ["名片", "商务", "横版"],
        "fabric_json": json.dumps({
            "version": "5.3.0",
            "objects": [
                {"type": "rect", "left": 0, "top": 0, "width": 540, "height": 324, "fill": "#ffffff", "selectable": False},
                {"type": "rect", "left": 0, "top": 0, "width": 8, "height": 324, "fill": "#2d3436", "selectable": False},
                {"type": "i-text", "left": 40, "top": 60, "text": "张 三", "fontSize": 32, "fontWeight": "bold", "fill": "#2d3436", "fontFamily": "PingFang SC", "selectable": True},
                {"type": "i-text", "left": 40, "top": 110, "text": "产品经理", "fontSize": 16, "fill": "#636e72", "fontFamily": "PingFang SC", "selectable": True},
                {"type": "line", "x1": 40, "y1": 150, "x2": 200, "y2": 150, "stroke": "#dfe6e9", "strokeWidth": 1, "selectable": False},
                {"type": "i-text", "left": 40, "top": 170, "text": "138-0000-0000\nzhangsan@company.com", "fontSize": 13, "fill": "#636e72", "fontFamily": "PingFang SC", "lineHeight": 1.8, "selectable": True},
                {"type": "i-text", "left": 300, "top": 60, "text": "公司名称", "fontSize": 20, "fontWeight": "bold", "fill": "#2d3436", "fontFamily": "PingFang SC", "selectable": True},
                {"type": "i-text", "left": 300, "top": 95, "text": "COMPANY NAME", "fontSize": 11, "fill": "#b2bec3", "fontFamily": "Arial", "selectable": True},
            ],
            "width": 540, "height": 324,
        }),
    },
    {
        "name": "电商促销 Banner",
        "description": "适合淘宝/京东等电商平台的促销横幅",
        "category": "banner",
        "tags": ["电商", "促销", "横幅"],
        "fabric_json": json.dumps({
            "version": "5.3.0",
            "objects": [
                {"type": "rect", "left": 0, "top": 0, "width": 750, "height": 352, "fill": "#ff6b6b", "selectable": False},
                {"type": "circle", "left": -50, "top": -50, "width": 200, "height": 200, "fill": "rgba(255,255,255,0.1)", "selectable": False},
                {"type": "circle", "left": 600, "top": 200, "width": 150, "height": 150, "fill": "rgba(255,255,255,0.1)", "selectable": False},
                {"type": "i-text", "left": 50, "top": 80, "text": "限时特惠", "fontSize": 56, "fontWeight": "bold", "fill": "#ffffff", "fontFamily": "PingFang SC", "selectable": True},
                {"type": "i-text", "left": 50, "top": 170, "text": "低至 5 折起", "fontSize": 36, "fill": "#fff3cd", "fontFamily": "PingFang SC", "selectable": True},
                {"type": "i-text", "left": 50, "top": 240, "text": "活动日期: 2026.4.20 - 4.30", "fontSize": 16, "fill": "rgba(255,255,255,0.8)", "fontFamily": "PingFang SC", "selectable": True},
                {"type": "rect", "left": 480, "top": 100, "width": 220, "height": 100, "fill": "#ffffff", "rx": 12, "ry": 12, "selectable": False},
                {"type": "i-text", "left": 530, "top": 120, "text": "立即抢购", "fontSize": 36, "fontWeight": "bold", "fill": "#ff6b6b", "fontFamily": "PingFang SC", "textAlign": "center", "selectable": True},
            ],
            "width": 750, "height": 352,
        }),
    },
    {
        "name": "极简 PPT 封面",
        "description": "适合演示文稿的极简风格封面",
        "category": "presentation",
        "tags": ["PPT", "演示", "极简"],
        "fabric_json": json.dumps({
            "version": "5.3.0",
            "objects": [
                {"type": "rect", "left": 0, "top": 0, "width": 1920, "height": 1080, "fill": "#f8f9fa", "selectable": False},
                {"type": "rect", "left": 0, "top": 0, "width": 1920, "height": 120, "fill": "#2d3436", "selectable": False},
                {"type": "i-text", "left": 200, "top": 300, "text": "演示文稿标题", "fontSize": 88, "fontWeight": "bold", "fill": "#2d3436", "fontFamily": "PingFang SC", "selectable": True},
                {"type": "rect", "left": 200, "top": 420, "width": 80, "height": 6, "fill": "#e94560", "selectable": False},
                {"type": "i-text", "left": 200, "top": 450, "text": "演讲人姓名 - 部门名称 - 2026年4月", "fontSize": 24, "fill": "#636e72", "fontFamily": "PingFang SC", "selectable": True},
                {"type": "i-text", "left": 200, "top": 900, "text": "CONFIDENTIAL", "fontSize": 14, "fill": "#b2bec3", "fontFamily": "Arial", "letterSpacing": 8, "selectable": False},
            ],
            "width": 1920, "height": 1080,
        }),
    },
]


# ============================================================
# 2. SVG 图标素材
# ============================================================

def make_svg_url(svg_content: str) -> str:
    """将 SVG 内容转为 data URI"""
    return "data:image/svg+xml," + quote(svg_content)


SVG_ICONS = [
    # 装饰类
    {"name": "星星", "type": "icon", "category": "decoration", "tags": ["星星", "装饰"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><polygon points="50,5 61,35 95,35 68,57 79,90 50,70 21,90 32,57 5,35 39,35" fill="#FFD700"/></svg>',
     "width": 100, "height": 100},
    {"name": "爱心", "type": "icon", "category": "decoration", "tags": ["爱心", "装饰"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 90"><path d="M50 85L7 47C-8 33-8 12 7 3C22-6 39-6 50 8C61-6 78-6 93 3C108 12 108 33 93 47L50 85Z" fill="#e94560"/></svg>',
     "width": 100, "height": 90},
    {"name": "圆点", "type": "icon", "category": "decoration", "tags": ["圆点", "装饰"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 50 50"><circle cx="25" cy="25" r="20" fill="#667eea"/></svg>',
     "width": 50, "height": 50},
    {"name": "波浪线", "type": "icon", "category": "decoration", "tags": ["波浪", "线条"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 40"><path d="M0 20 Q25 0 50 20 T100 20 T150 20 T200 20" fill="none" stroke="#667eea" stroke-width="4" stroke-linecap="round"/></svg>',
     "width": 200, "height": 40},

    # 箭头
    {"name": "箭头-右", "type": "icon", "category": "arrow", "tags": ["箭头", "右"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 60"><path d="M10 30 L70 30 M50 10 L80 30 L50 50" fill="none" stroke="#2d3436" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
     "width": 100, "height": 60},
    {"name": "箭头-左", "type": "icon", "category": "arrow", "tags": ["箭头", "左"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 60"><path d="M90 30 L30 30 M50 10 L20 30 L50 50" fill="none" stroke="#2d3436" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
     "width": 100, "height": 60},
    {"name": "箭头-上", "type": "icon", "category": "arrow", "tags": ["箭头", "上"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 100"><path d="M30 10 L30 70 M10 30 L30 10 L50 30" fill="none" stroke="#2d3436" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
     "width": 60, "height": 100},
    {"name": "箭头-下", "type": "icon", "category": "arrow", "tags": ["箭头", "下"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 100"><path d="M30 90 L30 30 M10 70 L30 90 L50 70" fill="none" stroke="#2d3436" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
     "width": 60, "height": 100},

    # 几何形状
    {"name": "六边形", "type": "shape", "category": "shape", "tags": ["六边形", "几何"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><polygon points="50,3 93,25 93,75 50,97 7,75 7,25" fill="#00a896"/></svg>',
     "width": 100, "height": 100},
    {"name": "菱形", "type": "shape", "category": "shape", "tags": ["菱形", "几何"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><polygon points="50,5 95,50 50,95 5,50" fill="#ff6b6b"/></svg>',
     "width": 100, "height": 100},
    {"name": "三角形", "type": "shape", "category": "shape", "tags": ["三角形", "几何"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><polygon points="50,10 90,90 10,90" fill="#ffd93d"/></svg>',
     "width": 100, "height": 100},
    {"name": "十字", "type": "shape", "category": "shape", "tags": ["十字", "几何"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M35 0 L65 0 L65 35 L100 35 L100 65 L65 65 L65 100 L35 100 L35 65 L0 65 L0 35 L35 35 Z" fill="#e94560"/></svg>',
     "width": 100, "height": 100},
    {"name": "五角星", "type": "shape", "category": "shape", "tags": ["星形", "几何"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><polygon points="50,0 63,35 100,35 70,57 82,95 50,72 18,95 30,57 0,35 37,35" fill="#ffd93d"/></svg>',
     "width": 100, "height": 100},

    # 常用图标
    {"name": "用户", "type": "icon", "category": "interface", "tags": ["用户", "人物"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="30" r="20" fill="#667eea"/><path d="M10 90 Q10 55 50 55 Q90 55 90 90" fill="#667eea"/></svg>',
     "width": 100, "height": 100},
    {"name": "邮件", "type": "icon", "category": "interface", "tags": ["邮件", "信封"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 80"><rect x="5" y="5" width="90" height="70" rx="5" fill="none" stroke="#2d3436" stroke-width="4"/><path d="M5 5 L50 45 L95 5" fill="none" stroke="#2d3436" stroke-width="4"/></svg>',
     "width": 100, "height": 80},
    {"name": "电话", "type": "icon", "category": "interface", "tags": ["电话", "手机"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M66 66C63 63 59 63 57 66L52 71C42 66 34 58 29 48L34 43C37 40 37 36 34 33C34 33 27 26 24 26C21 26 18 29 18 35C18 52 32 72 52 76C52 76 65 82 68 79C71 76 78 69 78 69C81 66 81 62 78 59L72 54C69 51 65 51 66 66Z" fill="#00a896"/></svg>',
     "width": 100, "height": 100},
    {"name": "定位", "type": "icon", "category": "interface", "tags": ["定位", "地图"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M50 5C30 5 15 20 15 40C15 65 50 95 50 95C50 95 85 65 85 40C85 20 70 5 50 5Z" fill="#e94560"/><circle cx="50" cy="38" r="12" fill="#ffffff"/></svg>',
     "width": 100, "height": 100},
    {"name": "对勾", "type": "icon", "category": "interface", "tags": ["对勾", "完成"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="45" fill="#00a896"/><path d="M25 50 L45 70 L75 30" fill="none" stroke="#ffffff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
     "width": 100, "height": 100},
    {"name": "叉号", "type": "icon", "category": "interface", "tags": ["叉号", "关闭"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="45" fill="#e94560"/><path d="M30 30 L70 70 M70 30 L30 70" fill="none" stroke="#ffffff" stroke-width="6" stroke-linecap="round"/></svg>',
     "width": 100, "height": 100},
    {"name": "齿轮", "type": "icon", "category": "interface", "tags": ["齿轮", "设置"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M50 15 L55 25 L65 20 L60 32 L72 32 L62 40 L70 48 L58 48 L62 60 L52 52 L45 62 L42 50 L30 52 L38 42 L28 35 L40 32 L35 20 L45 25 Z" fill="#636e72"/><circle cx="50" cy="50" r="12" fill="#ffffff"/></svg>',
     "width": 100, "height": 100},
    {"name": "放大镜", "type": "icon", "category": "interface", "tags": ["搜索", "放大镜"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="40" cy="40" r="25" fill="none" stroke="#2d3436" stroke-width="5"/><line x1="58" y1="58" x2="85" y2="85" stroke="#2d3436" stroke-width="5" stroke-linecap="round"/></svg>',
     "width": 100, "height": 100},

    # 自然元素
    {"name": "太阳", "type": "icon", "category": "nature", "tags": ["太阳", "天气"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="20" fill="#ffd93d"/><g stroke="#ffd93d" stroke-width="4" stroke-linecap="round"><line x1="50" y1="10" x2="50" y2="20"/><line x1="50" y1="80" x2="50" y2="90"/><line x1="10" y1="50" x2="20" y2="50"/><line x1="80" y1="50" x2="90" y2="50"/><line x1="22" y1="22" x2="29" y2="29"/><line x1="71" y1="71" x2="78" y2="78"/><line x1="22" y1="78" x2="29" y2="71"/><line x1="71" y1="29" x2="78" y2="22"/></g></svg>',
     "width": 100, "height": 100},
    {"name": "月亮", "type": "icon", "category": "nature", "tags": ["月亮", "天气"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M70 10C50 10 30 25 25 45C20 65 35 85 55 90C40 80 35 60 45 40C55 20 75 15 85 20C80 12 75 10 70 10Z" fill="#ffd93d"/></svg>',
     "width": 100, "height": 100},
    {"name": "云朵", "type": "icon", "category": "nature", "tags": ["云朵", "天气"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 80"><path d="M25 70C11 70 0 59 0 45C0 33 8 23 19 19C22 8 32 0 44 0C55 0 64 7 67 17C69 16 72 16 74 16C88 16 99 27 99 41C99 42 99 43 99 44C109 46 116 55 116 66C116 75 109 80 100 80H25Z" fill="#b2bec3"/></svg>',
     "width": 120, "height": 80},
    {"name": "闪电", "type": "icon", "category": "nature", "tags": ["闪电", "能量"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 100"><polygon points="35,0 10,55 30,55 20,100 50,40 30,40" fill="#ffd93d"/></svg>',
     "width": 60, "height": 100},

    # 播放/媒体
    {"name": "播放", "type": "icon", "category": "media", "tags": ["播放", "视频"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><polygon points="30,15 85,50 30,85" fill="#e94560"/></svg>',
     "width": 100, "height": 100},
    {"name": "暂停", "type": "icon", "category": "media", "tags": ["暂停", "视频"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect x="20" y="15" width="20" height="70" rx="3" fill="#636e72"/><rect x="60" y="15" width="20" height="70" rx="3" fill="#636e72"/></svg>',
     "width": 100, "height": 100},
    {"name": "收藏", "type": "icon", "category": "media", "tags": ["收藏", "星标"],
     "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><polygon points="50,5 63,35 95,35 70,55 80,90 50,70 20,90 30,55 5,35 37,35" fill="#ffd93d"/></svg>',
     "width": 100, "height": 100},
]


# ============================================================
# 3. 文字素材 - 预设文字样式
# ============================================================

TEXT_MATERIALS = [
    {"name": "大标题", "type": "text", "category": "title",
     "tags": ["标题", "大字"],
     "fabric_json": json.dumps({
         "type": "i-text", "text": "大标题", "fontSize": 72, "fontWeight": "bold",
         "fontFamily": "PingFang SC", "fill": "#2d3436",
     })},
    {"name": "副标题", "type": "text", "category": "subtitle",
     "tags": ["副标题"],
     "fabric_json": json.dumps({
         "type": "i-text", "text": "副标题文字", "fontSize": 36,
         "fontFamily": "PingFang SC", "fill": "#636e72",
     })},
    {"name": "正文", "type": "text", "category": "body",
     "tags": ["正文", "段落"],
     "fabric_json": json.dumps({
         "type": "i-text", "text": "这是一段正文文字，适合用于描述内容。",
         "fontSize": 18, "fontFamily": "PingFang SC", "fill": "#2d3436",
     })},
    {"name": "英文标题", "type": "text", "category": "title",
     "tags": ["英文", "标题"],
     "fabric_json": json.dumps({
         "type": "i-text", "text": "ENGLISH TITLE", "fontSize": 60, "fontWeight": "bold",
         "fontFamily": "Arial", "fill": "#2d3436", "letterSpacing": 5,
     })},
    {"name": "引用文字", "type": "text", "category": "quote",
     "tags": ["引用", "语录"],
     "fabric_json": json.dumps({
         "type": "i-text", "text": "这是一段引用文字", "fontSize": 24,
         "fontFamily": "PingFang SC", "fill": "#636e72", "fontStyle": "italic",
     })},
    {"name": "标签文字", "type": "text", "category": "label",
     "tags": ["标签", "小字"],
     "fabric_json": json.dumps({
         "type": "i-text", "text": "TAG LABEL", "fontSize": 14, "fontWeight": "bold",
         "fontFamily": "Arial", "fill": "#ffffff", "letterSpacing": 3,
     })},
    {"name": "数字展示", "type": "text", "category": "number",
     "tags": ["数字", "数据"],
     "fabric_json": json.dumps({
         "type": "i-text", "text": "100", "fontSize": 96, "fontWeight": "bold",
         "fontFamily": "Arial", "fill": "#667eea",
     })},
    {"name": "装饰文字", "type": "text", "category": "decorative",
     "tags": ["装饰", "花体"],
     "fabric_json": json.dumps({
         "type": "i-text", "text": "Hello", "fontSize": 48, "fontWeight": "bold",
         "fontFamily": "Georgia", "fill": "#e94560",
     })},
]


# ============================================================
# 4. 背景素材 - 渐变色和纯色背景
# ============================================================

def make_gradient_bg(colors: list[str], width: int = 1920, height: int = 1080) -> str:
    """生成渐变背景 SVG data URI"""
    stops = []
    for i, c in enumerate(colors):
        pct = i * 100 // (len(colors) - 1)
        stops.append(f"<stop offset='{pct}%' stop-color='{c}'/>")
    stops_str = "".join(stops)
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}'>"
        f"<defs><linearGradient id='g' x1='0%' y1='0%' x2='100%' y2='100%'>"
        f"{stops_str}</linearGradient></defs>"
        f"<rect width='100%' height='100%' fill='url(%23g)'/></svg>"
    )
    return "data:image/svg+xml," + quote(svg)


def make_solid_bg(color: str, width: int = 1920, height: int = 1080) -> str:
    """生成纯色背景 SVG data URI"""
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}'>"
        f"<rect width='100%' height='100%' fill='{color}'/></svg>"
    )
    return "data:image/svg+xml," + quote(svg)


BACKGROUND_MATERIALS = [
    {"name": "渐变蓝紫", "type": "background", "category": "gradient",
     "tags": ["渐变", "蓝色", "紫色"],
     "url": make_gradient_bg(["#667eea", "#764ba2"])},
    {"name": "渐变暖色", "type": "background", "category": "gradient",
     "tags": ["渐变", "暖色", "橙红"],
     "url": make_gradient_bg(["#ff6b6b", "#ffa07a"])},
    {"name": "渐变深色", "type": "background", "category": "gradient",
     "tags": ["渐变", "深色", "暗色"],
     "url": make_gradient_bg(["#1a1a2e", "#16213e"])},
    {"name": "渐变绿色", "type": "background", "category": "gradient",
     "tags": ["渐变", "绿色", "清新"],
     "url": make_gradient_bg(["#00a896", "#02c39a"])},
    {"name": "渐变金粉", "type": "background", "category": "gradient",
     "tags": ["渐变", "金色", "粉色"],
     "url": make_gradient_bg(["#ffd93d", "#ff6b6b"])},
    {"name": "纯白背景", "type": "background", "category": "solid",
     "tags": ["纯色", "白色"],
     "url": make_solid_bg("#ffffff")},
    {"name": "纯黑背景", "type": "background", "category": "solid",
     "tags": ["纯色", "黑色"],
     "url": make_solid_bg("#1a1a1a")},
    {"name": "浅灰背景", "type": "background", "category": "solid",
     "tags": ["纯色", "灰色"],
     "url": make_solid_bg("#f8f9fa")},
    {"name": "浅蓝背景", "type": "background", "category": "solid",
     "tags": ["纯色", "蓝色"],
     "url": make_solid_bg("#e8f4fd")},
    {"name": "浅粉背景", "type": "background", "category": "solid",
     "tags": ["纯色", "粉色"],
     "url": make_solid_bg("#fce4ec")},
]


# ============================================================
# 种子脚本主逻辑
# ============================================================

async def seed():
    """填充种子数据到数据库"""
    local_session = get_local_session()

    async with local_session() as db:
        # 创建表（如果不存在）
        engine = db.bind
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # 检查是否已有数据
        tpl_count = (await db.execute(select(func.count(Template.id)))).scalar() or 0
        force = "--reset" in sys.argv

        if tpl_count > 0 and not force:
            print(f"数据库已有 {tpl_count} 条模板。如需重新填充，请运行: python -m app.scripts.seed_data --reset")
            return

        if tpl_count > 0 and force:
            print(f"清除现有 {tpl_count} 条模板和素材...")
            await db.execute(Template.__table__.delete())
            await db.execute(Material.__table__.delete())
            await db.execute(User.__table__.delete())
            await db.commit()
            print("已清除。")

        print("=" * 50)
        print("开始填充种子数据...")
        print("=" * 50)

        # 1. 创建初始管理员（必须显式配置，避免默认弱口令进入环境）
        admin_username = os.getenv("SEED_ADMIN_USERNAME", "").strip()
        admin_email = os.getenv("SEED_ADMIN_EMAIL", "").strip()
        admin_password = os.getenv("SEED_ADMIN_PASSWORD", "")
        if not admin_username or not admin_email or not admin_password:
            raise RuntimeError(
                "缺少 SEED_ADMIN_USERNAME / SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD，"
                "拒绝创建默认管理员"
            )
        admin = User(
            username=admin_username,
            email=admin_email,
            hashed_password=hash_password(admin_password),
            is_active=True,
        )
        db.add(admin)
        await db.flush()
        print(f"[1/4] 创建初始管理员: {admin_username}")

        # 2. 模板素材
        for t in TEMPLATES:
            db.add(Template(
                name=t["name"], description=t["description"],
                category=t["category"], tags=t["tags"],
                fabric_json=t["fabric_json"], is_public=True,
                created_by=admin.id,
            ))
        print(f"[2/4] 填充 {len(TEMPLATES)} 个设计模板")

        # 3. SVG 元素素材
        for icon in SVG_ICONS:
            db.add(Material(
                name=icon["name"], type=icon["type"],
                url=make_svg_url(icon["svg"]),
                width=icon["width"], height=icon["height"],
                category=icon["category"], tags=icon["tags"],
                created_by=admin.id,
            ))
        print(f"[3/4] 填充 {len(SVG_ICONS)} 个 SVG 元素素材")

        # 4. 文字素材
        for txt in TEXT_MATERIALS:
            db.add(Material(
                name=txt["name"], type=txt["type"],
                url="",  # 文字素材使用 fabric_json 字段存储样式
                category=txt["category"], tags=txt["tags"],
                created_by=admin.id,
            ))
        print(f"       填充 {len(TEXT_MATERIALS)} 个文字素材")

        # 5. 背景素材
        for bg in BACKGROUND_MATERIALS:
            db.add(Material(
                name=bg["name"], type=bg["type"],
                url=bg["url"], width=1920, height=1080,
                category=bg["category"], tags=bg["tags"],
                created_by=admin.id,
            ))
        print(f"       填充 {len(BACKGROUND_MATERIALS)} 个背景素材")

        await db.commit()

        # 统计
        final_tpl = (await db.execute(select(func.count(Template.id)))).scalar()
        final_mat = (await db.execute(select(func.count(Material.id)))).scalar()
        print("=" * 50)
        print(f"填充完成!")
        print(f"  模板: {final_tpl} 条")
        print(f"  素材: {final_mat} 条")
        print(f"  管理员账号: {admin_username} / <来自 SEED_ADMIN_PASSWORD>")
        print("=" * 50)


if __name__ == "__main__":
    asyncio.run(seed())
