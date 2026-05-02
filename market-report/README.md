# Daily Market Report

Automated system that generates a PDF market brief every trading day at NYSE open (9:30 AM ET) and delivers it by email.

**Stack:** Python · yfinance · FRED API · Finnhub · ReportLab · Gmail SMTP

---

## Prerequisites

- Python 3.10+
- A free [FRED API key](https://fred.stlouisfed.org/docs/api/api_key.html)
- A free [Finnhub API key](https://finnhub.io/register) (optional — RSS fallback included)
- A Gmail account with an [App Password](https://myaccount.google.com/apppasswords) enabled

---

## Installation

```bash
cd market-report
pip install -r requirements.txt
```

---

## Configuration

### 1 — Credentials (`.env`)

Copy the template and fill in your keys:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `FRED_API_KEY` | 4f66c74b05a50f5c042fd2a3b1536500 |
| `GMAIL_USER` | richsarda@gmail.com |
| `GMAIL_APP_PASSWORD` | pkzp qimv nmhe mwmn |
| `FINNHUB_API_KEY` | Finnhub free-tier key (optional) |

### 2 — Tickers & series (`config/settings.yaml`)

Edit `tickers`, `ticker_names`, `fred_series`, and `email.recipients` to taste. All other parameters have sensible defaults.

### 3 — Logo

Place your logo as `assets/logo.png`. Transparent PNG works best. If the file is absent the header renders without a logo.

---

## Running manually

```bash
# from the market-report/ directory
python src/main.py
```

The PDF is saved to `output/market_YYYY-MM-DD.pdf` and emailed automatically.
Logs are written to `logs/market_report.log` (7-day rotation).

---

## Scheduling with Windows Task Scheduler

Run the following in **PowerShell as Administrator**, adjusting the Python path if needed:

```powershell
$python  = (Get-Command python).Source
$script  = "C:\Users\ricsa\OneDrive\Escritorio\Agentic Workflow\market-report\src\main.py"
$action  = New-ScheduledTaskAction -Execute $python -Argument $script `
               -WorkingDirectory "C:\Users\ricsa\OneDrive\Escritorio\Agentic Workflow\market-report"
$trigger = New-ScheduledTaskTrigger -Daily -At "09:30AM"
$settings= New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
               -StartWhenAvailable
Register-ScheduledTask -TaskName "DailyMarketReport" `
    -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest
```

> **Timezone note:** Windows Task Scheduler uses your system clock. If your PC is set to Eastern Time the trigger fires at exactly 9:30 AM ET and DST is handled automatically. If your system timezone differs, convert 9:30 AM ET to your local time before registering the task.

To verify the task was created: `Get-ScheduledTask -TaskName "DailyMarketReport"`  
To run it immediately for testing: `Start-ScheduledTask -TaskName "DailyMarketReport"`  
To remove it: `Unregister-ScheduledTask -TaskName "DailyMarketReport" -Confirm:$false`

---

## Output

```
output/
  market_2025-04-20.pdf   ← attached to email + stored locally
logs/
  market_report.log       ← rotating, 7-day retention
```

PDFs older than 30 days are deleted automatically (configurable via `report.retention_days`).

---

## Project structure

```
market-report/
├── src/
│   ├── main.py          # Orchestrator — run this
│   ├── data_fetch.py    # yfinance: prices + pre-market
│   ├── macro_fetch.py   # FRED: 20 macro series
│   ├── news_fetch.py    # Finnhub + RSS fallback
│   ├── pdf_builder.py   # ReportLab PDF assembly
│   └── emailer.py       # Gmail SMTP delivery
├── assets/logo.png      # Your logo (you provide)
├── config/settings.yaml # Tickers, series, thresholds
├── output/              # Generated PDFs
├── logs/                # Rotating logs
├── .env                 # Secrets — never commit
└── requirements.txt
```

---

## Known constraints

| Item | Note |
|---|---|
| `VIXCLS` (FRED) | Has a 1-trading-day lag. Report shows prior-day value. |
| Monthly/quarterly FRED series | GDP, UNRATE, UMCSENT, etc. show latest available reading with its date — not a daily update. |
| yfinance | Unofficial Yahoo Finance wrapper. Pin the version and monitor for breaks after Yahoo API changes. |
| Pre-market column | Only populated for US equities during pre-market hours (4:00–9:30 AM ET). Forex/crypto/futures always show live price. |
| Weekends & holidays | Script exits cleanly with no output on non-NYSE trading days. |

---

## Phase 4 — LLM-generated commentary (future)

The current summary is fully rules-based. When ready to add LLM-generated outlier commentary, set `ANTHROPIC_API_KEY` (or equivalent) in `.env` and swap `_generate_summary` in `main.py` for an LLM call. The data structures passed to it are already prepared.
