"""Formatted Telegram message builders."""
from __future__ import annotations

from apps.manual_trading.models import Signal, Prediction, DURATION_OPTIONS


def format_signal(symbol: str, signal: Signal, entry_price: float) -> str:
    """Format a signal into a clean Telegram message."""
    direction_label = "CALL (Up)" if signal.direction == "call" else "PUT (Down)"
    direction_emoji = "CALL" if signal.direction == "call" else "PUT"

    lines = [
        f"{direction_emoji} {symbol.replace('_otc', ' (OTC)').replace('_', '/')}",
        f"",
        f"Direction: {direction_label}",
        f"Confidence: {signal.confidence:.0%}",
        f"Entry Price: {entry_price:.5f}",
        f"",
        "Analysis:",
    ]

    for bullet in signal.reasoning:
        lines.append(f"  - {bullet}")

    return "\n".join(lines)


def format_prediction_confirmed(prediction: Prediction) -> str:
    """Format confirmation after a prediction is saved."""
    symbol_display = prediction.symbol.replace("_otc", " (OTC)").replace("_", "/")
    direction_emoji = "CALL" if prediction.direction == "call" else "PUT"
    duration_label = _duration_label(prediction.timeframe_sec)

    return (
        f"Prediction Recorded\n\n"
        f"{direction_emoji} {symbol_display}\n"
        f"Entry: {float(prediction.entry_price):.5f}\n"
        f"Duration: {duration_label}\n"
        f"Expires: {prediction.expiry_time.strftime('%H:%M:%S UTC')}\n\n"
        f"Tracking price movement..."
    )


def format_prediction_expired(
    prediction: Prediction,
    result: str,
    exit_price: float,
) -> str:
    """Format a prediction result message."""
    symbol_display = prediction.symbol.replace("_otc", " (OTC)").replace("_", "/")
    direction_emoji = "CALL" if prediction.direction == "call" else "PUT"

    if result == "win":
        status = "WIN"
    elif result == "loss":
        status = "LOSS"
    else:
        status = "TIE"

    return (
        f"Prediction Result\n\n"
        f"{status} {direction_emoji} {symbol_display}\n"
        f"Entry: {float(prediction.entry_price):.5f}\n"
        f"Exit: {exit_price:.5f}\n"
        f"Confidence: {prediction.confidence:.0%}"
    )


def format_stats(stats: dict) -> str:
    """Format the /stats response."""
    total = stats["total"]
    wins = stats["wins"]
    losses = stats["losses"]
    win_rate = stats["win_rate"]

    lines = [
        "Trading Stats",
        "",
        f"Total Predictions: {total}",
        f"Wins: {wins} | Losses: {losses}",
        f"Win Rate: {win_rate:.1f}%",
    ]

    if stats["by_symbol"]:
        lines.append("")
        lines.append("By Symbol:")
        for s in stats["by_symbol"]:
            sym = s["symbol"].replace("_otc", " (OTC)").replace("_", "/")
            sr = (s["wins"] / s["total"] * 100) if s["total"] > 0 else 0
            lines.append(f"  {sym}: {s['wins']}/{s['total']} ({sr:.0f}%)")

    if stats["by_confidence"]:
        lines.append("")
        lines.append("By Confidence:")
        for c in stats["by_confidence"]:
            cr = (c["wins"] / c["total"] * 100) if c["total"] > 0 else 0
            lines.append(f"  {c['bucket']}: {c['wins']}/{c['total']} ({cr:.0f}%)")

    return "\n".join(lines)


def format_recent(predictions: list[dict]) -> str:
    """Format recent predictions."""
    if not predictions:
        return "No recent predictions."

    lines = ["Recent Predictions", ""]
    for p in predictions:
        sym = p["symbol"].replace("_otc", " (OTC)").replace("_", "/")
        d = "CALL" if p["direction"] == "call" else "PUT"
        result = (p.get("result") or "pending").upper()
        conf = f"{p.get('confidence', 0):.0%}" if p.get("confidence") else "N/A"
        lines.append(f"  [{result}] {d} {sym} | {conf}")

    return "\n".join(lines)


def _duration_label(seconds: int) -> str:
    for opt in DURATION_OPTIONS:
        if opt.seconds == seconds:
            return opt.label
    return f"{seconds}s"
