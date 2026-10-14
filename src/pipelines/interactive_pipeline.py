#!/usr/bin/env python3
"""
Pipeline Interativo de Scraping, Pré-processamento e Upload.

Executa o fluxo completo de sincronização de imagens:
  1. Identificação de produtos (via lista manual ou varredura de catálogo)
  2. Download das imagens em alta resolução
  3. Pré-processamento profissional (crop de margem branca + letterbox 250x250)
  4. Sincronização com o diretório local (Desktop/mender_deploy/produtos/sv)
  5. Upload opcional para o Google Cloud Storage (conforme .env)
"""

import os
import sys
from pathlib import Path
from typing import List, Tuple, Optional, Set
import requests
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

# Caminhos base
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
SV_DIR = Path("/home/airis/Desktop/mender_deploy/produtos/sv")

# Módulos internos
from src.utils.image_preprocessor import process_image_file
import src.utils.config as constants


def ask_user(prompt: str, default: bool = True) -> bool:
    """Solicita confirmação interativa no terminal."""
    suffix = " [S/n]: " if default else " [s/N]: "
    try:
        resp = input(prompt + suffix).strip().lower()
        if not resp:
            return default
        return resp in ("s", "sim", "y", "yes")
    except (KeyboardInterrupt, EOFError):
        print("\nOperação cancelada pelo usuário.")
        sys.exit(0)


def step_1_collect_products() -> List[Tuple[str, str]]:
    """
    Etapa 1: Coleta os produtos a serem processados.
    Permite escolher entre lista rápida manual ou varredura automática da API.
    """
    print("\n" + "=" * 65)
    print("ETAPA 1: Identificação de Produtos")
    print("=" * 65)
    print("1) Informar lista de códigos PLU / ERP manualmente")
    print("2) Varrer toda a API e baixar o que estiver faltando em produtos/sv")
    
    choice = input("Escolha a opção [1]: ").strip() or "1"
    tasks: List[Tuple[str, str]] = []

    headers = {
        'Accept': 'application/json',
        'DomainKey': constants.DOMAIN_KEY,
        'Authorization': f'Basic {constants.AUTH_TOKEN}'
    }
    api_url = f"{constants.API_BASE_URL}/importacao/produtos"

    if choice == "1":
        raw_input_codes = input("\nDigite os PLUs separados por vírgula ou espaço: ").strip()
        if not raw_input_codes:
            print("Nenhum código informado.")
            return []
        import re
        codes = [c.strip() for c in re.split(r'[,;\s]+', raw_input_codes) if c.strip()]
        
        print(f"\nConsultando dados na API para {len(codes)} produtos...")
        for code in codes:
            try:
                res = requests.get(api_url, headers=headers, params={'codigo_erp': code}, timeout=15)
                items = res.json().get('data', [])
                if items and items[0].get('imagemUrls'):
                    img_urls = items[0]['imagemUrls']
                    # Pega a melhor resolução (500x500 preferencialmente)
                    best = sorted(img_urls, key=lambda x: x.get('tamanho', 0), reverse=True)[0]
                    tasks.append((code, best.get('localizacao')))
                    print(f"  ✓ {code}: {items[0].get('descricao')} -> Encontrado")
                else:
                    print(f"  ✗ {code}: Imagem não encontrada na API do Superville")
            except Exception as e:
                print(f"  ! Erro ao buscar {code}: {e}")
    else:
        print("\nIniciando busca automática de produtos com imagem...")
        # Varrer páginas da API
        try:
            first_page = requests.get(api_url, headers=headers, params={'limit': 100, 'page': 1, 'possui_imagem': 'true'}, timeout=15).json()
            total_pages = first_page.get('pagination', {}).get('page_count', 1)
            print(f"Total de {first_page.get('pagination', {}).get('count')} produtos com imagem.")
            
            # Carrega códigos locais
            local_sv_codes = {f.stem for f in SV_DIR.glob("*.jpg")} if SV_DIR.exists() else set()
            print(f"Imagens locais em produtos/sv: {len(local_sv_codes)}")
            
            for p in range(1, total_pages + 1):
                page_data = requests.get(api_url, headers=headers, params={'limit': 100, 'page': p, 'possui_imagem': 'true'}, timeout=15).json()
                for prod in page_data.get('data', []):
                    c = str(prod.get('codigo_erp'))
                    if c not in local_sv_codes and prod.get('imagemUrls'):
                        best = sorted(prod['imagemUrls'], key=lambda x: x.get('tamanho', 0), reverse=True)[0]
                        tasks.append((c, best.get('localizacao')))
        except Exception as e:
            print(f"Erro na varredura da API: {e}")

    print(f"\nTotal de produtos selecionados: {len(tasks)}")
    return tasks


def step_2_download_images(tasks: List[Tuple[str, str]]) -> List[Path]:
    """Etapa 2: Baixa as imagens brutas para a pasta data/."""
    print("\n" + "=" * 65)
    print("ETAPA 2: Download das Imagens")
    print("=" * 65)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    downloaded: List[Path] = []
    for code, url in tasks:
        target_path = DATA_DIR / f"{code}.jpg"
        print(f"Baixando {code}.jpg de {url}...")
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            with open(target_path, "wb") as f:
                f.write(r.content)
            downloaded.append(target_path)
            print(f"  ✓ Salvo em {target_path} ({len(r.content)} bytes)")
        except Exception as e:
            print(f"  ✗ Falha ao baixar {code}: {e}")

    return downloaded


def step_3_preprocess_images() -> List[Path]:
    """Etapa 3: Executa crop de margens brancas e letterboxing 250x250."""
    print("\n" + "=" * 65)
    print("ETAPA 3: Pré-processamento de Imagens")
    print("=" * 65)
    files = sorted(DATA_DIR.glob("*.jpg"))
    if not files:
        print("Nenhuma imagem em data/ para pré-processar.")
        return []

    print(f"Padronizando {len(files)} imagens para 250x250 px com crop de margem...")
    for f in files:
        try:
            process_image_file(f, f, target_size=(250, 250), padding_pct=0.08)
            print(f"  ✓ {f.name} pré-processada com sucesso (250x250)")
        except Exception as e:
            print(f"  ✗ Erro ao processar {f.name}: {e}")

    return files


def step_4_sync_to_mender_produtos() -> None:
    """Etapa 4: Copia imagens para Desktop/mender_deploy/produtos/sv."""
    print("\n" + "=" * 65)
    print("ETAPA 4: Sincronização Local (mender_deploy/produtos/sv)")
    print("=" * 65)
    SV_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(DATA_DIR.glob("*.jpg"))
    for f in files:
        dest = SV_DIR / f.name
        import shutil
        shutil.copy2(f, dest)
        print(f"  ✓ Copiado {f.name} -> {dest}")


def step_5_upload_to_gcs() -> None:
    """Etapa 5: Realiza o upload das imagens para o Google Cloud Storage."""
    print("\n" + "=" * 65)
    print("ETAPA 5: Upload para o Google Cloud Storage (GCS)")
    print("=" * 65)
    try:
        from google.cloud import storage
    except ImportError:
        print("Biblioteca google-cloud-storage não instalada.")
        return

    bucket_name = constants.GCS_BUCKET_NAME
    folder_name = constants.GCS_FOLDER_NAME
    print(f"Destino GCS: gs://{bucket_name}/{folder_name}")

    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
    except Exception as e:
        print(f"Erro ao autenticar com o GCP: {e}")
        print("Execute no terminal: gcloud auth application-default login")
        return

    files = sorted(DATA_DIR.glob("*.jpg"))
    for f in files:
        blob_path = f"{folder_name.rstrip('/')}/{f.name}"
        blob = bucket.blob(blob_path)
        print(f"Enviando {f.name} -> gs://{bucket_name}/{blob_path}...")
        try:
            blob.upload_from_filename(str(f), content_type="image/jpeg")
            print(f"  ✓ Upload concluído: {f.name}")
        except Exception as e:
            print(f"  ✗ Erro no upload de {f.name}: {e}")


def main():
    print("=" * 65)
    print("PIPELINE INTERATIVO - SCRAPING, PROCESSAMENTO E DEPLOY DE IMAGENS")
    print("=" * 65)

    # 1. Coleta
    if ask_user("Deseja identificar e baixar novas imagens da API do Superville?", default=True):
        tasks = step_1_collect_products()
        if tasks and ask_user(f"Confirmar download de {len(tasks)} imagens para data/?", default=True):
            step_2_download_images(tasks)
    
    # 2. Pré-processamento
    if ask_user("\nDeseja executar o pré-processamento (crop margens + letterbox 250x250) nas imagens de data/?", default=True):
        step_3_preprocess_images()

    # 3. Sincronização Local
    if ask_user("\nDeseja atualizar as imagens locais em Desktop/mender_deploy/produtos/sv?", default=True):
        step_4_sync_to_mender_produtos()

    # 4. Upload GCS
    if ask_user("\nDeseja fazer o upload das imagens para o GCS especificado no .env?", default=True):
        step_5_upload_to_gcs()

    print("\n" + "=" * 65)
    print("Pipeline finalizado com sucesso!")
    print("=" * 65)


if __name__ == "__main__":
    main()
