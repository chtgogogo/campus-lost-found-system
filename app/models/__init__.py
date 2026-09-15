"""汇总所有 ORM 模型，供 create_all / Alembic 自动发现。"""
from app.models.audit import AuditLog
from app.models.category import Category
from app.models.correction import CorrectionSample
from app.models.im import IMMessage, IMSession
from app.models.item import FoundItem, LostItem
from app.models.match import HandoverCode, MatchExclusion, MatchRecord
from app.models.user import TrustScoreLog, User

__all__ = [
    "User",
    "TrustScoreLog",
    "Category",
    "LostItem",
    "FoundItem",
    "MatchRecord",
    "HandoverCode",
    "MatchExclusion",
    "IMSession",
    "IMMessage",
    "AuditLog",
    "CorrectionSample",
]
