"""
Simplified image downloader using the Urbanic API endpoint.
No Selenium required - pure HTTP requests.

Pipeline (Método Novo):
  1. Busca todos os produtos da API Urbanic (com paginação automática)
  2. Lista imagens já existentes no GCP (Google Cloud Storage)
  3. Calcula a diferença: apenas imagens novas serão baixadas
  4. Baixa em paralelo as imagens novas para src/assets/raw_images/
  5. Nomeia cada imagem pelo codigo_erp.jpg
"""
import os
import sys
import json
import requests
import logging
from multiprocessing import Pool, current_process
from typing import Dict, List, Optional, Set, Tuple
from tqdm import tqdm
from urllib3.exceptions import InsecureRequestWarning
import urllib3

import src.utils.config as constants  # shared config at src/utils/config.py

urllib3.disable_warnings(InsecureRequestWarning)

# ──────────────────────────────────────────────
# Configuração
# ──────────────────────────────────────────────
API_ENDPOINT = f"{constants.API_BASE_URL}/importacao/produtos"
PREFERRED_IMAGE_SIZE = 250  # Prefer 250px images
MAX_WORKERS = 8             # Number of parallel download workers
BATCH_SIZE = 50             # Products per API page

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Global session per worker
requests_session = None


# ──────────────────────────────────────────────
# Worker helpers
# ──────────────────────────────────────────────

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


# ──────────────────────────────────────────────
# API helpers
# ──────────────────────────────────────────────

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


def collect_all_products() -> List[Tuple[int, str]]:
    """
    Fetch all products from all pages and build download tasks.
    Returns:
        List of (codigo_erp, image_url) tuples
    """
    logger.info("Fetching product data from API...")

    # Get first page to determine total pages
    first_page = fetch_products_page(1)
    if not first_page or not first_page.get('success'):
        logger.error("Failed to fetch first page")
        return []

    pagination = first_page.get('pagination', {})
    total_pages = pagination.get('page_count', 1)
    total_products = pagination.get('count', 0)

    logger.info(f"Found {total_products} products across {total_pages} pages")

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

    logger.info(f"Collected {len(download_tasks)} products with images")
    return download_tasks


# ──────────────────────────────────────────────
# GCP helpers
# ──────────────────────────────────────────────

def get_gcp_image_set() -> Optional[Set[str]]:
    """
    Lista as imagens já existentes no Google Cloud Storage.

    Retorna um set com os nomes de arquivo (e.g. '12345.jpg') presentes
    no bucket/pasta configurados, ou None caso a lib não esteja disponível
    ou ocorra algum erro de autenticação.

    Returns:
        Set[str] com nomes de arquivo remotos, ou None em caso de erro.
    """
    try:
        from google.cloud import storage  # type: ignore
    except ImportError:
        logger.warning(
            "google-cloud-storage não instalado. "
            "Pulando verificação de imagens no GCP. "
            "Instale com: pip install google-cloud-storage"
        )
        return None

    bucket_name = constants.GCS_BUCKET_NAME
    folder_name = constants.GCS_FOLDER_NAME

    if not bucket_name or not folder_name:
        logger.warning(
            "GCS_BUCKET_NAME ou GCS_FOLDER_NAME não configurados no .env. "
            "Pulando verificação de imagens no GCP."
        )
        return None

    try:
        # Tenta usar credenciais padrão (VM do GCP ou gcloud auth)
        client = storage.Client()
        prefix = folder_name.rstrip('/') + '/'
        blobs = client.list_blobs(bucket_name, prefix=prefix)

        gcp_files: Set[str] = set()
        for blob in blobs:
            # Remove o prefixo do diretório
            file_name = blob.name[len(prefix):]
            if file_name:
                gcp_files.add(file_name)

        logger.info(
            f"GCP: encontradas {len(gcp_files)} imagens em "
            f"gs://{bucket_name}/{folder_name}"
        )
        return gcp_files

    except Exception as e:
        logger.warning(f"Não foi possível listar imagens no GCP: {e}")
        logger.warning("Continuando sem verificação remota.")
        return None


def print_gcp_diff_report(
    api_tasks: List[Tuple[int, str]],
    gcp_images: Optional[Set[str]],
) -> List[Tuple[int, str]]:
    """
    Exibe relatório de diferença entre API, GCP e imagens locais.
    Retorna apenas as tarefas que precisam ser baixadas (novas imagens).

    Args:
        api_tasks:    Lista de (codigo_erp, url) vinda da API
        gcp_images:   Set de nomes de arquivo já no GCP (ou None se indisponível)

    Returns:
        Lista filtrada de tarefas a baixar
    """
    api_file_names = {f"{t[0]}.jpg" for t in api_tasks}

    print("\n" + "=" * 60)
    print("RELATÓRIO DE DIFERENÇAS")
    print("=" * 60)
    print(f"🌐 Produtos com imagem na API:         {len(api_tasks)}")

    if gcp_images is not None:
        only_in_api  = api_file_names - gcp_images
        only_in_gcp  = gcp_images - api_file_names
        in_both       = api_file_names & gcp_images

        print(f"☁️  Imagens existentes no GCP:          {len(gcp_images)}")
        print(f"✅ Já sincronizadas (API ∩ GCP):        {len(in_both)}")
        print(f"🆕 Novas na API (não estão no GCP):     {len(only_in_api)}")
        if only_in_gcp:
            print(f"🗑️  Somente no GCP (removidas da API):  {len(only_in_gcp)}")
    else:
        print("☁️  GCP: verificação indisponível (credenciais ou lib ausente)")
        return api_tasks  # Sem verificação remota, baixa tudo

    # Tarefas que ainda não existem no GCP (novas imagens)
    tasks_to_download = [
        t for t in api_tasks
        if f"{t[0]}.jpg" in only_in_api
    ]
    print(f"📥 Imagens a baixar agora:             {len(tasks_to_download)}")
    print("=" * 60 + "\n")

    return tasks_to_download


# ──────────────────────────────────────────────
# Download worker
# ──────────────────────────────────────────────

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


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

def run():
    """Main function to orchestrate the image downloading process."""
    print("=" * 60)
    print("Product Image Downloader (API-based)")
    print("=" * 60)

    # Ensure output directory exists
    os.makedirs(constants.RAW_IMAGES_DIR, exist_ok=True)

    # ── 1. Coleta todos os produtos da API ──
    all_tasks = collect_all_products()

    if not all_tasks:
        print("No products found to download.")
        return

    # ── 2. Verifica imagens no GCP ──
    gcp_images = get_gcp_image_set()

    # ── 3. Descobre imagens já baixadas localmente ──
    local_images: Set[str] = set()
    if os.path.isdir(constants.RAW_IMAGES_DIR):
        local_images = {
            f for f in os.listdir(constants.RAW_IMAGES_DIR)
            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
        }

    # ── 4. Relatório de diferenças e filtragem das tarefas ──
    download_tasks = print_gcp_diff_report(all_tasks, gcp_images)

    if not download_tasks:
        print("✅ Nenhuma imagem nova para baixar.")
        return
    print(f"Downloading {len(download_tasks)} product images...")
    print(f"Using {MAX_WORKERS} parallel workers")
    print(f"Output directory: {constants.RAW_IMAGES_DIR}")

    # ── 5. Download em paralelo ──
    results = []
    with Pool(processes=MAX_WORKERS, initializer=init_worker) as pool, \
         tqdm(total=len(download_tasks), desc="Downloading Images") as pbar:
        for result in pool.imap_unordered(download_image_worker, download_tasks, chunksize=10):
            results.append(result)
            pbar.update(1)

    # ── 6. Sumário final ──
    success_count = sum(1 for r in results if r)
    failed_count = len(results) - success_count

    print("\n" + "=" * 60)
    print("Download Complete")
    print("=" * 60)
    print(f"✅ Success: {success_count}/{len(download_tasks)}")
    print(f"❌ Failed:  {failed_count}/{len(download_tasks)}")
    print("=" * 60)


if __name__ == "__main__":
    run()
