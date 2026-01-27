#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import re
from pathlib import Path
from typing import Optional

import pandas as pd
from bs4 import BeautifulSoup, Tag

# for AIO as serps: python generate_serp_html.py
ASSET_FOLDER_NAME = "html_asset_files"

from urllib.parse import urlparse

def _domain_and_path(url: str, max_path: int = 50) -> tuple[str, str]:
    """
    Returns (domain, breadcrumb_text) where breadcrumb_text looks like:
      example.com › section › page
    """
    try:
        p = urlparse(url)
        domain = (p.netloc or "").lower()
        if domain.startswith("www."):
            domain = domain[4:]

        path = (p.path or "").strip("/")
        if not path:
            return domain, domain

        parts = [s for s in path.split("/") if s]
        crumb = " › ".join(parts)
        if len(crumb) > max_path:
            crumb = crumb[: max_path - 1].rstrip() + "…"

        return domain, f"{domain} › {crumb}"
    except Exception:
        return "", (url or "")

def _domain(url: str) -> str:
    try:
        d = urlparse(url).netloc
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def fix_asset_paths(html: str) -> str:
    # common "saved page" folder names -> renamed folder in same dir as script
    html = html.replace("_files/", f"{ASSET_FOLDER_NAME}/")
    html = html.replace("serp_files/", f"{ASSET_FOLDER_NAME}/")
    html = re.sub(r'(?i)\bfile:///', "", html)
    return html


def format_query(row: pd.Series) -> str:
    q = str(row.get("query", "")).strip()
    q = q.replace("COUNTYSEAT", str(row.get("CountySeat", "")).strip())
    q = q.replace("STATE", str(row.get("State", "")).strip())
    return q


def set_search_query(soup: BeautifulSoup, query: str) -> None:
    ta = soup.find("textarea", id="APjFqb")
    if ta is not None:
        ta["value"] = query
        ta.string = query

    title = soup.find("title")
    if title and title.string:
        title.string = re.sub(r"^.*(?= - Google Search$)", query, title.string)


def find_first_organic_result(rso: Tag) -> Optional[Tag]:
    # Organic results in this saved SERP are typically: div.MjjYud > div.A6K0A ... containing div.yuRUbf
    for mjj in rso.find_all("div", class_="MjjYud", recursive=True):
        if mjj.find("div", class_="yuRUbf") is not None:
            return mjj
    return None


def sanitize(result: Tag) -> None:
    # Make offline-friendly: remove ping + some JS attrs
    for a in result.find_all("a"):
        if a.has_attr("ping"):
            del a["ping"]
    for t in result.find_all(True):
        for attr in ("data-ved", "jsaction", "jscontroller", "jsname", "jsmodel", "jsuid"):
            if t.has_attr(attr):
                del t[attr]


def fill_one_result(result: Tag, url: str, title: str, snippet: str, source_name: str) -> None:
    display_site = (source_name or "").strip() or _domain(url)

    # Link + title
    a = result.select_one("div.yuRUbf a")
    if a is not None and url:
        a["href"] = url

    h3 = result.select_one("div.yuRUbf h3")
    if h3 is not None and title:
        h3.clear()
        h3.append(title)

    # Website title (THIS is the "Live Science" node in your template)
    for node in result.select("span.VuuXrf"):
        node.clear()
        node.append(display_site)

    # Breadcrumb/display URL line (often shows "https://www.livescience.com › ...")
    tbw = result.select_one("div.TbwUpd")
    if tbw is not None:
        tbw.clear()
        tbw.append(display_site)

    cite = result.select_one("cite")
    if cite is not None:
        cite.clear()
        cite.append(display_site)

    # Snippet
    sn = result.select_one("div.VwiC3b")
    if sn is not None:
        sn.clear()
        sn.append((snippet or "").strip())

    sanitize(result)



def render_serp(template_path: Path, out_path: Path, query: str, sources_df: pd.DataFrame) -> None:
    raw = template_path.read_text(encoding="utf-8", errors="ignore")
    raw = fix_asset_paths(raw)

    soup = BeautifulSoup(raw, "lxml")
    set_search_query(soup, query)

    rso = soup.select_one("div#rso")
    if rso is None:
        raise RuntimeError("Could not locate results container div#rso in serp_template.html")

    template_result = find_first_organic_result(rso)
    if template_result is None:
        raise RuntimeError("Could not find an organic result block to clone (div.MjjYud containing div.yuRUbf).")

    # Clear existing results inside rso, then insert new ones
    rso.clear()

    # Sort by rank if present
    sort_cols = [c for c in ("rank", "source_rank") if c in sources_df.columns]
    if sort_cols:
        sources_df = sources_df.sort_values(sort_cols, ascending=True, na_position="last")

    # Keep it reasonable like a SERP
    sources_df = sources_df.head(10)

    for _, row in sources_df.iterrows():
        url = str(row.get("source_url", "")).strip()
        title = str(row.get("source_title", "")).strip()
        snippet = str(row.get("source_text", "")).strip()
        source_name = (
            str(row.get("source_name", "")).strip()
            or str(row.get("root_domain", "")).strip()
        )

        block = copy.deepcopy(template_result)
        fill_one_result(block, url=url, title=title, snippet=snippet, source_name=source_name)
        rso.append(block)

    out_path.write_text(str(soup), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="serp_template.html")
    ap.add_argument("--retrievals", default="sample_data/retrievals.csv")
    ap.add_argument("--sources", default="sample_data/serps.csv", help="CSV of sources (supports aio_sources.csv or serps.csv schema)")
    ap.add_argument("--out_dir", default="out_serp_html")
    ap.add_argument("--limit", type=int, default=0, help="0 = all; else first N retrieval rows")
    args = ap.parse_args()

    template_path = Path(args.template)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    retr = pd.read_csv(Path(args.retrievals))
    src = pd.read_csv(Path(args.sources))

    # Normalize known source CSV schemas to the columns expected by render_serp().
    # Expected columns (any subset is fine):
    #   retrieval_id, source_url, source_title, source_text, source_name/root_domain, rank/source_rank
    if "serps_url" in src.columns and "source_url" not in src.columns:
        rename_map = {
            "serps_url": "source_url",
            "serps_title": "source_title",
            "serps_lede": "source_text",
            "serps_rank": "rank",
        }
        src = src.rename(columns={k: v for k, v in rename_map.items() if k in src.columns})

    # Some SERP exports use generic column names; handle a few common variants.
    if "url" in src.columns and "source_url" not in src.columns:
        src = src.rename(columns={"url": "source_url"})
    if "title" in src.columns and "source_title" not in src.columns:
        src = src.rename(columns={"title": "source_title"})
    if "snippet" in src.columns and "source_text" not in src.columns:
        src = src.rename(columns={"snippet": "source_text"})

    if "retrieval_id" not in retr.columns:
        raise RuntimeError("retrievals.csv must have a retrieval_id column")
    if "retrieval_id" not in src.columns:
        raise RuntimeError("sources CSV must have a retrieval_id column")

    # If you only want rows where aio_presence==1, uncomment:
    # retr = retr[retr.get("aio_presence", 0) == 1].copy()

    if args.limit and args.limit > 0:
        retr = retr.head(args.limit)

    src_groups = {str(rid): df for rid, df in src.groupby("retrieval_id", dropna=False)}

    rendered = 0
    for _, row in retr.iterrows():
        rid = str(row["retrieval_id"])
        q = format_query(row)

        sources_df = src_groups.get(rid)
        if sources_df is None or sources_df.empty:
            # still write a page, just with no results
            sources_df = src.head(0)

        out_path = out_dir / f"{rid}.html"
        render_serp(template_path, out_path, q, sources_df)
        rendered += 1

    print(f"Rendered {rendered} SERP HTML file(s) to: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
