#!/usr/bin/env python3
"""Stage 4: trace glyph masters into outlines and build a monospaced OpenType font.

master (ink density, UP*18 px per pitch) -> 2x bicubic upsample -> threshold at 50% ->
keep only ink touching the glyph's own cell -> potrace -> pathops (winding/overlap cleanup)
-> CFF charstrings.  Advance width = 600 units (1 pitch), UPM 1000, like Courier.
A FontForge pass then adds extrema, simplifies and rounds.

Run from a book dir containing work/masters.npz; writes work/font/<Family>-Regular.otf
"""
import json, os, re, subprocess, sys, tempfile
import numpy as np
from PIL import Image
from scipy import ndimage
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen
from fontTools.svgLib.path import parse_path
import pathops

FAMILY = os.environ.get('FAMILY', 'Recuperatus Mono')
MIN_SAMPLES = int(os.environ.get('MIN_SAMPLES', '10'))
MASTERS = os.environ.get('MASTERS', 'work/masters')
SKIP = set('[]|_°“”‘’—–')           # hand-built, not real glyphs, or OCR variants of the one quote/dash key
UP = 4; PITCH_PX = 18 * UP          # master pixels per pitch (matches 03_masters.py)
U0, V0 = -0.75, -1.55
ADV = 600
S = ADV / PITCH_PX                  # font units per master pixel
SUPER = 2                           # extra upsampling before thresholding


def glyph_bitmap(m):
    big = np.asarray(Image.fromarray(m.astype(np.float32)).resize(
        (m.shape[1] * SUPER, m.shape[0] * SUPER), Image.BICUBIC))
    bw = big > 0.5
    lab, n = ndimage.label(bw)
    if n == 0:
        return bw
    # keep components that reach into this glyph's own cell (|u| < 0.42 pitch)
    cx0 = int((-0.42 - U0) * PITCH_PX * SUPER); cx1 = int((0.42 - U0) * PITCH_PX * SUPER)
    keep = set(np.unique(lab[:, cx0:cx1])) - {0}
    return np.isin(lab, list(keep))


def trace(bw):
    """potrace a boolean image -> (svg path d strings, transform matrix)."""
    with tempfile.TemporaryDirectory() as td:
        pbm = os.path.join(td, 'g.pbm')
        Image.fromarray(~bw).convert('1').save(pbm)          # PBM: black = 1 = ink
        svg = subprocess.run(['potrace', pbm, '-b', 'svg', '-o', '-', '--flat', '-a', '1.0', '-O', '0.4', '-t', '8'],
                             capture_output=True, text=True, check=True).stdout
    t = re.search(r'transform="translate\(([-\d.]+),([-\d.]+)\) scale\(([-\d.]+),([-\d.]+)\)"', svg)
    tx, ty, sx, sy = map(float, t.groups())
    return re.findall(r' d="([^"]+)"', svg), (sx, 0, 0, sy, tx, ty)


def to_font_units(paths, potrace_tf, h):
    """potrace svg coords -> master pixels (y down) -> font units (y up, baseline 0, cell centred at 300)."""
    sx, _, _, sy, tx, ty = potrace_tf
    k = S / SUPER
    # master px x -> font: (x/SUPER/PITCH_PX + U0) * ADV + ADV/2 ; y -> -(y/SUPER/PITCH_PX + V0) * ADV
    path = pathops.Path()
    pen = TransformPen(path.getPen(), (k * sx, 0, 0, -k * sy, k * tx + (U0 * ADV + ADV / 2), -k * ty - V0 * ADV))
    for d in paths:
        parse_path(d, pen)
    path.simplify(fix_winding=True, keep_starting_points=False)
    return path


def main():
    data = np.load(MASTERS + '.npz')
    stats = json.load(open(MASTERS + '.json'))
    glyphs = {}
    for key in data.files:
        ch = chr(int(key[1:], 16))
        if ch in SKIP or stats[ch]['total'] < MIN_SAMPLES or not ch.isprintable():
            continue
        m = data[key]
        paths, tf = trace(glyph_bitmap(m))
        glyphs[ch] = to_font_units(paths, tf, m.shape[0])

    names = {ch: (f'uni{ord(ch):04X}' if not ch.isalnum() else ch) for ch in glyphs}
    order = ['.notdef', 'space'] + [names[c] for c in sorted(glyphs)]
    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap({32: 'space', **{ord(c): names[c] for c in glyphs}})
    charstrings = {}
    for name in ('.notdef', 'space'):
        p = T2CharStringPen(ADV, None); charstrings[name] = p.getCharString()
    bounds = []
    for ch, path in glyphs.items():
        p = T2CharStringPen(ADV, None); path.draw(p); charstrings[names[ch]] = p.getCharString()
        if path.bounds: bounds.append(path.bounds)
    b = np.array(bounds)
    asc, desc = int(np.ceil(b[:, 3].max())), int(np.floor(b[:, 1].min()))
    fb.setupCFF(FAMILY.replace(' ', ''), {'FullName': FAMILY}, charstrings, {})
    fb.setupHorizontalMetrics({n: (ADV, 0) for n in order})
    fb.setupHorizontalHeader(ascent=asc, descent=desc)
    fb.setupNameTable({'familyName': FAMILY, 'styleName': 'Regular',
                       'copyright': os.environ.get('COPYRIGHT', 'Copyright 2026 Piotr Mitros (https://github.com/pmitros/recuperatus), '
                                                    'with Reserved Font Name "Recuperatus".'),
                       'description': 'Monospaced typewriter face recovered by averaging thousands of scanned impressions per glyph.',
                       'licenseDescription': 'Dual-licensed: SIL Open Font License 1.1 (Reserved Font Name "Recuperatus"), '
                                             'or GNU Affero General Public License v3 or later.',
                       'licenseInfoURL': 'https://openfontlicense.org',
                       'trademark': os.environ.get('TRADEMARK', 'Recuperatus is a trademark of Piotr Mitros.')})
    fb.setupOS2(sTypoAscender=asc, sTypoDescender=desc, usWinAscent=asc, usWinDescent=-desc, xAvgCharWidth=ADV)
    fb.font['OS/2'].panose.bFamilyType = 2; fb.font['OS/2'].panose.bProportion = 9   # monospaced
    fb.setupPost(isFixedPitch=1)
    os.makedirs('work/font', exist_ok=True)
    raw = f'work/font/{FAMILY.replace(" ", "")}-raw.otf'
    fb.save(raw)
    print(f'{len(glyphs)} glyphs, ascent {asc}, descent {desc} -> {raw}')
    return raw


if __name__ == '__main__':
    main()
