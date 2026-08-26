# 每日邮件简报（Daily Email Brief）

自动读取你的**邮箱收件箱最近 24 小时**的邮件，用**本地大模型（Ollama）**将每封邮件内容**翻译成通顺中文**，发件人显示为简洁的联系人名称，输出为 JSON 简报，并每天定时自动运行。

- **翻译完全免费**：默认调用**本地 Ollama**（邮件内容不出本机），也预留了 Claude API 后端可随时切换。
- **支持两类邮箱**：
  - QQ 邮箱等个人邮箱：账号 + 授权码（最简单，推荐）
  - Microsoft 365 工作邮箱：OAuth2 IMAP（无 Azure 注册，但大学/公司租户可能拦截，见排障）

```
Outlook 收件箱 ──IMAP──> 拉取邮件 ──> 本地 Ollama 翻译成中文 ──> briefs/daily_brief_YYYY-MM-DD.json
```

## 目录结构

| 文件 | 作用 |
|---|---|
| `config.example.json` | 配置模板（复制为 `config.json` 后填写，真实配置不入库） |
| `auth.py` | MSAL 设备码授权 + token 刷新 |
| `imap_client.py` | OAuth2 IMAP 拉取并解析邮件 |
| `summarize.py` | 调用本地 Ollama（或 Claude API）把邮件内容翻译成中文 |
| `main.py` | 入口：编排 + 输出 JSON |
| `run_daily.bat` | 任务计划调用入口 |
| `setup_task.ps1` | 注册每日任务计划 |
| `briefs/` | 简报输出目录（自动创建） |

## 一、首次配置

0. 克隆仓库并准备 Python 环境（需 Python 3.10+）：
   ```powershell
   git clone https://github.com/<你的用户名>/daily-email-brief.git
   cd daily-email-brief
   python -m venv .venv
   .\.venv\Scripts\pip install -r requirements.txt
   ```
1. 复制配置模板并编辑：
   ```powershell
   copy config.example.json config.json
   ```
   - `email` 填你的**邮箱地址**（必填）
   - **QQ 邮箱**还需开启 IMAP 并填授权码：网页版 `mail.qq.com` → 设置 → 账号 → **开启 IMAP/SMTP 服务**（需短信验证），把生成的**授权码**填入 `imap_password`
   - **Microsoft 365 工作邮箱**：留空 `imap_password`，走 OAuth2 设备码授权（见下方"二"）
   - ⚠️ `config.json` 含你的邮箱密码级凭证，已在 `.gitignore` 中排除，**请勿提交到仓库**
2. 安装并启动 **Ollama**（摘要模型在本地跑）：
   ```powershell
   winget install Ollama.Ollama
   ollama pull qwen2.5:7b
   ```
   默认用 `qwen2.5:7b`（中文摘要质量较好）。CPU 上想更快可换更小的 `qwen2.5:3b`，改 `config.json` 的 `ollama_model` 即可。
3. （可选）如果以后想改用 Claude API 获得更高质量：在 `config.json` 把 `llm_backend` 改为 `"claude"`，并填 `claude_api_key` 或设置环境变量 `ANTHROPIC_API_KEY`。

## 二、首次授权与试运行

```powershell
cd daily-email-brief
.\.venv\Scripts\python.exe main.py --test-auth
```

- **QQ 邮箱**：授权码已填入 `config.json` 后，这一步直接验证连通，无需任何浏览器操作。
- **Microsoft 365 工作邮箱**：首次运行会打印一个**设备码**，浏览器打开 `https://microsoft.com/devicelogin` 登录授权（页面提示“应用未验证”属正常）。若返回 `AADSTS6501/6502` 说明租户拦截，需 IT 管理员协助或改用 QQ 邮箱。
- 看到 `✅ 授权成功并已连接邮箱` 即链路打通。

```powershell
.\.venv\Scripts\python.exe main.py --list   # 先看看最近24h有哪些邮件
.\.venv\Scripts\python.exe main.py          # 生成简报（写入 briefs\ 并打印）
```

## 三、配置每天自动运行

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_task.ps1
```

- 默认每天 **09:05** 运行，改时间请编辑 `setup_task.ps1` 里的 `$Time`。
- 常用命令：
  - 立即跑一次：`schtasks /run /tn DailyEmailBrief`
  - 查看状态：`schtasks /query /tn DailyEmailBrief`
  - 手动触发完整运行同上，也可直接运行 `run_daily.bat`。

## 四、简报格式

```json
{
  "generated_at": "2026-08-25T09:05:00+08:00",
  "period": { "start": "...", "end": "..." },
  "total": 12,
  "emails": [
    {
      "from": "张三 <zhangsan@corp.com>",
      "subject": "Weekly Report",
      "received_at": "2026-08-25T08:12:34Z",
      "summary": "通知本周五前提交项目周报，并更新进度看板。"
    }
  ]
}
```

## 五、排障

| 现象 | 处理 |
|---|---|
| 授权时提示 `AADSTS65001` 或“需要管理员同意” | 租户禁止了用户自助同意。联系 IT 管理员批准该应用对 IMAP 的权限，或确认邮箱已开启 IMAP |
| 连接 IMAP 失败 / 登录被拒 | 公司可能禁用了 IMAP。让管理员确认 `Set-CASMailbox -IMAPEnabled $true`（Exchange Online 默认开启） |
| `AADSTS50020` | `config.json` 里的 `email` 填错，请确认是工作邮箱完整地址 |
| 摘要全部返回“API key 无效” | 检查 `config.json` 的 `claude_api_key` 或环境变量 `ANTHROPIC_API_KEY` |
| refresh_token 过期 | 重新运行 `python main.py --test-auth`，会再次提示设备码登录 |
| 想只跑最近 N 小时 | `python main.py --hours 48` |

## 六、隐私与成本

- 邮件**正文会截断到 1000 字符**（`max_body_chars`）后发送给 Claude API 做摘要。请确认公司邮件政策允许内容外发给第三方 LLM；如不允许，请勿继续使用，或联系 IT 申请官方渠道。
- Claude API 按 token 计费。每天几十封 × 约 1KB 正文，量级极小（约每天 < $0.01 量级）；想更省可在 `config.json` 切到 `claude-haiku-4-5`。
- token 与 API key 保存在本项目目录内，请勿外泄；不要把 `token_cache.json` 提交到任何仓库。
