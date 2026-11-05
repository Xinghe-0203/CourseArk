"""任务诊断输出脱敏：保留请求路径与播放进度，隐藏凭据和签名。"""
import re

_KEYS = r"(?:password|passwd|pwd|username|phone|api[_-]?key|authorization|cookie|[a-z0-9_-]*token|enc|jobenc|attdurationenc|videofacecaptureenc|sign|signature)"
_QUOTED = re.compile(r"(?i)(\b" + _KEYS + r"[\"']?\s*[:=]\s*)([\"'])(.*?)\2")
_UNQUOTED = re.compile(r"(?i)((?<![\w-])" + _KEYS + r"\s*=\s*)[^&\s\"'<>]+")
_BEARER = re.compile(r"(?i)(Bearer\s+)[a-z0-9._~+/-]+")
_PLAYBACK_PATH = re.compile(r"(?i)(/(?:multimedia/)?log/(?:[^/?\s]+/)+)[^/?\s]+(?=\?)")
# v2.4.0 T10：裸文本凭据——「正在登录账号 13812345678」这类非 key=value
# 场景。手机号限 1 开头的 11 位；学号/工号常见 6-12 位纯数字（排除年份
# 4 位与金额等短数字），仅在「账号/学号/工号」引导词后生效，避免误伤普通数字。
_BARE_PHONE = re.compile(r"(?<![\d])(1[3-9]\d{9})(?![\d])")
_BARE_ID = re.compile(r"(?i)(账号|学号|工号|用户名)\s*[:：]?\s*([0-9]{6,12})(?![\d])")
_SECRET_KEY = re.compile(_KEYS, re.IGNORECASE)


def redact(message):
    text = str(message or '')
    text = _QUOTED.sub(lambda m: m[1] + m[2] + '[已隐藏]' + m[2], text)
    text = _UNQUOTED.sub(lambda m: m[1] + '[已隐藏]', text)
    text = _PLAYBACK_PATH.sub(lambda m: m[1] + '[已隐藏]', text)
    text = _BARE_ID.sub(lambda m: m[1] + ' [已隐藏]', text)
    return _BARE_PHONE.sub(lambda m: '[已隐藏]', _BEARER.sub(lambda m: m[1] + '[已隐藏]', text))


def redact_data(value):
    """仅用于公开诊断数据，不用于内部登录 Cookie 协议或任务凭据。"""
    if isinstance(value, dict):
        return {key: '[已隐藏]' if _SECRET_KEY.fullmatch(str(key)) else redact_data(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    return redact(value) if isinstance(value, str) else value


def patch_record(record):
    record['message'] = redact(record['message'])
