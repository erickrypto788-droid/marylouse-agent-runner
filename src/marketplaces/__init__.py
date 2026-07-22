from .mercadolivre import MercadoLivreMarketplace
from .amazon import AmazonMarketplace
from .shopee import ShopeeMarketplace
from .aliexpress import AliExpressMarketplace
from .csv_feed import CsvMarketplace

ALL_MARKETPLACES = [
    MercadoLivreMarketplace,
    AmazonMarketplace,
    ShopeeMarketplace,
    AliExpressMarketplace,
    CsvMarketplace,
]
