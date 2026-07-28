"""
Simplified image downloader using the Urbanic API endpoint.
No Selenium required - pure HTTP requests.
"""
import os
import json
import requests
import logging
from multiprocessing import Pool, current_process
from typing import Dict, List, Optional, Tuple
from tqdm import tqdm
from urllib3.exceptions import InsecureRequestWarning
import urllib3

import src.utils.config as constants

urllib3.disable_warnings(InsecureRequestWarning)

# Configuration
API_ENDPOINT = f"{constants.API_BASE_URL}/importacao/produtos"
PREFERRED_IMAGE_SIZE = 250  # Prefer 250px images
MAX_WORKERS = 8  # Number of parallel download workers
BATCH_SIZE = 50  # Products per API page

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# Global session per worker
requests_session = None


def init_worker():
    """Initialize HTTP session for each worker process."""
    global requests_session
    process_id = current_process().pid
    
    try:
        from requests.adapters import HTTPAdapter
        s = requests.Session()
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
        s.mount('http://', adapter)
        s.mount('https://', adapter)
        requests_session = s
        logging.debug(f"Worker {process_id} initialized")
    except Exception as e:
        logging.error(f"Failed to initialize worker {process_id}: {e}")
        requests_session = requests


def fetch_products_page(page: int) -> Optional[Dict]:
    """Fetch a single page of products from the API."""
    try:
        params = {
            'page': page,
            'possui_imagem': 'true'
        }
        # Use the same authentication headers from config
        headers = constants.HEADERS.copy() if hasattr(constants, 'HEADERS') else {
            'Accept': 'application/json'
        }
        
        response = requests.get(
            API_ENDPOINT,
            params=params,
            headers=headers,
            timeout=30,
            verify=False
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"Error fetching page {page}: {e}")
        return None


def get_best_image_url(image_urls: List[Dict]) -> Optional[str]:
    """
    Extract the best image URL from imagemUrls array.
    Prefers PREFERRED_IMAGE_SIZE, otherwise returns the largest available.
    """
    if not image_urls:
        return None
    
    # Try to find preferred size
    for img in image_urls:
        if img.get('tamanho') == PREFERRED_IMAGE_SIZE:
            return img.get('localizacao')
    
    # Fallback: get the largest size
    sorted_imgs = sorted(image_urls, key=lambda x: x.get('tamanho', 0), reverse=True)
    if sorted_imgs:
        return sorted_imgs[0].get('localizacao')
    
    return None


def download_image_worker(task: Tuple[int, str]) -> bool:
    """
    Download a single product image.
    Args:
        task: (codigo_erp, image_url)
    Returns:
        True if successful, False otherwise
    """
    global requests_session
    codigo_erp, image_url = task
    
    output_path = os.path.join(constants.RAW_IMAGES_DIR, f"{codigo_erp}.jpg")
    
    # Skip if already exists
    if os.path.exists(output_path):
        return True
    
    try:
        sess = requests_session or requests
        response = sess.get(image_url, timeout=20, verify=False)
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            f.write(response.content)
        
        logging.debug(f"Downloaded image for product {codigo_erp}")
        return True
    except Exception as e:
        logging.debug(f"Failed to download {image_url} for product {codigo_erp}: {e}")
        return False


def collect_all_products() -> List[Tuple[int, str]]:
    """
    Fetch all products from all pages and build download tasks.
    Returns:
        List of (codigo_erp, image_url) tuples
    """
    logging.info("Fetching product data from API...")
    
    # Get first page to determine total pages
    first_page = fetch_products_page(1)
    if not first_page or not first_page.get('success'):
        logging.error("Failed to fetch first page")
        return []
    
    pagination = first_page.get('pagination', {})
    total_pages = pagination.get('page_count', 1)
    total_products = pagination.get('count', 0)
    
    logging.info(f"Found {total_products} products across {total_pages} pages")
    
    download_tasks = []
    
    # Process first page
    for product in first_page.get('data', []):
        codigo_erp = product.get('codigo_erp')
        image_urls = product.get('imagemUrls', [])
        
        if codigo_erp and image_urls:
            best_url = get_best_image_url(image_urls)
            if best_url:
                download_tasks.append((codigo_erp, best_url))
    
    # Fetch remaining pages
    for page in tqdm(range(2, total_pages + 1), desc="Fetching API pages", initial=1, total=total_pages):
        page_data = fetch_products_page(page)
        
        if not page_data or not page_data.get('success'):
            logging.warning(f"Failed to fetch page {page}, skipping...")
            continue
        
        for product in page_data.get('data', []):
            codigo_erp = product.get('codigo_erp')
            image_urls = product.get('imagemUrls', [])
            
            if codigo_erp and image_urls:
                best_url = get_best_image_url(image_urls)
                if best_url:
                    download_tasks.append((codigo_erp, best_url))
    
    logging.info(f"Collected {len(download_tasks)} products with images")
    return download_tasks


def run():
    """Main function to orchestrate the image downloading process."""
    print("=" * 60)
    print("Product Image Downloader (API-based)")
    print("=" * 60)
    
    # Ensure output directory exists
    os.makedirs(constants.RAW_IMAGES_DIR, exist_ok=True)
    
    # Collect all download tasks
    download_tasks = collect_all_products()
    
    if not download_tasks:
        print("No products found to download.")
        return
    
    print(f"\nDownloading {len(download_tasks)} product images...")
    print(f"Using {MAX_WORKERS} parallel workers")
    print(f"Output directory: {constants.RAW_IMAGES_DIR}")
    
    # Download images in parallel
    results = []
    with Pool(processes=MAX_WORKERS, initializer=init_worker) as pool, \
         tqdm(total=len(download_tasks), desc="Downloading Images") as pbar:
        for result in pool.imap_unordered(download_image_worker, download_tasks, chunksize=10):
            results.append(result)
            pbar.update(1)
    
    # Summary
    success_count = sum(1 for r in results if r)
    failed_count = len(results) - success_count
    
    print("\n" + "=" * 60)
    print("Download Complete")
    print("=" * 60)
    print(f"✅ Success: {success_count}/{len(download_tasks)}")
    print(f"❌ Failed: {failed_count}/{len(download_tasks)}")
    print("=" * 60)


if __name__ == "__main__":
    run()
