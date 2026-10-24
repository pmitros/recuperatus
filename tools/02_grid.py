#!/usr/bin/env python3
"""Stage 2: fit a fixed-pitch grid to every OCR line.

Typewritten text sits on a comb: character centres are phase + k * pitch.  For each line we
pick the pitch maximising the coherence |mean(exp(2 pi i x / p))| of the character centres,
then assign every character an integer column k.  Output: work/grid/NNNN.json

Run from a book dir containing work/hocr/.
"""
import glob, json, os, sys
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hocr  # noqa: E402

PITCH_RANGE = (12.0, 21.0)   # pixels; 10 cpi at 180 ppi is 18 px, 12 cpi is 15 px


def fit_pitch(xs):
    ps = np.arange(*PITCH_RANGE, 0.005)
    z = np.exp(2j * np.pi * xs[None, :] / ps[:, None]).mean(1)
    k = int(np.argmax(np.abs(z)))
    p = ps[k]
    phase = (np.angle(z[k]) / (2 * np.pi) * p) % p
    return float(p), float(phase), float(np.abs(z[k]))


def page(path):
    out = 'work/grid/' + os.path.basename(path).replace('.hocr', '.json')
    lines = []
    for ln in hocr.parse(path):
        chars = [c for c in ln.chars if c.ch.strip()]
        if not chars:
            continue
        xs = np.array([(c.box[0] + c.box[2]) / 2 for c in chars])
        if len(xs) >= 6:
            p, ph, r = fit_pitch(xs)
        else:
            p, ph, r = None, None, 0.0
        rec = dict(box=ln.box, baseline=ln.baseline, pitch=p, phase=ph, coherence=r, chars=[])
        # Per-character boxes from the LSTM drift within long words; word boxes don't.  On a
        # typewriter a word's characters occupy consecutive columns, so place each word as a unit.
        for wi, (wbox, word) in enumerate(ln.words):
            word = [c for c in word if c.ch.strip()]
            if not word:
                continue
            wc = (wbox[0] + wbox[2]) / 2
            col0 = int(round((wc - (len(word) - 1) / 2 * p - ph) / p)) if p else None
            for i, c in enumerate(word):
                x = (ph + (col0 + i) * p) if p else (c.box[0] + c.box[2]) / 2
                rec['chars'].append(dict(ch=c.ch, conf=c.conf, box=c.box, col=(col0 + i) if p else None,
                                         base=float(ln.base_y(x)), w=wi))   # w: OCR word index (word breaks)
        lines.append(rec)
    json.dump(dict(lines=lines), open(out, 'w'))
    return len(lines)


if __name__ == '__main__':
    os.makedirs('work/grid', exist_ok=True)
    files = sorted(glob.glob('work/hocr/*.hocr'))
    with ProcessPoolExecutor(mp_context=multiprocessing.get_context('fork')) as ex:
        n = sum(ex.map(page, files))
    print(f'{len(files)} pages, {n} lines')
