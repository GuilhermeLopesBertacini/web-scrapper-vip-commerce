import os
import json
import requests
from multiprocessing import Pool
from typing import Dict, Tuple
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

# Variável global para o driver, usada por cada processo do pool
driver_process_global = None

def init_worker():
    """
    Inicializa um driver do Selenium para cada processo do pool.
    """
    global driver_process_global
    
    # Certifique-se que a variável CHROMEDRIVER_PATH está definida em seu config.py
    service = Service(executable_path=constants.CHROMEDRIVER_PATH) 
    
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    driver_process_global = webdriver.Chrome(service=service, options=chrome_options)


def download_image_worker(args: Tuple[str, str]) -> bool:
    """
    Worker function to download an image using a Selenium-driven browser.
    """
    global driver_process_global
    product_id, codigo_erp = args
    product_page_url = f"{constants.API_BASE_URL}/produto/{product_id}"
    output_path = os.path.join(constants.RAW_IMAGES_DIR, f"{codigo_erp}.jpg")

    if os.path.exists(output_path):
        return True
    
    try:
        driver_process_global.get(product_page_url)
        wait = WebDriverWait(driver_process_global, 15)

        # --- ETAPA 1: Lidar com o Banner de Cookies (COM SELETOR CORRIGIDO) ---
        try:
            # Este é o seletor correto, extraído do seu HTML.
            cookie_button = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "div.lgpd--cookie__opened button"))
            )
            cookie_button.click()
        except TimeoutException:
            # Se o banner não aparecer, ótimo, apenas continuamos.
            pass

        # --- ETAPA 2: Encontrar e baixar a imagem (COM SELETOR CORRIGIDO) ---
        # Este seletor também foi validado como o mais provável para a imagem principal.
        image_element = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.vip-slide-wrapper img"))
        )
        
        image_url = image_element.get_attribute('src')
        if not image_url or 'default_image' in image_url:
            # Ignora imagens placeholder
            return False

        image_response = requests.get(image_url, timeout=20, verify=False)
        image_response.raise_for_status()

        with open(output_path, 'wb') as f:
            f.write(image_response.content)
        
        return True
    
    except (TimeoutException, WebDriverException, requests.exceptions.RequestException, IOError):
        return False

def run():
    """
    Main function to orchestrate the image downloading process.
    """
    print("Starting image download process (Final Method)...")

    # (A validação de configuração e o carregamento do JSON permanecem os mesmos)
    os.makedirs(constants.RAW_IMAGES_DIR, exist_ok=True)
    with open(constants.PRODUCT_MAP_PATH, 'r', encoding='utf-8') as f:
        product_map: Dict[str, str] = json.load(f)
    tasks = list(product_map.items())
    
    processes = os.cpu_count()
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