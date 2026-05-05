#!/usr/bin/env python3
"""
Visualize Copybot trade logs on top of a memecoin chart.

The script reads one paper trading JSON file, fetches historical OHLCV candles
for one token via GeckoTerminal, and writes a standalone HTML chart with:
  - candlesticks
  - BUY / SELL markers
  - weighted average BUY and SELL lines

Usage:
  python3 visualize_trade_log.py bot/data/paper_mainnet_20260207_005449.json
  python3 visualize_trade_log.py bot/data/paper_mainnet_20260207_005449.json --token 7wqfc2zgutheTyFk3aEVT48ycfVyLfqM9qQDnzc1pump
  python3 visualize_trade_log.py bot/data/paper_mainnet_20260207_005449.json --all-tokens
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable


GECKO_ROOT = "https://api.geckoterminal.com/api/v2"
GECKO_NETWORK = "solana"
MIN_SECONDS_BETWEEN_REQUESTS = 2.1
PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"
LOCAL_TZ = datetime.now().astimezone().tzinfo or UTC

_LAST_REQUEST_AT = 0.0


@dataclass
class TradeRecord:
    token: str
    side: str
    price_eur: float
    amount: float
    value_eur: float
    timestamp: datetime
    pnl_eur: float | None
    pnl_percent: float | None


@dataclass
class PlotTrade:
    trade: TradeRecord
    chart_price_usd: float
    candle_time: str


@dataclass
class PoolInfo:
    address: str
    name: str
    price_usd: float | None
    reserve_usd: float | None
    dex_name: str | None


@dataclass
class CandleConfig:
    timeframe: str
    aggregate: int
    limit: int
    padding_before: timedelta
    padding_after: timedelta


def timeframe_seconds(config: CandleConfig) -> int:
    if config.timeframe == "minute":
        return 60 * config.aggregate
    if config.timeframe == "hour":
        return 3600 * config.aggregate
    if config.timeframe == "day":
        return 86400 * config.aggregate
    return 60


def rate_limited_get_json(url: str) -> dict:
    global _LAST_REQUEST_AT
    wait_seconds = MIN_SECONDS_BETWEEN_REQUESTS - (time.monotonic() - _LAST_REQUEST_AT)
    if wait_seconds > 0:
        time.sleep(wait_seconds)

    request = urllib.request.Request(
        url,
        headers={
            "accept": "application/json",
            "user-agent": "Mozilla/5.0 (compatible; copybot-chart/1.0)",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")

    _LAST_REQUEST_AT = time.monotonic()
    return json.loads(body)


def parse_trade(item: dict) -> TradeRecord:
    timestamp = datetime.fromisoformat(item["timestamp"])
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=LOCAL_TZ)
    return TradeRecord(
        token=item["token"],
        side=item["side"].upper(),
        price_eur=float(item["price_eur"]),
        amount=float(item["amount"]),
        value_eur=float(item["value_eur"]),
        timestamp=timestamp,
        pnl_eur=float(item["pnl_eur"]) if item.get("pnl_eur") is not None else None,
        pnl_percent=float(item["pnl_percent"]) if item.get("pnl_percent") is not None else None,
    )


def load_session(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def group_trades_by_token(trade_history: Iterable[dict]) -> dict[str, list[TradeRecord]]:
    grouped: dict[str, list[TradeRecord]] = defaultdict(list)
    for item in trade_history:
        trade = parse_trade(item)
        grouped[trade.token].append(trade)

    for token in grouped:
        grouped[token].sort(key=lambda t: t.timestamp)
    return dict(grouped)


def choose_candle_config(start: datetime, end: datetime) -> CandleConfig:
    span = max((end - start).total_seconds(), 60)
    if span <= 6 * 3600:
        return CandleConfig("minute", 1, 1000, timedelta(minutes=20), timedelta(minutes=20))
    if span <= 24 * 3600:
        return CandleConfig("minute", 5, 1000, timedelta(hours=1), timedelta(hours=1))
    if span <= 7 * 24 * 3600:
        return CandleConfig("hour", 1, 1000, timedelta(hours=6), timedelta(hours=6))
    if span <= 30 * 24 * 3600:
        return CandleConfig("hour", 4, 1000, timedelta(days=1), timedelta(days=1))
    return CandleConfig("day", 1, 1000, timedelta(days=3), timedelta(days=3))


def weighted_average_price(trades: list[TradeRecord], side: str) -> float | None:
    filtered = [trade for trade in trades if trade.side == side]
    total_amount = sum(trade.amount for trade in filtered)
    if total_amount <= 0:
        return None
    return sum(trade.amount * trade.price_eur for trade in filtered) / total_amount


def summarize_trades(trades: list[TradeRecord]) -> dict:
    buys = [trade for trade in trades if trade.side == "BUY"]
    sells = [trade for trade in trades if trade.side == "SELL"]
    realized_pnl = sum(trade.pnl_eur or 0.0 for trade in sells)
    return {
        "buy_count": len(buys),
        "sell_count": len(sells),
        "avg_buy": weighted_average_price(trades, "BUY"),
        "avg_sell": weighted_average_price(trades, "SELL"),
        "realized_pnl": realized_pnl,
        "first_trade_at": min(trade.timestamp for trade in trades),
        "last_trade_at": max(trade.timestamp for trade in trades),
    }


def nearest_candle_for_trade(trade: TradeRecord, candles: list[dict]) -> dict:
    trade_ts = trade.timestamp.timestamp()
    best = min(candles, key=lambda candle: abs(candle["timestamp"] - trade_ts))
    return best


def build_plot_trades(trades: list[TradeRecord], candles: list[dict]) -> list[PlotTrade]:
    plot_trades: list[PlotTrade] = []
    for trade in trades:
        candle = nearest_candle_for_trade(trade, candles)
        plot_trades.append(
            PlotTrade(
                trade=trade,
                chart_price_usd=float(candle["close"]),
                candle_time=candle["datetime"],
            )
        )
    return plot_trades


def weighted_average_chart_price(plot_trades: list[PlotTrade], side: str) -> float | None:
    filtered = [item for item in plot_trades if item.trade.side == side]
    total_amount = sum(item.trade.amount for item in filtered)
    if total_amount <= 0:
        return None
    return sum(item.trade.amount * item.chart_price_usd for item in filtered) / total_amount


def fetch_top_pool(token_address: str) -> PoolInfo:
    url = f"{GECKO_ROOT}/networks/{GECKO_NETWORK}/tokens/{token_address}/pools?page=1"
    payload = rate_limited_get_json(url)
    pools = payload.get("data") or []
    if not pools:
        raise RuntimeError(f"No pool found on GeckoTerminal for token {token_address}")

    best = pools[0]
    attributes = best.get("attributes", {})
    relationships = best.get("relationships", {})
    dex_data = ((relationships.get("dex") or {}).get("data") or {})

    return PoolInfo(
        address=attributes.get("address", ""),
        name=attributes.get("name") or attributes.get("base_token_price_quote_token") or token_address,
        price_usd=parse_float(attributes.get("token_price_usd")),
        reserve_usd=parse_float(attributes.get("reserve_in_usd")),
        dex_name=dex_data.get("id"),
    )


def parse_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_ohlcv(pool: PoolInfo, start: datetime, end: datetime) -> tuple[list[dict], CandleConfig]:
    config = choose_candle_config(start, end)
    from_dt = start - config.padding_before
    to_dt = end + config.padding_after

    before_timestamp = int(to_dt.timestamp()) + 1
    earliest_needed = int(from_dt.timestamp())
    candles_by_ts: dict[int, dict] = {}

    for _ in range(20):
        query = urllib.parse.urlencode(
            {
                "aggregate": config.aggregate,
                "limit": config.limit,
                "before_timestamp": before_timestamp,
                "currency": "usd",
            }
        )
        url = (
            f"{GECKO_ROOT}/networks/{GECKO_NETWORK}/pools/"
            f"{pool.address}/ohlcv/{config.timeframe}?{query}"
        )
        payload = rate_limited_get_json(url)
        ohlcv_list = ((payload.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        if not ohlcv_list:
            break

        for ts, open_, high, low, close, volume in ohlcv_list:
            candles_by_ts[int(ts)] = {
                "timestamp": int(ts),
                "datetime": datetime.fromtimestamp(int(ts), UTC).isoformat().replace("+00:00", "Z"),
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume),
            }

        oldest_ts = min(int(entry[0]) for entry in ohlcv_list)
        if oldest_ts <= earliest_needed or len(ohlcv_list) < config.limit:
            break
        before_timestamp = oldest_ts

    candles = sorted(candles_by_ts.values(), key=lambda candle: candle["timestamp"])
    candles = [candle for candle in candles if earliest_needed <= candle["timestamp"] <= int(to_dt.timestamp())]
    if not candles:
        raise RuntimeError(f"No OHLCV candles returned for pool {pool.address}")

    return candles, config


def build_trade_markers(plot_trades: list[PlotTrade], side: str) -> dict:
    selected = [item for item in plot_trades if item.trade.side == side]
    symbol = "triangle-up" if side == "BUY" else "triangle-down"
    color = "#19c37d" if side == "BUY" else "#ff5a5f"
    return {
        "type": "scatter",
        "mode": "markers",
        "name": side.title(),
        "x": [item.trade.timestamp.isoformat() for item in selected],
        "y": [item.chart_price_usd for item in selected],
        "marker": {
            "size": 13,
            "symbol": symbol,
            "color": color,
            "line": {"width": 1, "color": "#111827"},
        },
        "text": [
            (
                f"{side}<br>"
                f"Chart price: {item.chart_price_usd:.8f} USD<br>"
                f"Logged price: {item.trade.price_eur:.8f} EUR<br>"
                f"Amount: {item.trade.amount:.4f}<br>"
                f"Value: {item.trade.value_eur:.2f} EUR<br>"
                f"Trade time: {item.trade.timestamp.isoformat(sep=' ', timespec='seconds')}<br>"
                f"Nearest candle: {item.candle_time}"
            )
            for item in selected
        ],
        "hovertemplate": "%{text}<extra></extra>",
    }


def build_shapes(summary: dict, first_x: str, last_x: str) -> list[dict]:
    shapes = []
    shapes.append(
        {
            "type": "rect",
            "xref": "x",
            "yref": "paper",
            "x0": summary["first_trade_at"].isoformat(),
            "x1": summary["last_trade_at"].isoformat(),
            "y0": 0,
            "y1": 1,
            "fillcolor": "rgba(59, 130, 246, 0.08)",
            "line": {"width": 0},
            "layer": "below",
        }
    )
    if summary["avg_buy"] is not None:
        shapes.append(
            {
                "type": "line",
                "xref": "x",
                "yref": "y",
                "x0": first_x,
                "x1": last_x,
                "y0": summary["avg_buy"],
                "y1": summary["avg_buy"],
                "line": {"color": "#19c37d", "width": 2, "dash": "dash"},
            }
        )
    if summary["avg_sell"] is not None:
        shapes.append(
            {
                "type": "line",
                "xref": "x",
                "yref": "y",
                "x0": first_x,
                "x1": last_x,
                "y0": summary["avg_sell"],
                "y1": summary["avg_sell"],
                "line": {"color": "#ff5a5f", "width": 2, "dash": "dot"},
            }
        )
    return shapes


def build_annotations(summary: dict, first_x: str, last_x: str) -> list[dict]:
    annotations = []
    if summary["first_trade_at"] != summary["last_trade_at"]:
        annotations.append(
            {
                "x": summary["first_trade_at"].isoformat(),
                "y": 1,
                "xref": "x",
                "yref": "paper",
                "text": "Trade window",
                "showarrow": False,
                "yshift": 16,
                "font": {"color": "#93c5fd", "size": 11},
                "bgcolor": "rgba(15, 23, 42, 0.72)",
            }
        )
    if summary["avg_buy"] is not None:
        annotations.append(
            {
                "x": last_x,
                "y": summary["avg_buy"],
                "xref": "x",
                "yref": "y",
                "text": f"Avg Buy {summary['avg_buy']:.8f} EUR",
                "showarrow": False,
                "xanchor": "left",
                "font": {"color": "#19c37d"},
                "bgcolor": "rgba(15, 23, 42, 0.72)",
            }
        )
    if summary["avg_sell"] is not None:
        annotations.append(
            {
                "x": first_x,
                "y": summary["avg_sell"],
                "xref": "x",
                "yref": "y",
                "text": f"Avg Sell {summary['avg_sell']:.8f} EUR",
                "showarrow": False,
                "xanchor": "right",
                "font": {"color": "#ff5a5f"},
                "bgcolor": "rgba(15, 23, 42, 0.72)",
            }
        )
    return annotations


def compute_focus_range(summary: dict, candles: list[dict], config: CandleConfig) -> tuple[str, str]:
    candle_start = datetime.fromisoformat(candles[0]["datetime"].replace("Z", "+00:00"))
    candle_end = datetime.fromisoformat(candles[-1]["datetime"].replace("Z", "+00:00"))
    trade_start = summary["first_trade_at"]
    trade_end = summary["last_trade_at"]
    trade_span_seconds = max((trade_end - trade_start).total_seconds(), 0.0)
    step_seconds = timeframe_seconds(config)

    context_seconds = max(step_seconds * 20, trade_span_seconds * 0.75, step_seconds * 6)
    focus_start = max(candle_start, trade_start - timedelta(seconds=context_seconds))
    focus_end = min(candle_end, trade_end + timedelta(seconds=context_seconds))

    if focus_start >= focus_end:
        fallback = timedelta(seconds=max(step_seconds * 30, 3600))
        focus_start = max(candle_start, trade_start - fallback)
        focus_end = min(candle_end, trade_end + fallback)

    return (
        focus_start.isoformat().replace("+00:00", "Z"),
        focus_end.isoformat().replace("+00:00", "Z"),
    )


def compute_event_focus(trades: list[TradeRecord], config: CandleConfig, side: str) -> tuple[str, str] | None:
    selected = [trade for trade in trades if trade.side == side]
    if not selected:
        return None

    first = selected[0].timestamp
    last = selected[-1].timestamp
    span_seconds = max((last - first).total_seconds(), 0.0)
    step_seconds = timeframe_seconds(config)
    padding_seconds = max(step_seconds * 12, span_seconds * 0.6, step_seconds * 4)
    return (
        (first - timedelta(seconds=padding_seconds)).isoformat(),
        (last + timedelta(seconds=padding_seconds)).isoformat(),
    )


def render_html(
    session_path: Path,
    output_path: Path,
    token: str,
    trades: list[TradeRecord],
    candles: list[dict],
    pool: PoolInfo,
    config: CandleConfig,
) -> None:
    summary = summarize_trades(trades)
    plot_trades = build_plot_trades(trades, candles)
    avg_buy_chart = weighted_average_chart_price(plot_trades, "BUY")
    avg_sell_chart = weighted_average_chart_price(plot_trades, "SELL")
    x_values = [candle["datetime"] for candle in candles]
    first_x = x_values[0]
    last_x = x_values[-1]
    focus_start, focus_end = compute_focus_range(summary, candles, config)
    buy_focus = compute_event_focus(trades, config, "BUY")
    sell_focus = compute_event_focus(trades, config, "SELL")

    candle_trace = {
        "type": "candlestick",
        "name": "Price",
        "x": x_values,
        "open": [candle["open"] for candle in candles],
        "high": [candle["high"] for candle in candles],
        "low": [candle["low"] for candle in candles],
        "close": [candle["close"] for candle in candles],
        "increasing": {"line": {"color": "#19c37d"}},
        "decreasing": {"line": {"color": "#ff5a5f"}},
    }

    buy_markers = build_trade_markers(plot_trades, "BUY")
    sell_markers = build_trade_markers(plot_trades, "SELL")

    metadata_lines = [
        f"Session: {session_path.name}",
        f"Token: {token}",
        f"Pool: {pool.name}",
        f"Candle source: GeckoTerminal {config.timeframe} x{config.aggregate}",
        f"Trades: {summary['buy_count']} buys / {summary['sell_count']} sells",
        f"Realized PnL: {summary['realized_pnl']:+.2f} EUR",
        f"Focus starts at: {summary['first_trade_at'].isoformat(sep=' ', timespec='minutes')}",
    ]
    if avg_buy_chart is not None:
        metadata_lines.append(f"Avg buy on chart: {avg_buy_chart:.8f} USD")
    if avg_sell_chart is not None:
        metadata_lines.append(f"Avg sell on chart: {avg_sell_chart:.8f} USD")
    if pool.reserve_usd is not None:
        metadata_lines.append(f"Pool liquidity: ${pool.reserve_usd:,.0f}")

    layout = {
        "paper_bgcolor": "#07111f",
        "plot_bgcolor": "#07111f",
        "font": {"color": "#d1d5db", "family": "Arial, sans-serif"},
        "title": {
            "text": f"{token} - trade chart",
            "font": {"size": 22},
        },
        "margin": {"l": 60, "r": 80, "t": 70, "b": 50},
        "xaxis": {
            "title": "Time",
            "rangeslider": {"visible": False},
            "gridcolor": "rgba(148, 163, 184, 0.12)",
            "range": [focus_start, focus_end],
        },
        "yaxis": {
            "title": "Price (USD from GeckoTerminal)",
            "gridcolor": "rgba(148, 163, 184, 0.12)",
            "tickformat": ".8f",
        },
        "legend": {"orientation": "h", "y": 1.08, "x": 0},
        "shapes": build_shapes(
            {
                **summary,
                "avg_buy": avg_buy_chart,
                "avg_sell": avg_sell_chart,
            },
            first_x,
            last_x,
        ),
        "annotations": build_annotations(
            {
                **summary,
                "avg_buy": avg_buy_chart,
                "avg_sell": avg_sell_chart,
            },
            first_x,
            last_x,
        ),
        "hovermode": "x unified",
    }

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{token} trade chart</title>
  <script src="{PLOTLY_CDN}"></script>
  <style>
    body {{
      margin: 0;
      background: #030712;
      color: #e5e7eb;
      font-family: Arial, sans-serif;
    }}
    .wrap {{
      max-width: 1400px;
      margin: 0 auto;
      padding: 24px;
    }}
    .meta {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .card {{
      background: linear-gradient(180deg, #0f172a, #09101d);
      border: 1px solid rgba(148, 163, 184, 0.18);
      border-radius: 14px;
      padding: 14px 16px;
    }}
    .card strong {{
      display: block;
      color: #93c5fd;
      margin-bottom: 6px;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 14px;
    }}
    .toolbar button {{
      background: linear-gradient(180deg, #13233d, #0c172a);
      color: #e5e7eb;
      border: 1px solid rgba(148, 163, 184, 0.22);
      border-radius: 999px;
      padding: 10px 14px;
      cursor: pointer;
      font-size: 14px;
    }}
    .toolbar button:hover {{
      border-color: rgba(96, 165, 250, 0.7);
      color: #bfdbfe;
    }}
    #chart {{
      height: 78vh;
      min-height: 640px;
      border-radius: 18px;
      overflow: hidden;
      border: 1px solid rgba(148, 163, 184, 0.18);
      background: linear-gradient(180deg, #0b1323, #060b15);
    }}
    .note {{
      margin-top: 14px;
      color: #94a3b8;
      font-size: 14px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="meta">
      {"".join(f'<div class="card"><strong>Info</strong>{line}</div>' for line in metadata_lines)}
    </div>
    <div class="toolbar">
      <button type="button" onclick="focusTrades()">Trade Focus</button>
      <button type="button" onclick="showAll()">Full History</button>
      <button type="button" onclick="focusBuys()">Buy Cluster</button>
      <button type="button" onclick="focusSells()">Sell Cluster</button>
    </div>
    <div id="chart"></div>
    <div class="note">
      Die Chart startet automatisch im Trade-Zeitraum, damit du nicht erst weit nach links scrollen musst.
    </div>
    <div class="note">
      Die Marker werden fuer die Darstellung auf den naechsten Candle-Preis gelegt, damit Entries und Exits sauber auf der Chart sitzen. Der originale Log-Preis bleibt im Tooltip sichtbar.
    </div>
  </div>
  <script>
    const data = {json.dumps([candle_trace, buy_markers, sell_markers])};
    const layout = {json.dumps(layout)};
    const fullRange = {json.dumps([first_x, last_x])};
    const tradeFocusRange = {json.dumps([focus_start, focus_end])};
    const buyFocusRange = {json.dumps(list(buy_focus) if buy_focus else None)};
    const sellFocusRange = {json.dumps(list(sell_focus) if sell_focus else None)};

    function setRange(range) {{
      if (!range) return;
      Plotly.relayout('chart', {{
        'xaxis.range': range,
        'yaxis.autorange': true
      }});
    }}

    function focusTrades() {{
      setRange(tradeFocusRange);
    }}

    function showAll() {{
      setRange(fullRange);
    }}

    function focusBuys() {{
      setRange(buyFocusRange || tradeFocusRange);
    }}

    function focusSells() {{
      setRange(sellFocusRange || tradeFocusRange);
    }}

    Plotly.newPlot('chart', data, layout, {{responsive: true, displaylogo: false}}).then(() => {{
      focusTrades();
    }});
  </script>
</body>
</html>
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def sanitize_token(token: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in token)[:64]


def build_output_path(session_path: Path, token: str, output: str | None) -> Path:
    if output:
        return Path(output).expanduser().resolve()
    charts_dir = session_path.parent.parent / "charts"
    return (charts_dir / f"{session_path.stem}__{sanitize_token(token)}.html").resolve()


def select_tokens(grouped: dict[str, list[TradeRecord]], args: argparse.Namespace) -> list[str]:
    if args.all_tokens:
        return sorted(grouped.keys())
    if args.token:
        if args.token not in grouped:
            available = ", ".join(sorted(grouped))
            raise SystemExit(f"Token not found in session: {args.token}\nAvailable tokens: {available}")
        return [args.token]
    if len(grouped) == 1:
        return list(grouped.keys())
    available = "\n".join(f"  - {token} ({len(trades)} trades)" for token, trades in sorted(grouped.items()))
    raise SystemExit(
        "The session contains multiple tokens. Please pass --token <address> or --all-tokens.\n"
        f"Available tokens:\n{available}"
    )


def maybe_open(path: Path, should_open: bool) -> None:
    if not should_open:
        return
    import subprocess

    subprocess.run(["open", str(path)], check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize Copybot trade JSON on a coin chart.")
    parser.add_argument("session_json", help="Path to paper_trading / paper_mainnet JSON file")
    parser.add_argument("--token", help="Specific token address to visualize")
    parser.add_argument("--all-tokens", action="store_true", help="Generate one HTML chart per token in the session")
    parser.add_argument("--output", help="Optional output path for single-token mode")
    parser.add_argument("--open", action="store_true", help="Open generated chart(s) in the browser")
    args = parser.parse_args()

    session_path = Path(args.session_json).expanduser().resolve()
    if not session_path.exists():
        raise SystemExit(f"Session JSON not found: {session_path}")

    session = load_session(session_path)
    grouped = group_trades_by_token(session.get("trade_history") or [])
    if not grouped:
        raise SystemExit(f"No trade_history found in {session_path.name}")

    selected_tokens = select_tokens(grouped, args)
    generated_files: list[Path] = []

    for token in selected_tokens:
        trades = grouped[token]
        first_trade = min(trade.timestamp for trade in trades)
        last_trade = max(trade.timestamp for trade in trades)

        try:
            pool = fetch_top_pool(token)
            candles, config = fetch_ohlcv(pool, first_trade, last_trade)
        except Exception as exc:
            print(f"[skip] {token}: {exc}")
            continue

        output_path = build_output_path(session_path, token, args.output if len(selected_tokens) == 1 else None)
        render_html(session_path, output_path, token, trades, candles, pool, config)
        generated_files.append(output_path)
        print(f"[ok] {token} -> {output_path}")

    if not generated_files:
        raise SystemExit("No charts generated. This often happens for fake tokens or tokens with no pool data.")

    if args.open:
        for path in generated_files:
            maybe_open(path, True)


if __name__ == "__main__":
    main()
