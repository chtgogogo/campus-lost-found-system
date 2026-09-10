"""v13 增量测试：API 限流 + 图片魔数校验 + 词边界抽取。

- 限流：固定窗口计数器（core/ratelimit.py）；DEBUG=True 全局放行（测试套件依赖此豁免，
  本文件用 monkeypatch 显式开启后单测）。
- 图片校验：按魔数判型，拒收伪装文件（utils/image_validator.py）。
- 词边界：地点先抽并消费、名词消费式抽取（tagging_service v13 顺序）。
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.exceptions import RateLimitError
from app.core.ratelimit import check_rate_limit
from app.services.tagging_service import TaggingService
from app.utils.image_validator import detect_image_type, validate_images

from conftest import API, PNG, auth_header, register_and_login


# ---------------- 1. 限流 ----------------
class TestRateLimit:
    def test_fixed_window_blocks_over_limit(self, monkeypatch):
        monkeypatch.setattr(settings, "DEBUG", False)
        monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
        key = "test:rl-v13-a"  # 唯一 key，避免与其它用例的内存计数串扰
        check_rate_limit(key, 2)
        check_rate_limit(key, 2)
        with pytest.raises(RateLimitError):
            check_rate_limit(key, 2)

    def test_debug_bypasses(self, monkeypatch):
        monkeypatch.setattr(settings, "DEBUG", True)
        key = "test:rl-v13-b"
        for _ in range(5):
            check_rate_limit(key, 1)  # DEBUG 下永不抛

    def test_disabled_bypasses(self, monkeypatch):
        monkeypatch.setattr(settings, "DEBUG", False)
        monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
        key = "test:rl-v13-c"
        for _ in range(5):
            check_rate_limit(key, 1)

    def test_api_level_429(self, client, monkeypatch):
        """路由级接线验证：预览接口超限返回 429。

        注意先注册（DEBUG=True 时 send-sms 才返回 dev_code），再开限流。
        """
        token, *_ = register_and_login(client, "v13rl")
        monkeypatch.setattr(settings, "DEBUG", False)
        monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
        monkeypatch.setattr(settings, "RATE_LIMIT_PREVIEW_PER_MIN", 1)
        headers = auth_header(token)
        r1 = client.post(f"{API}/tags-preview", headers=headers, json={"description": "黑色雨伞"})
        assert r1.status_code == 200, r1.text
        r2 = client.post(f"{API}/tags-preview", headers=headers, json={"description": "黑色雨伞"})
        assert r2.status_code == 429, r2.text


# ---------------- 2. 图片魔数校验 ----------------
class TestImageValidator:
    def test_detect_known_types(self):
        assert detect_image_type(PNG) == "PNG"
        assert detect_image_type(b"\xff\xd8\xff\xe0" + b"x" * 20) == "JPEG"
        assert detect_image_type(b"GIF89a" + b"x" * 20) == "GIF"
        assert detect_image_type(b"RIFFxxxxWEBP" + b"x" * 8) == "WEBP"
        assert detect_image_type(b"BM" + b"x" * 20) == "BMP"

    def test_detect_rejects_disguised(self):
        assert detect_image_type(b"<html><body>x</body></html>") is None
        assert detect_image_type(b"#!/bin/bash\nrm -rf /") is None
        assert detect_image_type(b"") is None

    def test_validate_rejects_disguised_upload(self):
        with pytest.raises(Exception, match="不是有效图片"):
            validate_images([("evil.png", b"<svg onload=alert(1)>")])

    def test_validate_rejects_oversize(self, monkeypatch):
        monkeypatch.setattr(settings, "IMG_MAX_SIZE_MB", 1)
        big = PNG + b"\x00" * (1024 * 1024 + 1)
        with pytest.raises(Exception, match="上限"):
            validate_images([("big.png", big)])

    def test_validate_accepts_real_png(self):
        validate_images([("ok.png", PNG)])  # 不抛即通过

    def test_publish_rejects_disguised_image(self, client):
        """端到端：伪装成 .png 的文本文件发布被拒（ParamError → HTTP 422 + code 9001）。"""
        token, *_ = register_and_login(client, "v13img")
        r = client.post(
            f"{API}/lost-items",
            headers=auth_header(token),
            data={"title": "测试", "description": "测试", "category_name": "雨伞"},
            files={"images": ("fake.png", b"<html>not an image</html>", "image/png")},
        )
        assert r.status_code == 422
        assert "不是有效图片" in r.json()["message"]


# ---------------- 4. 打分引擎修复（评测集证据驱动） ----------------
def _item(**kw):
    from types import SimpleNamespace

    base = dict(
        title=None, description="", category_name="", category_id=None, tags=[],
        appearance=None, features=None, location="", lost_time=None, found_time=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestEngineFixesV13:
    def _score(self, lost_kw, found_kw):
        from app.services.match_service import MatchService

        return MatchService().score_detail(
            _item(description=lost_kw, category_name="手机"),
            _item(description=found_kw, category_name="手机"),
        )

    def test_brand_conflict_signal_and_penalty(self):
        """iPhone vs 华为：brand_conflict 信号 + 扣罚（评测集 N03/N13）。"""
        d = self._score("黑色 iPhone 13 直角边框", "黑色华为手机曲面屏")
        assert "brand_conflict" in d["signals"]
        d_none = self._score("黑色手机直角边框", "黑色手机曲面屏")
        assert "brand_conflict" not in d_none["signals"]
        assert d["total"] < d_none["total"]  # 同文本条件下品牌冲突分更低

    def test_no_brand_conflict_when_same_brand(self):
        """iPhone vs 苹果13：归一后同品牌 → 无冲突信号。"""
        d = self._score("黑色 iPhone 13", "黑色苹果13手机")
        assert "brand_conflict" not in d["signals"]

    def test_negated_state_words_not_extracted(self):
        from app.services.scoring_refs import extract_states

        states, _ = extract_states("全新无划痕，没有任何破损", set())
        assert states == {"全新"}  # 否定表达不计入
        states2, _ = extract_states("有磨损，屏幕无划痕", set())
        assert states2 == {"磨损"}

    def test_campus_regex_no_longer_eats_text(self):
        from app.services.scoring_refs import extract_place

        place, rest = extract_place("捡到一张蓝色的校园卡，交到服务台了")
        assert place["campus"] == set()  # 「校园卡」不再被吞成假校区
        assert "蓝色" in rest  # 颜色词未被连带消费

    def test_place_building_containment(self):
        from app.services.scoring_refs import place_score

        lost = {"room": set(), "floor": set(), "building": {"学生食堂"}, "campus": set()}
        found = {"room": set(), "floor": {"二楼"}, "building": {"食堂"}, "campus": set()}
        assert place_score(lost, found) > 0  # 学生食堂 ⊇ 食堂 → 命中

    def test_negation_golden_case(self):
        """P16 类场景：完好描述不受否定词干扰。"""
        from app.services.scoring_refs import extract_states

        states, _ = extract_states("全新未拆封，屏幕无划痕", set())
        assert "划痕" not in states
        assert "全新" in states


# ---------------- 5. 词边界抽取 ----------------
class TestWordBoundaryTagging:
    def test_library_no_fake_book_noun(self):
        tags = TaggingService.extract(description="在图书馆三楼丢了一张银行卡")
        assert "图书馆" in tags and "三楼" in tags
        assert "书" not in tags  # v13 核心：地点消费后不再拆出假名词

    def test_express_station_no_split(self):
        tags = TaggingService.extract(description="在校门口快递站捡到黑色雨伞")
        assert "快递站" in tags
        assert "快递" not in tags

    def test_keychain_no_nested_key(self):
        tags = TaggingService.extract(description="捡到一串钥匙串")
        assert "钥匙串" in tags
        assert "钥匙" not in tags  # 消费式抽取：长词命中后不再拆短词

    def test_laptop_vs_notebook_distinct(self):
        laptop = TaggingService.extract(description="捡到一台笔记本电脑，银色")
        paper = TaggingService.extract(description="丢了一本笔记本，里面夹着微积分提纲")
        assert "笔记本电脑" in laptop and "笔记本" not in laptop
        assert "笔记本" in paper and "笔记本电脑" not in paper

    def test_ordinary_extraction_unchanged(self):
        tags = TaggingService.extract(description="捡到一把黑色雨伞，伞面有白色星星图案")
        assert "雨伞" in tags and "黑色" in tags and "白色" in tags

    def test_brand_extraction_survives_consumption(self):
        tags = TaggingService.extract(description="在图书馆丢了一部 iPhone 13")
        assert "图书馆" in tags
        assert "苹果" in tags  # 品牌词典基于残余文本仍可命中
