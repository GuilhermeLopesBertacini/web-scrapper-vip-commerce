from dotenv import load_dotenv
import os

# --- Carregamento de Variáveis de Ambiente ---
load_dotenv()

# --- Constantes da API ---
API_BASE_URL = os.getenv("API_BASE_URL")
DOMAIN_KEY = os.getenv("DOMAIN_KEY")
AUTH_TOKEN = os.getenv("AUTH_TOKEN")

HEADERS = {
    'Accept': 'application/json',
    'DomainKey': DOMAIN_KEY,
    'Authorization': f'Basic {AUTH_TOKEN}'
}

# --- Constantes de Scraping e Datas ---
START_DATE = "2024-09-26 01:01:01"
END_DATE = "2025-09-26 01:01:01"
REQUEST_DELAY = 0.2

# --- Gerenciamento Dinâmico de Caminhos ---
SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(SRC_DIR, "assets")

RAW_IMAGES_DIR = os.path.join(ASSETS_DIR, "raw_images")
CHROMEDRIVER_PATH = os.path.join(ASSETS_DIR, "chromedriver-linux64", "chromedriver")
CHROME_BINARY_PATH = os.path.join(ASSETS_DIR, "chrome-linux64", "chrome")
PRODUCT_MAP_PATH = os.path.join(ASSETS_DIR, "data", "product_map.json")