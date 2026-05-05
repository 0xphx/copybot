#!/usr/bin/env python3
"""
Standalone trade log viewer for Copybot JSON sessions.

This tool intentionally lives outside the copybot project.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Iterable


GECKO_ROOT = "https://api.geckoterminal.com/api/v2"
FRANKFURTER_ROOT = "https://api.frankfurter.app"
NETWORK = "solana"
PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"
LOCAL_TZ = datetime.now().astimezone().tzinfo or UTC
REQUEST_GAP_SECONDS = 2.1
DEFAULT_COPYBOT_DATA_DIR = (Path(__file__).resolve().parent.parent / "bot" / "data").resolve()
CACHE_DIR = (Path(__file__).resolve().parent / ".cache").resolve()
GECKO_HISTORY_TTL_SECONDS = 365 * 24 * 3600
GECKO_POOL_TTL_SECONDS = 12 * 3600
FX_HISTORY_TTL_SECONDS = 365 * 24 * 3600

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
class CandleConfig:
    timeframe: str
    aggregate: int
    limit: int
    padding_before: timedelta
    padding_after: timedelta


@dataclass
class PoolInfo:
    address: str
    name: str
    reserve_usd: float | None
    token_price_usd: float | None


@dataclass
class PlotTrade:
    trade: TradeRecord
    marker_price: float
    marker_currency: str
    nearest_candle_time: str
    logged_price_display: float
    delta_percent: float | None


@dataclass
class DashboardRow:
    session_name: str
    session_path: Path
    token: str
    buy_count: int
    sell_count: int
    realized_pnl_eur: float
    first_trade_at: datetime
    last_trade_at: datetime


class ChartUnavailableError(RuntimeError):
    pass


def rate_limited_get_json(url: str) -> dict:
    global _LAST_REQUEST_AT
    cache_file = get_cache_file(url)
    ttl_seconds = get_cache_ttl_seconds(url)

    cached_payload = read_cache(cache_file, ttl_seconds)
    if cached_payload is not None:
        return cached_payload

    wait_seconds = REQUEST_GAP_SECONDS - (time.monotonic() - _LAST_REQUEST_AT)
    if wait_seconds > 0:
        time.sleep(wait_seconds)

    last_error: Exception | None = None

    for attempt in range(4):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "accept": "application/json",
                    "user-agent": "Mozilla/5.0 (compatible; trade-log-viewer/1.0)",
                },
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            _LAST_REQUEST_AT = time.monotonic()
            write_cache(cache_file, payload)
            return payload
        except urllib.error.HTTPError as exc:
            last_error = exc
            stale_payload = read_cache(cache_file, None)
            if stale_payload is not None and exc.code in (429, 500, 502, 503, 504):
                return stale_payload
            if exc.code != 429 or attempt == 3:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            sleep_seconds = float(retry_after) if retry_after else min(20.0, 2.5 * (attempt + 1))
            time.sleep(sleep_seconds)
        except Exception as exc:
            last_error = exc
            stale_payload = read_cache(cache_file, None)
            if stale_payload is not None:
                return stale_payload
            if attempt == 3:
                raise
            time.sleep(min(10.0, 1.5 * (attempt + 1)))

    if last_error:
        raise last_error
    raise RuntimeError(f"Unexpected fetch failure for {url}")


def get_cache_file(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def get_cache_ttl_seconds(url: str) -> int:
    if url.startswith(FRANKFURTER_ROOT):
        return FX_HISTORY_TTL_SECONDS
    if "/ohlcv/" in url:
        return GECKO_HISTORY_TTL_SECONDS
    return GECKO_POOL_TTL_SECONDS


def read_cache(cache_file: Path, ttl_seconds: int | None) -> dict | None:
    if not cache_file.exists():
        return None
    if ttl_seconds is not None:
        age_seconds = time.time() - cache_file.stat().st_mtime
        if age_seconds > ttl_seconds:
            return None
    try:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_cache(cache_file: Path, payload: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(payload), encoding="utf-8")


def parse_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
        pnl_eur=parse_float(item.get("pnl_eur")),
        pnl_percent=parse_float(item.get("pnl_percent")),
    )


def load_session(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def find_session_files(source_dir: Path) -> list[Path]:
    session_files = list(source_dir.glob("paper_mainnet_*.json")) + list(source_dir.glob("paper_trading_*.json"))
    return sorted(session_files, reverse=True)


def group_trades_by_token(trade_history: Iterable[dict]) -> dict[str, list[TradeRecord]]:
    grouped: dict[str, list[TradeRecord]] = defaultdict(list)
    for item in trade_history:
        trade = parse_trade(item)
        grouped[trade.token].append(trade)
    for token in grouped:
        grouped[token].sort(key=lambda trade: trade.timestamp)
    return dict(grouped)


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
        "Session contains multiple tokens. Pass --token <address> or --all-tokens.\n"
        f"Available tokens:\n{available}"
    )


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


def timeframe_seconds(config: CandleConfig) -> int:
    if config.timeframe == "minute":
        return 60 * config.aggregate
    if config.timeframe == "hour":
        return 3600 * config.aggregate
    if config.timeframe == "day":
        return 86400 * config.aggregate
    return 60


def pool_info_from_api_item(item: dict, fallback_name: str) -> PoolInfo:
    attributes = item.get("attributes") or {}
    return PoolInfo(
        address=attributes.get("address", ""),
        name=attributes.get("name") or fallback_name,
        reserve_usd=parse_float(attributes.get("reserve_in_usd")),
        token_price_usd=parse_float(attributes.get("token_price_usd")),
    )


def fetch_candidate_pools(identifier: str) -> list[PoolInfo]:
    token_url = f"{GECKO_ROOT}/networks/{NETWORK}/tokens/{identifier}/pools?page=1"
    try:
        payload = rate_limited_get_json(token_url)
        pools = payload.get("data") or []
        if pools:
            return [pool_info_from_api_item(item, identifier) for item in pools]
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise

    pool_url = f"{GECKO_ROOT}/networks/{NETWORK}/pools/{identifier}"
    try:
        payload = rate_limited_get_json(pool_url)
        item = payload.get("data")
        if item:
            return [pool_info_from_api_item(item, identifier)]
    except urllib.error.HTTPError:
        pass

    raise ChartUnavailableError(f"No GeckoTerminal token or pool found for identifier {identifier}")


def fetch_ohlcv(pool: PoolInfo, start: datetime, end: datetime, token_address: str | None = None) -> tuple[list[dict], CandleConfig]:
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
                **({"token": token_address} if token_address else {}),
            }
        )
        url = f"{GECKO_ROOT}/networks/{NETWORK}/pools/{pool.address}/ohlcv/{config.timeframe}?{query}"
        payload = rate_limited_get_json(url)
        ohlcv_list = ((payload.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        if not ohlcv_list:
            break

        for ts, open_, high, low, close, volume in ohlcv_list:
            candles_by_ts[int(ts)] = {
                "timestamp": int(ts),
                "datetime": datetime.fromtimestamp(int(ts), UTC).isoformat().replace("+00:00", "Z"),
                "open_usd": float(open_),
                "high_usd": float(high),
                "low_usd": float(low),
                "close_usd": float(close),
                "volume": float(volume),
            }

        oldest_ts = min(int(row[0]) for row in ohlcv_list)
        if oldest_ts <= earliest_needed or len(ohlcv_list) < config.limit:
            break
        before_timestamp = oldest_ts

    candles = sorted(candles_by_ts.values(), key=lambda candle: candle["timestamp"])
    candles = [c for c in candles if earliest_needed <= c["timestamp"] <= int(to_dt.timestamp())]
    if not candles:
        raise ChartUnavailableError(f"No OHLCV candles returned for pool {pool.address}")
    return candles, config


def fetch_best_pool_and_ohlcv(identifier: str, start: datetime, end: datetime) -> tuple[PoolInfo, list[dict], CandleConfig]:
    pools = fetch_candidate_pools(identifier)
    errors: list[str] = []

    for pool in pools[:8]:
        try:
            candles, config = fetch_ohlcv(pool, start, end, token_address=identifier)
            return pool, candles, config
        except Exception as exc:
            errors.append(f"{pool.address} ({pool.name}): {exc}")

    details = "\n".join(errors[:8]) if errors else "No candidate pools tried."
    raise ChartUnavailableError(f"Could not load historical candles for {identifier}.\n{details}")


def fetch_fx_rates(start_date: date, end_date: date, display_currency: str) -> dict[str, float]:
    if display_currency == "USD":
        return {}
    if display_currency != "EUR":
        raise RuntimeError(f"Unsupported display currency: {display_currency}")

    query = urllib.parse.urlencode({"from": "USD", "to": "EUR"})
    url = f"{FRANKFURTER_ROOT}/{start_date.isoformat()}..{end_date.isoformat()}?{query}"
    payload = rate_limited_get_json(url)
    rates = payload.get("rates") or {}
    result = {day: float(values["EUR"]) for day, values in rates.items() if "EUR" in values}
    if not result:
        raise RuntimeError("No FX rates returned from Frankfurter")
    return result


def convert_usd_to_display(usd_value: float, day_key: str, display_currency: str, fx_rates: dict[str, float]) -> float:
    if display_currency == "USD":
        return usd_value
    rate = fx_rates.get(day_key)
    if rate is None:
        previous_days = sorted(key for key in fx_rates if key <= day_key)
        if not previous_days:
            next_days = sorted(key for key in fx_rates if key >= day_key)
            if not next_days:
                raise RuntimeError(f"No FX rate available for {day_key}")
            rate = fx_rates[next_days[0]]
        else:
            rate = fx_rates[previous_days[-1]]
    return usd_value * rate


def convert_eur_to_display(eur_value: float, day_key: str, display_currency: str, fx_rates: dict[str, float]) -> float:
    if display_currency == "EUR":
        return eur_value
    if display_currency == "USD":
        rate = fx_rates.get(day_key)
        if rate is None or rate == 0:
            previous_days = sorted(key for key in fx_rates if key <= day_key)
            if not previous_days:
                raise RuntimeError(f"No FX rate available for {day_key}")
            rate = fx_rates[previous_days[-1]]
        return eur_value / rate
    raise RuntimeError(f"Unsupported display currency: {display_currency}")


def normalize_candles(candles: list[dict], display_currency: str, fx_rates: dict[str, float]) -> list[dict]:
    normalized = []
    for candle in candles:
        day_key = candle["datetime"][:10]
        normalized.append(
            {
                **candle,
                "open_display": convert_usd_to_display(candle["open_usd"], day_key, display_currency, fx_rates),
                "high_display": convert_usd_to_display(candle["high_usd"], day_key, display_currency, fx_rates),
                "low_display": convert_usd_to_display(candle["low_usd"], day_key, display_currency, fx_rates),
                "close_display": convert_usd_to_display(candle["close_usd"], day_key, display_currency, fx_rates),
            }
        )
    return normalized


def summarize_trades(trades: list[TradeRecord]) -> dict:
    buys = [trade for trade in trades if trade.side == "BUY"]
    sells = [trade for trade in trades if trade.side == "SELL"]
    return {
        "buy_count": len(buys),
        "sell_count": len(sells),
        "realized_pnl_eur": sum(trade.pnl_eur or 0.0 for trade in sells),
        "first_trade_at": min(trade.timestamp for trade in trades),
        "last_trade_at": max(trade.timestamp for trade in trades),
    }


def collect_dashboard_rows(source_dir: Path) -> list[DashboardRow]:
    rows: list[DashboardRow] = []
    for session_path in find_session_files(source_dir):
        try:
            session = load_session(session_path)
            grouped = group_trades_by_token(session.get("trade_history") or [])
        except Exception:
            continue

        for token, trades in grouped.items():
            summary = summarize_trades(trades)
            rows.append(
                DashboardRow(
                    session_name=session_path.name,
                    session_path=session_path,
                    token=token,
                    buy_count=summary["buy_count"],
                    sell_count=summary["sell_count"],
                    realized_pnl_eur=summary["realized_pnl_eur"],
                    first_trade_at=summary["first_trade_at"],
                    last_trade_at=summary["last_trade_at"],
                )
            )

    rows.sort(key=lambda row: row.last_trade_at, reverse=True)
    return rows


def nearest_candle_for_trade(trade: TradeRecord, candles: list[dict]) -> dict:
    trade_ts = trade.timestamp.astimezone(UTC).timestamp()
    return min(candles, key=lambda candle: abs(candle["timestamp"] - trade_ts))


def build_plot_trades(
    trades: list[TradeRecord],
    normalized_candles: list[dict],
    display_currency: str,
    fx_rates: dict[str, float],
) -> list[PlotTrade]:
    plot_trades: list[PlotTrade] = []
    for trade in trades:
        candle = nearest_candle_for_trade(trade, normalized_candles)
        day_key = trade.timestamp.astimezone(UTC).date().isoformat()
        logged_display = convert_eur_to_display(trade.price_eur, day_key, display_currency, fx_rates)
        marker_price = float(candle["close_display"])
        delta_percent = None
        if marker_price:
            delta_percent = ((logged_display - marker_price) / marker_price) * 100
        plot_trades.append(
            PlotTrade(
                trade=trade,
                marker_price=marker_price,
                marker_currency=display_currency,
                nearest_candle_time=candle["datetime"],
                logged_price_display=logged_display,
                delta_percent=delta_percent,
            )
        )
    return plot_trades


def weighted_average_chart_price(plot_trades: list[PlotTrade], side: str) -> float | None:
    selected = [item for item in plot_trades if item.trade.side == side]
    total_amount = sum(item.trade.amount for item in selected)
    if total_amount <= 0:
        return None
    return sum(item.trade.amount * item.marker_price for item in selected) / total_amount


def build_trade_markers(plot_trades: list[PlotTrade], side: str) -> dict:
    selected = [item for item in plot_trades if item.trade.side == side]
    return {
        "type": "scatter",
        "mode": "markers",
        "name": side.title(),
        "x": [item.trade.timestamp.isoformat() for item in selected],
        "y": [item.marker_price for item in selected],
        "marker": {
            "size": 13,
            "symbol": "triangle-up" if side == "BUY" else "triangle-down",
            "color": "#19c37d" if side == "BUY" else "#ff5a5f",
            "line": {"width": 1, "color": "#111827"},
        },
        "text": [
            (
                f"{side}<br>"
                f"Chart price: {item.marker_price:.8f} {item.marker_currency}<br>"
                f"Logged price: {item.logged_price_display:.8f} {item.marker_currency}<br>"
                f"Raw logged price: {item.trade.price_eur:.8f} EUR<br>"
                f"Amount: {item.trade.amount:.4f}<br>"
                f"Time: {item.trade.timestamp.isoformat(sep=' ', timespec='seconds')}<br>"
                f"Nearest candle: {item.nearest_candle_time}<br>"
                f"Delta: {item.delta_percent:+.2f}%"
            )
            for item in selected
        ],
        "hovertemplate": "%{text}<extra></extra>",
    }


def build_shapes(summary: dict, first_x: str, last_x: str, avg_buy: float | None, avg_sell: float | None) -> list[dict]:
    shapes = [
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
    ]
    if avg_buy is not None:
        shapes.append(
            {
                "type": "line",
                "xref": "x",
                "yref": "y",
                "x0": first_x,
                "x1": last_x,
                "y0": avg_buy,
                "y1": avg_buy,
                "line": {"color": "#19c37d", "width": 2, "dash": "dash"},
            }
        )
    if avg_sell is not None:
        shapes.append(
            {
                "type": "line",
                "xref": "x",
                "yref": "y",
                "x0": first_x,
                "x1": last_x,
                "y0": avg_sell,
                "y1": avg_sell,
                "line": {"color": "#ff5a5f", "width": 2, "dash": "dot"},
            }
        )
    return shapes


def build_annotations(summary: dict, first_x: str, last_x: str, avg_buy: float | None, avg_sell: float | None, currency: str) -> list[dict]:
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
    if avg_buy is not None:
        annotations.append(
            {
                "x": last_x,
                "y": avg_buy,
                "xref": "x",
                "yref": "y",
                "text": f"Avg Buy {avg_buy:.8f} {currency}",
                "showarrow": False,
                "xanchor": "left",
                "font": {"color": "#19c37d"},
                "bgcolor": "rgba(15, 23, 42, 0.72)",
            }
        )
    if avg_sell is not None:
        annotations.append(
            {
                "x": first_x,
                "y": avg_sell,
                "xref": "x",
                "yref": "y",
                "text": f"Avg Sell {avg_sell:.8f} {currency}",
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
    trade_start = summary["first_trade_at"].astimezone(UTC)
    trade_end = summary["last_trade_at"].astimezone(UTC)
    trade_span_seconds = max((trade_end - trade_start).total_seconds(), 0.0)
    step_seconds = timeframe_seconds(config)
    context_seconds = max(step_seconds * 20, trade_span_seconds * 0.75, step_seconds * 6)
    focus_start = max(candle_start, trade_start - timedelta(seconds=context_seconds))
    focus_end = min(candle_end, trade_end + timedelta(seconds=context_seconds))
    return (
        focus_start.isoformat().replace("+00:00", "Z"),
        focus_end.isoformat().replace("+00:00", "Z"),
    )


def compute_event_focus(plot_trades: list[PlotTrade], config: CandleConfig, side: str) -> tuple[str, str] | None:
    selected = [item for item in plot_trades if item.trade.side == side]
    if not selected:
        return None
    first = selected[0].trade.timestamp.astimezone(UTC)
    last = selected[-1].trade.timestamp.astimezone(UTC)
    span_seconds = max((last - first).total_seconds(), 0.0)
    step_seconds = timeframe_seconds(config)
    padding_seconds = max(step_seconds * 12, span_seconds * 0.6, step_seconds * 4)
    return (
        (first - timedelta(seconds=padding_seconds)).isoformat().replace("+00:00", "Z"),
        (last + timedelta(seconds=padding_seconds)).isoformat().replace("+00:00", "Z"),
    )


def sanitize_token(token: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in token)[:64]


def build_output_path(base_dir: Path, session_path: Path, token: str, output: str | None) -> Path:
    if output:
        return Path(output).expanduser().resolve()
    out_dir = base_dir / "out"
    return (out_dir / f"{session_path.stem}__{sanitize_token(token)}.html").resolve()


def generate_chart(
    base_dir: Path,
    session_path: Path,
    token: str,
    display_currency: str = "EUR",
    output: str | None = None,
) -> Path:
    session = load_session(session_path)
    grouped = group_trades_by_token(session.get("trade_history") or [])
    if token not in grouped:
        raise RuntimeError(f"Token not found in session {session_path.name}: {token}")

    trades = grouped[token]
    summary = summarize_trades(trades)
    pool, candles, config = fetch_best_pool_and_ohlcv(token, summary["first_trade_at"], summary["last_trade_at"])

    candle_dates = [datetime.fromisoformat(candle["datetime"].replace("Z", "+00:00")).date() for candle in candles]
    trade_dates = [trade.timestamp.astimezone(UTC).date() for trade in trades]
    start_date = min(candle_dates + trade_dates)
    end_date = max(candle_dates + trade_dates)

    usd_to_eur_rates = fetch_fx_rates(start_date, end_date, "EUR")
    normalized_candles = normalize_candles(candles, display_currency, usd_to_eur_rates)
    plot_trades = build_plot_trades(trades, normalized_candles, display_currency, usd_to_eur_rates)

    output_path = build_output_path(base_dir, session_path, token, output)
    render_html(output_path, session_path, token, pool, config, normalized_candles, plot_trades, summary, display_currency)
    return output_path


def render_html(
    output_path: Path,
    session_path: Path,
    token: str,
    pool: PoolInfo,
    config: CandleConfig,
    normalized_candles: list[dict],
    plot_trades: list[PlotTrade],
    summary: dict,
    display_currency: str,
) -> None:
    x_values = [candle["datetime"] for candle in normalized_candles]
    first_x = x_values[0]
    last_x = x_values[-1]
    focus_start, focus_end = compute_focus_range(summary, normalized_candles, config)
    buy_focus = compute_event_focus(plot_trades, config, "BUY")
    sell_focus = compute_event_focus(plot_trades, config, "SELL")
    avg_buy = weighted_average_chart_price(plot_trades, "BUY")
    avg_sell = weighted_average_chart_price(plot_trades, "SELL")

    candle_trace = {
        "type": "candlestick",
        "name": "Price",
        "x": x_values,
        "open": [c["open_display"] for c in normalized_candles],
        "high": [c["high_display"] for c in normalized_candles],
        "low": [c["low_display"] for c in normalized_candles],
        "close": [c["close_display"] for c in normalized_candles],
        "increasing": {"line": {"color": "#19c37d"}},
        "decreasing": {"line": {"color": "#ff5a5f"}},
    }

    buy_markers = build_trade_markers(plot_trades, "BUY")
    sell_markers = build_trade_markers(plot_trades, "SELL")

    metadata_lines = [
        f"Session: {session_path.name}",
        f"Token: {token}",
        f"Pool: {pool.name}",
        f"Display currency: {display_currency}",
        f"Candle source: GeckoTerminal {config.timeframe} x{config.aggregate}",
        f"FX source: Frankfurter (ECB reference)",
        f"Trades: {summary['buy_count']} buys / {summary['sell_count']} sells",
        f"Realized PnL: {summary['realized_pnl_eur']:+.2f} EUR",
    ]
    if avg_buy is not None:
        metadata_lines.append(f"Avg buy on chart: {avg_buy:.8f} {display_currency}")
    if avg_sell is not None:
        metadata_lines.append(f"Avg sell on chart: {avg_sell:.8f} {display_currency}")
    if pool.reserve_usd is not None:
        metadata_lines.append(f"Pool liquidity: ${pool.reserve_usd:,.0f}")

    layout = {
        "paper_bgcolor": "#07111f",
        "plot_bgcolor": "#07111f",
        "font": {"color": "#d1d5db", "family": "Arial, sans-serif"},
        "title": {"text": f"{token} - trade chart", "font": {"size": 22}},
        "margin": {"l": 60, "r": 80, "t": 70, "b": 50},
        "xaxis": {
            "title": "Time",
            "rangeslider": {"visible": False},
            "gridcolor": "rgba(148, 163, 184, 0.12)",
            "range": [focus_start, focus_end],
        },
        "yaxis": {
            "title": f"Price ({display_currency})",
            "gridcolor": "rgba(148, 163, 184, 0.12)",
            "tickformat": ".8f",
        },
        "legend": {"orientation": "h", "y": 1.08, "x": 0},
        "shapes": build_shapes(summary, first_x, last_x, avg_buy, avg_sell),
        "annotations": build_annotations(summary, first_x, last_x, avg_buy, avg_sell, display_currency),
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
      <button type="button" onclick="scaleX(0.6)">X enger</button>
      <button type="button" onclick="scaleX(1.6)">X weiter</button>
      <button type="button" onclick="scaleY(0.6)">Y enger</button>
      <button type="button" onclick="scaleY(1.6)">Y weiter</button>
      <button type="button" onclick="resetAxes()">Reset Axes</button>
    </div>
    <div id="chart"></div>
    <div class="note">
      Alles wird in {display_currency} angezeigt. Candles und Marker teilen sich dieselbe Y-Achse.
    </div>
    <div class="note">
      Marker liegen absichtlich auf dem Chart-Preis der naechsten Candle, damit die Candles visuell korrekt bleiben. Der umgerechnete Log-Preis steht im Tooltip.
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

    function currentXRange() {{
      const layout = document.getElementById('chart').layout;
      return layout.xaxis.range || fullRange;
    }}

    function currentYRange() {{
      const layout = document.getElementById('chart').layout;
      return layout.yaxis.range;
    }}

    function scaleTimeRange(range, factor) {{
      const start = new Date(range[0]).getTime();
      const end = new Date(range[1]).getTime();
      const center = (start + end) / 2;
      const half = ((end - start) * factor) / 2;
      return [
        new Date(center - half).toISOString(),
        new Date(center + half).toISOString()
      ];
    }}

    function scaleNumericRange(range, factor) {{
      if (!range) return null;
      const min = Number(range[0]);
      const max = Number(range[1]);
      const center = (min + max) / 2;
      const half = ((max - min) * factor) / 2;
      return [center - half, center + half];
    }}

    function focusTrades() {{ setRange(tradeFocusRange); }}
    function showAll() {{ setRange(fullRange); }}
    function focusBuys() {{ setRange(buyFocusRange || tradeFocusRange); }}
    function focusSells() {{ setRange(sellFocusRange || tradeFocusRange); }}
    function scaleX(factor) {{
      Plotly.relayout('chart', {{
        'xaxis.range': scaleTimeRange(currentXRange(), factor)
      }});
    }}
    function scaleY(factor) {{
      const yRange = scaleNumericRange(currentYRange(), factor);
      if (!yRange) return;
      Plotly.relayout('chart', {{
        'yaxis.range': yRange
      }});
    }}
    function resetAxes() {{
      Plotly.relayout('chart', {{
        'xaxis.range': tradeFocusRange,
        'yaxis.autorange': true
      }});
    }}

    Plotly.newPlot('chart', data, layout, {{
      responsive: true,
      displaylogo: false,
      scrollZoom: true,
      doubleClick: 'reset+autosize'
    }}).then(() => {{
      focusTrades();
    }});
  </script>
</body>
</html>
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def maybe_open(path: Path, should_open: bool) -> None:
    if should_open:
        subprocess.run(["open", str(path)], check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone chart viewer for Copybot JSON logs.")
    parser.add_argument("session_json", help="Path to paper_trading / paper_mainnet JSON")
    parser.add_argument("--token", help="Specific token address to visualize")
    parser.add_argument("--all-tokens", action="store_true", help="Generate one chart per token")
    parser.add_argument("--display-currency", choices=["EUR", "USD"], default="EUR")
    parser.add_argument("--output", help="Optional output HTML path in single-token mode")
    parser.add_argument("--open", action="store_true", help="Open generated chart(s) in browser")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    session_path = Path(args.session_json).expanduser().resolve()
    if not session_path.exists():
        raise SystemExit(f"Session JSON not found: {session_path}")

    session = load_session(session_path)
    grouped = group_trades_by_token(session.get("trade_history") or [])
    if not grouped:
        raise SystemExit("No trade_history found in the session JSON")

    selected_tokens = select_tokens(grouped, args)
    generated_files: list[Path] = []

    for token in selected_tokens:
        output_path = generate_chart(
            base_dir,
            session_path,
            token,
            args.display_currency,
            args.output if len(selected_tokens) == 1 else None,
        )
        generated_files.append(output_path)
        print(f"[ok] {token} -> {output_path}")

    if not generated_files:
        raise SystemExit("No charts generated.")

    if args.open:
        for path in generated_files:
            maybe_open(path, True)


if __name__ == "__main__":
    main()
