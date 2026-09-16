"""摘要生成：默认本地 Ollama（免费、内容不出本机），可选切换 Claude API。

配置项：
  llm_backend = "ollama"（默认）→ 调用本地 http://localhost:11434
  llm_backend = "claude"        → 调用 Anthropic API（需 claude_api_key 或 ANTHROPIC_API_KEY）
"""

import logging

import requests

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是一名邮件翻译助理。用户会提供一封邮件的发件人、主题和正文（可能是中文或英文）。"
    "请把邮件的主要内容完整翻译成通顺的中文（若正文已是中文，直接整理为通顺中文即可）。"
    "保留关键信息：时间、地点、金额、链接、验证码、需要用户做的事。"
    "只输出译文本身，不要任何前缀、引号或解释。"
)

FALLBACK_SUMMARY = "(翻译生成失败)"


class Summarizer:
    def __init__(self, config: dict):
        self.config = config
        self.backend = config.get("llm_backend", "ollama")
        if self.backend == "claude":
            import anthropic  # 延迟导入：Ollama 路径不依赖该包

            api_key = (config.get("claude_api_key") or "").strip() or None
            self._client = anthropic.Anthropic(api_key=api_key)
            self._model = config.get("claude_model", "claude-opus-5")

    def summarize(self, email_item: dict) -> str:
        content = (
            f"发件人：{email_item['from']}\n"
            f"主题：{email_item['subject']}\n"
            f"正文：{email_item['body']}"
        )
        try:
            if self.backend == "claude":
                return self._summarize_claude(content)
            return self._summarize_ollama(content)
        except Exception as e:  # noqa: BLE001 - 单封失败不中断整体
            log.error("摘要生成异常：%s", e)
            return FALLBACK_SUMMARY

    # ---- 本地 Ollama ----

    def _summarize_ollama(self, content: str) -> str:
        base = self.config.get("ollama_base_url", "http://localhost:11434")
        model = self.config.get("ollama_model", "qwen2.5:7b")
        resp = requests.post(
            f"{base}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 1024},
            },
            timeout=180,
        )
        resp.raise_for_status()
        text = (resp.json().get("message", {}).get("content") or "").strip()
        return text or "(摘要为空)"

    # ---- Claude API ----

    def _summarize_claude(self, content: str) -> str:
        import anthropic

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
            )
            text = "".join(
                b.text for b in response.content if b.type == "text"
            ).strip()
            return text or "(摘要为空)"
        except anthropic.AuthenticationError:
            return "(摘要失败：API key 无效)"
        except anthropic.RateLimitError:
            return "(摘要失败：API 限流)"
        except anthropic.APIStatusError as e:
            return f"(摘要失败：HTTP {e.status_code})"
