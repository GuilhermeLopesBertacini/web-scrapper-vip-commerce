from src.fetch_products_map import run as fetch_products_map
from src.download_images import run as download_images

def main():
    """
    Função principal que orquestra todo o processo de scraping.
    """
    print("--- INICIANDO PROCESSO COMPLETO DE SCRAPING ---")
    # Etapa 1: Buscar o mapa de produtos da API
    fetch_products_map()
    # Etapa 2: Baixar as imagens dos produtos
    download_images()
    print("\n--- PROCESSO COMPLETO FINALIZADO COM SUCESSO ---")

if __name__ == "__main__":
    main()