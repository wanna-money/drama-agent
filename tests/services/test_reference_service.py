"""背景参考图清单权威的行为测试。

**角色形象不在本模块管辖内** —— 它只来自「角色」页的造型(Look),经 subject_ref_service
下发。参考图面板若也承载角色图,就与造型指派重复表达同一件事。角色侧的用例在
tests/workflow/test_cast_alignment.py 与 test_video_generator_subject.py。

拦的是真实回归:类型错判、背景占位补全、旧快照读时兼容、脏数据不把面板整体搞挂。
纯定义/纯传值的断言不写(单测规范)。
"""
import pytest

from drama_agent.db.enums import ReferenceType
from drama_agent.services import reference_service as rs


# ── 类型归属 ────────────────────────────────────────────────────────
def test_persisted_type_survives_for_key_not_in_shots():
    """用户手动添加/从素材库选的背景图,即使不在任何镜头的 location 里,也必须保住其类型。
    在前端按"名字在不在某张表里"反猜类型,会把素材库选的图判进错误的组。"""
    source = {
        "references": [
            {"key": "自定义场景", "ref_type": "background", "image_url": "/img/test.png"},
        ],
        "shots": [],
    }
    by_key = {e["key"]: e for e in rs.build_list(source)}
    assert by_key["自定义场景"]["ref_type"] == ReferenceType.BACKGROUND.value
    assert by_key["自定义场景"]["image_url"] == "/img/test.png"


def test_placeholder_detected_from_shot_locations():
    source = {
        "references": [],
        "shots": [{"location": "INT. 咖啡馆 - 日"}],
    }
    by_key = {e["key"]: e for e in rs.build_list(source)}
    assert by_key["INT. 咖啡馆 - 日"]["ref_type"] == ReferenceType.BACKGROUND.value
    assert by_key["INT. 咖啡馆 - 日"]["image_url"] == ""       # 未上传占位


def test_characters_no_longer_produce_placeholders():
    """角色**不得**再生成参考图占位 —— 角色形象的唯一配置处是「角色」页的造型。

    这条删掉就会放走"参考图面板与造型指派两个入口管同一件事"的回归。
    """
    source = {
        "references": [],
        "story_analysis": {"characters": [{"name": "林夏"}, {"name": "陆沉"}]},
        "shots": [{"location": "客厅"}],
    }
    keys = [e["key"] for e in rs.build_list(source)]
    assert keys == ["客厅"]


def test_bound_entry_is_not_shadowed_by_its_own_placeholder():
    """同一个 key 既被探测到、又已绑定图时只出现一次,且保留已绑定的图。"""
    source = {
        "references": [{"key": "客厅", "ref_type": "background", "image_url": "/img/c.png"}],
        "shots": [{"location": "客厅"}],
    }
    result = rs.build_list(source)
    assert [e["key"] for e in result] == ["客厅"]
    assert result[0]["image_url"] == "/img/c.png"


def test_user_added_entries_are_kept_after_detected_ones():
    """用户手动添加的(探测不到的)条目不能在补占位时被丢掉。"""
    source = {
        "references": [{"key": "自定义背景", "ref_type": "background", "image_url": "/img/b.png"}],
        "shots": [{"location": "客厅"}],
    }
    keys = [e["key"] for e in rs.build_list(source)]
    assert keys == ["客厅", "自定义背景"]


def test_duplicate_locations_across_shots_collapse_to_one_entry():
    source = {
        "references": [],
        "shots": [{"location": "客厅"}, {"location": "客厅"}, {"location": ""}],
    }
    assert [e["key"] for e in rs.build_list(source)] == ["客厅"]


def test_detected_only_placeholder_is_not_removable():
    """纯探测出来的占位不是用户记录 —— 删了下次还会被探测出来,所以不给删除入口;
    一旦用户绑了图/手动加过,它就是记录,可删。"""
    source = {
        "references": [{"key": "客厅", "ref_type": "background", "image_url": "/c.png"}],
        "shots": [{"location": "客厅"}, {"location": "阳台"}],
    }
    by_key = {e["key"]: e for e in rs.build_list(source)}
    assert by_key["客厅"]["removable"] is True     # 已绑定 → 是用户记录
    assert by_key["阳台"]["removable"] is False    # 仅探测占位


# ── 读时兼容:旧快照 ─────────────────────────────────────────────────
def test_legacy_character_entries_are_read_not_dropped():
    """历史 `character_references` 里的角色条目仍读得出来 —— 不静默丢用户数据。

    界面不展示角色组,但读路径丢掉它们会让已上传的图凭空消失 —— 那是数据损失。
    """
    source = {"character_references": {"ChenWei": "/img/c.png"}, "shots": []}
    result = rs.stored(source)
    assert result == [
        {"key": "ChenWei", "ref_type": ReferenceType.CHARACTER.value, "image_url": "/img/c.png"}
    ]


def test_new_field_wins_over_legacy_field_when_both_present():
    """升级过后的状态两个字段都在时,以新字段为准,不能被旧字段的类型盖回去。"""
    source = {
        "references": [{"key": "山顶", "ref_type": "background", "image_url": "/img/m.png"}],
        "character_references": {"山顶": "/img/m.png"},
        "shots": [],
    }
    assert rs.build_list(source)[0]["ref_type"] == ReferenceType.BACKGROUND.value


# ── 写入校验 ────────────────────────────────────────────────────────
def test_normalize_rejects_unknown_ref_type():
    """非法 ref_type 必须报错而不是静默落成自由字符串(API 层映射 400)。"""
    with pytest.raises(ValueError):
        rs.normalize([{"key": "x", "ref_type": "prop", "image_url": ""}])


def test_normalize_drops_blank_keys_and_dedupes_by_key():
    out = rs.normalize([
        {"key": "  ", "ref_type": "background", "image_url": "/a.png"},
        {"key": "A", "ref_type": "background", "image_url": ""},
        {"key": "A", "ref_type": "background", "image_url": "/b.png"},
    ])
    assert out == [{"key": "A", "ref_type": "background", "image_url": "/b.png"}]


def test_stored_skips_malformed_rows_instead_of_raising():
    """读路径要容错:一条脏数据不能让整个参考图面板取不出来。"""
    source = {"references": [
        {"key": "好的", "ref_type": "background", "image_url": "/a.png"},
        {"key": "坏的", "ref_type": "prop", "image_url": "/b.png"},
        "not-a-dict",
    ]}
    assert [e["key"] for e in rs.stored(source)] == ["好的"]
