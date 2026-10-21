#!/usr/bin/env python3
"""Stage 6: clean up the traced font with FontForge and export OTF + hinted TTF.

  addExtrema / simplify / round / correctDirection, then:
  work/font/<Family>-Regular.otf   (CFF outlines)
  work/font/<Family>-Regular.ttf   (quadratic outlines, hinted with ttfautohint)
"""
import glob, os, subprocess
import fontforge

raw = os.environ.get('RAW') or sorted(glob.glob('work/font/*-raw.otf'))[-1]
f = fontforge.open(raw)
f.selection.all()
f.simplify(0.4, ('mergelines', 'smoothcurves', 'removesingletonpoints'))
f.correctDirection()
f.removeOverlap()
f.addExtrema()      # after simplify, which can drop extreme points
f.round()
problems = [g.glyphname for g in f.glyphs() if g.validate(True) & ~0x1 & 0x3fe]   # report non-trivial validation issues
base = raw.replace('-raw.otf', '-Regular')
f.generate(base + '.otf')
f.generate(base + '-unhinted.ttf')
subprocess.run(['ttfautohint', '--stem-width-mode=nnn', base + '-unhinted.ttf', base + '.ttf'], check=True)
os.remove(base + '-unhinted.ttf')
print('wrote', base + '.otf', base + '.ttf', '| validation issues in:', problems or 'none')
