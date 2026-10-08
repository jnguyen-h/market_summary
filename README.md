# market_summary

Static VN market snapshot (indices, sectors, watchlist, signals, news) published on GitHub Pages.
Data comes from Finhay via a Claude session; there is no scheduled refresh.

## Add symbols
1. Add the ticker to `watchlist.json`.
2. In Claude Code, ask: "refresh market_summary" (it pulls ~55 daily OHLC bars per new symbol from Finhay into `data/history.json`).
3. `python build.py`, commit, push.

`build.py` lists watchlist symbols that have no history yet.

## Refresh data
Ask Claude to refresh `data/market.json` (indices, sectors, news) and `data/history.json` (bars as `[open, high, low, close]`, oldest first), then `python build.py`.

## Files
- `signals.py`, `config.py`: indicator logic copied from the `market_analysis` bot.
- `data/*.json`: raw snapshot; `index.html`: generated, served by Pages.
