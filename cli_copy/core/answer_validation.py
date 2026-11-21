"""验证答案与题型/选项的对应关系，不从推理段落猜测字母。"""
import re
import unicodedata


def normalize_answer(q_type: str, answer: str, options=None) -> str:
    if not isinstance(answer, str):
        return ''
    # 题干加密未完全解出时，模型会「照着乱码」作答；这类答案提交后在学习通
    # 页面上就是乱码字，必须在归一化之前拦掉。只拦主观题，客观题答案只能是
    # 字母/true/false，不受影响。
    if q_type in ('填空题', '简答题'):
        from core.answer_quality import encoding_issues
        if encoding_issues(answer, label='答案'):
            return ''
    # NFKC 归一：全角字母/数字 → 半角（Ｆ→F、√ 保持），
    # 字体解密残留的康熙部首字符同步归位
    text = unicodedata.normalize('NFKC', answer).strip().strip('`* ')
    text = re.sub(r'^(?:最终答案|正确答案|答案|answer)\s*[:：]\s*', '', text, flags=re.I)
    # 剥掉包裹性装饰：括号、引号、句末标点（模型常见输出 (F)、A.、「true」。）
    text = text.strip('（()[]【】「」"\'' ).strip()
    text = re.sub(r'[.。!！?？,，]+$', '', text).strip()
    if q_type == '判断题':
        positive = {'对', '正确', '是', 'true', 't', '√', '1', 'yes', 'y'}
        negative = {'错', '错误', '不正确', '否', 'false', 'f', '×', '0', 'no', 'n'}
        lowered = text.lower()
        # T/F、对/错等常见缩写此前不被接受，模型答 F 会被判无效而随机作答（2026-11 实机日志）
        return 'true' if lowered in positive else 'false' if lowered in negative else ''
    if q_type in ('单选题', '多选题'):
        compact = re.sub(r'[,，;；、\s。．.（）()\-—_]+', '', text.upper())
        if re.fullmatch(r'[A-Z]+', compact):
            letters = ''.join(sorted(set(compact)))
            valid = {chr(65 + i) for i in range(len(options or []))}
            if set(letters) <= valid and (q_type == '多选题' or len(compact) == 1):
                return letters
        # 精确匹配选项正文，不把解释句中偶然出现的 A/B 当答案。
        choices = []
        for i, option in enumerate(options or []):
            body = re.sub(r'^[A-Z][.、．:：)）]?\s*', '', str(option).strip())
            if text == body:
                choices.append(chr(65 + i))
        if len(choices) == 1:
            return choices[0]
        if q_type == '多选题':
            parts = [p.strip() for p in re.split(r'[#|;；、,，]', text) if p.strip()]
            if len(parts) > 1:
                letters = [normalize_answer('单选题', p, options) for p in parts]
                if all(letters):
                    return ''.join(sorted(set(letters)))
        return ''
    return text


def accepted_response(result) -> bool:
    if not isinstance(result, dict):
        return False
    status = result.get('status')
    return status is True or status == 1 or (isinstance(status, str) and status.strip().lower() in ('true', '1'))
