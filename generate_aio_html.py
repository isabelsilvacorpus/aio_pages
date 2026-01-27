#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import re
from pathlib import Path
from typing import List, Optional
from html import unescape


import pandas as pd
from bs4 import BeautifulSoup, NavigableString, Tag

ASSET_FOLDER_NAME = "html_asset_files"
TEXT_COL = "formatted_text"

def _format_query_from_row(row) -> str:
    q = str(row.get("query", "")).strip()
    q = q.replace("COUNTYSEAT", str(row.get("CountySeat", "")).strip())
    q = q.replace("STATE", str(row.get("State", "")).strip())
    return q


def _replace_search_bar_query(soup: BeautifulSoup, query: str) -> None:
    # Search bar
    ta = soup.find("textarea", id="APjFqb")
    if ta is not None:
        ta["value"] = query
        ta.string = query

    # Page title
    title = soup.find("title")
    if title and title.string:
        title.string = re.sub(r"^.*(?= - Google Search$)", query, title.string)

def _fix_asset_paths(raw_html: str) -> str:
    raw_html = raw_html.replace("_files/", f"{ASSET_FOLDER_NAME}/")
    raw_html = re.sub(r'(?i)\bfile:///', "", raw_html)
    return raw_html


def _split_aio_text(aio_text: str, max_items: int = 8) -> List[str]:
    if not isinstance(aio_text, str):
        return []
    chunks = [c.strip() for c in re.split(r"\r?\n+", aio_text) if c.strip()]
    if len(chunks) >= 2:
        return chunks[:max_items]

    s = aio_text.strip()
    if not s:
        return []
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", s) if p.strip()]

    out: List[str] = []
    buf = ""
    for p in parts:
        if not buf:
            buf = p
        elif len(buf) < 140:
            buf = f"{buf} {p}"
        else:
            out.append(buf)
            buf = p
        if len(out) >= max_items - 1:
            break
    if buf and len(out) < max_items:
        out.append(buf)
    return out[:max_items]


def _find_aio_overview_list(aio_container: Tag) -> Optional[Tag]:
    return aio_container.find("ol", class_=lambda c: c and "IaGLZe" in c)


def _replace_aio_overview(soup: BeautifulSoup, aio_container: Tag, aio_text: str) -> None:
    """
    Replace the entire AI Overview body with non-enumerated text.
    - Clears the template's sample content (frog paragraph, headings, etc.)
    - Renders aio_text as paragraphs
    - Treats lines ending with ':' as section headers (bold)
    """
    body = aio_container.select_one("div.mZJni.Dn7Fzd")
    if body is None:
        raise RuntimeError("Could not locate AI Overview body (div.mZJni.Dn7Fzd) in the template.")

    body.clear()  # removes the frog template text and all its sections

    if not isinstance(aio_text, str) or not aio_text.strip():
        p = soup.new_tag("p")
        p["class"] = ["T286Pc"]
        p.string = "(No AI Overview text available for this row.)"
        body.append(p)
        return

    # Split into blocks by blank lines; within a block, keep single newlines as line breaks.
    blocks = [b.strip() for b in re.split(r"\r?\n\s*\r?\n", aio_text.strip()) if b.strip()]

    for b in blocks:
        lines = [ln.strip() for ln in re.split(r"\r?\n", b) if ln.strip()]

        # If it's a short line ending with ":" treat as a header
        if len(lines) == 1 and lines[0].endswith(":") and len(lines[0]) <= 80:
            h = soup.new_tag("div")
            h["class"] = ["T286Pc"]
            strong = soup.new_tag("strong")
            strong.string = lines[0]
            h.append(strong)
            body.append(h)
            continue

        p = soup.new_tag("p")
        p["class"] = ["T286Pc"]

        # Keep line breaks inside the paragraph
        for i, ln in enumerate(lines):
            if i:
                p.append(soup.new_tag("br"))

            ln_html = unescape(ln)
            frag = BeautifulSoup(ln_html, "html.parser")

            # safer: drop scripts/styles first
            for t in frag(["script", "style"]):
                t.decompose()

            # Force all injected elements to inherit typography from the parent container
            for t in frag.find_all(True):
                if t.name in {"ul", "ol", "li"}:
                    continue
                style = t.get("style", "")
                if style and not style.strip().endswith(";"):
                    style += ";"
                style += "font-family: inherit; font-size: inherit; font-style: inherit; line-height: inherit; color: inherit;"
                t["style"] = style
            for t in frag.find_all(["ul", "ol"]):
                style = t.get("style", "")
                if style and not style.strip().endswith(";"):
                    style += ";"
                style += (
                    "font-family: inherit; font-size: inherit; font-style: inherit; line-height: inherit; color: inherit;"
                    "-webkit-padding-start: 1.25em; padding-inline-start: 1.25em;"
                    "margin: 0.5em 0; list-style-position: outside;"
                )
                style += "list-style-type: disc;" if t.name == "ul" else "list-style-type: decimal;"
                t["style"] = style
            for t in frag.find_all("li"):
                style = t.get("style", "")
                if style and not style.strip().endswith(";"):
                    style += ";"
                style += "margin: 0.25em 0;"
                t["style"] = style

            heading_sizes = {
                "h1": "1.6em",
                "h2": "1.4em",
                "h3": "1.25em",
                "h4": "1.15em",
                "h5": "1.05em",
                "h6": "1.0em",
            }

            for t in frag.find_all(["h1","h2","h3","h4","h5","h6"]):
                style = t.get("style", "")
                if style and not style.strip().endswith(";"):
                    style += ";"
                style += f"font-family: inherit; line-height: inherit; color: inherit; margin: 0.6em 0 0.3em; font-size: {heading_sizes[t.name]}; font-weight: 700;"
                t["style"] = style

            for child in list(frag.contents):
                p.append(child)

        body.append(p)


def _find_sources_ul(aio_container: Tag) -> Optional[Tag]:
    return aio_container.find("ul", class_=lambda c: c and "EJw9bc" in c)


def _sanitize_card(card: Tag) -> None:
    for a in card.find_all("a"):
        if a.has_attr("ping"):
            del a["ping"]
    for t in card.find_all(True):
        for attr in ("data-ved", "jsaction", "jscontroller", "jsname", "jsmodel", "jsuid"):
            if t.has_attr(attr):
                del t[attr]


def _replace_first_text(card: Tag, old: str, new: str) -> bool:
    for node in card.descendants:
        if isinstance(node, NavigableString) and str(node) == old:
            node.replace_with(new)
            return True
    return False


def _build_card_from_template(template_card: Tag, url: str, title: str, snippet: str, source_name: str) -> Tag:
    card = copy.deepcopy(template_card)
    _sanitize_card(card)

    a_main = card.find("a", class_=lambda c: c and "NDNGvf" in c)
    if a_main is not None and url:
        a_main["href"] = url

    visible = [s for s in card.stripped_strings]
    if visible:
        _replace_first_text(card, visible[0], title or visible[0])
        if len(visible) > 1:
            _replace_first_text(card, visible[1], (snippet or "").strip() or visible[1])
        if len(visible) > 2:
            _replace_first_text(card, visible[2], source_name or visible[2])

    return card


def _replace_sources(soup: BeautifulSoup, aio_container: Tag, sources_df: pd.DataFrame) -> None:
    ul = _find_sources_ul(aio_container)
    if ul is None:
        raise RuntimeError("Could not locate the Sources container (<ul class='EJw9bc'>) in the template.")

    template_card = aio_container.find("div", class_=lambda c: c and "MFrAxb" in c)
    if template_card is None:
        raise RuntimeError("Could not locate a source card template (div.MFrAxb) in the template.")

    sort_cols = [c for c in ("rank", "source_rank") if c in sources_df.columns]
    if sort_cols:
        sources_df = sources_df.sort_values(sort_cols, ascending=True, na_position="last")

    sources_df = sources_df.head(8)

    new_ul = copy.copy(ul)
    new_ul.clear()

    for _, row in sources_df.iterrows():
        url = str(row.get("source_url", "")).strip()
        title = str(row.get("source_title", "")).strip()
        snippet = str(row.get("source_text", "")).strip()
        source_name = str(row.get("source_name", "")).strip() or str(row.get("root_domain", "")).strip()

        li = soup.new_tag("li")
        li["class"] = ["jydCyd"]

        card = _build_card_from_template(template_card, url, title, snippet, source_name)
        li.append(card)
        new_ul.append(li)

    ul.replace_with(new_ul)


def render_one(template_html_path: Path, out_path: Path, aio_text: str, sources_df: pd.DataFrame, query_str: str) -> None:
    raw_html = template_html_path.read_text(encoding="utf-8", errors="ignore")
    raw_html = _fix_asset_paths(raw_html)

    soup = BeautifulSoup(raw_html, "lxml")

    _replace_search_bar_query(soup, query_str)

    aio_container = soup.find(id="eKIzJc")
    if aio_container is None:
        raise RuntimeError("Could not locate AI Overview container: expected an element with id='eKIzJc'.")

    _replace_aio_overview(soup, aio_container, aio_text)
    _replace_sources(soup, aio_container, sources_df)

    out_path.write_text(str(soup), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="aio_template.html", type=str)
    ap.add_argument("--retrievals", default="sample_data/retrievals_formatted.csv", type=str)
    ap.add_argument("--sources", default="sample_data/aio_sources.csv", type=str)
    ap.add_argument("--out_dir", default="out_aio_html", type=str)
    ap.add_argument("--limit", default=0, type=int)
    args = ap.parse_args()

    template_path = Path(args.template)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    retr = pd.read_csv(Path(args.retrievals))
    src = pd.read_csv(Path(args.sources))

    retr = retr[(retr.get("aio_presence", 0) == 1) & retr[TEXT_COL].notna()].copy()
    if args.limit and args.limit > 0:
        retr = retr.head(args.limit)

    if "retrieval_id" not in src.columns:
        raise RuntimeError("aio_sources.csv must contain a 'retrieval_id' column.")

    src_groups = {str(rid): df for rid, df in src.groupby("retrieval_id", dropna=False)}

    rendered = 0
    for _, row in retr.iterrows():
        rid = str(row["retrieval_id"])
        aio_text = str(row[TEXT_COL])
        sources_df = src_groups.get(rid, src.head(0))

        out_path = out_dir / f"{rid}.html"
        query_str = _format_query_from_row(row)
        render_one(template_path, out_path, aio_text, sources_df, query_str)
        rendered += 1

    print(f"Rendered {rendered} HTML file(s) to: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
