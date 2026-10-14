import os
import json
import requests
import logging
import atexit
import urllib3
from bs4 import BeautifulSoup
from multiprocessing import Pool, current_process
from typing import Dict, Tuple, Optional, Callable
from tqdm import tqdm
from urllib3.exceptions import InsecureRequestWarning
import concurrent.futures
import math
import shutil

# --- IMPORTS DO SELENIUM ---
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

import src.utils.config as constants

urllib3.disable_warnings(InsecureRequestWarning)

# Logging and configuration
"""
Runtime configuration:
 - SHOW_BROWSER: whether to run Chrome windows visible (False = headless)
 - MAX_WORKERS: number of parallel browser processes to use (bounded to 4)
 - SELENIUM_TIMEOUT: seconds to wait for elements in Selenium
 - ALLOW_IMAGES: when False, Chrome will be launched with images disabled
 - DEFAULT_CHUNKSIZE: pool chunksize for multiprocessing
"""

# Debug: show browser windows? (False = headless)
# Allow overriding behavior via environment variables for aggressive tuning
SHOW_BROWSER = os.getenv("SHOW_BROWSER", "0") in ("1", "true", "True")

# System resources detection (no external deps)
def _get_system_resources():
    cpus = os.cpu_count() or 1
    mem_gb = None
    try:
        # Unix: sysconf approach
        pages = os.sysconf('SC_PHYS_PAGES')
        page_size = os.sysconf('SC_PAGE_SIZE')
        mem_bytes = pages * page_size
        mem_gb = mem_bytes / (1024 ** 3)
    except Exception:
        try:
            total, used, free = shutil.disk_usage('/')
            mem_gb = max(1, total / (1024 ** 3))
        except Exception:
            mem_gb = 4
    return int(cpus), float(mem_gb)

CPUS, MEM_GB = _get_system_resources()

# Max parallel browser instances (Selenium) - conservative default but allows override
DEFAULT_WORKERS = CPUS
MAX_WORKERS = int(os.getenv('MAX_WORKERS') or max(1, DEFAULT_WORKERS))
# Selenium wait timeout (seconds) - allow env override for slower/fast sites
SELENIUM_TIMEOUT = int(os.getenv('SELENIUM_TIMEOUT') or 8)
# Allow images to be loaded in the headless browser (some sites require this).
ALLOW_IMAGES = os.getenv('ALLOW_IMAGES', '0') in ('1', 'true', 'True')
# Default pool chunksize (can be bigger for large lists)
DEFAULT_CHUNKSIZE = int(os.getenv('DEFAULT_CHUNKSIZE') or 16)

# Threaded HTTP workers for fast-path (requests + BS4)
HTTP_WORKERS = int(os.getenv('HTTP_WORKERS') or min(32, max(4, CPUS * 2)))

logging.basicConfig(level=logging.DEBUG if SHOW_BROWSER else logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

driver_process_global = None
# Each worker will have its own requests Session for connection pooling
requests_session = None

def _try_get_image_url_requests(sess: requests.Session, page_url: str) -> Optional[str]:
    """Fast-path: fetch page HTML and extract image URL using BeautifulSoup.
    Extracted to module-level so threaded HTTP path can reuse it.
    """
    try:
        resp = sess.get(page_url, timeout=8, verify=False)
        if resp.status_code != 200:
            logging.debug(f"HTTP {resp.status_code} for {page_url}")
            return None
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 1) Open Graph
        og = soup.find('meta', property='og:image')
        if og:
            content = og.get('content')
            if content:
                return str(content)

        # 2) vip-image tag
        vip = soup.find('vip-image')
        if vip:
            img = vip.find('img')
            if img:
                src = img.get('src') or img.get('data-src')
                if src:
                    return str(src)

        # 3) Common selectors
        img = soup.select_one('vip-image.m-auto img, img.m-auto, img.vip-image')
        if img:
            src = img.get('src') or img.get('data-src')
            if src:
                return str(src)

        # 4) Heuristic: prefer product-like images
        imgs = soup.find_all('img')
        candidate = None
        for i in imgs:
            src = i.get('src') or i.get('data-src')
            if not src:
                continue
            if 'default' in src or 'placeholder' in src:
                continue
            if any(x in src for x in ['/produto', '/produtos', '/products', '/uploads', '/images']):
                return str(src)
            if candidate is None:
                candidate = src
        return str(candidate) if candidate is not None else None
    except Exception as e:
        logging.debug(f"Requests fast-path error for {page_url}: {e}")
        return None


def _download_image_bytes(sess: requests.Session, image_url: str, output_path: str) -> bool:
    try:
        resp = sess.get(image_url, timeout=20, verify=False)
        resp.raise_for_status()
        with open(output_path, 'wb') as f:
            f.write(resp.content)
        return True
    except Exception as e:
        logging.debug(f"Failed to download or write image from {image_url}: {e}")
        return False

def init_worker():
    """
    Inicializa um driver do Selenium para cada processo do pool.
    """
    global driver_process_global
    
    process_id = current_process().pid
    # Setup requests session for this worker to reuse TCP connections
    global requests_session
    try:
        from requests.adapters import HTTPAdapter
        s = requests.Session()
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
        s.mount('http://', adapter)
        s.mount('https://', adapter)
        requests_session = s
    except Exception:
        requests_session = requests

    try:
        service = Service(executable_path=constants.CHROMEDRIVER_PATH)
        chrome_options = webdriver.ChromeOptions()
        chrome_options.binary_location = constants.CHROME_BINARY_PATH

        user_data_dir = os.path.join('/tmp', f'chrome_profile_{process_id}')
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")

        # Allow showing the browser window for debugging by setting SHOW_BROWSER=1
        if not SHOW_BROWSER:
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-background-networking")
        chrome_options.add_argument("--safebrowsing-disable-download-protection")
        chrome_options.add_argument("--disable-default-apps")
        chrome_options.add_argument("--disable-translate")
        chrome_options.add_argument("--disable-sync")
        # Optionally disable image downloading to speed up loads (some sites still set src via JS)
        if not ALLOW_IMAGES:
            chrome_options.add_argument("--blink-settings=imagesEnabled=false")

        driver_process_global = webdriver.Chrome(service=service, options=chrome_options)
        logging.info(f"Started Chrome driver in process {process_id} (headless={not SHOW_BROWSER})")

        # Ensure driver quits when worker process exits
        def _quit_driver():
            try:
                if driver_process_global:
                    driver_process_global.quit()
            except Exception:
                pass

        try:
            atexit.register(_quit_driver)
        except Exception:
            pass
    except Exception as e:
        logging.error(f"Failed to start Chrome driver in process {process_id}: {e}")
        import traceback
        traceback.print_exc()
        # Exit worker to avoid spinning without a driver
        os._exit(1)

def download_image_worker(args: Tuple[str, str]) -> bool:
    """
    Worker function to download an image using a Selenium-driven browser.
    """
    global driver_process_global, requests_session
    product_id, codigo_erp = args

    # Sempre salvar pelo codigo_erp para manter consistência com demais processos
    output_path = os.path.join(constants.RAW_IMAGES_DIR, f"{codigo_erp}.jpg")

    if os.path.exists(output_path):
        return True

    def try_get_image_url(page_url: str) -> Optional[str]:
        """Load the product page and return the image URL or None."""
        if driver_process_global is None:
            logging.debug("No webdriver available in worker")
            return None
        try:
            logging.debug(f"Loading page: {page_url}")
            driver_process_global.get(page_url)
            wait = WebDriverWait(driver_process_global, SELENIUM_TIMEOUT)

            # Try to accept cookies if present
            try:
                cookie_button = wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "div.lgpd--cookie__opened button"))
                )
                cookie_button.click()
            except TimeoutException:
                pass

            # Wait for product image
            image_element = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "vip-image.m-auto img"))
            )

            image_url = image_element.get_attribute('src')
            logging.debug(f"Found image src attribute: {image_url}")
            if not image_url or 'default_image' in image_url:
                logging.debug("Image URL missing or is default placeholder")
                return None
            return image_url
        except (TimeoutException, WebDriverException) as e:
            try:
                title = driver_process_global.title
                current = driver_process_global.current_url
                snippet = driver_process_global.page_source[:500]
                logging.debug(f"On error - title: {title}; current_url: {current}")
                if SHOW_BROWSER:
                    print("--- Page snippet start ---")
                    print(snippet)
                    print("--- Page snippet end ---")
            except Exception:
                pass
            logging.debug(f"Selenium error while loading {page_url}: {e}")
            return None

    # use module-level fast-path to avoid duplication
    # try_get_image_url_requests -> use _try_get_image_url_requests with requests_session

    # Build base URL
    base = (constants.DOMAIN_KEY or "").rstrip('/')
    if base and not base.startswith(('http://', 'https://')):
        base = 'https://' + base

    if not base:
        logging.error(
            "DOMAIN_KEY is not set (empty). Set DOMAIN_KEY in your environment or .env so the scraper can build product URLs."
        )
        return False

    urls_to_try = [
        f"{base}/produto/{product_id}",
        f"{base}/produto/{codigo_erp}"
    ]

    for url in urls_to_try:
        logging.info(f"Trying URL: {url}")
        # Fast-path: try to extract URL via HTTP + BeautifulSoup
        sess = requests_session or requests
        image_url = _try_get_image_url_requests(sess, url)
        if image_url:
            logging.debug(f"Fast-path found image URL: {image_url}")
        else:
            # Fall back to Selenium when JS rendering is required
            image_url = try_get_image_url(url)
        if image_url:
            try:
                if _download_image_bytes(sess, image_url, output_path):
                    logging.info(f"Saved image for product {product_id} -> {output_path}")
                    return True
                else:
                    return False
            except Exception as e:
                logging.debug(f"Unexpected error while saving image {image_url}: {e}")
                return False

    return False

def run():
    """
    Main function to orchestrate the image downloading process.
    """
    print("Starting image download process (optimized)...")

    os.makedirs(constants.RAW_IMAGES_DIR, exist_ok=True)
    with open(constants.PRODUCT_MAP_PATH, 'r', encoding='utf-8') as f:
        product_map: Dict[str, str] = json.load(f)
    tasks = list(product_map.items())

    # Prepare a requests Session tuned for concurrency
    from requests.adapters import HTTPAdapter
    sess = requests.Session()
    adapter = HTTPAdapter(pool_connections=100, pool_maxsize=200)
    sess.mount('http://', adapter)
    sess.mount('https://', adapter)

    # Stage 1: fast-path using threads (requests + BeautifulSoup)
    print(f"Running threaded fast-path with up to {HTTP_WORKERS} workers...")
    fast_failures: list[Tuple[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=HTTP_WORKERS) as exc, tqdm(total=len(tasks), desc="Fast HTTP pass") as pbar:
        futures = {}

        def _http_attempt(task: Tuple[str, str]) -> bool:
            product_id, codigo_erp = task
            output_path = os.path.join(constants.RAW_IMAGES_DIR, f"{codigo_erp}.jpg")
            if os.path.exists(output_path):
                return True
            base = (constants.DOMAIN_KEY or "").rstrip('/')
            if base and not base.startswith(('http://', 'https://')):
                base = 'https://' + base
            if not base:
                logging.error("DOMAIN_KEY is not set (empty). Skipping fast-path.")
                return False
            urls = [f"{base}/produto/{product_id}", f"{base}/produto/{codigo_erp}"]
            for url in urls:
                image_url = _try_get_image_url_requests(sess, url)
                if image_url:
                    if _download_image_bytes(sess, image_url, output_path):
                        logging.info(f"[HTTP] Saved image for {product_id} -> {output_path}")
                        return True
            return False

        for t in tasks:
            futures[exc.submit(_http_attempt, t)] = t

        for fut in concurrent.futures.as_completed(futures):
            task = futures[fut]
            try:
                ok = fut.result()
            except Exception as e:
                logging.debug(f"HTTP worker exception for {task}: {e}")
                ok = False
            if not ok:
                fast_failures.append(task)
            pbar.update(1)

    # Stage 2: Selenium for the remaining tasks (if any)
    total_tasks = len(tasks)
    fast_success = total_tasks - len(fast_failures)
    print(f"Fast-path success: {fast_success}/{total_tasks}. Need Selenium for {len(fast_failures)} tasks.")

    selenium_success = 0
    if fast_failures:
        # Only attempt Selenium if the binary paths exist
        if not (os.path.exists(constants.CHROMEDRIVER_PATH) and os.path.exists(constants.CHROME_BINARY_PATH)):
            logging.warning("Chromedriver or Chrome binary not found; skipping Selenium stage.")
        else:
            # Number of Selenium processes should be limited by MAX_WORKERS and available failures
            processes = max(1, min(MAX_WORKERS, len(fast_failures)))
            print(f"Running Selenium stage with {processes} processes (MAX_WORKERS={MAX_WORKERS})...")
            chunksize = DEFAULT_CHUNKSIZE
            results = []
            with Pool(processes=processes, initializer=init_worker) as pool, tqdm(total=len(fast_failures), desc="Selenium pass") as pbar:
                for result in pool.imap_unordered(download_image_worker, fast_failures, chunksize=chunksize):
                    results.append(result)
                    pbar.update(1)
            selenium_success = sum(1 for r in results if r is True)

    total_success = fast_success + selenium_success

    print("\n" + "-"*10 + " Download Complete " + "-"*10)
    print(f"✅ Success: {total_success}/{len(tasks)}")
    print(f"❌ Failed or Not Found: {len(tasks) - total_success}/{len(tasks)}")
    print("-" * 39)

if __name__ == "__main__":
    run()