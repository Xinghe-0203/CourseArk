"""验证答案与题型/选项的对应关系，不从推理段落猜测字母。"""
import re


def normalize_answer(q_type: str, answer: str, options=None) -> str:
    if not isinstance(answer, str):
        return ''
    text = answer.strip().strip('`* ')
    text = re.sub(r'^(?:最终答案|正确答案|答案|answer)\s*[:：]\s*', '', text, flags=re.I)
    if q_type == '判断题':
        positive = {'对', '正确', '是', 'true', '√', '1'}
        negative = {'错', '错误', '不正确', '否', 'false', '×', '0'}
        return 'true' if text.lower() in positive else 'false' if text.lower() in negative else ''
    if q_type in ('单选题', '多选题'):
        compact = re.sub(r'[,，;；、\s]', '', text.upper())
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
