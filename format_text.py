import os, argparse
import pandas as pd
from openai import OpenAI
import sys

# export OPENAI_API_KEY="YOUR_KEY"
# python format_text.py

INPUT_CSV = "sample_data/retrievals.csv"
OUTPUT_CSV = "sample_data/retrievals_formatted.csv"

DEV = """
You format text into an HTML fragment to be inserted inside:
<p class="T286Pc">{HERE}</p>

Output ONLY the HTML fragment for {HERE}. Do NOT include <p>, <html>, <body>, <div>, or any commentary.

Allowed tags only: <br>, <b>, <ul>, <ol>, <li>, <h3>, <h4>.
No attributes. No markdown.
"""

USR = """
Format the INPUT TEXT to resemble a Google AI Overview layout using headings, bullets, bold, and line breaks.

CRITICAL CONSTRAINT:
- Preserve the input text verbatim.
- Do not add, remove, reorder, or modify any words, characters, or punctuation.
- The output must contain all original characters in the same order.
- Only insert HTML tags (from the allowed list) and whitespace/line breaks to structure the text.
- Headings may only wrap existing text; do not invent new titles.
- Bullet points should be added only when there is a list of sentences that follow the structure "lorem ipsum: sentence follows."
- Bold the clause before the colon in bullet points. 
- Do not add line breaks between bullet points.  
- Only assign headings to standalone phrases followed by lists (e.g. "Who is eligible for a free card?", 
"Key Information and Statistics", "Key Takeaways").

INPUT TEXT:
"""

IN_PER_1M  = 0.40
OUT_PER_1M = 1.60

def est_cost(totals):
    return (totals["in"] * IN_PER_1M + totals["out"] * OUT_PER_1M) / 1_000_000

def fmt(text, client, model, totals):
    text = "" if pd.isna(text) else str(text)

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "developer", "content": DEV},
            {"role": "user", "content": f"{USR}\n{text}"},
        ],
        temperature=0.2,
    )

    if getattr(resp, "usage", None):
        totals["in"] += resp.usage.prompt_tokens or 0
        totals["out"] += resp.usage.completion_tokens or 0

    return (resp.choices[0].message.content or "").rstrip("\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gpt-5.2")
    ap.add_argument("--progress-every", type=int, default=1)
    args = ap.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set")

    df = pd.read_csv(INPUT_CSV)
    if "aio_text" not in df.columns:
        raise SystemExit(f"Missing column aio_text. Found: {list(df.columns)}")

    client = OpenAI()
    totals = {"in": 0, "out": 0}

    n = len(df)
    out = []

    for i, text in enumerate(df["aio_text"].tolist(), start=1):
        out.append(fmt(text, client=client, model=args.model, totals=totals))

        if args.progress_every > 0 and (i % args.progress_every == 0 or i == n):
            cost = est_cost(totals)
            sys.stderr.write(
                f"\rRow {i}/{n} | in={totals['in']} out={totals['out']} | cumulative_est=${cost:.6f}   "
            )
            sys.stderr.flush()

    sys.stderr.write("\n")

    df["formatted_text"] = out
    df.to_csv(OUTPUT_CSV, index=False)

    final_cost = est_cost(totals)
    print(f"Total estimated cost: ${final_cost:.6f}")
    print(f"Done. Wrote: {OUTPUT_CSV}")
    print(f"Input tokens:  {totals['in']}")
    print(f"Output tokens: {totals['out']}")

if __name__ == "__main__":
    main()