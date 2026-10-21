#!/usr/bin/env python3
"""Stage 3: build a super-resolved master image for every character.

For each OCR label, sample up to N confident instances from across the book, resample each
cell at UP x resolution in pitch-normalised coordinates (so slight pitch drift between lines
doesn't blur the result), register them to sub-pixel accuracy against a running median, and
take the median.  Thousands of noisy 180 ppi copies -> one clean high-resolution glyph.

Output: work/masters.npz  (label -> master, plus per-label stats) and work/masters.png
Run from a book dir containing pages/ and work/grid/.
"""
import glob, json, os, random
from collections import defaultdict
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from skimage.registration import phase_cross_correlation

N = 600                 # instances per label
MIN_CONF = 90
MIN_COHERENCE = 0.9
PITCH = tuple(map(float, os.environ.get('PITCH', '17.5,18.6').split(',')))   # lines of this typewriter pitch (10 cpi at 180 ppi by default)
OUT = os.environ.get('MASTERS', 'work/masters')   # writes OUT.npz, OUT.json, OUT.png
UP = 4                  # super-resolution factor
# cell window in pitch units, relative to (cell centre, baseline)
U0, U1 = -0.75, 0.75
V0, V1 = -1.55, 0.65
random.seed(0)


def ink(path):
    """Page as ink density: 0 = paper, 1 = ink (same levels as the clean PDF)."""
    a = np.asarray(Image.open(path).convert('L'), dtype=np.float32)
    paper = np.percentile(a, 60); lo = min(np.percentile(a, 0.5), paper - 98)
    return 1 - np.clip((a - lo) / (paper - 18 - lo), 0, 1)


def grid_coords(pitch):
    nu = int(round((U1 - U0) * 18 * UP)); nv = int(round((V1 - V0) * 18 * UP))
    u = np.linspace(U0, U1, nu) * pitch; v = np.linspace(V0, V1, nv) * pitch
    return np.meshgrid(v, u, indexing='ij')   # (dy, dx) offsets in page pixels


def main():
    # 1. choose instances
    by_label = defaultdict(list)
    for gpath in sorted(glob.glob('work/grid/*.json')):
        pg = os.path.basename(gpath)[:-5]
        for li, ln in enumerate(json.load(open(gpath))['lines']):
            if not ln['pitch'] or ln['coherence'] < MIN_COHERENCE or not PITCH[0] <= ln['pitch'] <= PITCH[1]:
                continue
            cols = [c['col'] for c in ln['chars']]
            for c in ln['chars']:
                if c['conf'] >= MIN_CONF and len(c['ch']) == 1 and cols.count(c['col']) == 1:
                    by_label[c['ch']].append((pg, ln['phase'] + c['col'] * ln['pitch'], c['base'], ln['pitch']))
    chosen = defaultdict(list)
    for lab, inst in by_label.items():
        for x in random.sample(inst, min(N, len(inst))):
            chosen[x[0]].append((lab,) + x[1:])
    print('labels:', len(by_label), {k: len(v) for k, v in sorted(by_label.items(), key=lambda kv: -len(kv[1]))[:12]}, '...')

    # 2. sample cells page by page
    crops = defaultdict(list)
    for pg, items in sorted(chosen.items()):
        im = ink(f"{os.environ.get('PAGES_DIR', 'pages')}/{pg}.png")
        for lab, cx, base, pitch in items:
            dy, dx = grid_coords(pitch)
            crops[lab].append(ndimage.map_coordinates(im, [base + dy, cx + dx], order=3, mode='constant'))

    # 3. register and median
    masters, stats = {}, {}
    for lab, cs in crops.items():
        cs = np.stack(cs).astype(np.float32)
        ref = np.median(cs, 0)
        for _ in range(3):
            shifts = [phase_cross_correlation(ref, c, upsample_factor=4, normalization=None)[0] for c in cs]
            al = np.stack([ndimage.shift(c, s, order=1) for c, s in zip(cs, shifts)])
            ref = np.median(al, 0)
        r = np.array([np.corrcoef(ref.ravel(), a.ravel())[0, 1] for a in al])
        masters[lab] = ref
        stats[lab] = dict(n=len(cs), total=len(by_label[lab]), corr_median=float(np.median(r)),
                          corr_p10=float(np.percentile(r, 10)))
    np.savez_compressed(OUT + '.npz', **{f'u{ord(k):04x}': v for k, v in masters.items()})
    json.dump(stats, open(OUT + '.json', 'w'), indent=1)

    # 4. contact sheet
    labs = sorted(masters, key=lambda k: -stats[k]['total'])
    h, w = next(iter(masters.values())).shape
    cols = 16; rows = (len(labs) + cols - 1) // cols
    sheet = Image.new('L', (cols * (w + 8), rows * (h + 24)), 255); d = ImageDraw.Draw(sheet)
    for i, lab in enumerate(labs):
        x, y = (i % cols) * (w + 8), (i // cols) * (h + 24)
        sheet.paste(Image.fromarray((255 * (1 - np.clip(masters[lab], 0, 1))).astype(np.uint8)), (x, y + 20))
        d.text((x + 2, y + 2), f'{lab} {stats[lab]["total"]}', fill=0)
    sheet.save(OUT + '.png')
    print('masters:', len(masters))


if __name__ == '__main__':
    main()
