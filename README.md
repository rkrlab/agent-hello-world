# Agent Hello World

A small GitHub Actions automation repo centered on a **paper-only crypto research and monitoring workflow**, with a simpler Bitcoin alert kept as a secondary example.

Current flows in this repository:

This example checks the current PONS price using DexScreener. It runs every six hours and can also be started manually from an iPhone. When the price is above the configured threshold, it opens one GitHub issue; GitHub then sends the normal issue notification.
- **Bitcoin price alert** using CoinGecko
- **Paper-only crypto execution** from committed research signals
- **Paper position monitoring** against live DexScreener data

The pattern is:

**trigger → GitHub Actions → Python decision logic → GitHub issue or comment**

No wallet access, transaction signing, exchange credentials, or extra infrastructure is required.

## Repository layout

- `agent.py`: fetches the current Bitcoin price and decides whether an alert should fire
- `paper_executor.py`: converts a committed signal into a deterministic paper execution record
- `position_monitor.py`: evaluates a saved paper position against live pair data
- `.github/workflows/bitcoin-monitor.yml`: runs the Bitcoin alert workflow
- `.github/workflows/paper-execution.yml`: runs the paper execution workflow
- `.github/workflows/paper-position-monitor.yml`: runs the paper position monitor workflow
- `signals/`: committed signal inputs
- `positions/`: frozen paper positions
- `observations/`: research observations and follow-up notes

## Paper workflow

This is the main story of the repository:

1. A committed file in `signals/` captures a research signal.
2. **Crypto paper execution** freezes sizing, slippage assumptions, and risk rules into a GitHub issue.
3. A saved file in `positions/` records the frozen paper position.
4. **Paper position monitor** re-checks that position against live DexScreener data.
5. GitHub issue comments become the monitoring log for state changes and daily heartbeat updates.

Manual paper execution runs default to `signals/example.json`, and manual paper monitor runs can target a different position file when needed.

## Bitcoin alert

The Bitcoin workflow runs every six hours, can be started manually, and also runs on pushes that change the alert logic. It checks CoinGecko and opens a single GitHub issue titled **Bitcoin price alert** when the threshold is met.

### Try it from your iPhone

1. Open this repository in the GitHub app or Safari.
2. Open **Actions** → **PONS price monitor**.
3. Tap **Run workflow**.
4. Leave **Force a test alert** set to `true`, then tap **Run workflow**.
5. Open **Issues** to see the alert issue.

### Configure the threshold

The default threshold is **$1.00**. To change it:

1. Open **Settings** → **Secrets and variables** → **Actions** → **Variables**.
2. Add a repository variable named `PONS_ALERT_ABOVE_USD`.
3. Set it to the price that should trigger an issue, such as `0.75`.

The scheduled run uses that threshold. It will not create duplicates while an open issue titled **PONS price alert** already exists. Close the issue when you want the monitor to be able to alert again.
2. Add a repository variable named `BTC_ALERT_ABOVE_USD`.
3. Set it to the target price, such as `125000`.

The scheduled run uses that threshold and will not create duplicates while an open issue titled **Bitcoin price alert** already exists.
Close that issue when you want the monitor to be able to alert again.

## Paper execution

The paper execution workflow reads a committed JSON signal, applies deterministic sizing and slippage rules, and opens a GitHub issue containing the frozen execution record.

- It is **simulation only**
- It never sends a transaction
- It never accesses a wallet
- It preserves the execution record for later monitoring

Run **Actions** → **Crypto paper execution** and provide a committed file from `signals/`, or let pushes to that directory trigger the workflow automatically.

## Paper position monitor

The paper position monitor reads a saved position from `positions/`, fetches the live pair from DexScreener, and comments on the associated issue when:

- the position state changes
- or the daily heartbeat has not been posted yet

Possible states include `HOLD`, `SCALE_READY`, `TP1`, `TP2`, `STOP`, `STRUCTURAL_FAIL`, and `LIQUIDITY_WARNING`.

- `agent.py`: calls DexScreener for the default PONS pair and decides whether the threshold was crossed.
- `.github/workflows/pons-monitor.yml`: supplies the free runtime and creates the GitHub issue.
- `README.md`: iPhone setup and testing instructions.
Manual runs can override the default position file in **Actions** → **Paper position monitor**.

## Notes

- GitHub Issues and comments are used as the visible log of alerts, simulated trades, and monitoring updates.
- Workflow output names are part of the contract between the Python scripts and the workflow files.
- The repo intentionally keeps the Bitcoin alert as a lightweight demo, but the paper workflow is the primary operating path.