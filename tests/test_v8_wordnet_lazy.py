"""P0-② 语义匹配开关的懒加载缺陷回归测试（不联网、不依赖真实 nltk）。

覆盖三种情形：
1. nltk 包存在但 wordnet 语料缺失 → 降级为纯精确 containment（不崩、不误命中）。
2. _ensure_wordnet() 在语料缺失时返回 False。
3. USE_WORDNET=False 时 _wordnet_synonyms 恒为空集合。

测试环境无真实 nltk，全部通过 monkeypatch 注入 stub，禁止触发真实 import nltk。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import match_service


class _NltkStub:
    """模拟「nltk 包可导入但语料缺失」：download 抛异常，import corpus 亦失败。

    注：download 抛异常会使 _ensure_wordnet() 在进入 `import nltk.corpus.wordnet`
    之前即走 except 分支返回 False，因此本测试不会触发真实 import nltk。
    """

    def download(self, *args, **kwargs):  # noqa: D401
        # 模拟离线 / 无语料：下载失败
        raise Exception("corpus unavailable (offline)")


def _make_item(**kwargs) -> SimpleNamespace:
    """构造一个轻量伪物品对象（仅携带语义路径所需的字段）。"""
    return SimpleNamespace(**kwargs)


@pytest.fixture
def _stub_env(monkeypatch):
    """注入 USE_WORDNET=True + _nltk stub（download 抛异常），并复位运行期状态。"""
    monkeypatch.setattr(match_service, "USE_WORDNET", True)
    monkeypatch.setattr(match_service, "_nltk", _NltkStub())
    monkeypatch.setattr(match_service, "_wordnet_ready", False)
    monkeypatch.setattr(match_service, "_wn", None)
    yield


def test_nltk_present_but_corpus_missing_degrades_to_exact(_stub_env):
    """nltk 存在但语料缺失 → 结果与纯精确 containment 一致，不崩、不误命中。"""
    lost = _make_item(
        tags=["laptop999", "mouse888"],
        appearance=None,
        features=None,
        location=None,
        category_name="其他",
    )
    found = _make_item(
        tags=["laptop999", "charger777"],
        appearance=None,
        features=None,
        location=None,
        category_name="其他",
    )

    # 纯精确 containment：失物并集 {laptop999, mouse888} 命中候选并集
    # {laptop999, charger777} 仅 1 个，故 1/2 = 0.5。选定 token 均不在 _ZH_SYNONYMS 中，
    # 且 wordnet 语料缺失，因此语义路径不得产生任何同义误命中。
    expected_exact = 1 / 2

    rate = match_service.MatchService.semantic_tag_match_rate(lost, found)
    assert rate == pytest.approx(expected_exact)
    # 额外确认：若发生同义误召回，rate 必然 > expected_exact。
    assert rate == expected_exact


def test_ensure_wordnet_returns_false_when_corpus_missing(_stub_env):
    """语料缺失时 _ensure_wordnet() 必须返回 False（不崩、不抛）。"""
    assert match_service._ensure_wordnet() is False
    assert match_service._wordnet_ready is False


def test_wordnet_synonyms_empty_when_disabled(monkeypatch):
    """USE_WORDNET=False 时 _wordnet_synonyms 恒为空集合。"""
    monkeypatch.setattr(match_service, "USE_WORDNET", False)
    assert match_service._wordnet_synonyms("key") == set()
    assert match_service._wordnet_synonyms("钥匙") == set()
