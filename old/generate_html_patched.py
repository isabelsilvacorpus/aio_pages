#!/usr/bin/env python3
import argparse
import csv
import html
import re
import os
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

from urllib.parse import urlparse, unquote

def _favicon_url(source_url: str, root_domain: str) -> str:
    host = ""
    if source_url:
        try:
            host = urlparse(source_url).netloc
        except Exception:
            host = ""
    if not host:
        host = (root_domain or "").strip()
    host = host.lstrip("www.")
    if not host:
        return ""
    # what Google uses in the saved page for favicons
    return f"https://encrypted-tbn2.gstatic.com/faviconV2?url=https://{host}&client=AIM&size=128&type=FAVICON&fallback_opts=TYPE,SIZE,URL"

def populate_and_show_sources_panel(soup: BeautifulSoup, sources: list[dict]) -> None:
    # Sources live in the "corroboration" panel in this template
    panel = soup.select_one('div.wDa0n[role="dialog"]')
    if panel is None:
        return

    # 1) Force it visible (template has display:none)
    style = panel.get("style", "")
    if "display:none" in style.replace(" ", ""):
        style = re.sub(r"display\s*:\s*none\s*;?", "display:block;", style)
    if "display:" not in style.replace(" ", ""):
        style = (style + ";" if style and not style.endswith(";") else style) + "display:block;"
    panel["style"] = style

    # 2) Find the list and a template <li> to clone (so formatting stays exact)
    ul = panel.select_one("ul.bTFeG")
    if ul is None:
        return
    li_template = ul.select_one("li.CyMdWb")
    if li_template is None:
        return

    ul.clear()

    for s in sources:
        li = BeautifulSoup(str(li_template), "html.parser").select_one("li.CyMdWb")

        title = (s.get("source_title") or s.get("source_name") or s.get("root_domain") or "Source").strip()
        snippet = (s.get("source_text") or "").strip()
        url = (s.get("source_url") or "").strip()
        root_domain = (s.get("root_domain") or "").strip()

        a = li.select_one("a.NDNGvf")
        if a is not None:
            # keep NDNGvf structure but disable navigation if you want
            a["href"] = url if url else "#"
            a["target"] = "_blank"
            a["rel"] = "noopener"
            a["aria-label"] = f"{title}. Opens in new tab."
            if not url:
                a["onclick"] = "return false"

        t = li.select_one(".Nn35F")
        if t is not None:
            t.string = title

        sn = li.select_one(".vhJ6Pe")
        if sn is not None:
            if snippet:
                sn.string = snippet
            else:
                sn.decompose()

        img = li.select_one("img.sGgDgb")
        if img is not None:
            fav = _favicon_url(url, root_domain)
            if fav:
                img["src"] = fav

        ul.append(li)

def populate_sources_list(soup: BeautifulSoup, sources: list[dict]) -> bool:
    ul = soup.select_one('div.wDa0n[role="dialog"] ul.bTFeG') or soup.select_one("ul.bTFeG")
    if ul is None:
        return False

    li_template = ul.select_one("li.CyMdWb")
    if li_template is None:
        return False

    # Clear existing lis
    ul.clear()

    for idx, s in enumerate(sources, start=1):
        li = BeautifulSoup(str(li_template), "html.parser").select_one("li.CyMdWb")

        title = (s.get("source_title") or s.get("source_name") or s.get("root_domain") or "Source").strip()
        snippet = (s.get("source_text") or "").strip()
        url = (s.get("source_url") or "").strip()

        # Anchor overlay (NDNGvf)
        a = li.select_one("a.NDNGvf")
        if a is not None:
            # keep styling attributes; just neutralize navigation if you want
            a["href"] = url if url else "#"
            a["target"] = "_blank"
            a["rel"] = "noopener"
            a["aria-label"] = f"{title}. Opens in new tab."
            if not url:
                a["onclick"] = "return false"

        # Title
        t = li.select_one(".Nn35F")
        if t is not None:
            t.string = title

        # Snippet
        sn = li.select_one(".vhJ6Pe")
        if sn is not None:
            if snippet:
                sn.string = snippet
            else:
                sn.decompose()

        # Optional: favicon (you can leave the template’s img alone; or replace src)
        # img = li.select_one("img.sGgDgb")
        # if img is not None:
        #     fav = _favicon_url(url, (s.get("root_domain") or "").strip())
        #     if fav:
        #         img["src"] = fav

        ul.append(li)

    return True

def read_csv_dicts(path: Path):
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def sanitize_filename(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s)
    return s[:180] if len(s) > 180 else s


def build_aio_html(aio_text: str) -> str:
    aio_text = (aio_text or "").strip()
    parts: list[str] = []

    if aio_text:
        paras = re.split(r"\n\s*\n+", aio_text)
        for p in paras:
            p = p.strip()
            if not p:
                continue
            esc = html.escape(p).replace("\n", "<br/>")
            parts.append(f"<p>{esc}</p>")
    else:
        parts.append("<p><em>(No AI Overview text found for this row.)</em></p>")

    # Keep Google’s body wrapper for typography
    return f'<div class="LT6XE">{"".join(parts)}</div>'



def set_query_fields(soup: BeautifulSoup, query: str):
    query = (query or "").strip()
    if not query:
        return

    if soup.title is not None:
        soup.title.string = f"{query} - Google Search"

    q_input = soup.find("input", attrs={"name": "q"})
    if q_input is not None:
        q_input["value"] = query


def replace_aio_container(soup: BeautifulSoup, aio_body_html: str, sources: list[dict]) -> bool:
    root = soup.find(id="m-x-content")
    if root is None:
        return False

    body_target = root.select_one("div.jloFI") or root.select_one("div.LT6XE")
    if body_target is not None:
        body_target.clear()
        frag = BeautifulSoup(aio_body_html, "html.parser")
        for node in list(frag.contents):
            body_target.append(node)

    populate_and_show_sources_panel(soup, sources)
    return True


def rewrite_local_asset_links(soup: BeautifulSoup, rel_assets_prefix: str):
    """Rewrite file:///... and /Users/... asset URLs to a repo-relative assets folder."""
    if not rel_assets_prefix:
        rel_assets_prefix = "."

    def _rewrite(val: str):
        if not val:
            return None
        v = str(val).strip()
        path_str = None

        if v.startswith("file://"):
            parsed = urlparse(v)
            path_str = unquote(parsed.path or "")
        elif v.startswith("/Users/") or v.startswith("/users/"):
            path_str = v
        else:
            return None

        if not path_str:
            return None

        p = Path(path_str)
        parts = p.parts

        # Prefer preserving subpaths after a *_files directory
        idx = None
        for i, part in enumerate(parts):
            if part.endswith("_files"):
                idx = i
                break

        if idx is not None and idx + 1 < len(parts):
            rel = Path(*parts[idx + 1 :])
        else:
            rel = Path(p.name)

        return f"{rel_assets_prefix.rstrip('/')}/{rel.as_posix()}"

    for tag in soup.find_all(True):
        for attr in ("src", "href"):
            if tag.has_attr(attr):
                repl = _rewrite(tag.get(attr))
                if repl:
                    tag[attr] = repl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="aio_template.html")
    ap.add_argument("--retrievals", default="sample_data/retrievals.csv")
    ap.add_argument("--sources", default="sample_data/aio_sources.csv")
    ap.add_argument("--outdir", default="out")  # ensure out/aio_assets exists (you moved it)
    ap.add_argument("--limit", type=int, default=0, help="0 = no limit")
    args = ap.parse_args()

    template_path = Path(args.template)
    retrievals_path = Path(args.retrievals)
    sources_path = Path(args.sources)
    outdir = Path(args.outdir)

    # Asset folder lives next to this script
    script_dir = Path(__file__).resolve().parent
    assets_dir = script_dir / "html_asset_files"
    rel_assets_prefix = Path(os.path.relpath(assets_dir, outdir)).as_posix()
    outdir.mkdir(parents=True, exist_ok=True)

    template_html = template_path.read_text("utf-8", errors="ignore")

    retrieval_rows = read_csv_dicts(retrievals_path)
    source_rows = read_csv_dicts(sources_path)

    grouped_sources: dict[str, list[dict]] = defaultdict(list)
    for r in source_rows:
        rid = (r.get("retrieval_id") or "").strip()
        if rid:
            grouped_sources[rid].append(r)

    def sort_key(s: dict):
        for k in ("source_rank", "rank"):
            v = (s.get(k) or "").strip()
            if v.isdigit():
                return int(v)
        return 10**9

    for rid in list(grouped_sources.keys()):
        grouped_sources[rid].sort(key=sort_key)

    written = 0
    for row in retrieval_rows:
        rid = (row.get("retrieval_id") or "").strip()
        if not rid:
            continue

        soup = BeautifulSoup(template_html, "html.parser")
        rewrite_local_asset_links(soup, rel_assets_prefix)

        query = row.get("query") or ""
        aio_text = row.get("aio_text") or ""
        sources_for_rid = grouped_sources.get(rid, [])

        set_query_fields(soup, query)

        aio_html = build_aio_html(aio_text)
        ok = replace_aio_container(soup, aio_html, sources_for_rid)
        if not ok:
            (soup.body or soup).append(BeautifulSoup(f"<div>{aio_html}</div>", "html.parser"))

        out_path = outdir / f"{sanitize_filename(rid)}.html"
        out_path.write_text(str(soup), "utf-8")

        written += 1
        if args.limit and written >= args.limit:
            break

    print(f"Wrote {written} HTML files to: {outdir.resolve()}")


if __name__ == "__main__":
    main()
