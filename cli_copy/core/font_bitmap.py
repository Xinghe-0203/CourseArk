"""字体位图匹配：固定基线、盒式降采样、两级汉明距离。

参考 OCS 的 FRB2 协议与渲染坐标；实现使用 Pillow 和 Python 整数位运算。
来源及许可证见 resource/font-reference-NOTICE.md。
低置信度或异常轮廓不猜字，交由题目处理层提示用户核对。
"""
import io
import struct
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from core.paths import get_resource_path


@lru_cache(maxsize=1)
def reference_table():
    data = Path(get_resource_path('resource/font_ref_cx.bin')).read_bytes()
    if data[:4] != b'FRB2' or len(data) < 20:
        raise ValueError('字体参考数据格式无效')
    count, threshold, coarse_size, fine_size = struct.unpack_from('<4I', data, 4)
    if not 0 < count <= 100000 or coarse_size != 16 or fine_size != 24 or not 0 < threshold < 255:
        raise ValueError('字体参考数据参数无效')
    if len(data) != 20 + count * (4 + 32 + 72):
        raise ValueError('字体参考数据长度无效')
    cps = struct.unpack_from(f'<{count}I', data, 20)
    offset = 20 + count * 4
    coarse = [int.from_bytes(data[offset+i*32:offset+(i+1)*32], 'big') for i in range(count)]
    offset += count * 32
    fine = [int.from_bytes(data[offset+i*72:offset+(i+1)*72], 'big') for i in range(count)]
    return cps, coarse, fine, threshold


def features(font, char, threshold):
    canvas = Image.new('L', (480, 480), 0)
    draw = ImageDraw.Draw(canvas)
    draw.text(((480-font.getlength(char))/2, 384), char, font=font, fill=255, anchor='ls')
    if canvas.getextrema()[1] <= 40:
        return None
    values = []
    for size in (16, 24):
        pixels = canvas.resize((size, size), Image.Resampling.BOX).getdata()
        bits = 0
        for pixel in pixels:
            bits = (bits << 1) | int(pixel > threshold)
        values.append(bits)
    return values


def match(coarse, fine, table, minimum_margin=.30):
    cps, coarse_ref, fine_ref, _ = table
    indices = sorted(range(len(cps)), key=lambda i: (coarse_ref[i] ^ coarse).bit_count())[:40]
    # 同一个字符可能有多种字重，只与不同字符比较次优距离。
    scores = {}
    for i in indices:
        cp = cps[i]
        score = (fine_ref[i] ^ fine).bit_count()
        scores[cp] = min(score, scores.get(cp, 577))
    ranked = sorted(scores.items(), key=lambda item: item[1])
    if len(ranked) < 2:
        return None
    (cp, best), (_, second) = ranked[:2]
    margin = 1-best/second if second else 0
    if margin < minimum_margin or best > 100:
        return None
    return chr(cp)


def decode_characters(font_data: bytes, chars: set[str]) -> dict[str, str]:
    table = reference_table()
    font = ImageFont.truetype(io.BytesIO(font_data), 360)
    result = {}
    for char in chars:
        value = features(font, char, table[3])
        if value:
            real = match(*value, table)
            if real:
                result[char] = real
    return result
