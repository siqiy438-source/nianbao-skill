#!/usr/bin/env python3
"""
给一份报告安排文件夹：一家公司一个文件夹，年报原件、精读 PDF、工作文件都在里面。

用法：
  python3 folder.py <年报或半年报.pdf> [--year 2025]

做的事：
  1. 认出公司简称和年份（先看 PDF 里的「股票简称」，再看文件名开头）。
  2. 在这份 PDF 所在的文件夹里建「<简称>」文件夹；PDF 已经在公司文件夹里就直接用。
  3. 把这份 PDF 挪进公司文件夹；原来那个文件夹里、文件名以公司简称开头的其他 PDF
     （往年年报、季报、半年报、以前的精读）也一起挪进去。
  4. 建「<公司文件夹>/工作文件/<年份>/」，放导出的文字、report.json、预览图。

--year：对答案时用。后来的半年报要放进被检查的那一年的工作文件夹，比如 --year 2025。

最后打印要用的路径，后面几步照抄。
"""
import re
import shutil
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import guess_company_year  # noqa: E402


def name_prefix(filename):
    """文件名开头、数字之前的部分：「中际联合2025年年度报告.pdf」→「中际联合」。"""
    m = re.match(r"\s*([^\d\s_（(【\[]+)", filename)
    return m.group(1).strip() if m else ""


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    pdf = Path(args[0]).expanduser().resolve()
    want_year = int(args[args.index("--year") + 1]) if "--year" in args else None
    if not pdf.exists():
        sys.exit(f"✗ 找不到文件：{pdf}")

    doc = fitz.open(pdf)
    full, year, short, code = guess_company_year(doc)
    doc.close()
    pre = name_prefix(pdf.name)
    short = short or pre or (full or "").replace("股份有限公司", "").replace("有限公司", "") or pdf.stem
    if not year:
        m = re.search(r"(20\d{2})", pdf.name)
        year = int(m.group(1)) if m else None
    work_year = want_year or year

    names = {n for n in (short, pre) if n and len(n) >= 2}
    parent = pdf.parent
    if parent.name in names:            # 已经在公司文件夹里了
        company = parent
        source_dir = None
    else:
        company = parent / short
        source_dir = parent
    company.mkdir(exist_ok=True)

    moved, skipped = [], []

    def move_in(f):
        dest = company / f.name
        if f.resolve() == dest.resolve():
            return dest
        if dest.exists():
            skipped.append(f.name)
            return f
        shutil.move(str(f), str(dest))
        moved.append(f.name)
        return dest

    pdf = move_in(pdf)
    if source_dir:
        for f in sorted(source_dir.iterdir()):
            if f.is_file() and f.suffix.lower() == ".pdf" and any(f.name.startswith(n) for n in names):
                move_in(f)

    # 半年报单独一个工作文件夹，不和同一年的年报撞名；对答案（--year）时用被检查那一年的
    half = not want_year and ("半年度报告" in pdf.name or "半年报" in pdf.name)
    tag = f"{work_year}半年报" if half else (str(work_year) if work_year else pdf.stem)
    work = company / "工作文件" / tag
    work.mkdir(parents=True, exist_ok=True)
    out_pdf = company / (f"{short}{tag}_第三节精读.pdf" if half else
                         f"{short}{work_year or ''}年报_第三节精读.pdf")   # 对答案时就是被检查那一年的精读

    print(f"公司：{short}（{full or '?'}，代码 {code or '?'}），报告年份 {year or '?'}")
    print(f"公司文件夹：{company}")
    print(f"这份报告：{pdf}")
    print(f"工作文件夹：{work}")
    print(f"精读 PDF：{out_pdf}")
    if moved:
        print("挪进公司文件夹的：" + "、".join(moved))
    if skipped:
        print("⚠ 公司文件夹里已经有同名文件，没挪：" + "、".join(skipped))


if __name__ == "__main__":
    main()
