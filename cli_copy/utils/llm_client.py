"""
AutoChaoxingCLI - LLM客户端模块

封装大语言模型API调用，支持任意OpenAI兼容API。
用户可自定义 base_url / api_key / model，兼容：
- OpenAI
- DeepSeek
- 通义千问
- 文心一言
- Ollama本地模型
- 任何OpenAI兼容API
"""

import re
import json
from loguru import logger

from core.request_client import get_external_session

SYSTEM_PROMPT = """你是课程学习助手。仔细分析题干与每个选项，先在内部推理再给出最终答案。
不要编造缺失的题干、图片或选项；信息不足或不能判断时 answer 返回空字符串。
只返回 JSON 对象：{"answers":[{"index":1,"answer":"B"}]}，每题 index 对应输入编号。
单选只返回一个实际存在的字母；多选返回按顺序排列的字母；判断仅返回 true 或 false。
填空多个空使用中文分号分隔，简答使用完整文本。不要在 answer 中加入理由、题型或编号。"""


class LLMClient:
    """
    大语言模型客户端

    封装与OpenAI兼容API的交互，支持自定义API地址、模型、温度等参数。

    Attributes:
        api_base (str): API基础URL
        api_key (str): API密钥
        model (str): 模型名称
        temperature (float): 生成温度
        max_tokens (int): 最大token数（0表示不限制，由模型自行决定）
        timeout (int): 请求超时（秒）
    """

    def __init__(self, api_base: str, api_key: str, model: str = "deepseek-chat",
                 temperature: float = 0.1, max_tokens: int = 4096, timeout: int = 180):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._auth_failed = False

    def _build_prompt(self, questions: list[dict]) -> str:
        """构建题目提示词"""
        lines = []
        for i, q in enumerate(questions, 1):
            q_type = q.get("question_type", "未知")
            q_text = q.get("question_text", "")
            options = q.get("options", [])
            lines.append(f"第{i}题【{q_type}】{q_text}")
            for opt in options:
                lines.append(opt)
            lines.append("---")
        return "\n".join(lines)

    def _parse_response(self, text: str, question_count: int) -> list[str | None]:
        """解析LLM返回的答案"""
        answers = [None] * question_count
        text = re.sub(r'<think>[\s\S]*?</think>', '', text).strip()
        # 兼容 JSON 数组/对象与旧模型的编号输出；解释不会被解析成选项。
        plain = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.I)
        try:
            data = json.loads(plain)
            rows = data.get('answers', []) if isinstance(data, dict) else data
            if isinstance(rows, list):
                for pos, row in enumerate(rows):
                    if isinstance(row, dict):
                        index = int(row.get('index', pos+1))-1
                        value = row.get('answer')
                    else:
                        index, value = pos, row
                    if 0 <= index < question_count and isinstance(value, str):
                        answers[index] = value.strip() or None
                return answers
        except (ValueError, TypeError):
            pass
        pattern = re.compile(r"(?:\*\*|`)?(?:第)?(\d+)(?:题)?[.、：:]\s*(.+)")
        for line in text.strip().split("\n"):
            m = pattern.match(line.strip().lstrip("-* "))
            if m:
                idx = int(m.group(1)) - 1
                ans = m.group(2).strip().strip("*`")
                if 0 <= idx < question_count:
                    answers[idx] = ans
        return answers

    def answer(self, questions: list[dict]) -> list[str | None]:
        """批量回答题目"""
        if not questions:
            return []
        prompt = self._build_prompt(questions)
        response_text = self._call_api(prompt)
        if response_text is None:
            return [None] * len(questions)
        return self._parse_response(response_text, len(questions))

    def answer_single(self, question: dict) -> str | None:
        """回答单道题目"""
        results = self.answer([question])
        return results[0] if results else None

    def _call_api(self, prompt: str) -> str | None:
        """调用LLM API"""
        if self._auth_failed:
            return None
        if not self.api_key:
            logger.debug("LLM api_key未配置，跳过调用")
            return None
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
        }
        # 仅在max_tokens > 0时传入，部分模型不支持此参数
        if self.max_tokens and self.max_tokens > 0:
            payload["max_tokens"] = self.max_tokens
        try:
            logger.info(f"请求 LLM (model={self.model}, 长度={len(prompt)}字符)...")
            resp = get_external_session().post(url, headers=headers, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            if usage:
                logger.info(f"LLM 返回完成 (输入={usage.get('prompt_tokens', '?')}tokens, "
                            f"输出={usage.get('completion_tokens', '?')}tokens)")
            else:
                logger.info("LLM 返回完成")
            return content
        except Exception as e:
            # 区分超时、连接错误、HTTP错误和响应格式异常
            err_name = type(e).__name__
            if "Timeout" in err_name:
                logger.error(f"LLM 请求超时 (>{self.timeout}s)")
            elif "ConnectionError" in err_name:
                logger.error(f"LLM 连接失败: {self.api_base}")
            elif "HTTPError" in err_name:
                status = getattr(getattr(e, 'response', None), 'status_code', '?')
                if status in (401, 403):
                    self._auth_failed = True
                    logger.error(f"LLM HTTP {status}: AI 接口认证失败，请检查设置中的 API Key、接口地址与模型权限；本任务停止重复调用，继续使用题库回退")
                else:
                    logger.error(f"LLM HTTP {status}: 接口请求失败，请检查模型与服务状态")
            elif isinstance(e, (KeyError, IndexError)):
                logger.error(f"LLM 响应格式异常: {e}")
            else:
                logger.error(f"LLM 调用异常: {e}")
            return None
