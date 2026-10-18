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

SYSTEM_PROMPT = """你是严谨的课程答题助手，正在帮助一位大学生完成在线课程题目。请结合题目所属课程的知识、题干与全部选项，先在内部推理再给出最终答案。

【作答规则】
1. 即使不确定，也必须给出你认为最可能正确的答案，禁止留空、禁止回答"无法判断"。
2. 单选：只返回一个字母，且必须是题目给出的选项字母之一。
3. 多选：返回全部正确选项的字母，按字母顺序拼接（例如 ABD），不要加空格或分隔符。
4. 判断：只返回 true 或 false。
5. 填空：按空的顺序返回答案，多个空之间用中文分号"；"分隔。
6. 简答：用简洁、完整、可直接提交的知识点作答（约 30-120 字），不要写"根据题意"之类的话。
7. 不要编造题干中不存在的选项；不要输出题型名、题号或解题过程。

【输出格式】
只返回一个 JSON 对象，不要 Markdown 代码块、不要任何额外文字：
{"answers":[{"index":1,"answer":"B","reason":"一句话依据"}]}
index 从 1 开始连续编号，与输入题目编号一一对应；reason 会被忽略，仅用于促使你核对依据。"""

STRICT_PROMPT = """

【严格模式】上一次回答无法被解析。本次只允许输出一个 JSON 对象：
{"answers":[{"index":1,"answer":"B"}]}
不要输出 ```json 围栏、不要输出任何解释、不要输出思考过程；每题 answer 必须非空。"""


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

    @staticmethod
    def _context_lines(context: dict | None) -> list[str]:
        """把作答场景（课程/作业/考试）转成提示词开头，帮助模型锁定学科知识。"""
        if not context:
            return []
        lines = []
        course = str(context.get("course") or "").strip()
        media = str(context.get("media") or "").strip()
        kind = str(context.get("kind") or "").strip() or "作业"
        if course:
            lines.append(f"课程：{course}")
        if media:
            lines.append(f"作答内容：{kind}「{media}」")
        extra = str(context.get("extra") or "").strip()
        if extra:
            lines.append(f"补充说明：{extra}")
        if lines:
            lines.append("请结合该课程的知识范围作答，答案要符合教材与课程常见口径。")
        return lines

    def _build_prompt(self, questions: list[dict], context: dict | None = None) -> str:
        """构建题目提示词"""
        lines = self._context_lines(context)
        if lines:
            lines.append("")
        total = len(questions)
        lines.append(f"共 {total} 题，请全部作答并严格按题目编号返回。")
        lines.append("")
        for i, q in enumerate(questions, 1):
            q_type = q.get("question_type", "未知")
            q_text = q.get("question_text", "")
            options = q.get("options", [])
            lines.append(f"第{i}题【{q_type}】{q_text}")
            for opt in options:
                lines.append(opt)
            lines.append("---")
        return "\n".join(lines)

    @staticmethod
    def _clean_value(value) -> str | None:
        """清理模型返回值的常见装饰（答案：/B./**B**/"B"），保留原始语义。"""
        if value is None:
            return None
        text = str(value).strip()
        text = re.sub(r'^(?:最终)?答案\s*[:：]\s*', '', text)
        text = text.strip().strip('“”"\'`*_ ')
        # 选择题常见的 "B." / "B、" / "(B)"；仅在形式明显时去除装饰
        match = re.fullmatch(r'[(\[（【]?\s*([A-Za-z])\s*[)\]）】]?[.、,，:：]?', text)
        if match and not text.isalpha():
            return match.group(1).upper()
        return text or None

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
                        answers[index] = self._clean_value(value)
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
                    answers[idx] = self._clean_value(ans)
        return answers

    def answer(self, questions: list[dict], context: dict | None = None,
               strict: bool = False) -> list[str | None]:
        """批量回答题目

        Args:
            questions: 题目列表，每项含 question_type/question_text/options
            context: 作答场景 {"course": 课程名, "media": 作业/考试名, "kind": "作业"|"考试"}
            strict: 严格模式（解析失败后重试时使用，要求只输出 JSON）
        """
        if not questions:
            return []
        prompt = self._build_prompt(questions, context)
        response_text = self._call_api(prompt, strict=strict)
        if response_text is None:
            return [None] * len(questions)
        return self._parse_response(response_text, len(questions))

    def answer_single(self, question: dict, context: dict | None = None,
                      strict: bool = False) -> str | None:
        """回答单道题目"""
        results = self.answer([question], context=context, strict=strict)
        return results[0] if results else None

    def _call_api(self, prompt: str, strict: bool = False) -> str | None:
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
                {"role": "system", "content": SYSTEM_PROMPT + (STRICT_PROMPT if strict else "")},
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
            if not content or not str(content).strip():
                logger.warning("LLM 返回空内容（可能被安全策略拦截或超出上下文）")
            else:
                logger.debug(f"LLM 原始返回: {str(content)[:300]}")
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
                    logger.error(f"LLM HTTP {status}: AI 接口认证失败，请检查设置中的 API Key、接口地址与模型权限；本任务停止重复调用，未作答的题目将按兜底策略处理")
                else:
                    logger.error(f"LLM HTTP {status}: 接口请求失败，请检查模型与服务状态")
            elif isinstance(e, (KeyError, IndexError)):
                logger.error(f"LLM 响应格式异常: {e}")
            else:
                logger.error(f"LLM 调用异常: {e}")
            return None
