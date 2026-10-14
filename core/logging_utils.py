"""所有日志出口统一屏蔽即时探测，并移除认证字段。"""
import re

_KEYS = r'(?:password|passwd|pwd|uname|username|phone|api[_-]?key|authorization|cookie|[a-z0-9_-]*token|enc|jobenc|attdurationenc|videofacecaptureenc|sign|signature)'
_SECRET = re.compile(r"(?i)(\b" + _KEYS + r"\b[\"']?\s*[:=]\s*)([\"'])(.*?)\2")
_FORM = re.compile(r"(?i)(\b" + _KEYS + r"\b\s*[:=]\s*)([^&\s,}\]]+)")
_BEARER = re.compile(r'(?i)(Bearer\s+)[a-z0-9._~+/-]+')
_LOG_PATH = re.compile(r'(/(?:mooc-ans/)?multimedia/log/[^/\s?]+/[^/\s?]+/)[^/?\s]+')


def redact(message):
    message = str(message)
    message = _SECRET.sub(lambda m: m[1] + m[2] + '[已隐藏]' + m[2], message)
    message = _BEARER.sub(lambda m: m[1] + '[已隐藏]', message)
    message = _FORM.sub(lambda m: m[1] + '[已隐藏]', message)
    return _LOG_PATH.sub(r'\1[已隐藏]', message)


def patch_log(record):
    record['message'] = redact(record['message'])


def visible_log(record):
    return not record['extra'].get('instant_probe')
