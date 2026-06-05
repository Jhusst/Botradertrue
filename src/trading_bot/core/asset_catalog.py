from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class AssetInfo:
    symbol: str
    display_name: str
    asset_class: str  # crypto | precious_metal
    price_decimals: int
    strategy_name: str


CRYPTO_DEFAULT = AssetInfo(
    symbol="*",
    display_name="Cripto",
    asset_class="crypto",
    price_decimals=2,
    strategy_name="TrendPullbackMVP",
)

ASSETS: dict[str, AssetInfo] = {
    "BTC/USDT": AssetInfo("BTC/USDT", "Bitcoin (BTC)", "crypto", 2, "TrendPullbackMVP"),
    "BTC/USDT:USDT": AssetInfo("BTC/USDT:USDT", "Bitcoin (BTC)", "crypto", 2, "TrendPullbackMVP"),
    "ETH/USDT": AssetInfo("ETH/USDT", "Ethereum (ETH)", "crypto", 2, "TrendPullbackMVP"),
    "ETH/USDT:USDT": AssetInfo("ETH/USDT:USDT", "Ethereum (ETH)", "crypto", 2, "TrendPullbackMVP"),
    "SOL/USDT": AssetInfo("SOL/USDT", "Solana (SOL)", "crypto", 2, "TrendPullbackMVP"),
    "SOL/USDT:USDT": AssetInfo("SOL/USDT:USDT", "Solana (SOL)", "crypto", 2, "TrendPullbackMVP"),
    "BNB/USDT": AssetInfo("BNB/USDT", "BNB", "crypto", 2, "TrendPullbackMVP"),
    "BNB/USDT:USDT": AssetInfo("BNB/USDT:USDT", "BNB", "crypto", 2, "TrendPullbackMVP"),
    "DOGE/USDT": AssetInfo("DOGE/USDT", "Dogecoin (DOGE)", "crypto", 5, "TrendPullbackMVP"),
    "DOGE/USDT:USDT": AssetInfo("DOGE/USDT:USDT", "Dogecoin (DOGE)", "crypto", 5, "TrendPullbackMVP"),
    "XRP/USDT": AssetInfo("XRP/USDT", "Ripple (XRP)", "crypto", 4, "TrendPullbackMVP"),
    "XRP/USDT:USDT": AssetInfo("XRP/USDT:USDT", "Ripple (XRP)", "crypto", 4, "TrendPullbackMVP"),
    "WIF/USDT": AssetInfo("WIF/USDT", "dogwifhat (WIF)", "crypto", 4, "TrendPullbackMVP"),
    "WIF/USDT:USDT": AssetInfo("WIF/USDT:USDT", "dogwifhat (WIF)", "crypto", 4, "TrendPullbackMVP"),
    "LINK/USDT": AssetInfo("LINK/USDT", "Chainlink (LINK)", "crypto", 3, "TrendPullbackMVP"),
    "LINK/USDT:USDT": AssetInfo("LINK/USDT:USDT", "Chainlink (LINK)", "crypto", 3, "TrendPullbackMVP"),
    "AVAX/USDT": AssetInfo("AVAX/USDT", "Avalanche (AVAX)", "crypto", 3, "TrendPullbackMVP"),
    "AVAX/USDT:USDT": AssetInfo("AVAX/USDT:USDT", "Avalanche (AVAX)", "crypto", 3, "TrendPullbackMVP"),
    "ADA/USDT": AssetInfo("ADA/USDT", "Cardano (ADA)", "crypto", 4, "TrendPullbackMVP"),
    "ADA/USDT:USDT": AssetInfo("ADA/USDT:USDT", "Cardano (ADA)", "crypto", 4, "TrendPullbackMVP"),
    "HYPE/USDT": AssetInfo("HYPE/USDT", "Hyperliquid (HYPE)", "crypto", 3, "TrendPullbackMVP"),
    "HYPE/USDT:USDT": AssetInfo("HYPE/USDT:USDT", "Hyperliquid (HYPE)", "crypto", 3, "TrendPullbackMVP"),
    "1000PEPE/USDT:USDT": AssetInfo(
        "1000PEPE/USDT:USDT", "PEPE (1000x)", "crypto", 6, "TrendPullbackMVP"
    ),
    "XAU/USDT:USDT": AssetInfo(
        "XAU/USDT:USDT", "Oro (XAU)", "precious_metal", 2, "PreciousMetalsMVP"
    ),
    "XAG/USDT:USDT": AssetInfo(
        "XAG/USDT:USDT", "Plata (XAG)", "precious_metal", 3, "PreciousMetalsMVP"
    ),
}

ASSET_CLASS_LABELS = {
    "crypto": "Cripto",
    "precious_metal": "Metal",
}


def get_asset_info(symbol: str) -> AssetInfo:
    if symbol in ASSETS:
        return ASSETS[symbol]
    if "XAU" in symbol.upper() or "GOLD" in symbol.upper():
        return ASSETS["XAU/USDT:USDT"]
    if "XAG" in symbol.upper() or "SILVER" in symbol.upper():
        return ASSETS["XAG/USDT:USDT"]
    return CRYPTO_DEFAULT


def quantize_price(value: Decimal, symbol: str) -> Decimal:
    decimals = get_asset_info(symbol).price_decimals
    quantum = Decimal(10) ** -decimals
    return value.quantize(quantum)


def is_futures_symbol(symbol: str) -> bool:
    return ":" in symbol


def asset_class_label(asset_class: str) -> str:
    return ASSET_CLASS_LABELS.get(asset_class, asset_class)


def parse_watch_symbols(watch_symbols: str) -> list[str]:
    return [s.strip() for s in watch_symbols.split(",") if s.strip()]
