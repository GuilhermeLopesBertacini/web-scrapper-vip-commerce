from typing import Dict, Any, Optional, List
from tqdm import tqdm
import requests
import json
import os
from multiprocessing import Pool
import src.utils.config as constants


def fetch_orders_page(page: int, start_created: str, end_created: str) -> Dict[str, Any]:
    """
    Busca uma única página de pedidos da API.
    """
    url = f"{constants.API_BASE_URL}/importacao/pedidos"
    params = {
        'start_created': start_created,
        'end_created': end_created,
        'page': page
    }
    try:
        response = requests.get(url, headers=constants.HEADERS, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Erro crítico ao buscar a página de pedidos {page}: {e}")
        raise

def fetch_products_order(order_code: str) -> Optional[List[Dict[str, Any]]]:
    """
    Busca os produtos associados a um código de pedido. (Função Worker)
    """
    url = f"{constants.API_BASE_URL}/importacao/pedidos/{order_code}/pedido-produtos"
    try:
        response = requests.get(url, headers=constants.HEADERS, timeout=30)
        response.raise_for_status()
        return response.json().get("data", [])
    except requests.exceptions.RequestException as e:
        return None


def save_to_file(product_map: Dict[str, str], filename: str):
    """
    Salva o mapa de produtos em um arquivo JSON.
    """
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(product_map, f, indent=4, ensure_ascii=False)
        print(f"\nMapa de produtos salvo com sucesso em '{filename}'.")
    except IOError as e:
        print(f"\n[ERRO] Falha ao salvar o arquivo de saída: {e}")


def run():
    """
    Função principal para orquestrar o processo de scraping.
    """
    print("Iniciando processo de extração de dados da API VipCommerce...")

    # Etapa 1: Obter todos os códigos de pedido (sequencial)
    all_order_codes: List[str] = []
    current_page = 1
    total_pages = 1

    print("Buscando todos os pedidos...")
    with tqdm(total=total_pages, desc="Páginas de Pedidos") as pbar:
        while current_page <= total_pages:
            try:
                data = fetch_orders_page(current_page, constants.START_DATE, constants.END_DATE)
                if current_page == 1:
                    total_pages = data.get("pagination", {}).get("page_count", 1)
                    pbar.total = total_pages
                    pbar.refresh()
                
                orders = data.get("data", [])
                for order in orders:
                    if 'codigo' in order:
                        all_order_codes.append(order['codigo'])
                
                pbar.update(1)
                current_page += 1
            except requests.exceptions.RequestException:
                print(f"\n[ERRO CRÍTICO] Falha na busca de pedidos. Saindo.")
                return

    print(f"\nTotal de {len(all_order_codes)} pedidos encontrados.")

    # Etapa 2: Buscar produtos para cada pedido (em paralelo)
    print(f"\nBuscando e agregando produtos para cada pedido em paralelo...")
    product_map: Dict[str, str] = {}
    
    with Pool(processes=os.cpu_count()) as pool, tqdm(total=len(all_order_codes), desc="Processando Pedidos") as pbar:
        for product_list in pool.imap_unordered(fetch_products_order, all_order_codes):
            if product_list:
                for product in product_list:
                    produto_id = product.get("produto_id")
                    codigo_erp = product.get("codigo_erp")
                    if produto_id and codigo_erp:
                        product_map[produto_id] = codigo_erp
            pbar.update(1)

    print(f"\nProcesso concluído. Encontrados {len(product_map)} produtos únicos.")
    
    # Etapa 4: Salvar o mapa em um arquivo JSON
    save_to_file(product_map, constants.PRODUCT_MAP_PATH)

if __name__ == "__main__":
    run()