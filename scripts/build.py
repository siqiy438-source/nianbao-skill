#!/usr/bin/env python3
"""
把 report.json 排成 PDF（封面 + 正文，带书签和页码）。

用法：
  python3 build.py <report.json> <输出.pdf> [--preview <图片文件夹>]

  --preview  顺手把每一页存成 PNG，方便用 Read 一页页检查排版

report.json 的格式见 references/报告格式.md。
"""
import html
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

try:  # PyMuPDF：新版叫 pymupdf，旧版叫 fitz
    import pymupdf as fitz
except ImportError:
    import fitz

SKILL = Path(__file__).resolve().parent.parent
ASSETS = SKILL / "assets"

# 报告类型：默认年报；读半年报时在 meta 里写 "doc_short": "半年报", "doc_name": "半年度报告"
DOC_SHORT = "年报"
DOC_NAME = "年度报告"

# kami 的正文字体：仓耳今楷 W04（正文）/ W05（标题）。先找本 Skill 自带的，再找 kami Skill 里的；都没有就退到系统宋体
FONT_DIRS = [ASSETS / "fonts", Path.home() / ".claude/skills/kami/assets/fonts"]


def find_font(name):
    for d in FONT_DIRS:
        f = d / name
        if f.exists() and f.stat().st_size > 1_000_000:
            return f
    return None


FONT_W04 = find_font("TsangerJinKai02-W04.ttf")
FONT_W05 = find_font("TsangerJinKai02-W05.ttf") or FONT_W04
PARCHMENT = (0xf5 / 255, 0xf4 / 255, 0xed / 255)
STONE = (0x6b / 255, 0x6a / 255, 0x64 / 255)

KNOWN_BLOCKS = {"p", "h", "kpis", "chart", "cols", "table", "quote", "tip", "callout", "list",
                "flags", "compare", "verdict", "checkup", "pagebreak"}
CHART_KINDS = {"bar", "barh", "diverge", "line", "donut", "stack100"}


# ---------------------------------------------------------------- 文字小标记
def esc(s):
    return html.escape(str(s if s is not None else ""), quote=False)


def md(s):
    """**加粗**、==强调色==、[[+9.4%]] 涨跌色。其余原样转义。"""
    t = esc(s)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"==(.+?)==", r'<span class="hl">\1</span>', t)

    def delta(m):
        x = m.group(1).strip()
        cls = "up" if x[:1] in "+▲↑" else "down" if x[:1] in "-−▼↓" else "flat"
        return f'<span class="{cls}">{x}</span>'
    t = re.sub(r"\[\[(.+?)\]\]", delta, t)
    # 数字和紧跟的单位包在一起，不让换行拆开
    t = re.sub(r"(?<![\d.,A-Za-z])([+\-−]?\d[\d,]*(?:\.\d+)?\s?(?:万亿|亿元|亿台|亿|万人|万件|万台|万|倍|个百分点|%|个|期|台|家|名|人|天|年|元|页))",
               r'<span class="nb">\1</span>', t)
    return t


def src_span(src, prefix=None):
    if not src:
        return ""
    if prefix is None:
        prefix = DOC_SHORT
    s = str(src)
    if s.startswith("第"):
        s = prefix + s
    return f'<span class="src">{esc(s)}</span>'


def src_label(src):
    """图表、表格底下的来源：「第48页」→「来源：年报第48页」；「半年报第6页」→「来源：半年报第6页」；「计算」原样。"""
    if not src:
        return ""
    s = str(src)
    if s.startswith("第"):
        return f"来源：{DOC_SHORT}{esc(s)}"
    if re.search(r"第[\d–\-、,，]+页", s):
        return f"来源：{esc(s)}"
    return esc(s)


def dir_of(item):
    d = item.get("dir")
    if d:
        return d
    x = str(item.get("delta", "")).strip()
    return "up" if "+" in x[:4] or "▲" in x else "down" if ("−" in x[:4] or "-" in x[:4] or "▼" in x) else "flat"


# ---------------------------------------------------------------- 各种块
class Ctx:
    def __init__(self):
        self.charts = []
        self.fig_no = 0

    def chart_id(self):
        return f"c{len(self.charts) + 1}"


def b_p(b, ctx):
    return f'<p>{md(b["text"])}{(" " + src_span(b.get("src"))) if b.get("src") else ""}</p>'


def b_h(b, ctx):
    return f'<h3 class="sub">{md(b["text"])}{src_span(b.get("src"))}</h3>'


def b_kpis(b, ctx):
    items = b["items"]
    cols = b.get("cols") or min(4, len(items))
    out = [f'<div class="kpis c{cols}">']
    for it in items:
        delta = it.get("delta")
        d = f'<div class="delta {dir_of(it)}">{md(delta)}</div>' if delta else ""
        note = it.get("note", "")
        src = src_span(it.get("src"))
        n = f'<div class="note">{md(note)}{src}</div>' if (note or src) else ""
        unit = f'<span class="unit">{esc(it.get("unit", ""))}</span>' if it.get("unit") else ""
        out.append(f'<div class="kpi"><div class="label">{md(it["label"])}</div>'
                   f'<div class="value">{esc(it["value"])}{unit}</div>{d}{n}</div>')
    out.append("</div>")
    return "".join(out)


def b_chart(b, ctx):
    cid = ctx.chart_id()
    spec = {k: v for k, v in b.items() if k not in ("type", "title", "sub", "note", "src", "height")}
    spec["id"] = cid
    ctx.charts.append(spec)
    kind = b.get("kind")
    n = len(b.get("categories", []))
    default_h = {"barh": 26 * n + 16, "diverge": 26 * n + 12, "stack100": 44 * n + 40, "donut": 230}.get(kind, 210)
    h = b.get("height") or default_h
    title = ""
    if b.get("title"):  # 没标题的图（紧跟在小标题下面的）不编号
        ctx.fig_no += 1
        title = f'<div class="fig-title"><span class="fig-no">图 {ctx.fig_no}</span>{md(b["title"])}</div>'
    sub = f'<div class="fig-sub">{md(b.get("sub", ""))}</div>' if b.get("sub") else ""
    note = md(b.get("note", ""))
    srcs = src_label(b.get("src"))
    foot = f'<div class="fig-foot"><span>{note}</span><span>{srcs}</span></div>' if (note or srcs) else ""
    return f'<div class="fig">{title}{sub}<div class="chart" id="{cid}" style="height:{int(h)}px"></div>{foot}</div>'


def b_cols(b, ctx):
    inner = "".join(render_block(x, ctx) for x in b["items"])
    return f'<div class="cols2">{inner}</div>'


def b_table(b, ctx):
    head = b.get("head", [])
    align = b.get("align") or (["l"] + ["r"] * (len(head) - 1))
    em = set(b.get("em", []))
    cls = lambda i: {"r": ' class="r"', "c": ' class="c"'}.get(align[i] if i < len(align) else "l", "")
    rows = b.get("rows", [])
    short1 = rows and all(len(re.sub(r"[*=\[\]]", "", str(r[0]))) <= 8 for r in rows)
    widths = b.get("widths") or []
    wattr = lambda i: f' style="width:{widths[i]}"' if i < len(widths) and widths[i] else ""
    out = [f'<div class="tbl-wrap"><table class="tbl{" nowrap1" if short1 else ""}"><thead><tr>']
    out += [f"<th{cls(i)}{wattr(i)}>{md(h)}</th>" for i, h in enumerate(head)]
    out.append("</tr></thead><tbody>")
    for ri, row in enumerate(b.get("rows", [])):
        out.append(f'<tr{" class=\"em\"" if ri in em else ""}>')
        out += [f"<td{cls(i)}>{md(c)}</td>" for i, c in enumerate(row)]
        out.append("</tr>")
    out.append("</tbody></table>")
    note = b.get("note", "")
    srcs = src_label(b.get("src"))
    if note or srcs:
        out.append(f'<div class="tbl-foot"><span>{md(note)}</span><span>{srcs}</span></div>')
    out.append("</div>")
    return "".join(out)


def b_quote(b, ctx):
    return (f'<div class="quote"><div class="orig"><span class="tag">{DOC_SHORT}原话 {src_span(b.get("src"), "")}</span>'
            f'「{md(b["orig"])}」</div><div class="plain"><span class="tag">说人话</span>{md(b["plain"])}</div></div>')


def b_tip(b, ctx):
    tag = b.get("tag", "刘总读法")
    return f'<div class="tip"><span class="tag">{esc(tag)}</span>{md(b["text"])}</div>'


def b_callout(b, ctx):
    return f'<div class="callout"><div class="t">{md(b["title"])}</div><div class="x">{md(b.get("text", ""))}</div></div>'


def b_list(b, ctx):
    tag = "ol" if b.get("style") == "nums" else "ul"
    cls = "nums" if tag == "ol" else "dots"
    out = [f'<{tag} class="{cls}">']
    for it in b["items"]:
        if isinstance(it, dict):
            t = f'<span class="lt">{md(it.get("t", ""))}</span>' if it.get("t") else ""
            sep = "：" if it.get("t") and it.get("x") else ""
            out.append(f'<li>{t}{sep}{md(it.get("x", ""))}{src_span(it.get("src"))}</li>')
        else:
            out.append(f"<li>{md(it)}</li>")
    out.append(f"</{tag}>")
    return "".join(out)


LEVEL = {"要盯": "hi", "留意": "mid", "放心": "lo", "高": "hi", "中": "mid", "低": "lo",
         # 第 07 章「对答案」用：当时的担心 / 推测后来怎么样了
         "应验": "hi", "更差": "hi", "推错": "mid", "新情况": "mid", "对了": "lo", "好转": "lo", "待看": "lo",
         # 第二、三讲的体检表：过关 / 留意 / 危险；一页看懂的体检结论：过关 / 留意 / 有雷
         "过关": "lo", "危险": "hi", "有雷": "hi"}


def b_flags(b, ctx):
    out = ['<div class="flags">']
    for it in b["items"]:
        lv = it.get("level", "留意")
        ask = f'<div class="fq">调研可以问：{md(it["ask"])}</div>' if it.get("ask") else ""
        out.append(f'<div class="flag"><div class="lv {LEVEL.get(lv, "mid")}">{esc(lv)}</div><div>'
                   f'<div class="ft">{md(it["title"])} {src_span(it.get("src"))}</div>'
                   f'<div class="fx">{md(it.get("text", ""))}</div>{ask}</div></div>')
    out.append("</div>")
    return "".join(out)


VERD = {"做到了": "yes", "进行中": "part", "没做到": "no"}


def b_compare(b, ctx):
    out = ['<div class="tbl-wrap"><table class="tbl cmp"><thead><tr><th style="width:34%">公司说要做的</th>'
           f'<th>{DOC_SHORT}里交出的结果</th><th style="width:62px">判断</th></tr></thead><tbody>']
    for it in b["items"]:
        v = it.get("verdict", "进行中")
        out.append(f'<tr><td class="said">{md(it["said"])}</td><td>{md(it["did"])} {src_span(it.get("src"))}</td>'
                   f'<td class="v {VERD.get(v, "part")}">{esc(v)}</td></tr>')
    out.append("</tbody></table></div>")
    return "".join(out)


def b_verdict(b, ctx):
    items = "".join(
        f'<div class="vi"><div class="vl">{md(i["label"])}</div><div class="vv">{esc(i["value"])}</div>'
        f'<div class="vn">{md(i.get("note", ""))}</div></div>' for i in b.get("items", []))
    basis = b.get("basis", "")
    if isinstance(basis, list):
        basis = "<br>".join(md(x) for x in basis)
    else:
        basis = md(basis)
    return (f'<div class="verdict"><div class="vt">{md(b.get("title", "明年怎么看"))}</div>'
            f'<div class="vgrid">{items}</div><div class="vbasis">{basis}</div></div>')


def b_checkup(b, ctx):
    """体检表：查什么｜这家公司｜刘总的标准｜判断。第二、三讲的排雷、三张表、毛利率和 ROE 用。"""
    title = f'<div class="ck-title">{md(b["title"])}</div>' if b.get("title") else ""
    out = [f'<div class="ckup">{title}<table class="tbl ck"><thead><tr><th style="width:21%">查什么</th>'
           '<th>这家公司</th><th style="width:27%">刘总的标准</th><th style="width:48pt">判断</th></tr></thead><tbody>']
    for it in b.get("items", []):
        lv = it.get("level", "留意")
        note = f'<div class="cn">{md(it["note"])}</div>' if it.get("note") else ""
        out.append(f'<tr><td class="ci">{md(it.get("item", ""))}</td>'
                   f'<td><div class="cv">{md(str(it.get("value", "")))} {src_span(it.get("src"))}</div>{note}</td>'
                   f'<td class="cr">{md(it.get("rule", ""))}</td>'
                   f'<td><span class="lv {LEVEL.get(lv, "mid")}">{esc(lv)}</span></td></tr>')
    out.append("</tbody></table>")
    if b.get("note"):
        out.append(f'<div class="tbl-foot"><span>{md(b["note"])}</span><span></span></div>')
    out.append("</div>")
    return "".join(out)


def b_pagebreak(b, ctx):
    return '<div style="break-after: page"></div>'


RENDER = {"p": b_p, "h": b_h, "kpis": b_kpis, "chart": b_chart, "cols": b_cols, "table": b_table,
          "quote": b_quote, "tip": b_tip, "callout": b_callout, "list": b_list, "flags": b_flags,
          "compare": b_compare, "verdict": b_verdict, "checkup": b_checkup, "pagebreak": b_pagebreak}


def render_block(b, ctx):
    t = b.get("type")
    if t not in RENDER:
        raise SystemExit(f"✗ 不认识的块类型：{t}（可用：{', '.join(sorted(KNOWN_BLOCKS))}）")
    return RENDER[t](b, ctx)


# ---------------------------------------------------------------- 页面
def font_faces():
    if not FONT_W04:
        return ""
    return (f'<style>@font-face{{font-family:"TsangerJinKai02";src:url("{FONT_W04.as_uri()}") format("truetype");font-weight:400}}'
            f'@font-face{{font-family:"TsangerJinKai02";src:url("{FONT_W05.as_uri()}") format("truetype");font-weight:500}}</style>')


def page_html(body, charts, title):
    css = (ASSETS / "report.css").as_uri()
    ech = (ASSETS / "echarts.min.js").as_uri()
    cjs = (ASSETS / "charts.js").as_uri()
    specs = json.dumps(charts, ensure_ascii=False)
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{esc(title)}</title>
{font_faces()}<link rel="stylesheet" href="{css}"><script src="{ech}"></script><script src="{cjs}"></script></head>
<body>{body}
<script>
document.fonts.ready.then(() => window.renderCharts({specs})).then(() => {{ window.__ready = true; }})
  .catch(e => {{ document.title = 'ERR ' + e; window.__ready = true; }});
</script></body></html>"""


def cover_html(r):
    m, c = r["meta"], r["cover"]
    three = any(b.get("type") == "checkup" for ch in r.get("chapters", []) for b in ch.get("blocks", []))
    kick = "刘总《轻松读年报》三讲读法" if three else "第三节「管理层讨论与分析」"
    kp = "".join(
        f'<div class="ck"><div class="l">{md(k["label"])}</div><div class="v">{esc(k["value"])}'
        f'<span class="u">{esc(k.get("unit", ""))}</span></div><div class="d">{md(k.get("delta", ""))}</div></div>'
        for k in c.get("kpis", [])[:4])
    sub = f'<div class="headsub">{md(c["sub"])}</div>' if c.get("sub") else ""
    foot = (f'读法　{esc(m.get("method", "刘总《轻松读年报》第一讲"))}<br>资料　{esc(m.get("source", ""))}<br>'
            f'{esc(m.get("page_note", ""))}<br>整理于 {esc(m.get("made", ""))} · 对未来的判断是推测，不构成投资建议')
    body = f"""<div class="cover">
<div class="kick">{DOC_SHORT}精读 · {kick}</div>
<div class="co">{esc(m["company"])}</div>
<div class="yr">{esc(m["year"])} 年{DOC_NAME}</div>
<div class="code">{esc(m.get("code", ""))}</div>
<div class="head">{md(c["headline"])}</div>{sub}
<div class="ckpis">{kp}</div>
<div class="foot">{foot}</div></div>"""
    return page_html(body, [], m["company"])


def body_html(r):
    ctx = Ctx()
    parts = []
    s = r.get("summary")
    if s:
        qa = "".join(f'<div class="qa-row"><div class="qa-q"><span class="n">{i + 1}</span><span>{md(x["q"])}</span></div>'
                     f'<div class="qa-a">{md(x["a"])}</div></div>' for i, x in enumerate(s.get("qa", [])))
        extra = "".join(render_block(b, ctx) for b in s.get("blocks", []))
        ck = s.get("checkup")
        if ck:  # 第二、三讲的体检结论，一行
            extra = (f'<div class="ckline"><span class="lv {LEVEL.get(ck.get("level", "留意"), "mid")}">{esc(ck.get("level", "留意"))}</span>'
                     f'<span class="ckl">排雷和体检</span><span class="ckt">{md(ck.get("text", ""))}</span></div>') + extra
        watch = ""
        if s.get("watch"):
            cards = "".join(f'<div class="w"><div class="wt">{md(w["t"])}</div><div class="wx">{md(w.get("x", ""))}</div></div>'
                            for w in s["watch"][:3])
            watch = f'<div class="watch-title">{md(s.get("watch_title", "最要盯的三件事"))}</div><div class="watch">{cards}</div>'
        parts.append(f'<section class="summary"><div class="ch-head"><div class="ch-kicker">'
                     f'<span>{esc(s.get("kicker", "读完年报，要能回答这五个问题"))}</span></div>'
                     f'<h1 class="ch-title">{md(s.get("title", "一页看懂"))}</h1>'
                     f'{("<p class=ch-lead>" + md(s["lead"]) + "</p>") if s.get("lead") else ""}</div>'
                     f'<div class="qa">{qa}</div>{extra}{watch}</section>')
    for ci, ch in enumerate(r.get("chapters", [])):
        blocks = "".join(render_block(b, ctx) for b in ch.get("blocks", []))
        kicker = f'<span>{md(ch["kicker"])}</span>' if ch.get("kicker") else ""
        lead = f'<p class="ch-lead">{md(ch["lead"])}</p>' if ch.get("lead") else ""
        cls = "chapter first" if ci == 0 else ("chapter newpage" if ch.get("newpage") else "chapter")
        parts.append(f'<section class="{cls}"><div class="ch-head"><div class="ch-kicker"><span class="ch-num">{esc(ch.get("num", ""))}</span>'
                     f'{kicker}</div><h1 class="ch-title">{md(ch["title"])}</h1>{lead}</div>{blocks}</section>')
    g = r.get("glossary")
    if g:
        items = "".join(f'<div class="gl"><div class="gt">{md(x["term"])}</div><div class="gd">{md(x["plain"])}</div></div>' for x in g)
        parts.append(f'<section class="chapter newpage"><div class="ch-head"><div class="ch-kicker"><span class="ch-num">附录</span>'
                     f'<span>看不懂的词，来这里查</span></div><h1 class="ch-title">名词小词典</h1></div><div class="gloss">{items}</div>'
                     f'{("<div class=endnote>" + md(r["endnote"]) + "</div>") if r.get("endnote") else ""}</section>')
    return page_html("".join(parts), ctx.charts, r["meta"]["company"]), ctx.charts


# ---------------------------------------------------------------- 检查 report.json 的基本结构
def validate(r):
    errs = []
    for k in ("meta", "cover", "summary", "chapters"):
        if k not in r:
            errs.append(f"缺少顶层字段 {k}")
    if errs:
        return errs
    for k in ("company", "year"):
        if not r["meta"].get(k):
            errs.append(f"meta.{k} 没填")
    if not r["cover"].get("headline"):
        errs.append("cover.headline（封面一句话结论）没填")

    def walk(blocks, where):
        for i, b in enumerate(blocks):
            t = b.get("type")
            w = f"{where} 第{i + 1}块"
            if t not in KNOWN_BLOCKS:
                errs.append(f"{w}：不认识的类型 {t}")
                continue
            if t == "cols":
                walk(b.get("items", []), w + " 里")
            if t == "chart":
                kind = b.get("kind")
                if kind not in CHART_KINDS:
                    errs.append(f"{w}：图表类型 {kind} 不支持（可用 {', '.join(sorted(CHART_KINDS))}）")
                    continue
                cats = b.get("categories", [])
                for s in b.get("series", []):
                    if len(s.get("data", [])) != len(cats):
                        errs.append(f"{w}「{b.get('title', '')}」：系列「{s.get('name', '')}」有 {len(s.get('data', []))} 个数，"
                                    f"但分类有 {len(cats)} 个")
                    if any(not isinstance(x, (int, float)) for x in s.get("data", [])):
                        errs.append(f"{w}「{b.get('title', '')}」：数据里有非数字")
                if kind == "donut" and len(cats) > 6:
                    errs.append(f"{w}「{b.get('title', '')}」：环形图超过 6 块，请把小的合并成「其他」")
                if kind in ("bar", "line") and len(b.get("series", [])) > 4:
                    errs.append(f"{w}「{b.get('title', '')}」：系列超过 4 个，拆成两张图")
    walk(r["summary"].get("blocks", []), "一页看懂")
    for ch in r["chapters"]:
        walk(ch.get("blocks", []), f"「{ch.get('title', '')}」")
    return errs


# ---------------------------------------------------------------- 出 PDF
def render_pdf(html_path, pdf_path, cover=False):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            browser = p.chromium.launch(channel="chrome")
        # 画图时的页面宽度必须等于纸上正文的宽度（A4 宽 210mm − 左右边距 32mm = 178mm ≈ 672px），
        # 否则图表按屏幕宽度画好、打印时纸变窄，右边会被截掉
        width = 794 if cover else 658
        page = browser.new_page(viewport={"width": width, "height": 1123})
        page.emulate_media(media="print")
        page.goto(Path(html_path).as_uri())
        page.wait_for_function("window.__ready === true", timeout=60000)
        if page.title().startswith("ERR"):
            raise SystemExit("✗ 图表脚本出错：" + page.title())
        if cover:
            page.pdf(path=str(pdf_path), width="210mm", height="297mm", print_background=True,
                     margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        else:
            page.pdf(path=str(pdf_path), format="A4", print_background=True,
                     margin={"top": "16mm", "bottom": "18mm", "left": "18mm", "right": "18mm"},
                     outline=True, tagged=True)
        browser.close()


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    src, out = Path(args[0]), Path(args[1])
    preview = Path(args[args.index("--preview") + 1]) if "--preview" in args else None
    r = json.loads(src.read_text(encoding="utf-8"))
    global DOC_SHORT, DOC_NAME
    DOC_SHORT = r.get("meta", {}).get("doc_short", DOC_SHORT)
    DOC_NAME = r.get("meta", {}).get("doc_name", DOC_NAME)

    errs = validate(r)
    if errs:
        print("✗ report.json 有问题，先改：")
        for e in errs:
            print("  - " + e)
        sys.exit(2)

    work = Path(tempfile.mkdtemp(prefix="nianbao_"))
    (work / "cover.html").write_text(cover_html(r), encoding="utf-8")
    body, charts = body_html(r)
    (work / "body.html").write_text(body, encoding="utf-8")

    m = r["meta"]
    left = f'{m["company"]} {m["year"]} {DOC_SHORT}精读'
    render_pdf(work / "cover.html", work / "cover.pdf", cover=True)
    render_pdf(work / "body.html", work / "body.pdf")

    doc = fitz.open(work / "cover.pdf")
    bodydoc = fitz.open(work / "body.pdf")
    btoc = [t for t in bodydoc.get_toc() if t[0] == 1]
    doc.insert_pdf(bodydoc)
    font = fitz.Font(fontfile=str(FONT_W04)) if FONT_W04 else fitz.Font("china-ss")
    for i, pg in enumerate(doc):
        pg.draw_rect(pg.rect, color=None, fill=PARCHMENT, overlay=False)
        if i == 0:
            continue
        text = f"{i + 1}  ·  {left}"
        w = font.text_length(text, fontsize=8.5)
        kw = {"fontfile": str(FONT_W04), "fontname": "tjk"} if FONT_W04 else {"fontname": "china-ss"}
        pg.insert_text(((pg.rect.width - w) / 2, pg.rect.height - 9.5 * 72 / 25.4), text, fontsize=8.5, color=STONE, **kw)
    doc.subset_fonts()
    doc.set_toc([[1, "封面", 1]] + [[1, t[1], t[2] + 1] for t in btoc])
    doc.set_metadata({"title": f'{m["company"]} {m["year"]} {DOC_SHORT} · 精读', "author": f"{DOC_SHORT}精读",
                      "subject": "管理层讨论与分析 精读", "creator": "nianbao skill"})
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out, garbage=3, deflate=True)
    n = doc.page_count

    print(f"✓ 已生成：{out}（共 {n} 页，{len(charts)} 张图）")
    for t in [[1, "封面", 1]] + [[1, t[1], t[2] + 1] for t in btoc]:
        print(f"  第{t[2]:>2}页  {t[1]}")
    three = any(b.get("type") == "checkup" for ch in r.get("chapters", []) for b in ch.get("blocks", []))
    limit = 22 if three else 16   # 三讲的报告多了排雷、三张表、毛利率和 ROE 三章
    if n > limit:
        print(f"⚠ 超过 {limit} 页，偏长：删掉重复的话，或把次要的图并到一起")
    if preview:
        preview.mkdir(parents=True, exist_ok=True)
        for f in preview.glob("p*.png"):
            f.unlink()
        for i, pg in enumerate(doc):
            pg.get_pixmap(dpi=110).save(preview / f"p{i + 1:02d}.png")
        print(f"  预览图：{preview}/p01.png … p{n:02d}.png")
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
