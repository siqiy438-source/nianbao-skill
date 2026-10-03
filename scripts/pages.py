#!/usr/bin/env python3
"""
把 PDF 的几页转成图片，用来核对表格、看图里的数字、看排好的报告。
能直接读 PDF 页面的 agent（比如 Claude Code 的 Read 工具）不用它；Codex 等先转成图片再看。

用法：
  python3 pages.py <PDF> <起-止> <输出文件夹> [--dpi 110]

  <起-止> 是 PDF 页码（PDF 阅读器里看到的第几页，从 1 数），比如 7-8、30
输出：<输出文件夹>/page_007.png …，每张一页
"""
import sys
from pathlib import Path

import fitz  # PyMuPDF


def main():
    args = sys.argv[1:]
    if len(args) < 3:
        print(__doc__)
        sys.exit(1)
    pdf, rng, out = Path(args[0]), args[1], Path(args[2])
    dpi = int(args[args.index("--dpi") + 1]) if "--dpi" in args else 110
    a, b = (int(x) for x in rng.split("-")) if "-" in rng else (int(rng), int(rng))
    doc = fitz.open(pdf)
    out.mkdir(parents=True, exist_ok=True)
    for p in range(max(1, a), min(b, doc.page_count) + 1):
        f = out / f"page_{p:03d}.png"
        doc[p - 1].get_pixmap(dpi=dpi).save(f)
        print(f)


if __name__ == "__main__":
    main()
