#!/usr/bin/env python3
"""
交付前自检：结构、数字出处、名词解释、措辞。

用法：
  python3 check.py <report.json> [<工作文件夹>]

  工作文件夹里要有 extract.py 导出的 第二节.txt、第三节.txt（还有 --extra 导出的 原文_*.txt），
  默认就是 report.json 所在的文件夹。

数字怎么核对：
  - 带了页码（src）的数字，先到那几页（前后各放宽一页，表格可能跨页）去找；
    在别的页找到了，会提醒「页码对不上」；哪儿都找不到，会提醒「没找到」。
  - 按显示的小数位允许四舍五入（492.55 亿写成 492 亿会被抓出来），并考虑千元、万元、元的换算。
  - 自己算的数登记进 report.json 的 calc 清单；数字前后几个字里写了「计算」「推测」的也算登记过。
  - 这是抽查，不是证明：碰巧和原文另一个数一样的错数字，它抓不到。关键数字还是要回原文看。

结果：
  ✗ 必须改    ⚠ 逐条看一眼
"""
import json
import re
import sys
from pathlib import Path

# 报告里出现就必须在「名词小词典」里解释的词
JARGON = ["ToB", "ToC", "OBM", "OEM", "ODM", "DTC", "ROE", "扣非", "毛利率", "净利率", "合同负债", "非经常性损益",
          "百分点", "国补", "双寡头", "费用率", "存货", "周转", "商誉", "资本开支", "自由现金流", "应收账款",
          "归母", "现金流", "H 股", "H股", "市占率", "渗透率", "产能利用率", "在手订单",
          # 第二、三讲
          "关联交易", "担保", "质押", "审计意见", "流动比率", "净现金", "权益乘数", "资产周转率", "未分配利润",
          "资本公积", "库存股", "高送转", "增发", "账龄", "环比", "资产负债率"]
# 公司八股、AI 腔：我们自己的话里不要出现（引用年报原话、公司自己的说法不算）
BANNED = ["值得注意的是", "综上所述", "总而言之", "总的来说", "至关重要", "毋庸置疑", "不言而喻", "底层逻辑", "抓手",
          "赋能", "助力", "打造", "全方位", "深度融合", "高质量发展", "持续发力", "强劲势能", "行稳致远",
          "让我们", "不难看出", "由此可见", "显而易见"]
QUOTED_KEYS = (".orig", ".said")  # 这些字段是照抄年报 / 公司自己的说法

FACTORS = {
    "亿": [1, 1e5, 1e4, 1e8, 1e3], "亿元": [1, 1e5, 1e4, 1e8, 1e3],
    "万": [1, 1e4, 1e1], "万人": [1, 1e4], "万台": [1, 1e4], "万件": [1, 1e4], "万家": [1, 1e4], "万名": [1, 1e4],
    "万亿": [1, 1e4, 1e8], "亿台": [1, 1e4, 1e8], "亿件": [1, 1e4, 1e8], "亿人": [1, 1e4, 1e8], "亿户": [1, 1e4, 1e8],
    "%": [1], "": [1, 1e5, 1e4, 1e8],
}
NUM_RE = re.compile(r"([+\-−]?)(\d[\d,]*(?:\.\d+)?)\s*(万亿|亿元|亿台|亿件|亿人|亿户|亿|万人|万台|万件|万家|万名|万|%|个百分点)?")
PAGE_MARK = re.compile(r"==== PDF第(\d+)页(?:｜页脚印的是第(\d+)页)? ====")


def all_strings(o, path=""):
    if isinstance(o, str):
        yield path, o
    elif isinstance(o, dict):
        for k, v in o.items():
            if k in ("type", "kind", "color", "colors", "src", "labelUnit", "widths", "align"):
                continue
            yield from all_strings(v, f"{path}.{k}" if path else k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from all_strings(v, f"{path}[{i}]")


def nums_in(text):
    out = []
    for m in re.finditer(r"(?<![\d.])-?\d[\d,]*(?:\.\d+)?", text):
        try:
            out.append(float(m.group(0).replace(",", "")))
        except ValueError:
            pass
    return out


def load_pages(texts):
    """{页码: [这一页的数字]}；有页脚页码用页脚页码，没有就用 PDF 页码。"""
    pages = {}
    for t in texts:
        parts = PAGE_MARK.split(t)
        # split 的结果：[开头, pdf页, 页脚页, 正文, pdf页, 页脚页, 正文, ...]
        for i in range(1, len(parts) - 2, 3):
            key = int(parts[i + 1]) if parts[i + 1] else int(parts[i])
            pages.setdefault(key, []).extend(nums_in(parts[i + 2]))
    return pages


def found(raw, unit, bag):
    """按显示的小数位允许四舍五入误差，并考虑千元、万元、元等单位换算。"""
    v = abs(float(raw.replace(",", "").replace("−", "-")))
    d = len(raw.split(".")[1]) if "." in raw else 0
    tol = 0.5 * 10 ** (-d) + 1e-9
    for k in FACTORS.get(unit, [1]):
        target, t = v * k, tol * k
        for x in bag:
            if abs(abs(x) - target) <= t:
                return True
    return False


def cited_pages(src):
    """「第12–14页」「第11、48页」「第17–19、37页」→ 页码列表；「计算」之类返回空。"""
    if not src or not str(src).startswith("第"):
        return []
    out = []
    for part in re.split(r"[、,，]", str(src)):
        nums = [int(x) for x in re.findall(r"\d+", part)]
        if len(nums) == 2 and re.search(r"[–\-~～至]", part):
            out += list(range(nums[0], nums[1] + 1))
        else:
            out += nums
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    rp = Path(sys.argv[1])
    work = Path(sys.argv[2]) if len(sys.argv) > 2 else rp.parent
    r = json.loads(rp.read_text(encoding="utf-8"))
    errs, warns = [], []

    # ---------- 结构
    s = r.get("summary", {})
    if len(s.get("qa", [])) != 5:
        errs.append(f"「一页看懂」要正好 5 个问题，现在是 {len(s.get('qa', []))} 个")
    blocks_all = [b for ch in r.get("chapters", []) for b in ch.get("blocks", [])] + s.get("blocks", [])
    flat = []
    for b in blocks_all:
        flat.append(b)
        if b.get("type") == "cols":
            flat += b.get("items", [])
    if not any(b.get("type") == "verdict" for b in flat):
        errs.append("没有「明年怎么看」的判断（verdict 块），按刘总的要求要给出业绩区间")
    kinds = {b.get("kind") for b in flat if b.get("type") == "chart"}
    for need, name in (("bar", "柱状图"), ("line", "折线图"), ("donut", "环形/饼图")):
        if need not in kinds:
            warns.append(f"没有{name}；用户要求柱状、折线、饼图都有")
    n_chart = sum(1 for b in flat if b.get("type") == "chart")
    if n_chart < 8:
        warns.append(f"只有 {n_chart} 张图，偏少（一般 10–16 张）")
    for b in flat:
        if b.get("type") == "chart" and not b.get("src"):
            errs.append(f"图「{b.get('title', '（无标题）')}」没写来源页码 src")
        if b.get("type") == "chart" and not b.get("title"):
            warns.append("有一张图没写 title（不写就不编号，读者也不知道这张图在说什么）")
        if b.get("type") == "kpis":
            for it in b.get("items", []):
                if not it.get("src") and "计算" not in str(it.get("note", "")):
                    warns.append(f"数字卡片「{it.get('label')}」没写来源页码")
        if b.get("type") == "chart" and b.get("kind") == "donut":
            if any(x < 0 for x in b["series"][0]["data"]):
                errs.append(f"环形图「{b.get('title')}」里有负数，不能画成构成图")
    # 第二、三讲：排雷、三张表体检、毛利率和 ROE
    n_ck = sum(1 for b in flat if b.get("type") == "checkup")
    if n_ck < 3:
        warns.append(f"体检表（checkup 块）只有 {n_ck} 张；排雷、三张表、毛利率和 ROE 三章各要一张")
    for b in flat:
        if b.get("type") == "checkup":
            for it in b.get("items", []):
                if it.get("level") not in ("过关", "留意", "危险"):
                    errs.append(f"体检表「{it.get('item')}」的判断要写 过关 / 留意 / 危险，现在是「{it.get('level')}」")
                if not it.get("src"):
                    warns.append(f"体检表「{it.get('item')}」没写来源页码 src")
                if not it.get("rule"):
                    warns.append(f"体检表「{it.get('item')}」没写刘总的标准 rule")
    ck = s.get("checkup")
    if not ck:
        warns.append("「一页看懂」没写体检结论（summary.checkup）")
    elif ck.get("level") not in ("过关", "留意", "有雷"):
        errs.append(f"体检结论 summary.checkup.level 要写 过关 / 留意 / 有雷，现在是「{ck.get('level')}」")
    if len(r.get("glossary", [])) < 8:
        warns.append("名词小词典不到 8 个词，不懂的人可能看不明白")

    # ---------- 名词：用到了就要解释
    text_all = "\n".join(t for p, t in all_strings({k: v for k, v in r.items() if k != "glossary"}))
    gloss = " ".join(g.get("term", "") + " " + g.get("plain", "") for g in r.get("glossary", []))
    for j in JARGON:
        if re.search(re.escape(j), text_all, re.I) and not re.search(re.escape(j), gloss, re.I):
            warns.append(f"用到了「{j}」，名词小词典里没解释")

    # ---------- 措辞
    for p, t in all_strings(r):
        if any(q in p for q in QUOTED_KEYS):
            continue
        for w in BANNED:
            if w in t:
                warns.append(f"「{w}」是八股腔，换成大白话（位置 {p}）")

    # ---------- 数字出处
    files = [work / "第二节.txt", work / "第三节.txt"] + sorted(work.glob("原文_*.txt"))
    texts = [f.read_text(encoding="utf-8") for f in files if f.exists()]
    if not texts:
        warns.append(f"工作文件夹 {work} 里没有 第二节.txt / 第三节.txt，跳过数字核对")
    else:
        pages = load_pages(texts)
        allbag = [x for v in pages.values() for x in v]
        calc = {str(c.get("n", "")).replace(",", "").rstrip("%亿万+ ") for c in r.get("calc", [])}
        problems = []

        def locate(raw, unit, src):
            """返回 None 表示没问题；否则返回提醒文字。"""
            cp = cited_pages(src)
            if cp:
                near = set()
                for pgn in cp:
                    near.update([pgn - 1, pgn, pgn + 1])
                if found(raw, unit, [x for pgn in near for x in pages.get(pgn, [])]):
                    return None
                where = [pgn for pgn in sorted(pages) if found(raw, unit, pages[pgn])]
                if where:
                    return f"标的是{src}，但原文在第{'、'.join(map(str, where[:3]))}页"
                return "原文里没找到"
            if found(raw, unit, allbag):
                return None
            return "原文里没找到"

        def check_text(p, t, unit_hint="", src=None):
            # 正文里顺手写的「（第30页）」也算这段话的出处
            inline = re.findall(r"第\d+(?:[–\-]\d+)?(?:[、,，]\d+(?:[–\-]\d+)?)*页", t)
            if inline:
                src = "、".join([str(src)[1:-1]] if src and str(src).startswith("第") else []) + \
                      "".join("、" + x[1:-1] for x in inline)
                src = "第" + src.lstrip("、") + "页"
            for m in NUM_RE.finditer(t):
                raw, unit = m.group(2), m.group(3) or unit_hint
                v = float(raw.replace(",", ""))
                before = t[max(0, m.start() - 1): m.start()]
                after = t[m.end(): m.end() + 2]
                if before == "第" or after[:1] in ("页", "年", "期", "季", "月", "日", "章", "倍", "代", "类", "节", "块") \
                        or after in ("件事", "个问"):
                    continue
                if 1990 <= v <= 2035 and not unit:
                    continue
                if v <= 12 and not unit and "." not in raw:
                    continue
                if unit == "个百分点" or raw.replace(",", "") in calc:
                    continue
                # 数字附近写了「计算」「推测」的，算登记过（只看前后几个字，不是整段都放过）
                window = t[max(0, m.start() - 8): m.end() + 14]
                if "计算" in window or "推测" in window:
                    continue
                if "约" in t[max(0, m.start() - 3): m.start()] or "≈" in t[max(0, m.start() - 2): m.start()]:
                    continue
                # 区间写法「139–268 亿」：前一个数借用后一个数的单位
                if not unit:
                    mm = re.match(r"\s*[–\-~～至到]\s*\d[\d,]*(?:\.\d+)?\s*(亿|万|%)", t[m.end():])
                    if mm:
                        unit = mm.group(1)
                msg = locate(raw, unit, src)
                if msg:
                    problems.append((raw + unit, msg, t[max(0, m.start() - 14): m.end() + 6].replace("\n", " ")))

        def kpi_items(items, p, inherited):
            for i, it in enumerate(items):
                src = it.get("src", inherited)
                if "计算" in str(it.get("note", "")) or "计算" in str(src or ""):
                    continue
                check_text(f"{p}[{i}].value", str(it.get("value", "")), it.get("unit", ""), src)
                for k in ("label", "delta", "note"):
                    if it.get(k):
                        check_text(f"{p}[{i}].{k}", str(it[k]), "", src)

        def walk(o, p="", src=None):
            if isinstance(o, dict):
                src = o.get("src", src)
                t = o.get("type")
                if t == "kpis":
                    kpi_items(o.get("items", []), p + ".items", src)
                    return
                if t == "chart":
                    sub = str(o.get("sub", "")) + str(o.get("title", ""))
                    unit = "%" if (o.get("labelUnit") == "%" or o.get("kind") in ("diverge", "stack100")) else \
                           ("亿" if "亿" in sub else "")
                    if "计算" not in str(o.get("src", "")) and "计算" not in str(o.get("note", "")):
                        for s_ in o.get("series", []):
                            for x in s_.get("data", []):
                                raw = f"{x:g}" if isinstance(x, (int, float)) else str(x)
                                if raw.replace(",", "").lstrip("-") in calc:
                                    continue
                                msg = locate(raw, unit, src)
                                if msg:
                                    problems.append((raw + unit, msg, f"图「{o.get('title', '')}」的数据"))
                    for k in ("title", "sub", "note"):
                        if o.get(k):
                            check_text(f"{p}.{k}", str(o[k]), "", src)
                    return
                if t == "verdict":  # 推测的区间不核对；依据里的事实要核对
                    b = o.get("basis", "")
                    for i, x in enumerate(b if isinstance(b, list) else [b]):
                        check_text(f"{p}.basis[{i}]", str(x), "", None)
                    return
                for k, v in o.items():
                    if k in ("meta", "glossary", "src", "type", "kind", "orig", "calc", "endnote", "said", "widths", "align",
                             "rule", "level", "kicker"):
                        continue
                    if p == "cover" and k == "kpis":
                        kpi_items(v, "cover.kpis", None)
                        continue
                    walk(v, f"{p}.{k}" if p else k, src)
            elif isinstance(o, list):
                for i, v in enumerate(o):
                    walk(v, f"{p}[{i}]", src)
            elif isinstance(o, str):
                check_text(p, o, "", src)

        walk(r)
        seen = set()
        for n, msg, ctx in problems:
            if (n, ctx) in seen:
                continue
            seen.add((n, ctx))
            warns.append(f"数字 {n}：{msg}。…{ctx}…  → 算出来的写进 calc 清单；抄错、页码标错就改")
        for c in r.get("calc", []):
            print(f"· 算式：{c.get('n')} = {c.get('how', '（没写怎么算）')}")

    # ---------- 输出
    for e in errs:
        print("✗ " + e)
    for w in warns:
        print("⚠ " + w)
    if not errs and not warns:
        print("✓ 全部通过（数字是抽查，关键数字仍要回原文看）")
    elif not errs:
        print(f"✓ 没有必须改的；{len(warns)} 条提醒逐条看一眼")
    else:
        print(f"✗ {len(errs)} 处必须改，{len(warns)} 条提醒")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
