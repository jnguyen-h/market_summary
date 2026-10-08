"""Build index.html from watchlist.json + data/*.json. Run: python build.py"""
import json
import sys
from html import escape
from pathlib import Path

import pandas as pd

from signals import analyze

ROOT = Path(__file__).parent


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def fmt(n, d=0):
    return f"{n:,.{d}f}"


def pct_class(v):
    return "up" if v > 0 else "down" if v < 0 else "flat"


def pct(v):
    return f'<span class="{pct_class(v)}">{v:+.2f}%</span>'


def stock_rows(symbols, history):
    rows, missing = [], []
    for sym in symbols:
        bars = history["bars"].get(sym)
        if not bars:
            missing.append(sym)
            continue
        df = pd.DataFrame(bars, columns=history["fields"])
        close, prev = float(df["close"].iloc[-1]), float(df["close"].iloc[-2])
        res = analyze(df)
        rows.append({
            "symbol": sym, "close": close, "chg": (close / prev - 1) * 100,
            "signal": res.signal, "strength": res.strength,
            "entry": res.entry_price, "stop": res.stop_loss, "target": res.target_price,
            "why": ", ".join(res.indicators), "error": res.error,
        })
    return rows, missing


def render(market, rows, missing, as_of):
    idx = "".join(
        f'<div class="card"><div class="lbl">{escape(i["name"])}</div>'
        f'<div class="big">{fmt(i["value"], 2)}</div>'
        f'<div>{pct(i["change_percent"])} <span class="muted">{i["change"]:+.2f}</span></div></div>'
        for i in market["indices"]
    )
    b = market["breadth"]
    breadth = (f'<p><span class="up">{b["advancers"]} up</span> · <span class="down">{b["decliners"]} down</span> · '
               f'{b["limit_up"]} limit-up · {b["limit_down"]} limit-down <span class="muted">(VN-Index, {b["total"]} stocks)</span></p>')
    sectors = "".join(
        f'<tr><td>{escape(s["name"])}</td><td class="r">{pct(s["change_percent"])}</td>'
        f'<td class="r muted">{fmt(s["trading_value"] / 1e9, 0)} bn</td></tr>'
        for s in market["sectors"]
    )
    quotes = "".join(
        f'<tr><td><b>{r["symbol"]}</b></td><td class="r">{fmt(r["close"])}</td><td class="r">{pct(r["chg"])}</td></tr>'
        for r in rows
    )
    sig_rows = sorted(rows, key=lambda r: (r["signal"] == "NEUTRAL", r["symbol"]))
    signals = "".join(
        f'<tr><td><b>{r["symbol"]}</b></td><td><span class="tag {r["signal"].lower()}">{r["signal"]} {r["strength"] if r["signal"] != "NEUTRAL" else ""}</span></td>'
        + (f'<td class="r">{fmt(r["entry"])}</td><td class="r">{fmt(r["stop"])}</td><td class="r">{fmt(r["target"])}</td>'
           if r["signal"] != "NEUTRAL" else '<td class="r muted">–</td><td class="r muted">–</td><td class="r muted">–</td>')
        + f'<td class="muted why">{escape(r["why"] or r["error"] or "")}</td></tr>'
        for r in sig_rows
    )
    news = "".join(
        f'<li><a href="{escape(n["url"])}" rel="noopener">{escape(n["title"])}</a> '
        f'<span class="muted">{escape(n["source"])} · {n["published_at"][11:16]}'
        f'{" · " + ", ".join(n["symbols"]) if n["symbols"] else ""}</span></li>'
        for n in market["news"]
    )
    miss = (f'<p class="muted">No data yet for: {escape(", ".join(missing))} (see README to add).</p>' if missing else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VN Market Summary</title>
<style>
:root{{--bg:#fff;--fg:#1a1a1a;--muted:#6b7280;--line:#e5e7eb;--card:#f8fafc;--up:#0a8f4d;--down:#d12d2d;--buy:#dff5e8;--sell:#fde4e4;--neu:#eceff3}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1115;--fg:#e8e8e8;--muted:#9aa0aa;--line:#262a33;--card:#171a21;--up:#3ecf80;--down:#ff6b6b;--buy:#163a28;--sell:#40191b;--neu:#232731}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:960px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px;margin:0}}h2{{font-size:16px;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}}
.muted{{color:var(--muted)}}.up{{color:var(--up)}}.down{{color:var(--down)}}.flat{{color:var(--muted)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px}}
.lbl{{color:var(--muted);font-size:13px}}.big{{font-size:24px;font-weight:600}}
table{{width:100%;border-collapse:collapse}}td{{padding:6px 8px;border-bottom:1px solid var(--line)}}.r{{text-align:right;font-variant-numeric:tabular-nums}}
.scroll{{overflow-x:auto}}.why{{font-size:12px;min-width:220px}}
.tag{{padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600;background:var(--neu);white-space:nowrap}}.tag.buy{{background:var(--buy);color:var(--up)}}.tag.sell{{background:var(--sell);color:var(--down)}}
ul{{padding-left:18px}}li{{margin:6px 0}}a{{color:inherit}}
</style></head><body><main>
<h1>VN Market Summary</h1>
<p class="muted">Snapshot from Finhay · market data {escape(market["updated_at"][:16].replace("T", " "))} (UTC+7) · price history to {as_of} · session {escape(market["session"])}</p>
<h2>Indices</h2><div class="grid">{idx}</div>{breadth}
<h2>Sectors</h2><div class="scroll"><table>{sectors}</table></div>
<h2>Watchlist</h2><div class="scroll"><table>{quotes}</table></div>{miss}
<h2>Signals</h2><div class="scroll"><table>
<tr class="muted"><td>Symbol</td><td>Signal</td><td class="r">Entry</td><td class="r">Stop</td><td class="r">Target</td><td>Basis</td></tr>{signals}</table></div>
<p class="muted">Technical signals from daily bars; informational only, not investment advice.</p>
<h2>News</h2><ul>{news}</ul>
</main></body></html>"""


def main():
    watch = load("watchlist.json")["symbols"]
    history, market = load("data/history.json"), load("data/market.json")
    rows, missing = stock_rows(watch, history)
    (ROOT / "index.html").write_text(render(market, rows, missing, history["as_of"]), encoding="utf-8")
    print(f"index.html: {len(rows)} symbols" + (f"; missing data: {', '.join(missing)}" if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
