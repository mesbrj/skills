#!/usr/bin/env python3
"""GFM -> Notion-flavored Markdown for mirroring a repo folder into Notion.

    md2notion.py docs out/ --repo /path/to/repo

Converts what Notion does not read natively, or reads wrongly:
  * GFM pipe tables -> <table>/<tr>/<td> XML
  * repo-relative / absolute-path links -> inline code paths (they cannot resolve in Notion)
  * unfenced ASCII box diagrams -> fenced, so they keep their alignment
  * hard-wrapped > blockquotes -> one quote block instead of a stack of them
  * autolink bait (bare filenames, paths, hostnames, file:line) -> inline code
  * "` + " inside a table cell -> "` `+` ", which Notion would otherwise render as a bullet
  * **bold** spanning two hard-wrapped lines -> re-closed per line, which Notion keeps
Fenced code blocks are passed through untouched.
"""
import argparse
import json
import os
import re
import pathlib


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("src", help="folder to mirror, relative to --repo (e.g. docs, .specs)")
    p.add_argument("out", help="directory for the converted chunks + manifest.json")
    p.add_argument("--repo", default=".", help="repository root (default: cwd)")
    p.add_argument(
        "--chunk-limit", type=int, default=35000,
        help="max characters per output chunk (default: 35000)",
    )
    return p.parse_args()


_args = parse_args()
REPO = pathlib.Path(_args.repo).resolve()
SRC = REPO / _args.src
OUT = pathlib.Path(_args.out)
CHUNK_LIMIT = _args.chunk_limit

FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
SEP_RE = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")
LINK_RE = re.compile(r"\[([^\]\[]*)\]\(([^)\s]+)\)")
LINENO_RE = re.compile(r"[:#]L?\d+(?:[-–]L?\d+)?$")
# file extensions that are also real TLDs, so Notion linkifies them
FILE_EXT = "md|sh|so|py|go|rs|ts|pl|io|co|ai|it|is|me|tv|ly|to|cc|ws|fm"
# bare filenames whose extension is a real TLD get linkified by Notion
FILE_TOKEN_RE = re.compile(
    r"(?<![\w./`-])([A-Za-z0-9][\w-]*\.(?:%s)(?:\.\d+)*)(?![\w`]|\.\w)" % FILE_EXT
)
# the same filename reached through a path: `.specs/STATE.md`, `scripts/lessons.py`.
# FILE_TOKEN_RE's lookbehind rejects these, so they need their own (longer-first) pass.
PATH_TOKEN_RE = re.compile(
    r"(?<![\w`-])((?:\.{0,2}[\w.-]*/)+[A-Za-z0-9][\w-]*\.(?:%s)(?:\.\d+)*)(?![\w`]|\.\w)" % FILE_EXT
)
# bare hostnames in prose: Notion turns these into real (usually useless) links
HOST_TOKEN_RE = re.compile(
    r"(?<![\w./`-])((?:[A-Za-z0-9][\w-]*\.)+(?:com|org|net|dev|gcr\.io)"
    r"(?:/[\w./-]*[\w/-])?|localhost)(?![\w`-])"
)


# An inline code span may itself contain backticks when it is opened with a longer
# delimiter run (`` `grep -c '```' README.md` ``). A naive `[^`]*` split cuts such a span
# in half and then "protects" tokens that were already inside code, producing nested
# backticks. Match the opening run and require the same run to close it. The backreference
# must be exactly as long as the opener, so a ``` run never closes a ` span. The
# backreference needs a capturing group, so walk the matches instead of re.split.
SPAN_RE = re.compile(
    r"(?<![`\\])(`+)(?:(?!(?<![`\\])\1(?!`)).)*?(?<![`\\])\1(?!`)"  # span, closed by an equal run
    r"|\[[^\]]*\]\([^)]*\)"                            # markdown link
)



def segments(text):
    """Split into (is_code, text) segments so code fences stay verbatim."""
    segs, buf, fence = [], [], None
    for line in text.split("\n"):
        if fence is None:
            m = FENCE_RE.match(line)
            if m:
                segs.append((False, "\n".join(buf)))
                buf, fence = [line], m.group(1)[0] * 3
                continue
            buf.append(line)
        else:
            buf.append(line)
            if line.strip().startswith(fence) and line.strip().rstrip("`~") == "":
                segs.append((True, "\n".join(buf)))
                buf, fence = [], None
    segs.append((fence is not None, "\n".join(buf)))
    return segs


def split_cells(line):
    """Split a pipe-table row, ignoring | inside inline code or escaped with \\."""
    s = line.strip()
    cells, cur, i = [], [], 0
    if s.startswith("|"):
        s = s[1:]
    # a | inside an inline code span is content, not a cell boundary. Mask the spans
    # first: naive backtick toggling miscounts a span opened with a longer run.
    incode = bytearray(len(s))
    for m in SPAN_RE.finditer(s):
        if m.group(0).startswith("`"):
            for j in range(m.start(), m.end()):
                incode[j] = 1
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            # only \| is a cell escape; every other backslash is literal content
            if s[i + 1] == "|":
                cur.append("|")
            else:
                cur.append(c)
                cur.append(s[i + 1])
            i += 2
            continue
        if c == "|" and not incode[i]:
            cells.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    last = "".join(cur)
    if last.strip() or not cells:
        cells.append(last)
    return [c.strip() for c in cells]


def cell_text(c):
    return re.sub(r"<br\s*/?>", "<br>", c)


def table_xml(rows, has_header):
    out = ['<table fit-page-width="true" header-row="%s">' % ("true" if has_header else "false")]
    width = max(len(r) for r in rows)
    for row in rows:
        out.append("\t<tr>")
        for i in range(width):
            out.append("\t\t<td>%s</td>" % cell_text(row[i] if i < len(row) else ""))
        out.append("\t</tr>")
    out.append("</table>")
    return "\n".join(out)


def convert_tables(text):
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("|") and i + 1 < len(lines) and SEP_RE.match(lines[i + 1]) \
                and "|" in lines[i + 1]:
            rows = [split_cells(line)]
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(split_cells(lines[i]))
                i += 1
            out.append(table_xml(rows, True))
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def norm_path(url, srcdir):
    frag = ""
    if "#" in url:
        url, frag = url.split("#", 1)
        frag = "#" + frag
    if url.startswith(str(REPO) + "/"):
        p = url[len(str(REPO)) + 1:]
    elif url.startswith("/"):
        p = url.lstrip("/")
    else:
        p = os.path.normpath(os.path.join(srcdir, url))
    return p, frag


def convert_links(text, srcdir):
    def repl(m):
        label, url = m.group(1), m.group(2)
        if url.startswith(("http://", "https://", "mailto:", "#")):
            return m.group(0)
        p, frag = norm_path(url, srcdir)
        t = label.strip("`")
        core = LINENO_RE.sub("", t)
        base = os.path.basename(p)
        if core == p or core == base or core.endswith("/" + base) or p.endswith("/" + core):
            return "`%s`" % t
        return "%s (`%s`)" % (label, p + frag)

    return LINK_RE.sub(repl, text)


def merge_quotes(text):
    """Consecutive > lines render as separate quote blocks in Notion; join with <br>."""
    out, run = [], []
    for line in text.split("\n"):
        if line.startswith(">"):
            run.append(line[1:].strip())
            continue
        if run:
            out.append("> " + "<br>".join(run))
            run = []
        out.append(line)
    if run:
        out.append("> " + "<br>".join(run))
    return "\n".join(out)


def flatten_backtick_spans(text):
    """Notion cannot store an inline code span that itself contains backticks.

    Every delimiter length it accepts (1, 4, escaped) still ends the span at the inner
    backtick, which then swallows the following text into a stray span. Drop the span
    and escape its backticks instead: the characters survive verbatim, and any file
    token inside is still protected separately by protect_autolinks.
    """
    out = []
    for line in text.split("\n"):
        buf, pos = [], 0
        for m in SPAN_RE.finditer(line):
            span = m.group(0)
            if span.startswith("`") and m.group(1) and "`" in span[len(m.group(1)):-len(m.group(1))]:
                inner = span[len(m.group(1)):-len(m.group(1))]
                span = inner.replace("`", "\\`")
            buf.append(line[pos:m.start()])
            buf.append(span)
            pos = m.end()
        buf.append(line[pos:])
        out.append("".join(buf))
    return "\n".join(out)


def protect_autolinks(text):
    """Notion linkifies bare scheme-like tokens (file:line); backticks stop it."""
    def protect(s):
        s = re.sub(r"(?<!`)\b([Ff]ile:line)\b(?!`)", r"`\1`", s)
        s = PATH_TOKEN_RE.sub(r"`\1`", s)
        s = FILE_TOKEN_RE.sub(r"`\1`", s)
        return HOST_TOKEN_RE.sub(r"`\1`", s)

    out = []
    for line in text.split("\n"):
        buf, pos = [], 0
        for m in SPAN_RE.finditer(line):
            buf.append(protect(line[pos:m.start()]))  # outside any span
            buf.append(m.group(0))                    # code span / link, verbatim
            pos = m.end()
        buf.append(protect(line[pos:]))
        out.append("".join(buf))
    return "\n".join(out)


ART_RE = re.compile(
    r"\+-{2,}|-{2,}[>]|[<]-{2,}|^\s*[|v^]\s*$|[\u2500\u2502\u250c\u2514\u251c"
    r"\u2510\u2518\u2524\u252c\u2534\u25ba]"
)


def fence_ascii_art(text):
    """Unfenced box diagrams lose their alignment in Notion's proportional font."""
    blocks, cur = [], []
    for line in text.split("\n"):
        if line.strip():
            cur.append(line)
            continue
        blocks.append(cur)
        blocks.append(None)  # blank-line separator
        cur = []
    blocks.append(cur)

    def is_art(b):
        return bool(b) and sum(1 for l in b if ART_RE.search(l)) * 2 >= len(b)

    out, i = [], 0
    while i < len(blocks):
        b = blocks[i]
        if is_art(b):
            run = list(b)
            i += 1
            # absorb a single blank line when more art follows (split box borders)
            while i + 1 < len(blocks) and blocks[i] is None and is_art(blocks[i + 1]):
                run.append("")
                run.extend(blocks[i + 1])
                i += 2
            out.append("```text\n" + "\n".join(run) + "\n```")
            continue
        out.append("" if b is None else "\n".join(b))
        i += 1
    return "\n".join(out)


# Notion's table-cell parser turns "` + " (code-span close, space, plus, space) into a
# bullet glyph. Backticking the plus is the only form that survives with spacing intact:
# backslash escapes, &#43; and non-breaking/zero-width spaces are all normalised away first.
PLUS_AFTER_CODE_RE = re.compile(r"(?<=`) \+ ")


def fix_plus_after_code(text):
    out = []
    for line in text.split("\n"):
        if line.lstrip().startswith(("<td>", "<tr", "<table", "</table")):
            line = PLUS_AFTER_CODE_RE.sub(" `+` ", line)
        out.append(line)
    return "\n".join(out)


def bold_per_line(par):
    """Notion drops **emphasis** that opens and closes on different source lines.

    Re-close and re-open it on each line so hard-wrapped prose keeps both the wrapping
    and the bold. The reopening marker goes after the line's indent: `**` only counts
    as emphasis when it abuts a non-space character.
    """
    out, bold = [], False
    for line in par.split("\n"):
        indent = line[:len(line) - len(line.lstrip())]
        body = line[len(indent):]
        if not body:
            out.append(line)
            continue
        opened = bold
        tick, i = False, 0
        while i < len(body):
            if body[i] == "`":
                tick = not tick
                i += 1
                continue
            if not tick and body.startswith("**", i):
                bold = not bold
                i += 2
                continue
            i += 1
        if opened:
            body = "**" + body
        if bold:
            body = body.rstrip() + "**"
        out.append(indent + body)
    return "\n".join(out)


def fix_bold_across_lines(text):
    """Apply bold_per_line to each paragraph, leaving table XML alone."""
    blocks, cur, intable = [], [], False
    for line in text.split("\n"):
        if line.startswith("<table"):
            intable = True
        if intable or not line.strip():
            if cur:
                blocks.append(bold_per_line("\n".join(cur)))
                cur = []
            blocks.append(line)
            if line.startswith("</table>"):
                intable = False
            continue
        cur.append(line)
    if cur:
        blocks.append(bold_per_line("\n".join(cur)))
    return "\n".join(blocks)


def convert(path):
    raw = path.read_text()
    srcdir = str(path.parent.relative_to(REPO))
    parts = []
    for is_code, seg in segments(raw):
        if is_code:
            parts.append(seg)
        else:
            seg = merge_quotes(protect_autolinks(flatten_backtick_spans(convert_links(convert_tables(seg), srcdir))))
            parts.append(fix_bold_across_lines(fix_plus_after_code(fence_ascii_art(seg))))
    text = "\n".join(parts)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def chunk(text):
    """Split at top-level block boundaries, never inside a code fence or table."""
    blocks, cur, fence, intable = [], [], None, False
    for line in text.split("\n"):
        cur.append(line)
        if fence is None:
            m = FENCE_RE.match(line)
            if m:
                fence = m.group(1)[0] * 3
                continue
            if line.startswith("<table"):
                intable = True
            elif line.startswith("</table>"):
                intable = False
                blocks.append("\n".join(cur)); cur = []
            elif not intable and line.strip() == "":
                blocks.append("\n".join(cur)); cur = []
        elif line.strip().startswith(fence) and line.strip().rstrip("`~") == "":
            fence = None
            blocks.append("\n".join(cur)); cur = []
    if cur:
        blocks.append("\n".join(cur))

    chunks, buf = [], ""
    for b in blocks:
        if buf and len(buf) + len(b) + 1 > CHUNK_LIMIT:
            chunks.append(buf.rstrip("\n"))
            buf = ""
        buf += b + "\n"
    if buf.strip():
        chunks.append(buf.rstrip("\n"))
    return chunks


OUT.mkdir(parents=True, exist_ok=True)

manifest = []
for src in sorted(SRC.rglob("*")):
    if not src.is_file():
        continue
    rel = src.relative_to(SRC)
    if src.suffix == ".md":
        body = convert(src)
    else:
        body = "```json\n%s\n```\n" % src.read_text().rstrip("\n")
    chunks = chunk(body)
    slug = str(rel).replace("/", "__")
    paths = []
    for n, c in enumerate(chunks):
        f = OUT / ("%s.%02d.md" % (slug, n))
        f.write_text(c)
        paths.append(str(f))
    manifest.append({"rel": str(rel), "name": rel.name, "dir": str(rel.parent),
                     "bytes": len(body), "chunks": paths})

(OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
for m in manifest:
    print("%-52s %7d bytes  %d chunk(s)" % (m["rel"], m["bytes"], len(m["chunks"])))
