def evaluate(rows):
    # Diagnostic only: returns row count and does not calculate returns, signals, PnL, Sharpe, or trading decisions.
    return {'row_count': len(rows), 'performance_computed': False}
