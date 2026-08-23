-- 默认内置 provider 初始化 SQL(手动在启动前执行一次)。
-- 覆盖:内置文本模型 DeepSeek(drama)+ 2 个内置视频 provider + 2 个内置图片 provider。
-- 幂等:ON CONFLICT (provider_id) DO NOTHING —— 重复执行、或与代码 seed 并存都不会重复插入
--       (custom_providers 有 UNIQUE(provider_id))。
--
-- 适用:PostgreSQL 或 SQLite(≥3.24 支持 ON CONFLICT)。
-- models_json 为 JSON 文本;各 model dict 至少含 id/label/provider/kind,视频再带能力字段,
-- 与 row_to_provider() 的 Model(**m) 反序列化一致。
-- base_url 为各内置 provider 的官方地址(锁死,UI 只读);api_key 留空(NULL),在「模型管理」界面配置。

INSERT INTO custom_providers (id, provider_id, label, protocol, kind, base_url, api_key, models_json, enabled, builtin)
VALUES
  (
    'b0000000-0000-4000-8000-000000000001',
    'drama', 'DeepSeek', 'openai-compat', 'llm', 'https://api.deepseek.com', NULL,
    '[{"id":"deepseek-v4-flash","label":"DeepSeek V4 Flash","provider":"drama","kind":"llm"},{"id":"deepseek-v4-pro","label":"DeepSeek V4 Pro","provider":"drama","kind":"llm"}]',
    1, 1
  ),
  (
    'b0000000-0000-4000-8000-000000000002',
    'seedance-video', '字节跳动', 'seedance', 'video', 'https://ark.cn-beijing.volces.com/api/v3', NULL,
    '[{"id":"seedance","label":"Seedance 2.0","provider":"seedance-video","kind":"video","resolutions":["720p","1080p"],"default_resolution":"1080p","supported_actions":["rerun","regenerate"]}]',
    1, 1
  ),
  (
    'b0000000-0000-4000-8000-000000000004',
    'minimax-video', 'MiniMax', 'minimax', 'video', 'https://api.minimaxi.com', NULL,
    '[{"id":"minimax","label":"MiniMax H3","provider":"minimax-video","kind":"video","resolutions":["768P","2K"],"default_resolution":"768P","supported_actions":["rerun","regenerate","upscale"]}]',
    1, 1
  ),
  (
    'b0000000-0000-4000-8000-000000000005',
    'doubao-image', '豆包 Seedream', 'doubao-image', 'image', 'https://ark.cn-beijing.volces.com/api/v3', NULL,
    '[{"id":"doubao-seedream-3-0-t2i","label":"Seedream 5.0 pro","provider":"doubao-image","kind":"image"}]',
    1, 1
  ),
  (
    'b0000000-0000-4000-8000-000000000006',
    'openai-image', 'OpenAI GPT Image', 'openai-image', 'image', 'https://api.openai.com/v1', NULL,
    '[{"id":"gpt-image-2","label":"GPT Image 2","provider":"openai-image","kind":"image"}]',
    0, 1
  )
ON CONFLICT (provider_id) DO NOTHING;
