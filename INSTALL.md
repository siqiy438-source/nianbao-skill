# 安装 nianbao（给 AI agent 看的安装说明）

适用于 **Claude Code** 和 **Codex**，系统是 macOS 或 Linux（Windows 请在 WSL 里装）。

## 一步装好（推荐）

```bash
rm -rf /tmp/nianbao-skill && git clone --depth 1 https://github.com/siqiy438-source/nianbao-skill.git /tmp/nianbao-skill && bash /tmp/nianbao-skill/install.sh
```

`install.sh` 会做这些事：

1. 电脑上有 Claude Code（`~/.claude`），就装到 `~/.claude/skills/nianbao`；有 Codex（`$CODEX_HOME`，默认 `~/.codex`），就装到 `$CODEX_HOME/skills/nianbao`。两个都有就都装。
2. 目标文件夹已经存在、又不是从这个仓库装的，**不会覆盖**，会提示出来；这时请先问用户怎么处理。
3. 把 Python 依赖（PyMuPDF、Playwright 和它的 Chromium）装进单独的环境 `~/.nianbao/venv`，不动系统的 Python。第一次要下载几分钟。
4. 试排一份范例报告，看到「✓ 已生成」就说明装好了。

装完告诉用户：**新开一个对话**，skill 才会出现。

## 手动安装（install.sh 跑不了时）

1. 把仓库 clone 到 skill 目录：
   - Claude Code：`~/.claude/skills/nianbao`
   - Codex：`${CODEX_HOME:-~/.codex}/skills/nianbao`
2. 装依赖：
   ```bash
   python3 -m venv ~/.nianbao/venv
   ~/.nianbao/venv/bin/python -m pip install pymupdf playwright
   ~/.nianbao/venv/bin/python -m playwright install chromium
   ```
3. 验证（`<skill 目录>` 换成第 1 步的路径）：
   ```bash
   bash <skill 目录>/run.sh build <skill 目录>/references/示例-美的2024.json /tmp/nianbao测试.pdf
   ```
   看到「✓ 已生成」就装好了。

## 怎么用

- Claude Code：输入 `/nianbao`，再把年报 PDF 拖进来。
- Codex：说「用 nianbao 读这份年报」，再给出年报 PDF 的路径。

年报全文去巨潮资讯网 cninfo.com.cn 下载，要全文版，不要摘要版。

## 常见问题

- **提示没有 git 或 python3**：macOS 上运行 `xcode-select --install`，装完再跑一次。
- **Chromium 下载失败或很慢**：网络问题，重新跑一次 `install.sh` 就行，已经装好的部分会跳过。
- **报告字体和截图不一样**：正文字体「仓耳今楷」有授权限制，仓库里不带。没有它会自动换成思源宋体或系统宋体，不影响使用。想要一样的效果，可以把 `TsangerJinKai02-W04.ttf`、`TsangerJinKai02-W05.ttf` 放进 `<skill 目录>/assets/fonts/`。

## 更新和卸载

- 更新：再跑一次上面「一步装好」那行命令。
- 卸载：删掉 skill 目录（`~/.claude/skills/nianbao` 和/或 `~/.codex/skills/nianbao`）和 `~/.nianbao`。
