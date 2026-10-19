#!/usr/bin/env bash
# Stage 1: per-character OCR boxes.  Run from a book dir with pages/; writes work/hocr/NNNN.hocr
set -euo pipefail
mkdir -p work/hocr
ls pages/*.png | xargs -P "$(nproc)" -I{} sh -c '
  b=$(basename {} .png); [ -s work/hocr/$b.hocr ] && exit 0
  OMP_THREAD_LIMIT=1 tesseract {} work/hocr/$b -l eng -c hocr_char_boxes=1 hocr 2>/dev/null'
ls work/hocr/*.hocr | wc -l
