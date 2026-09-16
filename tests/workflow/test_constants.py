"""generation_duration_for:叙事时长 vs 模型能力下限的调和函数(唯一权威)。"""
import pytest

from drama_agent import provider as provider_pkg
from drama_agent.provider.registry import ProviderRegistry
from drama_agent.provider.video.providers import builtin_video_providers
from drama_agent.workflow.constants import generation_duration_for


@pytest.fixture(autouse=True)
def video_provider_registry(monkeypatch):
    """模块级单例默认只含 env/DB provider(生产靠 seed 灌内置数据),测试直接用
    builtin_video_providers() 构造一个含 seedance(min_duration=4)的 registry,
    不依赖 DB seed 流程。"""
    reg = ProviderRegistry(builtin=builtin_video_providers())
    monkeypatch.setattr(provider_pkg, "provider_registry", reg)


def test_narrative_at_or_above_model_floor_passes_through():
    # seedance: min_duration=4 —— 叙事时长已 >= 下限,不需要抬高
    assert generation_duration_for(5, "seedance") == 5
    assert generation_duration_for(4, "seedance") == 4


def test_narrative_below_model_floor_is_raised_to_floor():
    # 叙事时长 1 秒(如一次击中),seedance 下限 4 秒 —— 生成时长必须垫高到 4
    assert generation_duration_for(1, "seedance") == 4


def test_empty_model_ref_passes_through():
    """未声明目标模型(如复用剧本直达分镜)时没有约束可依据,原样返回。"""
    assert generation_duration_for(1, "") == 1


def test_unknown_model_ref_passes_through():
    """model_ref 解析不到(自定义 provider 未声明能力)时原样返回,不报错。"""
    assert generation_duration_for(1, "no-such-model-xyz") == 1
