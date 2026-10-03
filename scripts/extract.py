#!/usr/bin/env python3
"""
从年报 PDF 里找出「第二节 公司简介和主要财务指标」和「第三节 管理层讨论与分析」，
再按名字找出第二、三讲要读的「重要事项」「股份变动及股东情况」「财务报告」三节，
按页导出文字。每页开头标上 PDF 页码和页脚印的页码，方便回头核对、在报告里注明出处。

用法：
  python3 extract.py <年报.pdf> <工作文件夹> [--s2 8-11] [--s3 12-68]

  --s2 / --s3  自动没找对时，手动指定 PDF 页码范围（PDF 阅读器里看到的第几页，从 1 数）
  --no-more    只导第二、三节，不导重要事项、股东情况、财务报告
  --extra 起-止:名字  另外导出几页（可以写多次），存成 原文_名字.txt，
               比如港股的主席报告：--extra 6-9:主席报告；check.py 核对数字时也会读它
  --as 名字    对答案用：把后来的季报、半年报、下一年年报导进原来的工作文件夹，
               文件名加前缀（原文_名字_第二节.txt、原文_名字_第三节.txt、原文_名字_xxx.txt），
               比如 --as 2026半年报

输出（都在工作文件夹里）：
  第二节.txt   第三节.txt   meta.json（公司名、年份、页码范围、第三节小标题目录、页码对照）
  原文_重要事项.txt   原文_股东情况.txt   原文_财务报告.txt（财务报告很长，按 meta.json 里「先翻到」的页码去读）
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

try:  # PyMuPDF：新版叫 pymupdf，旧版叫 fitz
    import pymupdf as fitz
except ImportError:
    import fitz

CN_NUM = "一二三四五六七八九十"

# 第三节在不同年份、不同交易所、港股里的叫法
S3_NAMES = [
    "管理层讨论与分析", "管理層討論與分析", "管理层讨论及分析", "管理層討論及分析",
    "经营情况讨论与分析", "經營情況討論與分析", "董事会报告", "董事會報告",
]
# 第二节（财务概要）的叫法
S2_NAMES = [
    "公司简介和主要财务指标", "公司簡介和主要財務指標", "会计数据和财务指标摘要", "會計數據和財務指標摘要",
    "会计数据和业务数据摘要", "財務摘要", "财务摘要", "財務概要", "财务概要", "五年財務摘要",
    "五年财务摘要", "財務概覽", "财务概览", "財務資料概要",
]


def squash(s: str) -> str:
    """去掉所有空白，方便匹配「第三节 管理层 讨论与分析」这类被拆开的标题。"""
    return re.sub(r"\s+", "", s or "")


def is_section_heading(line: str) -> bool:
    return bool(re.match(rf"^第[{CN_NUM}]+[节節]", squash(line)))


def page_lines(page, head=None):
    lines = [l.strip() for l in page.get_text().splitlines() if l.strip()]
    return lines[:head] if head else lines


def looks_like_toc(page) -> bool:
    """目录页：一页里有好几个「第X节」，或者满是省略号引导线。"""
    txt = page.get_text()
    n_heads = sum(1 for l in txt.splitlines() if is_section_heading(l))
    return n_heads >= 3 or txt.count("....") >= 5 or txt.count("…") >= 8


def page_no_of_line(line):
    """这一行是不是页码行：「- 8 -」「8」「8 / 250」「……第 8 页」。是就返回数字。"""
    s = squash(line)
    m = (re.fullmatch(r"[-－—]?(\d{1,3})[-－—]?", s)
         or re.fullmatch(r"(\d{1,3})/\d{1,4}", s)
         or re.search(r"第(\d{1,3})页(共\d+页)?$", s))
    return int(m.group(1)) if m else None


def printed_number(page):
    """找页脚/页眉上印的页码。"""
    lines = page_lines(page)
    for l in lines[:3] + lines[-3:]:
        n = page_no_of_line(l)
        if n is not None:
            return n
    return None


def page_offset(doc):
    """PDF 页码 - 页脚页码，取最常见的差值；找不到就返回 None。"""
    diffs = []
    step = max(1, doc.page_count // 60)
    for i in range(0, doc.page_count, step):
        n = printed_number(doc[i])
        if n is not None:
            diffs.append((i + 1) - n)
    if len(diffs) < 5:
        return None
    off, cnt = Counter(diffs).most_common(1)[0]
    return off if cnt >= len(diffs) * 0.6 else None


def find_by_outline(doc, names):
    """用 PDF 自带书签找章节：返回 (起始页, 结束页, 书签层级, 子书签列表)。"""
    toc = doc.get_toc(simple=True)
    for idx, (lvl, title, pg) in enumerate(toc):
        t = squash(title)
        if any(n in t for n in names) and pg > 0:
            end = None
            subs = []
            for lvl2, title2, pg2 in toc[idx + 1:]:
                if lvl2 <= lvl:
                    end = pg2 - 1 if pg2 > 0 else None
                    break
                t2 = title2.strip()
                if re.match(r"^(OLE_LINK|_Toc|_Hlk|_Ref|_GoBack)", t2) or len(t2) > 40:
                    continue
                subs.append((lvl2 - lvl, t2, pg2))
            if end is None or end < pg:
                end = pg if end is None else pg
            return pg, end, subs
    return None


def find_by_scan(doc, names):
    """没有书签时，逐页看页首几行，找「第X节 ××」这样的标题。"""
    heads = []  # (page_no, squashed_title)
    for i in range(doc.page_count):
        page = doc[i]
        if looks_like_toc(page):
            continue
        for l in page_lines(page, head=12):
            s = squash(l)
            if is_section_heading(l) and len(s) <= 30:
                heads.append((i + 1, s))
                break
            # 港股年报没有「第X节」，标题单独占一行
            if any(s == n for n in names):
                heads.append((i + 1, s))
                break
    # 去掉同一标题在连续页眉里反复出现的情况，只留第一次
    seen, uniq = set(), []
    for pg, s in heads:
        key = re.sub(rf"^第[{CN_NUM}]+[节節]", "", s)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((pg, s))
    for k, (pg, s) in enumerate(uniq):
        if any(n in s for n in names):
            end = uniq[k + 1][0] - 1 if k + 1 < len(uniq) else doc.page_count
            return pg, max(pg, end), []
    return None


# 第二、三讲要读的几节：按名字找，不按「第几节」找（年报是第六、七、十节，半年报是第五、六、八节）
MORE_SECTIONS = [
    ("重要事项", ["重要事项", "重要事項"]),
    ("股东情况", ["股份变动及股东情况", "股份變動及股東情況", "股本变动及股东情况", "普通股股份变动及股东情况"]),
    ("财务报告", ["财务报告", "財務報告"]),
]
# 每一节里要先翻到的地方：(标签, [正则，按顺序试], 找的范围)，取第一次出现的页
# 范围：False = 整节；True = 只在附注里（「项目注释」那页往后）；"line" = 单独成一行的标题（报表名；审计报告正文里顺带提到的不算）
def _note(x):
    """附注小标题：「5、应收账款」「（5）应收账款」「(5) 应收账款」"""
    return rf"(\d+[、.]|[（(]\d+[)）]){x}"


KEY_SPOTS = {
    "重要事项": [("承诺事项", [r"承诺事项履行情况", r"承诺事项"], False),
                 ("关联交易", [r"重大关联交易", r"关联交易"], False),
                 ("担保", [r"重大担保", r"担保情况"], False),
                 ("诉讼", [r"重大诉讼"], False)],
    "股东情况": [("前十名股东（看质押）", [r"前十名股东|前10名股东"], False),
                 ("实际控制人", [r"实际控制人"], False)],
    "财务报告": [("审计报告", [r"审计意见", r"审计报告"], False),
                 ("合并资产负债表", [r"合并(及公司)?资产负债表"], "line"),
                 ("合并利润表", [r"合并(及公司)?利润表"], "line"),
                 ("合并现金流量表", [r"合并(及公司)?现金流量表"], "line"),
                 ("合并所有者权益变动表", [r"合并(及公司)?(所有者|股东)权益变动表"], "line"),
                 ("应收账款", [_note("应收账款")], True), ("存货", [r"存货分类", _note("存货")], True),
                 ("其他应收款", [_note("其他应收款")], True), ("短期借款", [_note("短期借款")], True),
                 ("其他应付款", [_note("其他应付款")], True), ("长期借款", [_note("长期借款")], True),
                 ("营业收入和营业成本", [_note("营业收入(和|及)营业成本")], True),
                 ("投资收益", [_note("投资收益")], True)],
}
NOTES_START = r"合并财务报表(主要)?项目(注释|附注)"


def find_section(doc, names):
    """找「第X节 ××」这种一级章节：书签标题要么以「第X节」开头，要么正好就是这个名字。
    （不能只看包含：重要提示里的「保证……财务报告真实」也含「财务报告」）
    这一节到下一个「第X节」书签为止；有的年报把附注小标题也标成一级书签，不能见到一级书签就停。"""
    toc = doc.get_toc(simple=True)
    head = lambda t: bool(re.match(rf"^第[{CN_NUM}]+[节節]", t))
    for idx, (lvl, title, pg) in enumerate(toc):
        t = squash(title)
        if pg <= 0 or not any(n in t for n in names):
            continue
        if not (head(t) or t in names):
            continue
        end = doc.page_count
        for lvl2, title2, pg2 in toc[idx + 1:]:
            t2 = squash(title2)
            if lvl2 <= lvl and pg2 > 0 and (head(t2) or "备查文件" in t2):
                end = max(pg, pg2 - 1)
                break
        return pg, end, "PDF书签"
    r = find_by_scan(doc, names)
    return (r[0], r[1], "逐页扫描标题") if r else None


def key_spots(doc, start, end, spots):
    """每个标签在这一节里第一次出现的 PDF 页码（跳过目录页）；附注里的项目从「项目注释」那页往后找。"""
    texts = {p: squash(doc[p - 1].get_text()) for p in range(start, end + 1)}
    lines = {p: [squash(l) for l in page_lines(doc[p - 1])] for p in range(start, end + 1)}
    pages = [p for p in range(start, end + 1) if not looks_like_toc(doc[p - 1])]
    notes_from = next((p for p in pages if re.search(NOTES_START, texts[p])), start)
    out = []
    for label, pats, in_notes in spots:
        rng = [p for p in pages if p >= notes_from] if in_notes is True else pages
        hit = None
        for pat in pats:
            if in_notes == "line":
                hit = next((p for p in rng if any(re.fullmatch(r"(20\d{2}年[^合]{0,4})?" + pat + r"([（(]续[)）])?", l) for l in lines[p])), None)
            else:
                hit = next((p for p in rng if re.search(pat, texts[p])), None)
            if hit:
                break
        out.append((label, hit))
    return out


def parse_range(r):
    a, b = r.split("-")
    return int(a), int(b)


CN_DIGIT = {"〇": 0, "零": 0, "○": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


# 报告名：「2026 年半年度报告」「2025年年度报告」「2026年第三季度报告」「2026 中期報告」
REPORT_KINDS = [
    ("半年报", "半年度报告|半年度報告|半年报|半年報|中期报告|中期報告"),
    ("季报", "第[一三]季度报告|第[一三]季度報告|[一三]季度报告|[一三]季度報告"),
    ("年报", "年度报告|年度報告|年報|年报"),
]


def guess_report(doc):
    """认出这是哪一年的年报 / 半年报 / 季报，返回 (年份, 类型)，认不出返回 (None, None)。

    不能取第一个出现的「20XX 年报」：半年报开头常写「具体可参见 2025 年年报」，
    会把 2026 年半年报认成 2025 年。做法是数前 12 页里每个「年份 + 报告名」出现几次
    （每页页眉都印着这份报告自己的标题，封面多算几票），取票最多的；
    一样多就取更晚的年份，因为报告只会引用以前的报告。"""
    votes = Counter()
    for i in range(min(12, doc.page_count)):
        flat = squash(doc[i].get_text())
        w = 5 if i == 0 else 1
        for kind, alt in REPORT_KINDS:
            for m in re.finditer(rf"(20\d{{2}})年?(?:{alt})", flat):
                votes[(int(m.group(1)), kind)] += w
            for m in re.finditer(rf"([二〇零○][〇零○一二三四五六七八九]{{3}})年(?:{alt})", flat):
                votes[(int("".join(str(CN_DIGIT[c]) for c in m.group(1))), kind)] += w
        for m in re.finditer(r"(?:年度报告|年度報告|年報|年报)(20\d{2})", flat):
            votes[(int(m.group(1)), "年报")] += w
    if not votes:
        return None, None
    return max(votes, key=lambda k: (votes[k], k[0]))


def guess_company_year(doc):
    text = "".join(doc[i].get_text() for i in range(min(12, doc.page_count)))
    flat = squash(text)
    year, _ = guess_report(doc)
    name = None
    m = re.search(r"([\u4e00-\u9fa5（）()A-Za-z]{2,30}?(股份有限公司|集團有限公司|集团有限公司|控股有限公司|有限公司))", flat)
    if m:
        name = m.group(1)
    short, code = None, None
    m = re.search(r"股票简称[:：]?([\u4e00-\u9fa5A-Za-z＊*]{2,10}?)股票代码[:：]?(\d{6})", flat)
    if m:
        short, code = m.group(1), m.group(2)
    else:
        m = re.search(r"(?:上海|深圳|北京)证券交易所([\u4e00-\u9fa5A-Za-z＊*]{2,8}?)(\d{6})", flat)
        if m:
            short, code = m.group(1), m.group(2)
    if not code:
        m = re.search(r"股份代號[:：]?(\d{4,5})", flat)
        if m:
            code = m.group(1)
    return name, year, short, code


def dump(doc, start, end, offset, path):
    out = []
    for p in range(start, end + 1):
        page = doc[p - 1]
        printed = (p - offset) if offset is not None else None
        tag = f"==== PDF第{p}页" + (f"｜页脚印的是第{printed}页" if printed is not None else "") + " ===="
        raw = [l.rstrip() for l in page.get_text().splitlines()]
        # 只去掉页首、页尾几行里「正好是这一页页码」的那一行。
        # 不能按「单独一行的小数字」去删：表格里的 158、17、23 这类单元格也是单独一行。
        nonempty = [i for i, l in enumerate(raw) if l.strip()]
        drop = set()
        if printed is not None:
            for i in nonempty[:3] + nonempty[-3:]:
                if page_no_of_line(raw[i]) == printed:
                    drop.add(i)
        lines = [l for i, l in enumerate(raw) if i not in drop]
        out.append(tag + "\n" + "\n".join(lines).strip() + "\n")
    Path(path).write_text("\n".join(out), encoding="utf-8")
    return sum(len(x) for x in out)


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    pdf, outdir = Path(args[0]), Path(args[1])
    manual = {}
    for flag in ("--s2", "--s3"):
        if flag in args:
            manual[flag] = parse_range(args[args.index(flag) + 1])
    extras = [args[i + 1] for i, a in enumerate(args) if a == "--extra" and i + 1 < len(args)]
    tag = args[args.index("--as") + 1] if "--as" in args else ""
    pre = f"原文_{tag}_" if tag else ""       # 对答案：后来的报告加前缀，和原来的年报放在一起
    outdir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf)
    offset = page_offset(doc)
    name, year, short, code = guess_company_year(doc)
    _, kind = guess_report(doc)

    found = {}
    for key, names, flag in (("s2", S2_NAMES, "--s2"), ("s3", S3_NAMES, "--s3")):
        if flag in manual:
            found[key] = (*manual[flag], [], "手动指定")
            continue
        r = find_by_outline(doc, names)
        how = "PDF书签"
        if not r:
            r = find_by_scan(doc, names)
            how = "逐页扫描标题"
        if r:
            found[key] = (*r, how)

    meta = {
        "pdf": str(pdf.resolve()),
        "total_pages": doc.page_count,
        "company_guess": name, "short_name_guess": short, "stock_code_guess": code,
        "year_guess": year, "kind_guess": kind,
        "page_offset": offset,
        "page_note": ("页脚页码 = PDF页码 - %d" % offset) if offset is not None else "没识别出页脚页码，引用时用 PDF 页码",
    }

    print(f"年报：{pdf.name}（共 {doc.page_count} 页）")
    print(f"猜测：{name or '?'}｜简称 {short or '?'}｜代码 {code or '?'}｜{year or '?'} 年{kind or ''}")
    print("页码：" + meta["page_note"])

    ok = True
    for key, label, fname in (("s2", "第二节（财务概要）", pre + "第二节.txt"), ("s3", "第三节（管理层讨论与分析）", pre + "第三节.txt")):
        if key not in found:
            print(f"✗ 没找到{label}。先用 Read 看目录页，再加 {('--s2' if key == 's2' else '--s3')} 起-止 手动指定。")
            ok = False
            continue
        start, end, subs, how = found[key]
        n = dump(doc, start, end, offset, outdir / fname)
        meta[key] = {"pdf_pages": [start, end], "how": how, "chars": n,
                     "outline": [{"level": lv, "title": t, "pdf_page": pg} for lv, t, pg in subs]}
        pr = f"（页脚 {start - offset}–{end - offset}）" if offset is not None else ""
        print(f"✓ {label}：PDF 第 {start}–{end} 页{pr}，{end - start + 1} 页，{n} 字，靠{how}找到 → {fname}")
        if key == "s3" and subs:
            print("  第三节小标题：")
            for lv, t, pg in subs:
                if lv <= 2:
                    print(f"  {'  ' * (lv - 1)}{t}  → PDF第{pg}页")
        if key == "s3" and (end - start + 1) > 120:
            print("  ⚠ 第三节超过 120 页，可能把后面的章节也算进来了，请用 Read 看一下目录核对。")

    # 第二、三讲：重要事项（承诺、关联交易、担保）、股东情况（质押）、财务报告（审计意见、三张表、附注）
    meta["more"] = {}
    if "--no-more" not in args:
        for label, names in MORE_SECTIONS:
            r = find_section(doc, names)
            fn = f"{pre}{label}.txt" if pre else f"原文_{label}.txt"
            if not r:
                print(f"⚠ 没找到「{label}」这一节。用 Read 看目录页，再加 --extra 起-止:{label} 手动导出。")
                continue
            start, end, how = r
            n = dump(doc, start, end, offset, outdir / fn)
            spots = key_spots(doc, start, end, KEY_SPOTS.get(label, []))
            meta["more"][label] = {"pdf_pages": [start, end], "how": how, "chars": n,
                                   "spots": [{"label": a, "pdf_page": b} for a, b in spots]}
            pr = f"（页脚 {start - offset}–{end - offset}）" if offset is not None else ""
            print(f"✓ {label}：PDF 第 {start}–{end} 页{pr}，{end - start + 1} 页，{n} 字，靠{how}找到 → {fn}")
            if spots:
                print("  先翻到：" + "　".join(f"{a} PDF第{b}页" if b else f"{a} 没找到" for a, b in spots))

    meta["extra"] = []
    for ex in extras:
        rng, _, label = ex.partition(":")
        a, b = parse_range(rng)
        label = label or f"{a}-{b}"
        fn = f"{pre}{label}.txt" if pre else f"原文_{label}.txt"
        n = dump(doc, a, b, offset, outdir / fn)
        meta["extra"].append({"name": label, "pdf_pages": [a, b], "chars": n})
        print(f"✓ 另外导出：PDF 第 {a}–{b} 页，{n} 字 → {fn}")

    meta_name = f"meta_{tag}.json" if tag else "meta.json"
    (outdir / meta_name).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
