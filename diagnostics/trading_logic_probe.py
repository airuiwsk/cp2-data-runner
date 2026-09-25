def signal(price, moving_average):
    return 1 if price > moving_average else 0

def strategy_return(signal_value, asset_return):
    return signal_value * asset_return
