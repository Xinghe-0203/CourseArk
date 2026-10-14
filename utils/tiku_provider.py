"""
AutoChaoxingCLI - 在线题库查询提供者

支持多个在线题库源：
1. 言溪题库 (enncy)
2. GO题/网课小工具 (icodef)
3. LIKE知识库 (datam)

按配置顺序依次查询，第一个返回结果的源即为最终答案。
"""

import re
from difflib import SequenceMatcher
from typing import Optional

from loguru import logger

from core.request_client import get_external_session


def _is_subsequence(sub: str, text: str) -> bool:
    """
    检查sub是否是text的子序列

    用于模糊匹配答案与选项文本。
    例如: "急性中毒" 是 "急性有机磷农药中毒" 的子序列

    Args:
        sub: 较短的字符串
        text: 较长的字符串

    Returns:
        bool: sub是text的子序列返回True
    """
    it = iter(text)
    return all(c in it for c in sub)


class TikuProvider:
    """在线题库查询提供者"""

    def __init__(self, config: dict = None):
        config = config or {}
        self.timeout = config.get("timeout", 10)
        self.providers = []

        provider_order = config.get("order", ["enncy", "icodef", "datam"])

        if "enncy" in provider_order:
            token = config.get("enncy-token", "")
            if token:
                self.providers.append(EnncyProvider(token, self.timeout))

        if "icodef" in provider_order:
            token = config.get("icodef-token", "")
            if token:
                self.providers.append(IcodefProvider(token, self.timeout))

        if "datam" in provider_order:
            token = config.get("datam-token", "")
            if token:
                self.providers.append(DatamProvider(token, self.timeout))

        if self.providers:
            logger.info(f"已启用 {len(self.providers)} 个在线题库源: {[p.name for p in self.providers]}")
        else:
            logger.info("未配置在线题库Token，仅使用本地缓存和LLM")

    def query(self, question_text: str, options: list = None) -> Optional[str]:
        """按配置顺序依次查询各题库源"""
        if not self.providers:
            return None
        if not question_text or len(question_text.strip()) < 2:
            return None

        for provider in self.providers:
            try:
                answer = provider.query(question_text, options)
                if answer and answer.strip():
                    logger.debug(f"题库'{provider.name}'返回答案: {answer[:50]}")
                    return answer.strip()
            except Exception as e:
                logger.debug(f"题库'{provider.name}'查询失败: {e}")
                continue
        return None

    @staticmethod
    def match_answer_to_options(answer: str, options: list) -> Optional[str]:
        """将题库返回的文本答案与选项匹配，转换为选项字母"""
        if not answer or not options:
            return None

        # 答案已经是选项字母格式
        if re.fullmatch(r'[A-Za-z]', answer.strip()):
            return answer.strip().upper()

        # 多选题字母
        compact_letters = re.sub(r'[,，;；\s]+', '', answer.strip())
        if len(compact_letters) > 1 and re.fullmatch(r'[A-Za-z]+', compact_letters):
            return "".join(sorted(set(compact_letters.upper())))

        answer_clean = answer.strip()
        best_match = None
        best_score = 0.0

        for i, option in enumerate(options):
            if not option:
                continue
            option_text = re.sub(r'^[A-Da-d][.、．\s]+', '', option).strip()
            if not option_text:
                continue
            # 直接包含匹配
            if option_text in answer_clean or answer_clean in option_text:
                return chr(65 + i)
            # 子序列匹配（答案文本是选项文本的子序列）
            if _is_subsequence(answer_clean, option_text):
                return chr(65 + i)
            # 相似度匹配
            score = SequenceMatcher(None, answer_clean, option_text).ratio()
            if score > best_score:
                best_score = score
                best_match = chr(65 + i)

        if best_score >= 0.8 and best_match:
            return best_match
        return None


class EnncyProvider:
    """言溪题库提供者"""
    name = "言溪题库"

    def __init__(self, token: str, timeout: int = 10):
        self.token = token
        self.timeout = timeout

    def query(self, question: str, options: list = None) -> Optional[str]:
        url = "https://tk.enncy.cn/query"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
        }
        data = {"question": question, "token": self.token}
        resp = get_external_session().post(url, headers=headers, data=data, timeout=self.timeout)
        result = resp.json()
        if result.get("code") == 0 or result.get("data"):
            answer = result.get("data", {}).get("answer", "") if isinstance(result.get("data"), dict) else result.get("data", "")
            if answer:
                return str(answer)
        return None


class IcodefProvider:
    """GO题库提供者"""
    name = "GO题库"

    def __init__(self, token: str, timeout: int = 10):
        self.token = token
        self.timeout = timeout

    def query(self, question: str, options: list = None) -> Optional[str]:
        url = "https://q.icodef.com/wyn-nb?v=4"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
            "Authorization": f"Bearer {self.token}",
        }
        data = {"question": question}
        resp = get_external_session().post(url, headers=headers, data=data, timeout=self.timeout)
        result = resp.json()
        answer = result.get("data") or result.get("answer") or ""
        if answer:
            return str(answer)
        return None


class DatamProvider:
    """LIKE知识库提供者"""
    name = "LIKE知识库"

    def __init__(self, token: str, timeout: int = 10):
        self.token = token
        self.timeout = timeout

    def query(self, question: str, options: list = None) -> Optional[str]:
        url = "https://app.datam.site/api/v1/query"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
            "Authorization": f"Bearer {self.token}",
        }
        payload = {"question": question}
        resp = get_external_session().post(url, headers=headers, json=payload, timeout=self.timeout)
        result = resp.json()
        answer = result.get("data", {}).get("answer", "") if isinstance(result.get("data"), dict) else result.get("data", "")
        if answer:
            return str(answer)
        return None
