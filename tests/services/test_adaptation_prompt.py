def test_prompt_carries_source_and_exact_episode_count():
    """集数模式:源文本 + '恰好 N 集'都要进 prompt(拦'忘了把切分配置告诉 LLM')。"""
    from drama_agent.services.adaptation_service import build_adaptation_prompt
    _system, user = build_adaptation_prompt("小说正文ABC", target_episodes=5)
    assert "小说正文ABC" in user
    assert "恰好 5 集" in user


def test_prompt_carries_per_episode_duration_and_lets_model_pick_count():
    """时长模式:告知每集目标秒数,集数交模型定(不预算总时长)。"""
    from drama_agent.services.adaptation_service import build_adaptation_prompt
    _system, user = build_adaptation_prompt("小说正文ABC", seconds_per_ep=90)
    assert "小说正文ABC" in user
    assert "约 90 秒" in user
    assert "恰好" not in user      # 时长模式不得写死集数
