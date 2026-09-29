# 更换 API Key / 模型 / 网关的三种方式(按临时→持久排序)

# ── 方式 1:临时(当前终端会话有效) ─────────────────────────
# Git Bash:
#   export PIXDANCE_CHAT_KEY=sk-你的新key
#   python -m finagent.cli --eval
# CMD:
#   set PIXDANCE_CHAT_KEY=sk-你的新key
# PowerShell:
#   $env:PIXDANCE_CHAT_KEY="sk-你的新key"

# ── 方式 2:写入系统环境变量(永久,重开终端生效) ──────────────
# PowerShell(管理员不必):
#   [Environment]::SetEnvironmentVariable("PIXDANCE_CHAT_KEY", "sk-你的新key", "User")
# 或 Windows 设置 → 系统 → 高级系统设置 → 环境变量 → 用户变量新建

# ── 方式 3:改配置默认值(适合换到别的网关/变量名) ───────────────
# 编辑 finagent/config.py:
#   api_key_env: str = "PIXDANCE_CHAT_KEY"   ← 改成任意环境变量名
#   api_base: str = "https://token.pixdance.top/v1"  ← 换网关地址
#   model: str = "kimi-k3"                   ← 换模型
# 换 OpenAI 官方示例:
#   api_base = "https://api.openai.com/v1"
#   api_key_env = "OPENAI_API_KEY"
#   model = "gpt-4o"

# 验证 key 是否可用(不改代码):
# python -c "import urllib.request,json,os; r=urllib.request.Request('https://token.pixdance.top/v1/models', headers={'Authorization':'Bearer '+os.environ['PIXDANCE_CHAT_KEY']}); print(urllib.request.urlopen(r).read().decode()[:200])"
