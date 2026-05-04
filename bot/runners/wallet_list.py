"""
Wallet List - HTML Übersicht aller Wallets
Aufruf: python main.py list
        python main.py list --analysis

Startet einen lokalen Webserver (Port 7432) und öffnet die Übersicht im Browser.
Ausgeschlossene Trades werden in data/excluded_trades.json gespeichert.
"""
import sqlite3
import sys
import os
import json
import webbrowser
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

DB_OBSERVER    = "data/observer_performance.db"
DB_ANALYSIS    = "data/wallet_performance.db"
AXIOM_DB       = "data/axiom.db"
AXIOM_JSON     = "data/axiom_wallets.json"
EXCLUDED_FILE  = "data/excluded_trades.json"
PORT           = 7432


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def load_excluded():
    p = Path(EXCLUDED_FILE)
    if p.exists():
        try:
            return set(json.loads(p.read_text(encoding='utf-8')))
        except Exception:
            pass
    return set()


def save_excluded(excluded_set):
    Path(EXCLUDED_FILE).write_text(json.dumps(sorted(list(excluded_set)), indent=2), encoding='utf-8')


def load_wallet_categories():
    cats = {}
    if Path(AXIOM_DB).exists():
        try:
            conn = connect(AXIOM_DB)
            rows = conn.execute("SELECT wallet, category FROM axiom_wallets").fetchall()
            conn.close()
            for r in rows:
                cats[r['wallet']] = r['category']
            return cats
        except Exception:
            pass
    if Path(AXIOM_JSON).exists():
        try:
            data = json.loads(Path(AXIOM_JSON).read_text(encoding='utf-8'))
            for entry in data:
                if isinstance(entry, dict) and 'wallet' in entry:
                    cats[entry['wallet']] = entry.get('category', 'Unknown')
            return cats
        except Exception:
            pass
    return cats


def load_wallet_stats(db_path):
    if not Path(db_path).exists():
        return []
    try:
        conn = connect(db_path)
        rows = conn.execute("""
            SELECT wallet, total_trades, winning_trades, losing_trades,
                   total_pnl_eur, avg_pnl_eur, win_rate, confidence_score,
                   strategy_label, dynamic_sl, dynamic_tp, last_updated
            FROM wallet_stats ORDER BY confidence_score DESC
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def load_all_trades(db_path):
    if not Path(db_path).exists():
        return {}
    try:
        conn = connect(db_path)
        rows = conn.execute("""
            SELECT s.id, s.wallet, s.token, s.price_eur as exit_price,
                   s.pnl_eur, s.pnl_percent, s.price_missing, s.reason,
                   s.timestamp as sell_time, s.max_price_pct, s.min_price_pct, s.session_id,
                   (SELECT b.price_eur FROM wallet_trades b
                    WHERE b.wallet=s.wallet AND b.token=s.token AND b.side='BUY'
                      AND b.session_id=s.session_id AND b.timestamp<=s.timestamp
                    ORDER BY b.timestamp DESC LIMIT 1) as entry_price
            FROM wallet_trades s WHERE s.side='SELL' ORDER BY s.timestamp DESC
        """).fetchall()
        conn.close()
        by_wallet = {}
        for r in rows:
            d = dict(r)
            w = d['wallet']
            if w not in by_wallet:
                by_wallet[w] = []
            by_wallet[w].append(d)
        return by_wallet
    except Exception:
        return {}


def load_observer_trade_counts(wallets):
    if not Path(DB_OBSERVER).exists():
        return {}
    try:
        conn = connect(DB_OBSERVER)
        placeholders = ",".join("?" for _ in wallets)
        rows = conn.execute(f"""
            SELECT wallet, COUNT(*) as cnt FROM wallet_trades
            WHERE wallet IN ({placeholders}) AND side='SELL'
              AND reason NOT IN ('SESSION_ENDED','CRASH_RECOVERY') AND price_missing=0
            GROUP BY wallet
        """, wallets).fetchall()
        conn.close()
        return {r['wallet']: r['cnt'] for r in rows}
    except Exception:
        return {}


def compute_wallet_stats_excluding(trades_by_wallet, excluded):
    result = {}
    for wallet, trades in trades_by_wallet.items():
        active = [t for t in trades
                  if str(t['id']) not in excluded
                  and t.get('reason') not in ('SESSION_ENDED', 'CRASH_RECOVERY')
                  and not t.get('price_missing')]
        if not active:
            result[wallet] = {'wins': 0, 'losses': 0, 'total_pnl': 0, 'wr': 0, 'avg_pnl': 0, 'ev': 0, 'n': 0}
            continue
        wins   = [t for t in active if (t['pnl_eur'] or 0) > 0]
        losses = [t for t in active if (t['pnl_eur'] or 0) <= 0]
        total  = sum(t['pnl_eur'] or 0 for t in active)
        wr     = len(wins) / len(active)
        avg_w  = sum(t['pnl_eur'] for t in wins)   / len(wins)   if wins   else 0
        avg_l  = sum(t['pnl_eur'] for t in losses) / len(losses) if losses else 0
        ev     = wr * avg_w - (1 - wr) * abs(avg_l)
        result[wallet] = {
            'wins': len(wins), 'losses': len(losses),
            'total_pnl': round(total, 2), 'wr': round(wr * 100, 1),
            'avg_pnl': round(total / len(active), 2), 'ev': round(ev, 2), 'n': len(active),
        }
    return result


def pnl_color(val):
    if val is None: return "#888"
    return "#4ade80" if val > 0 else "#f87171" if val < 0 else "#888"


def generate_html(stats, categories, obs_counts, all_trades, excluded, db_label):
    all_wallets = {}
    for s in stats:
        all_wallets[s['wallet']] = s
    for w, cat in categories.items():
        if w not in all_wallets:
            all_wallets[w] = {
                'wallet': w, 'total_trades': 0, 'winning_trades': 0, 'losing_trades': 0,
                'total_pnl_eur': 0, 'avg_pnl_eur': 0, 'win_rate': 0, 'confidence_score': 0.0,
                'strategy_label': 'UNKNOWN', 'dynamic_sl': None, 'dynamic_tp': None, 'last_updated': '-'
            }

    wallet_list = list(all_wallets.values())
    live_stats  = compute_wallet_stats_excluding(all_trades, excluded)

    trades_json     = json.dumps(all_trades, default=str)
    categories_json = json.dumps(categories)
    obs_counts_json = json.dumps(obs_counts)
    excluded_json   = json.dumps(list(excluded))
    live_stats_json = json.dumps(live_stats)

    import math as _math
    conf_data = {}
    for s in stats:
        addr    = s['wallet']
        n       = s.get('total_trades', 0) or 0
        wr      = s.get('win_rate', 0) or 0
        avg_pnl = s.get('avg_pnl_eur', 0) or 0

        wr_component   = wr * 0.55
        avg_pnl_norm   = max(_math.tanh(avg_pnl / 50.0), 0.0) if avg_pnl else 0.0
        pnl_component  = avg_pnl_norm * 0.45
        trade_factor   = min(n / 100.0, 1.0)
        raw_score      = wr_component + pnl_component
        live_conf      = round(max(0.0, min(1.0, raw_score * trade_factor)), 4)

        conf_data[addr] = {
            'n':             n,
            'wr':            round(wr * 100, 1),
            'wr_component':  round(wr_component, 4),
            'pnl_component': round(pnl_component, 4),
            'trade_factor':  round(trade_factor, 4),
            'raw_score':     round(raw_score, 4),
            'live_conf':     live_conf,
            'avg_pnl':       round(avg_pnl, 2),
            'avg_pnl_norm':  round(avg_pnl_norm, 4),
            'wins':          s.get('winning_trades', 0) or 0,
            'losses':        s.get('losing_trades', 0) or 0,
        }
    conf_data_json = json.dumps(conf_data)

    rows_html = ""
    for w in wallet_list:
        addr    = w['wallet']
        cat     = categories.get(addr, 'Unknown')
        conf    = w['confidence_score'] or 0.0
        label   = w['strategy_label'] or 'UNKNOWN'
        sl      = w['dynamic_sl']
        tp      = w['dynamic_tp']
        obs_cnt = obs_counts.get(addr, 0)
        ls      = live_stats.get(addr, {})

        # Zeige den live berechneten Score in der Tabelle
        cd = conf_data.get(addr, {})
        display_conf = cd.get('live_conf', conf)

        sl_str = f"{sl:.1f}%" if sl is not None else "-"
        tp_str = f"+{tp:.1f}%" if tp is not None else "-"

        cat_colors = {'ActiveWallet':'#4ade80','CandidateWallet':'#facc15','ArchivedWallet':'#888','OwnWallet':'#60a5fa'}
        label_colors = {'ASYMMETRIC':'#a78bfa','RUNNER':'#38bdf8','SCALPER':'#4ade80','LOSS_MAKER':'#f87171','MIXED':'#fb923c','OBSERVER':'#94a3b8','UNKNOWN':'#555'}
        cat_color   = cat_colors.get(cat, '#888')
        label_color = label_colors.get(label, '#555')
        conf_pct    = int(display_conf * 100)
        conf_color  = '#4ade80' if display_conf >= 0.6 else '#facc15' if display_conf >= 0.35 else '#f87171'

        progress_html = ""
        if cat == 'CandidateWallet':
            pct = min(obs_cnt / 20 * 100, 100)
            progress_html = f"""
            <div style="margin-top:4px;font-size:11px;color:#aaa;">
                Observer: {obs_cnt}/20
                <div style="background:#222;border-radius:3px;height:4px;margin-top:2px;">
                    <div style="background:#facc15;width:{pct:.0f}%;height:4px;border-radius:3px;"></div>
                </div>
            </div>"""

        pnl_val = ls.get('total_pnl', 0)
        wr_val  = ls.get('wr', 0)
        n_val   = ls.get('n', 0)
        ev_val  = ls.get('ev', 0)

        rows_html += f"""
        <tr onclick="showDetail('{addr}')" style="cursor:pointer;" class="wallet-row" data-wallet="{addr}" data-cat="{cat}" data-label="{label}" data-conf="{display_conf}" data-pnl="{pnl_val}" data-wr="{wr_val}" data-trades="{n_val}" data-ev="{ev_val}">
            <td>
                <span style="font-family:monospace;font-size:12px;">{addr[:8]}...{addr[-4:]}</span>
                <span style="display:block;font-size:10px;color:#444;font-family:monospace;">{addr}</span>
                {progress_html}
            </td>
            <td><span style="background:{cat_color}22;color:{cat_color};padding:2px 8px;border-radius:12px;font-size:12px;">{cat.replace('Wallet','')}</span></td>
            <td onclick="event.stopPropagation();showConfBreakdown('{addr}')" title="Klicken für Score-Aufschlüsselung">
                <div style="display:flex;align-items:center;gap:6px;">
                    <div style="background:#222;border-radius:4px;height:6px;width:60px;">
                        <div style="background:{conf_color};width:{conf_pct}%;height:6px;border-radius:4px;"></div>
                    </div>
                    <span style="color:{conf_color};font-weight:600;">{display_conf:.2f}</span>
                    <span style="color:#444;font-size:10px;">ⓘ</span>
                </div>
            </td>
            <td class="dyn-wr" data-wallet="{addr}" style="color:#ddd;">{wr_val:.1f}%</td>
            <td class="dyn-pnl" data-wallet="{addr}" style="color:{'#4ade80' if pnl_val>=0 else '#f87171'};font-weight:600;">{'+' if pnl_val>=0 else ''}{pnl_val:.2f} EUR</td>
            <td class="dyn-trades" data-wallet="{addr}" style="color:#aaa;">{n_val}</td>
            <td class="dyn-ev" data-wallet="{addr}" style="color:{'#4ade80' if ev_val>=0 else '#f87171'};">{'+' if ev_val>=0 else ''}{ev_val:.2f}</td>
            <td><span style="background:{label_color}22;color:{label_color};padding:2px 6px;border-radius:8px;font-size:11px;">{label}</span></td>
            <td style="color:#f87171;">{sl_str}</td>
            <td style="color:#4ade80;">{tp_str}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Copybot – Wallet Übersicht</title>
<style>
  * {{ box-sizing:border-box;margin:0;padding:0; }}
  body {{ background:#0f0f0f;color:#ddd;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }}
  .header {{ background:#161616;border-bottom:1px solid #222;padding:14px 24px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:100; }}
  .header h1 {{ font-size:17px;font-weight:700;color:#fff; }}
  .badge {{ background:#222;padding:3px 10px;border-radius:20px;font-size:12px;color:#aaa; }}
  .controls {{ padding:12px 24px;display:flex;gap:10px;flex-wrap:wrap;align-items:center;background:#0f0f0f;border-bottom:1px solid #1a1a1a; }}
  .search {{ background:#1a1a1a;border:1px solid #2a2a2a;color:#ddd;padding:7px 12px;border-radius:8px;font-size:13px;width:260px;outline:none; }}
  select {{ background:#1a1a1a;border:1px solid #2a2a2a;color:#ddd;padding:7px 10px;border-radius:8px;font-size:13px;outline:none;cursor:pointer; }}
  .stats-bar {{ display:flex;gap:12px;padding:10px 24px;background:#111;border-bottom:1px solid #1a1a1a;flex-wrap:wrap; }}
  .stat {{ background:#161616;border:1px solid #222;border-radius:8px;padding:8px 14px;min-width:110px; }}
  .stat-label {{ font-size:10px;color:#555;text-transform:uppercase;letter-spacing:0.5px; }}
  .stat-value {{ font-size:19px;font-weight:700;margin-top:2px; }}
  .excluded-bar {{ display:none;background:#1a0a00;border-bottom:1px solid #f8731733;padding:8px 24px;font-size:12px;color:#fb923c; }}
  .table-wrap {{ padding:0 24px 24px;overflow-x:auto; }}
  table {{ width:100%;border-collapse:collapse;margin-top:14px; }}
  th {{ text-align:left;padding:9px 10px;font-size:11px;color:#555;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid #1a1a1a;cursor:pointer;user-select:none;white-space:nowrap; }}
  th:hover {{ color:#888; }}
  td {{ padding:11px 10px;border-bottom:1px solid #151515;vertical-align:middle; }}
  .wallet-row:hover {{ background:#161616; }}
  .wallet-row:hover td:first-child {{ border-left:2px solid #4ade80;padding-left:8px; }}
  .wallet-row.excluded-row {{ opacity:0.35; }}
  .overlay {{ display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:200; }}
  .panel {{ position:fixed;right:0;top:0;bottom:0;width:min(720px,100vw);background:#111;border-left:1px solid #222;overflow-y:auto;z-index:201;transform:translateX(100%);transition:transform .2s; }}
  .panel.open {{ transform:translateX(0); }}
  .panel-header {{ background:#161616;border-bottom:1px solid #222;padding:14px 18px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:10; }}
  .panel-header h2 {{ font-size:14px;font-weight:600; }}
  .close-btn {{ background:#222;border:none;color:#aaa;cursor:pointer;padding:5px 10px;border-radius:6px;font-size:13px; }}
  .close-btn:hover {{ background:#333;color:#fff; }}
  .panel-body {{ padding:18px; }}
  .meta-grid {{ display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:18px; }}
  .meta-card {{ background:#1a1a1a;border:1px solid #222;border-radius:8px;padding:10px 14px; }}
  .meta-card .label {{ font-size:10px;color:#555;text-transform:uppercase; }}
  .meta-card .value {{ font-size:17px;font-weight:700;margin-top:3px; }}
  .trades-table {{ width:100%;border-collapse:collapse;font-size:12px; }}
  .trades-table th {{ padding:7px 8px;font-size:10px;color:#555;text-transform:uppercase;border-bottom:1px solid #222;text-align:left; }}
  .trades-table td {{ padding:7px 8px;border-bottom:1px solid #161616;font-family:monospace;vertical-align:middle; }}
  .trade-row.excluded {{ opacity:0.3;text-decoration:line-through; }}
  .exclude-cb {{ cursor:pointer;width:14px;height:14px;accent-color:#f87171; }}
  .recalc-badge {{ display:inline-block;background:#f8731722;color:#fb923c;padding:1px 7px;border-radius:8px;font-size:10px;margin-left:6px; }}
  .conf-popup {{ display:none;position:fixed;top:0;left:0;right:0;bottom:0;z-index:500;background:rgba(0,0,0,0.65);align-items:center;justify-content:center; }}
  .conf-popup.open {{ display:flex; }}
  .conf-box {{ background:#161616;border:1px solid #2a2a2a;border-radius:12px;padding:24px;min-width:400px;max-width:520px;box-shadow:0 8px 40px rgba(0,0,0,0.7);max-height:90vh;overflow-y:auto; }}
  .conf-box h3 {{ font-size:14px;color:#fff;margin-bottom:4px; }}
  .conf-box .sub {{ font-size:11px;color:#444;margin-bottom:18px;font-family:monospace;word-break:break-all; }}
  .conf-row {{ display:flex;align-items:center;gap:10px;margin-bottom:10px; }}
  .conf-row .clabel {{ font-size:12px;color:#888;width:180px;flex-shrink:0;line-height:1.4; }}
  .conf-bar-wrap {{ flex:1;background:#222;border-radius:4px;height:8px; }}
  .conf-bar-fill {{ height:8px;border-radius:4px; }}
  .conf-row .cval {{ font-size:13px;font-weight:700;width:55px;text-align:right;flex-shrink:0; }}
  .conf-note {{ margin-top:12px;font-size:11px;color:#444;line-height:1.7; }}
</style>
</head>
<body>

<div class="header">
  <h1>Copybot <span style="color:#555;font-weight:400;">Wallet Übersicht</span></h1>
  <div style="display:flex;gap:8px;align-items:center;">
    <span class="badge">{db_label}</span>
    <span class="badge" id="wallet-count">–</span>
    <button onclick="location.reload()" style="background:#222;border:none;color:#aaa;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:12px;">↻</button>
  </div>
</div>

<div class="controls">
  <input class="search" type="text" placeholder="Wallet suchen..." oninput="filterTable()">
  <select onchange="filterTable()" id="cat-filter">
    <option value="">Alle Kategorien</option>
    <option value="Active">Active</option>
    <option value="Candidate">Candidate</option>
    <option value="Archived">Archived</option>
    <option value="Own">Own</option>
  </select>
  <select onchange="filterTable()" id="label-filter">
    <option value="">Alle Labels</option>
    <option value="ASYMMETRIC">Asymmetric</option>
    <option value="RUNNER">Runner</option>
    <option value="SCALPER">Scalper</option>
    <option value="MIXED">Mixed</option>
    <option value="LOSS_MAKER">Loss Maker</option>
    <option value="UNKNOWN">Unknown</option>
  </select>
  <select onchange="sortTable(this.value)">
    <option value="pnl">Sortierung: PnL ↓</option>
    <option value="conf">Sortierung: Confidence ↓</option>
    <option value="wr">Sortierung: Win Rate ↓</option>
    <option value="trades">Sortierung: Trades ↓</option>
    <option value="ev">Sortierung: EV ↓</option>
  </select>
  <label style="display:flex;align-items:center;gap:6px;font-size:13px;color:#aaa;cursor:pointer;">
    <input type="checkbox" id="show-excluded" onchange="filterTable()" style="accent-color:#fb923c;">
    Ausgeschlossene anzeigen
  </label>
</div>

<div class="excluded-bar" id="excluded-bar"></div>
<div class="stats-bar" id="stats-bar"></div>

<div class="table-wrap">
<table>
  <thead>
    <tr>
      <th onclick="sortTable('wallet')">Wallet</th>
      <th onclick="sortTable('cat')">Kategorie</th>
      <th>Confidence ⓘ</th>
      <th onclick="sortTable('wr')">Win Rate</th>
      <th onclick="sortTable('pnl')">PnL EUR*</th>
      <th onclick="sortTable('trades')">Trades*</th>
      <th onclick="sortTable('ev')">EV*</th>
      <th>Label</th>
      <th>SL</th>
      <th>TP</th>
    </tr>
  </thead>
  <tbody id="table-body">{rows_html}</tbody>
</table>
<div style="margin-top:10px;font-size:11px;color:#444;">* Werte ohne ausgeschlossene Trades &nbsp;|&nbsp; ⓘ Confidence anklicken für Aufschlüsselung</div>
</div>

<div class="conf-popup" id="conf-popup" onclick="this.classList.remove('open')">
  <div class="conf-box" onclick="event.stopPropagation()">
    <h3>Confidence Score &nbsp;<span id="conf-popup-score" style="float:right;font-size:20px;"></span></h3>
    <div class="sub" id="conf-popup-addr"></div>
    <div id="conf-popup-body"></div>
    <div class="conf-note">
      Formel: (WinRate×0.55 + tanh(AvgPnL/50)×0.45) × min(n/100, 1.0)<br>
      Mindestens 5 Trades für echten Score, sonst 0.0.<br>
      Trade-Faktor dämpft proportional bis 100 Trades – ab 100 volle Gewichtung.
    </div>
    <div style="margin-top:16px;text-align:right;">
      <button onclick="document.getElementById('conf-popup').classList.remove('open')"
        style="background:#222;border:none;color:#aaa;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px;">
        Schließen
      </button>
    </div>
  </div>
</div>

<div class="overlay" id="overlay" onclick="closePanel()"></div>
<div class="panel" id="detail-panel">
  <div class="panel-header">
    <h2 id="panel-title">Wallet Detail</h2>
    <button class="close-btn" onclick="closePanel()">✕</button>
  </div>
  <div class="panel-body" id="panel-body"></div>
</div>

<script>
const ALL_TRADES   = {trades_json};
const CATEGORIES   = {categories_json};
const OBS_COUNTS   = {obs_counts_json};
const CONF_DATA    = {conf_data_json};
let   EXCLUDED     = new Set({excluded_json});
let   LIVE_STATS   = {live_stats_json};

const REASON_SHORT = {{
  'WALLET_SOLD':'Wallet sold','OBSERVER_STAGNATION':'Stagnation','OBSERVER_MAX_HOLD':'Max hold',
  'PRICE_UNAVAILABLE':'No price','SESSION_ENDED':'Session end','STOP_LOSS':'Stop loss',
  'TAKE_PROFIT':'Take profit','INACTIVITY':'Inactivity','EMERGENCY_EXIT_CONNECTION_LOST':'Emergency',
  'MISSED_SELL_DETECTED_ON_RECONNECT':'Missed sell','CRASH_RECOVERY':'Crash rec.'
}};

function pnlColor(v) {{ return v>0?'#4ade80':v<0?'#f87171':'#888'; }}
function fmtPrice(v) {{ return v==null?'-':parseFloat(v).toFixed(8); }}
function fmtPnl(v)   {{ return v==null?'-':(v>=0?'+':'')+parseFloat(v).toFixed(2)+' EUR'; }}
function fmtPct(v)   {{ return v==null?'-':(v>=0?'+':'')+parseFloat(v).toFixed(1)+'%'; }}

// ── Confidence Breakdown ──────────────────────────────────────────────

function showConfBreakdown(addr) {{
  const d = CONF_DATA[addr];
  if (!d) {{ alert('Keine Confidence-Daten für dieses Wallet.'); return; }}

  // Live Score aus Formel berechnen (nicht gespeicherter DB-Wert)
  const liveScore = Math.min(Math.max(d.raw_score * d.trade_factor, 0), 1);
  const liveColor = liveScore >= 0.6 ? '#4ade80' : liveScore >= 0.35 ? '#facc15' : '#f87171';

  // Schritt 1: WinRate + AvgPnL → raw_score
  const step1 = [
    {{
      label: 'Win Rate',
      sub:   `${{d.wins}}W / ${{d.losses}}L von ${{d.n}} Trades`,
      raw:   d.wr.toFixed(1) + '%',
      val:   d.wr_component,
      max:   0.55,
      color: '#60a5fa',
    }},
    {{
      label: 'Avg PnL (tanh-normalisiert)',
      sub:   `tanh(${{d.avg_pnl>=0?'+':''}}${{d.avg_pnl.toFixed(2)}} / 50) = ${{d.avg_pnl_norm.toFixed(3)}}`,
      raw:   (d.avg_pnl>=0?'+':'')+d.avg_pnl.toFixed(2)+' EUR',
      val:   d.pnl_component,
      max:   0.45,
      color: '#4ade80',
    }},
  ];

  let body = '<div style="font-size:11px;color:#555;margin-bottom:12px;">Schritt 1: Basis-Score (WinRate + AvgPnL)</div>';
  for (const c of step1) {{
    const pct = c.max > 0 ? Math.min(c.val/c.max*100,100) : 0;
    body += `<div class="conf-row">
      <div class="clabel">${{c.label}}<br><span style="font-size:10px;color:#555;">${{c.sub}}</span></div>
      <div class="conf-bar-wrap"><div class="conf-bar-fill" style="width:${{pct.toFixed(1)}}%;background:${{c.color}};"></div></div>
      <div class="cval" style="color:${{c.color}};">${{c.val.toFixed(3)}}</div>
    </div>
    <div style="font-size:10px;color:#444;margin:-6px 0 10px 190px;">Rohwert: ${{c.raw}} → max ${{c.max.toFixed(2)}} Pkt</div>`;
  }}

  body += `<div style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:6px;padding:10px 14px;margin:12px 0;display:flex;justify-content:space-between;align-items:center;">
    <span style="font-size:12px;color:#888;">Basis-Score (max 1.0)</span>
    <span style="font-size:16px;font-weight:700;color:#ddd;">${{d.raw_score.toFixed(4)}}</span>
  </div>`;

  // Schritt 2: × trade_factor
  const tfPct = Math.min(d.trade_factor * 100, 100);
  body += `<div style="font-size:11px;color:#555;margin-bottom:12px;margin-top:4px;">Schritt 2: Dämpfung durch Trade-Anzahl</div>
  <div class="conf-row">
    <div class="clabel">Trade-Faktor<br><span style="font-size:10px;color:#555;">min(${{d.n}} / 100, 1.0)</span></div>
    <div class="conf-bar-wrap"><div class="conf-bar-fill" style="width:${{tfPct.toFixed(1)}}%;background:#fb923c;"></div></div>
    <div class="cval" style="color:#fb923c;">${{d.trade_factor.toFixed(2)}}×</div>
  </div>
  <div style="font-size:10px;color:#444;margin:-6px 0 12px 190px;">${{d.n}} von 100 Trades → ${{(d.trade_factor*100).toFixed(0)}}% Gewichtung</div>`;

  // Ergebnis (live berechnet)
  body += `<div style="margin-top:16px;padding-top:14px;border-top:1px solid #222;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
      <span style="font-size:13px;color:#aaa;">${{d.raw_score.toFixed(4)}} × ${{d.trade_factor.toFixed(2)}} =</span>
      <span style="font-size:22px;font-weight:700;color:${{liveColor}};">${{liveScore.toFixed(4)}}</span>
    </div>
    <div style="background:#222;border-radius:4px;height:10px;">
      <div style="background:${{liveColor}};width:${{Math.min(liveScore*100,100).toFixed(1)}}%;height:10px;border-radius:4px;"></div>
    </div>
  </div>`;

  document.getElementById('conf-popup-score').textContent = liveScore.toFixed(2);
  document.getElementById('conf-popup-score').style.color = liveColor;
  document.getElementById('conf-popup-addr').textContent  = addr;
  document.getElementById('conf-popup-body').innerHTML    = body;
  document.getElementById('conf-popup').classList.add('open');
}}

// ── Ausschluss ────────────────────────────────────────────────────────

function toggleExclude(tradeId, cb) {{
  tradeId = String(tradeId);
  if (cb.checked) {{ EXCLUDED.add(tradeId); }} else {{ EXCLUDED.delete(tradeId); }}
  saveExcluded(); recomputeStats(); updateDetailStats(currentWallet); updateExcludedBar(); updateStatsBar();
}}

function saveExcluded() {{
  fetch('http://localhost:{PORT}/save_excluded', {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify(Array.from(EXCLUDED))
  }}).catch(() => console.warn('Server nicht erreichbar.'));
}}

function recomputeStats() {{
  const ns = {{}};
  for (const [wallet, trades] of Object.entries(ALL_TRADES)) {{
    const active = trades.filter(t => !EXCLUDED.has(String(t.id)) && t.reason !== 'SESSION_ENDED' && t.reason !== 'CRASH_RECOVERY' && !t.price_missing);
    if (!active.length) {{ ns[wallet]={{wins:0,losses:0,total_pnl:0,wr:0,avg_pnl:0,ev:0,n:0}}; continue; }}
    const wins=active.filter(t=>(t.pnl_eur||0)>0), losses=active.filter(t=>(t.pnl_eur||0)<=0);
    const total=active.reduce((s,t)=>s+(t.pnl_eur||0),0), wr=wins.length/active.length;
    const avgW=wins.length?wins.reduce((s,t)=>s+(t.pnl_eur||0),0)/wins.length:0;
    const avgL=losses.length?losses.reduce((s,t)=>s+(t.pnl_eur||0),0)/losses.length:0;
    ns[wallet]={{wins:wins.length,losses:losses.length,total_pnl:Math.round(total*100)/100,
      wr:Math.round(wr*1000)/10,avg_pnl:Math.round(total/active.length*100)/100,
      ev:Math.round((wr*avgW-(1-wr)*Math.abs(avgL))*100)/100,n:active.length}};
  }}
  LIVE_STATS=ns;
  document.querySelectorAll('.wallet-row').forEach(row=>{{
    const addr=row.dataset.wallet, ls=LIVE_STATS[addr]||{{}};
    const pnl=ls.total_pnl||0,wr=ls.wr||0,n=ls.n||0,ev=ls.ev||0;
    row.dataset.pnl=pnl; row.dataset.wr=wr; row.dataset.trades=n; row.dataset.ev=ev;
    const wrEl=row.querySelector('.dyn-wr'),pnlEl=row.querySelector('.dyn-pnl');
    const nEl=row.querySelector('.dyn-trades'),evEl=row.querySelector('.dyn-ev');
    if(wrEl)  wrEl.textContent=wr.toFixed(1)+'%';
    if(pnlEl){{pnlEl.textContent=(pnl>=0?'+':'')+pnl.toFixed(2)+' EUR';pnlEl.style.color=pnlColor(pnl);}}
    if(nEl)   nEl.textContent=n;
    if(evEl)  {{evEl.textContent=(ev>=0?'+':'')+ev.toFixed(2);evEl.style.color=pnlColor(ev);}}
  }});
}}

function updateExcludedBar() {{
  const bar=document.getElementById('excluded-bar');
  if(EXCLUDED.size>0){{bar.style.display='block';bar.textContent=`⚠ ${{EXCLUDED.size}} Trade(s) ausgeschlossen – Statistiken ohne diese berechnet.`;}}
  else bar.style.display='none';
}}

// ── Detail Panel ──────────────────────────────────────────────────────

let currentWallet=null;

function showDetail(addr) {{
  currentWallet=addr;
  document.getElementById('panel-title').textContent=addr.slice(0,8)+'...'+addr.slice(-6);
  updateDetailStats(addr);
  document.getElementById('overlay').style.display='block';
  document.getElementById('detail-panel').classList.add('open');
}}

function updateDetailStats(addr) {{
  if(!addr) return;
  const trades=ALL_TRADES[addr]||[],cat=CATEGORIES[addr]||'Unknown',obs=OBS_COUNTS[addr]||0,ls=LIVE_STATS[addr]||{{}};
  const pnl=ls.total_pnl||0,wr=ls.wr||0,wins=ls.wins||0,lss=ls.losses||0,ev=ls.ev||0,n=ls.n||0;

  let obsProgress='';
  if(cat==='CandidateWallet'){{
    const pct=Math.min(obs/20*100,100);
    obsProgress=`<div class="meta-card" style="grid-column:1/-1;"><div class="label">Observer Fortschritt</div>
      <div style="display:flex;align-items:center;gap:10px;margin-top:6px;">
        <div style="background:#222;border-radius:4px;height:8px;flex:1;">
          <div style="background:#facc15;width:${{pct.toFixed(0)}}%;height:8px;border-radius:4px;"></div>
        </div><span style="color:#facc15;font-weight:700;">${{obs}}/20</span>
      </div></div>`;
  }}

  let tradesHtml='';
  if(!trades.length){{tradesHtml='<p style="color:#555;text-align:center;padding:20px;">Noch keine Trades.</p>';}}
  else{{
    const exclCount=trades.filter(t=>EXCLUDED.has(String(t.id))).length;
    const badge=exclCount>0?`<span class="recalc-badge">${{exclCount}} ausgeschlossen</span>`:'';
    const trows=trades.map((t,i)=>{{
      const pnlV=t.pnl_eur||0,excl=EXCLUDED.has(String(t.id));
      const flag=t.price_missing?'<span style="color:#f87171;font-size:10px;">[!]</span>':'';
      const reason=REASON_SHORT[t.reason]||t.reason||'-';
      const ts=(t.sell_time||'').slice(0,16).replace('T',' ');
      return `<tr class="${{excl?'trade-row excluded':'trade-row'}}">
        <td onclick="event.stopPropagation()"><input type="checkbox" class="exclude-cb" ${{excl?'checked':''}} onchange="toggleExclude(${{t.id}},this)"></td>
        <td style="color:#555;">${{i+1}}</td>
        <td style="font-size:11px;">${{(t.token||'').slice(0,12)}}...</td>
        <td>${{fmtPrice(t.entry_price)}}</td><td>${{fmtPrice(t.exit_price)}}</td>
        <td style="color:${{pnlColor(pnlV)}};font-weight:600;">${{fmtPnl(pnlV)}}</td>
        <td style="color:${{pnlColor(pnlV)}};">${{fmtPct(t.pnl_percent)}}</td>
        <td style="color:#888;font-size:11px;">${{reason}} ${{flag}}</td>
        <td style="color:#555;font-size:11px;">${{ts}}</td>
      </tr>`;
    }}).join('');
    tradesHtml=`<h3 style="font-size:12px;color:#555;text-transform:uppercase;margin-bottom:8px;">Trades (${{trades.length}}) ${{badge}}</h3>
      <table class="trades-table"><thead><tr>
        <th title="Ausschließen">✕</th><th>#</th><th>Token</th><th>Entry EUR</th><th>Exit EUR</th>
        <th>P&L EUR</th><th>P&L%</th><th>Grund</th><th>Datum</th>
      </tr></thead><tbody>${{trows}}</tbody></table>`;
  }}

  document.getElementById('panel-body').innerHTML=`
    <div class="meta-grid">
      <div class="meta-card"><div class="label">Kategorie</div><div class="value" style="font-size:13px;">${{cat.replace('Wallet','')}}</div></div>
      <div class="meta-card"><div class="label">Win Rate</div><div class="value">${{wr.toFixed(1)}}%</div></div>
      <div class="meta-card"><div class="label">PnL (bereinigt)</div><div class="value" style="color:${{pnlColor(pnl)}};font-size:15px;">${{fmtPnl(pnl)}}</div></div>
      <div class="meta-card"><div class="label">EV / Trade</div><div class="value" style="color:${{pnlColor(ev)}};font-size:15px;">${{(ev>=0?'+':'')+ev.toFixed(2)}} EUR</div></div>
      <div class="meta-card"><div class="label">Trades (W/L)</div><div class="value" style="font-size:14px;">${{n}} <span style="color:#555;font-size:12px;">(${{wins}}W/${{lss}}L)</span></div></div>
      <div class="meta-card"><div class="label">Adresse</div><div class="value" style="font-size:10px;font-family:monospace;word-break:break-all;">${{addr}}</div></div>
      ${{obsProgress}}
    </div>${{tradesHtml}}`;
}}

function closePanel() {{
  document.getElementById('overlay').style.display='none';
  document.getElementById('detail-panel').classList.remove('open');
  currentWallet=null;
}}

document.addEventListener('keydown', e=>{{ if(e.key==='Escape') closePanel(); }});

// ── Filter & Sort ─────────────────────────────────────────────────────

function filterTable() {{
  const search=document.querySelector('.search').value.toLowerCase();
  const cat=document.getElementById('cat-filter').value.toLowerCase();
  const label=document.getElementById('label-filter').value.toLowerCase();
  const showExcl=document.getElementById('show-excluded').checked;
  let visible=0;
  document.querySelectorAll('.wallet-row').forEach(r=>{{
    const addr=r.dataset.wallet,wTrades=ALL_TRADES[addr]||[];
    const allExcl=wTrades.length>0&&wTrades.every(t=>EXCLUDED.has(String(t.id)));
    const show=(!search||r.textContent.toLowerCase().includes(search))
            &&(!cat||(r.dataset.cat||'').toLowerCase().includes(cat))
            &&(!label||(r.dataset.label||'').toLowerCase().includes(label))
            &&(showExcl||!allExcl);
    r.style.display=show?'':'none';
    if(show) visible++;
    r.classList.toggle('excluded-row',allExcl);
  }});
  document.getElementById('wallet-count').textContent=visible+' Wallets';
  updateStatsBar();
}}

function sortTable(key) {{
  const tbody=document.getElementById('table-body');
  const rows=Array.from(tbody.querySelectorAll('.wallet-row'));
  const dir=tbody.dataset.sortKey===key?parseInt(tbody.dataset.sortDir||'-1')*-1:-1;
  tbody.dataset.sortKey=key; tbody.dataset.sortDir=dir;
  const val=(r,k)=>{{switch(k){{
    case 'conf': return parseFloat(r.dataset.conf)||0;
    case 'wr':   return parseFloat(r.dataset.wr)||0;
    case 'pnl':  return parseFloat(r.dataset.pnl)||0;
    case 'trades':return parseInt(r.dataset.trades)||0;
    case 'ev':   return parseFloat(r.dataset.ev)||0;
    case 'wallet':return r.dataset.wallet||'';
    case 'cat':  return r.dataset.cat||'';
    default:     return 0;
  }}}};
  rows.sort((a,b)=>{{const va=val(a,key),vb=val(b,key);return typeof va==='string'?va.localeCompare(vb)*dir:(va-vb)*dir;}});
  rows.forEach(r=>tbody.appendChild(r));
}}

function updateStatsBar() {{
  const rows=Array.from(document.querySelectorAll('.wallet-row')).filter(r=>r.style.display!=='none');
  let totalPnl=0,active=0,candidates=0,totalEv=0,evCount=0;
  rows.forEach(r=>{{
    const ls=LIVE_STATS[r.dataset.wallet]||{{}};
    totalPnl+=ls.total_pnl||0;
    if(ls.ev){{totalEv+=ls.ev;evCount++;}}
    const c=(r.dataset.cat||'').toLowerCase();
    if(c.includes('active')) active++;
    if(c.includes('candidate')) candidates++;
  }});
  const avgEv=evCount?totalEv/evCount:0;
  document.getElementById('stats-bar').innerHTML=`
    <div class="stat"><div class="stat-label">Wallets</div><div class="stat-value" style="color:#ddd;">${{rows.length}}</div></div>
    <div class="stat"><div class="stat-label">Active</div><div class="stat-value" style="color:#4ade80;">${{active}}</div></div>
    <div class="stat"><div class="stat-label">Candidates</div><div class="stat-value" style="color:#facc15;">${{candidates}}</div></div>
    <div class="stat"><div class="stat-label">PnL gesamt*</div><div class="stat-value" style="color:${{pnlColor(totalPnl)}};"> ${{totalPnl>=0?'+':''}}${{totalPnl.toFixed(2)}} EUR</div></div>
    <div class="stat"><div class="stat-label">Ø EV / Trade*</div><div class="stat-value" style="color:${{pnlColor(avgEv)}};font-size:16px;">${{avgEv>=0?'+':''}}${{avgEv.toFixed(2)}} EUR</div></div>
    <div class="stat"><div class="stat-label">Ausgeschlossen</div><div class="stat-value" style="color:${{EXCLUDED.size>0?'#fb923c':'#555'}};font-size:16px;">${{EXCLUDED.size}}</div></div>`;
}}

updateExcludedBar(); sortTable('pnl'); filterTable();
</script>
</body>
</html>"""


_html_content = ""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = _html_content.encode('utf-8')
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path == "/save_excluded":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            try:
                save_excluded(set(json.loads(body)))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            except Exception as e:
                self.send_response(500); self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404); self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, fmt, *args):
        pass


def run(args=None):
    global _html_content
    if args is None:
        args = []

    use_analysis = "--analysis" in args
    db_path      = DB_ANALYSIS if use_analysis else DB_OBSERVER
    db_label     = "ANALYSIS"  if use_analysis else "OBSERVER"

    print(f"[WalletList] Lade Daten ({db_label})...")
    stats      = load_wallet_stats(db_path)
    categories = load_wallet_categories()
    obs_counts = load_observer_trade_counts(list(categories.keys()))
    all_trades = load_all_trades(db_path)
    excluded   = load_excluded()

    total_trades = sum(len(v) for v in all_trades.values())
    print(f"[WalletList] {len(all_trades)} Wallets | {total_trades} Trades | {len(excluded)} ausgeschlossen")

    _html_content = generate_html(stats, categories, obs_counts, all_trades, excluded, db_label)

    server = HTTPServer(("127.0.0.1", PORT), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    url = f"http://localhost:{PORT}/"
    print(f"[WalletList] Server läuft auf {url}")
    webbrowser.open(url)
    print("[WalletList] Übersicht geöffnet. Drücke Ctrl+C zum Beenden.")

    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()
        print("\n[WalletList] Server beendet.")
