"""管理后台取证导出服务（v10 变更 D，R2 §5.1/§5.4）。

把原先散在 `app/routers/admin.py` 的 `_build_conversation` / `_build_forensic_row`
下沉到服务层，并扩展出：

- 结构化对话 `build_conversation_rows`（详情接口用）；
- `scope=profile` 的精简取证行 `build_profile_row`；
- 三种格式渲染器 `render_csv` / `render_xlsx` / `render_md`，统一返回
  `(bytes, media_type, filename)`，由路由层直接包成 `Response`。

设计约束：

1. **openpyxl 惰性导入**：模块导入期绝不 `import openpyxl`。未安装时
   `render_xlsx` 抛 `ExportDependencyError`，路由层转 400 + `code 9001`，
   **禁止 500 堆栈**（AC-D12）。
2. **md 零依赖**：纯 f-string 拼装，内容需转义 `|` 与换行，否则表格被撑破。
3. `build_conversation` 的输出格式与 v7 **逐字节一致**（`[iso] 角色: 内容`，
   以 ` ⏎ ` 连接），`test_v7_admin_export.py` 依赖该格式。
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.im import IMMessage, IMSession
from app.models.item import FoundItem, LostItem
from app.models.match import MatchRecord
from app.models.user import User

# ---------------------------------------------------------------------------
# 字段定义（scope → 列顺序）。列顺序即导出文件的列顺序，改动会影响存量取证模板。
# ---------------------------------------------------------------------------
FORENSIC_FIELDS: list[str] = [
    "match_id",
    "lost_item_id", "lost_category", "lost_title", "lost_description",
    "lost_images", "lost_student_no", "lost_phone",
    "found_item_id", "found_category", "found_description",
    "found_images", "found_student_no", "found_phone",
    "completed_at",
    "conversation",
]

PROFILE_FIELDS: list[str] = [
    "match_id",
    "lost_item_id", "lost_category", "lost_title",
    "lost_student_no", "lost_phone", "lost_real_name",
    "found_item_id", "found_category",
    "found_student_no", "found_phone", "found_real_name",
    "match_score", "status", "completed_at",
]

CONVERSATION_FIELDS: list[str] = ["match_id", "sent_at", "role_label", "content"]

# scope → (列定义, Sheet 名)
SCOPE_FIELDS: dict[str, list[str]] = {
    "profile": PROFILE_FIELDS,
    "conversation": CONVERSATION_FIELDS,
    "all": FORENSIC_FIELDS,
}

_ROLE_LABELS: dict[int, str] = {0: "失主", 1: "拾得者"}

_MEDIA_TYPES: dict[str, str] = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "md": "text/markdown; charset=utf-8",
}


class ExportDependencyError(RuntimeError):
    """导出所需的可选依赖缺失（当前仅 xlsx 的 openpyxl）。

    由路由层捕获并转成 `400 + {"code": 9001, "message": ...}`，绝不冒泡成 500。
    """


def role_label(sender_role) -> str:
    """把 `IMMessage.sender_role` 映射为中文角色名（未知值按「拾得者」兜底）。"""
    try:
        return _ROLE_LABELS.get(int(sender_role), "拾得者")
    except (TypeError, ValueError):
        return "拾得者"


# ---------------------------------------------------------------------------
# 对话
# ---------------------------------------------------------------------------
def _load_messages(db: Session, match_id: int) -> list[IMMessage]:
    """取该匹配下全部 IM 消息（按 sent_at 升序）；无会话返回空列表。"""
    session_ids = [
        sid for (sid,) in db.query(IMSession.id)
        .filter(IMSession.match_id == match_id).all()
    ]
    if not session_ids:
        return []
    return (
        db.query(IMMessage)
        .filter(IMMessage.session_id.in_(session_ids))
        .order_by(IMMessage.sent_at.asc())
        .all()
    )


def build_conversation(db: Session, match_id: int) -> str:
    """拼接该匹配下全部 IM 对话文本（按 sent_at 升序），单行以 ⏎ 分隔。

    ⚠️ 输出格式与 v7 完全一致，`test_v7_admin_export.py` 依赖之，不得修改。

    Args:
        db: 数据库会话。
        match_id: 匹配 id。

    Returns:
        `"[iso] 失主: 内容 ⏎ [iso] 拾得者: 内容"`；无会话/无消息返回空串。
    """
    msgs = _load_messages(db, match_id)
    if not msgs:
        return ""
    parts = []
    for m in msgs:
        ts = m.sent_at.isoformat() if m.sent_at else ""
        parts.append(f"[{ts}] {role_label(m.sender_role)}: {m.content}")
    return " ⏎ ".join(parts)


def build_conversation_rows(db: Session, match_id: int) -> list[dict]:
    """结构化对话（详情接口 / conversation scope 导出用）。

    Args:
        db: 数据库会话。
        match_id: 匹配 id。

    Returns:
        `[{"sent_at": datetime|None, "sender_role": int, "role_label": str,
        "content": str}, ...]`，按 sent_at 升序；无会话返回 `[]`。
    """
    rows: list[dict] = []
    for m in _load_messages(db, match_id):
        try:
            sender_role = int(m.sender_role)
        except (TypeError, ValueError):
            sender_role = 1
        rows.append({
            "sent_at": m.sent_at,
            "sender_role": sender_role,
            "role_label": role_label(m.sender_role),
            "content": str(m.content or ""),
        })
    return rows


# ---------------------------------------------------------------------------
# 取证行
# ---------------------------------------------------------------------------
def _sides(db: Session, match: MatchRecord):
    """取匹配双方的物品与用户对象（任一缺失以 None 返回，不抛异常）。"""
    lost = db.get(LostItem, match.lost_id)
    found = db.get(FoundItem, match.found_id)
    lost_user = db.get(User, lost.publisher_id) if lost else None
    found_user = db.get(User, found.finder_id) if found else None
    return lost, found, lost_user, found_user


def build_forensic_row(db: Session, match: MatchRecord) -> dict:
    """构建单条全量取证行（含双方明文 student_no/phone、扁平对话文本）。

    列集合 = `FORENSIC_FIELDS`，与 v7 完全一致。
    """
    lost, found, lost_user, found_user = _sides(db, match)
    return {
        "match_id": match.id,
        "lost_item_id": lost.id if lost else "",
        "lost_category": lost.category_name if lost else "",
        "lost_title": lost.title if lost else "",
        "lost_description": lost.description if lost else "",
        "lost_images": "|".join(lost.images or []) if lost and lost.images else "",
        "lost_student_no": lost_user.student_no if lost_user else "",
        "lost_phone": lost_user.phone if lost_user else "",
        "found_item_id": found.id if found else "",
        "found_category": found.category_name if found else "",
        "found_description": found.description if found else "",
        "found_images": "|".join(found.images or []) if found and found.images else "",
        "found_student_no": found_user.student_no if found_user else "",
        "found_phone": found_user.phone if found_user else "",
        "completed_at": match.completed_at.isoformat() if match.completed_at else "",
        "conversation": build_conversation(db, match.id),
    }


def build_profile_row(db: Session, match: MatchRecord) -> dict:
    """构建单条「个人信息」行（`scope=profile`）：双方身份 + 物品摘要，**不含对话**。

    列集合 = `PROFILE_FIELDS`。
    """
    lost, found, lost_user, found_user = _sides(db, match)
    return {
        "match_id": match.id,
        "lost_item_id": lost.id if lost else "",
        "lost_category": lost.category_name if lost else "",
        "lost_title": lost.title if lost else "",
        "lost_student_no": lost_user.student_no if lost_user else "",
        "lost_phone": lost_user.phone if lost_user else "",
        "lost_real_name": (lost_user.real_name or "") if lost_user else "",
        "found_item_id": found.id if found else "",
        "found_category": found.category_name if found else "",
        "found_student_no": found_user.student_no if found_user else "",
        "found_phone": found_user.phone if found_user else "",
        "found_real_name": (found_user.real_name or "") if found_user else "",
        "match_score": float(match.match_score) if match.match_score is not None else "",
        "status": int(match.status) if match.status is not None else "",
        "completed_at": match.completed_at.isoformat() if match.completed_at else "",
    }


def build_conversation_export_rows(db: Session, match: MatchRecord) -> list[dict]:
    """`scope=conversation` 的导出行：一条消息一行（列集合 = `CONVERSATION_FIELDS`）。

    无消息的匹配也输出一行占位（`content` 为空），便于核对「该匹配确实没有对话」。
    """
    rows = build_conversation_rows(db, match.id)
    if not rows:
        return [{"match_id": match.id, "sent_at": "", "role_label": "", "content": ""}]
    return [
        {
            "match_id": match.id,
            "sent_at": r["sent_at"].isoformat() if r["sent_at"] else "",
            "role_label": r["role_label"],
            "content": r["content"],
        }
        for r in rows
    ]


def collect_rows(db: Session, matches: Iterable[MatchRecord], scope: str) -> list[dict]:
    """按 scope 聚合导出行。

    Args:
        db: 数据库会话。
        matches: 匹配记录序列（调用方已过滤掉不存在的 id）。
        scope: `profile` / `conversation` / `all`。

    Returns:
        行 dict 列表，键集合与 `SCOPE_FIELDS[scope]` 一致。
    """
    rows: list[dict] = []
    for match in matches:
        if scope == "profile":
            rows.append(build_profile_row(db, match))
        elif scope == "conversation":
            rows.extend(build_conversation_export_rows(db, match))
        else:
            rows.append(build_forensic_row(db, match))
    return rows


# ---------------------------------------------------------------------------
# 渲染器：统一返回 (bytes, media_type, filename)
# ---------------------------------------------------------------------------
def export_filename(scope: str, ext: str) -> str:
    """导出文件名 `forensic_matches_{scope}_{YYYYMMDD}.{ext}`。"""
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"forensic_matches_{scope}_{date_str}.{ext}"


def render_csv(rows: list[dict], scope: str) -> tuple[bytes, str, str]:
    """渲染 CSV（UTF-8，含表头）。

    Returns:
        `(内容字节, media_type, 文件名)`。
    """
    fields = SCOPE_FIELDS[scope]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8"), _MEDIA_TYPES["csv"], export_filename(scope, "csv")


def _autofit(ws, fields: list[str], rows: list[dict]) -> None:
    """按该列最长值近似自适应列宽（上限 60，避免超宽列撑爆 Excel 视口）。"""
    from openpyxl.utils import get_column_letter

    for idx, field in enumerate(fields, start=1):
        longest = len(str(field))
        for row in rows:
            longest = max(longest, len(str(row.get(field, ""))))
        ws.column_dimensions[get_column_letter(idx)].width = min(longest + 2, 60)


def _write_sheet(ws, fields: list[str], rows: list[dict]) -> None:
    """写入单个工作表：首行加粗表头 + 冻结首行 + 列宽自适应。"""
    from openpyxl.styles import Font

    ws.append(list(fields))
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    for row in rows:
        ws.append([str(row.get(f, "")) for f in fields])
    _autofit(ws, fields, rows)


def render_xlsx(db: Session, matches: list[MatchRecord], scope: str) -> tuple[bytes, str, str]:
    """渲染 xlsx（openpyxl **惰性导入**）。

    `scope=all` 输出两个 Sheet（`个人信息` / `对话记录`），其余为单 Sheet。

    Args:
        db: 数据库会话。
        matches: 匹配记录列表。
        scope: 导出范围。

    Returns:
        `(内容字节, media_type, 文件名)`。

    Raises:
        ExportDependencyError: 未安装 openpyxl（路由层转 400，禁止 500）。
    """
    try:
        from openpyxl import Workbook
    except ImportError as exc:      # pragma: no cover - 依赖可用性由部署环境决定
        raise ExportDependencyError("服务器未安装 openpyxl，无法导出 xlsx") from exc

    wb = Workbook()
    if scope == "all":
        ws_profile = wb.active
        ws_profile.title = "个人信息"
        _write_sheet(ws_profile, PROFILE_FIELDS, collect_rows(db, matches, "profile"))
        ws_conv = wb.create_sheet("对话记录")
        _write_sheet(ws_conv, CONVERSATION_FIELDS, collect_rows(db, matches, "conversation"))
    else:
        ws = wb.active
        ws.title = "个人信息" if scope == "profile" else "对话记录"
        _write_sheet(ws, SCOPE_FIELDS[scope], collect_rows(db, matches, scope))

    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue(), _MEDIA_TYPES["xlsx"], export_filename(scope, "xlsx")


def _md_escape(value) -> str:
    """转义 Markdown 表格单元格内容（`|` 与换行会撑破表格）。"""
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def render_md(db: Session, matches: list[MatchRecord], scope: str) -> tuple[bytes, str, str]:
    """渲染 Markdown（纯 f-string，零依赖）。

    每条匹配一节 `## 匹配 #<id>`；个人信息用 Markdown 表格，对话用有序列表。

    Args:
        db: 数据库会话。
        matches: 匹配记录列表。
        scope: 导出范围。

    Returns:
        `(内容字节, media_type, 文件名)`。
    """
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = [
        "# 失物招领取证导出",
        "",
        f"- 导出时间：{date_str}",
        f"- 导出范围：{scope}",
        f"- 匹配条数：{len(matches)}",
        "",
    ]
    for match in matches:
        lines.append(f"## 匹配 #{match.id}")
        lines.append("")
        if scope in ("profile", "all"):
            row = build_profile_row(db, match)
            lines.append("| 字段 | 值 |")
            lines.append("| --- | --- |")
            for field in PROFILE_FIELDS:
                lines.append(f"| {_md_escape(field)} | {_md_escape(row.get(field, ''))} |")
            lines.append("")
        if scope in ("conversation", "all"):
            lines.append("### 对话记录")
            lines.append("")
            conv = build_conversation_rows(db, match.id)
            if not conv:
                lines.append("_（无对话）_")
            else:
                for i, item in enumerate(conv, start=1):
                    ts = item["sent_at"].isoformat() if item["sent_at"] else ""
                    lines.append(f"{i}. [{ts}] {item['role_label']}：{_md_escape(item['content'])}")
            lines.append("")
    content = "\n".join(lines) + "\n"
    return content.encode("utf-8"), _MEDIA_TYPES["md"], export_filename(scope, "md")


def render(db: Session, matches: list[MatchRecord], scope: str, fmt: str) -> tuple[bytes, str, str]:
    """按 `(scope, format)` 分派到对应渲染器。

    Args:
        db: 数据库会话。
        matches: 匹配记录列表。
        scope: `profile` / `conversation` / `all`（调用方须已校验）。
        fmt: `csv` / `xlsx` / `md`（调用方须已校验）。

    Returns:
        `(内容字节, media_type, 文件名)`。

    Raises:
        ExportDependencyError: xlsx 且 openpyxl 缺失。
    """
    if fmt == "xlsx":
        return render_xlsx(db, matches, scope)
    if fmt == "md":
        return render_md(db, matches, scope)
    return render_csv(collect_rows(db, matches, scope), scope)
