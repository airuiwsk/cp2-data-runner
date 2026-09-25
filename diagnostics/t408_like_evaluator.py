import pandas as pd

def evaluate_t408_like(csv_path):
    df = pd.read_csv(csv_path)
    df["Date"] = pd.to_datetime(df["Date"], utc=False)
    df = df.sort_values("Date").set_index("Date")
    monthly = df["Close"].resample("ME").last().dropna()
    sma10 = monthly.rolling(10).mean()
    signal = (monthly > sma10).astype(int)
    next_return = monthly.pct_change().shift(-1)
    strategy_gross = signal * next_return
    switch = signal.diff().abs().fillna(0.0)
    strategy_net = strategy_gross - switch * 0.001
    benchmark = next_return
    incremental = strategy_net - benchmark
    sample = pd.DataFrame({
        "signal": signal,
        "strategy_net": strategy_net,
        "benchmark": benchmark,
        "incremental": incremental,
    }).loc["2007-10-01":"2018-11-30"].dropna()
    cash = sample[sample["signal"] == 0]
    long = sample[sample["signal"] == 1]
    return {
        "n_months": int(len(sample)),
        "n_cash": int(len(cash)),
        "mean_strategy_net": float(sample["strategy_net"].mean()),
        "mean_incremental": float(sample["incremental"].mean()),
        "mean_benchmark_after_long": float(long["benchmark"].mean()) if len(long) else None,
        "mean_benchmark_after_cash": float(cash["benchmark"].mean()) if len(cash) else None,
    }
