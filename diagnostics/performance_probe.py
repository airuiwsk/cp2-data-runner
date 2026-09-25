def summarize(returns):
    mean_return = sum(returns) / len(returns) if returns else 0.0
    passed = mean_return > 0.0
    return {'mean_return': mean_return, 'passed': passed}
