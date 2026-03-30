"""Zeigt die Spaltenstruktur der Dune Query - zum Debuggen."""
import urllib.request, json
from pathlib import Path

api_key = (Path(__file__).parent.parent / ".env").read_text().split("=")[1].strip()
url = "https://api.dune.com/api/v1/query/5263787/results?limit=3"
req = urllib.request.Request(url, headers={"X-Dune-Api-Key": api_key})
with urllib.request.urlopen(req, timeout=30) as r:
    data = json.loads(r.read())

rows = data.get("result", {}).get("rows", [])
if rows:
    print("Spalten:", list(rows[0].keys()))
    print()
    for i, row in enumerate(rows):
        print(f"Zeile {i+1}:")
        for k, v in row.items():
            print(f"  {k}: {repr(v)}")
        print()
