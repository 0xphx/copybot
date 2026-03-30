"""
gmgn_fetch.py - Wird von Claude-Extension ausgefuehrt um GMGN-Daten zu holen.
Schreibt Ergebnisse in eine Temp-Datei die find_wallets.py einliest.

Nicht direkt aufrufen - wird von find_wallets.py intern gestartet.
"""

# Dieser Code wird als JavaScript im GMGN-Tab ausgefuehrt (via Claude-Extension)
# Das Ergebnis wird in %TEMP%/gmgn_wallet_data.json gespeichert

JS_TEMPLATE = """
(async () => {{
  const period  = "{period}";
  const tag     = "{tag}";
  const limit   = {limit};
  const map     = {{"1d":"pnl_1d","7d":"pnl_7d","30d":"pnl_30d"}};
  const orderby = map[period] || "pnl_7d";
  const url     = "https://gmgn.ai/defi/quotation/v1/rank/sol/wallets/" + period
    + "?orderby=" + orderby + "&direction=desc&period=" + period
    + "&tag=" + tag + "&wallet_tag=" + tag + "&limit=" + limit;

  try {{
    const r = await fetch(url, {{
      headers: {{"Accept": "application/json", "Referer": "https://gmgn.ai/sol/wallets/smart_money"}},
      credentials: "include"
    }});
    const d = await r.json();
    window._gmgn_result = d;
    return (d?.data?.rank || []).length + " Wallets geladen";
  }} catch(e) {{
    window._gmgn_result = {{error: e.message}};
    return "FEHLER: " + e.message;
  }}
}})()
"""
