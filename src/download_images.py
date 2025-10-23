import os
import json
import requests
from multiprocessing import Pool, current_process
from typing import Dict, Tuple, Optional
from tqdm import tqdm
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# --- IMPORTS DO SELENIUM ---
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

import src.utils.config as constants

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

driver_process_global = None

def init_worker():
    """
    Inicializa um driver do Selenium para cada processo do pool.
    """
    global driver_process_global
    
    service = Service(executable_path=constants.CHROMEDRIVER_PATH) 
    chrome_options = webdriver.ChromeOptions()
    chrome_options.binary_location = constants.CHROME_BINARY_PATH

    process_id = current_process().pid
    user_data_dir = os.path.join('/tmp', f'chrome_profile_{process_id}')
    chrome_options.add_argument(f"--user-data-dir={user_data_dir}")

    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    driver_process_global = webdriver.Chrome(service=service, options=chrome_options)

def download_image_worker(args: Tuple[str, str]) -> bool:
    """
    Worker function to download an image using a Selenium-driven browser.
    """
    global driver_process_global
    product_id, codigo_erp = args

    # Sempre salvar pelo codigo_erp para manter consistência com demais processos
    output_path = os.path.join(constants.RAW_IMAGES_DIR, f"{codigo_erp}.jpg")

    if os.path.exists(output_path):
        return True

    def try_get_image_url(page_url: str) -> Optional[str]:
        """Tenta carregar a página e extrair a URL da imagem do produto.
        Retorna a URL da imagem se encontrada e válida; caso contrário, None.
        """
        if driver_process_global is None:
            return None
        try:
            driver_process_global.get(page_url)
            wait = WebDriverWait(driver_process_global, 15)

            # Aceitar cookies se o banner aparecer
            try:
                cookie_button = wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "div.lgpd--cookie__opened button"))
                )
                cookie_button.click()
            except TimeoutException:
                pass

            # Espera a imagem do produto aparecer
            image_element = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "vip-image.m-auto img"))
            )

            image_url = image_element.get_attribute('src')
            if not image_url or 'default_image' in image_url:
                return None
            return image_url
        except (TimeoutException, WebDriverException):
            return None

    # 1) Tenta pela URL com product_id
    base = (constants.DOMAIN_KEY or "").rstrip('/')
    if not base:
        return False
    urls_to_try = [
        f"{base}/produto/{product_id}",
        f"{base}/produto/{codigo_erp}"
    ]

    for url in urls_to_try:
        image_url = try_get_image_url(url)
        if image_url:
            try:
                image_response = requests.get(image_url, timeout=20, verify=False)
                image_response.raise_for_status()
                with open(output_path, 'wb') as f:
                    f.write(image_response.content)
                return True
            except (requests.exceptions.RequestException, IOError):
                return False

    return False

def run():
    """
    Main function to orchestrate the image downloading process.
    """
    print("Starting image download process (Final Production Method)...")

    os.makedirs(constants.RAW_IMAGES_DIR, exist_ok=True)
    with open(constants.PRODUCT_MAP_PATH, 'r', encoding='utf-8') as f:
        product_map: Dict[str, str] = json.load(f)
    tasks = list(product_map.items())
    
    processes = max(1, (os.cpu_count() or 1)) 
    print(f"Running with {processes} parallel browser instances...")

    results = []
    with Pool(processes=processes, initializer=init_worker) as pool, tqdm(total=len(tasks), desc="Downloading Images") as pbar:
        for result in pool.imap_unordered(download_image_worker, tasks):
            results.append(result)
            pbar.update(1)

    success_count = sum(1 for r in results if r is True)
    failed_count = len(tasks) - success_count
    
    print("\n" + "-"*10 + " Download Complete " + "-"*10)
    print(f"✅ Success: {success_count}/{len(tasks)}")
    print(f"❌ Failed or Not Found: {failed_count}/{len(tasks)}")
    print("-" * 39)

if __name__ == "__main__":
    run()