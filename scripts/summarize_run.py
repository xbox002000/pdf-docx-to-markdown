"""Summarize the last local run: documents, chunks, and simulated PPE charges."""
import glob
import json

def load(pattern):
    return [json.load(open(f)) for f in sorted(glob.glob(pattern)) if not f.endswith("__metadata__.json")]

items = load("storage/datasets/default/*.json")
docs = [i for i in items if i.get("type") == "document"]
chunks = [i for i in items if i.get("type") == "chunk"]
print(f"{len(docs)} document item(s), {len(chunks)} chunk item(s)")
for d in docs:
    if d.get("status") != "success":
        print(f"  ERROR {d.get('source')}: {d.get('error', '')[:120]}")
        continue
    st = d.get("stats", {})
    print(f"  {d['fileName']}: {d['pagesConverted']}/{d['pageCount']} pages, {st.get('tables', 0)} tables, "
          f"{st.get('headings', 0)} headings, {d.get('chunkCount', 0)} chunks, {d['processingMs']} ms")
log = load("storage/datasets/charging-log/*.json")
prices = {k: v["eventPriceUsd"] for k, v in json.load(open(".actor/pay_per_event.json")).items()}
counts = {}
for e in log:
    counts[e["event_name"]] = counts.get(e["event_name"], 0) + e["charged_count"]
total = 0.0
for k, n in counts.items():
    if k not in prices:
        print(f"  (ignored) {k}: {n} x - not in pay_per_event.json. Synthetic 'apify-default-dataset-item' "
              "must be REMOVED in Console monetization settings, otherwise every chunk item is billed.")
        continue
    usd = n * prices[k]
    total += usd
    print(f"  charge {k}: {n} x ${prices[k]} = ${usd:.4f}")
print(f"  TOTAL simulated charge (custom events): ${total:.4f}")
