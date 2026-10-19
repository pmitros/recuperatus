"""Parse tesseract hOCR (with hocr_char_boxes=1) into lines of characters."""
import re
from dataclasses import dataclass, field

@dataclass
class Char:
    ch: str
    box: tuple          # x0, y0, x1, y1 (pixels)
    conf: float

@dataclass
class Line:
    box: tuple
    baseline: tuple     # (slope, offset) relative to box bottom-left, tesseract convention
    chars: list = field(default_factory=list)
    words: list = field(default_factory=list)   # list of (word bbox, [Char])

    def base_y(self, x):
        slope, off = self.baseline
        return self.box[3] + off + slope * (x - self.box[0])

LINE_RE = re.compile(r"<span class='ocr_(?:line|caption|textfloat|header)'[^>]*title=\"bbox (\d+) (\d+) (\d+) (\d+); baseline ([-\d.]+) ([-\d.]+)")
WORD_RE = re.compile(r"<span class='ocrx_word'[^>]*title='bbox (\d+) (\d+) (\d+) (\d+)")
CHAR_RE = re.compile(r"class='ocrx_cinfo' title='x_bboxes (\d+) (\d+) (\d+) (\d+); x_conf ([\d.]+)'>([^<]*)<")

def unescape(s):
    return s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")

def parse(path):
    text = open(path).read()
    lines = []
    # split on line spans, then word spans within, then chars
    for m in LINE_RE.finditer(text):
        end = text.find("<span class='ocr_", m.end())
        chunk = text[m.end(): end if end > 0 else len(text)]
        ln = Line(tuple(map(int, m.group(1, 2, 3, 4))), (float(m.group(5)), float(m.group(6))))
        parts = WORD_RE.split(chunk)          # [pre, x0, y0, x1, y1, body, x0, ...]
        for i in range(1, len(parts) - 4, 5):
            wbox = tuple(map(int, parts[i:i + 4]))
            word = [Char(unescape(c[5]), tuple(map(int, c[:4])), float(c[4])) for c in CHAR_RE.findall(parts[i + 4])]
            if word:
                ln.words.append((wbox, word)); ln.chars.extend(word)
        if ln.chars:
            lines.append(ln)
    return lines
