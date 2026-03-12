#!/usr/bin/env python3
"""
Script para comparar imagens locais com as que existem no Google Cloud Storage
Faz análise completa mostrando:
- Quantas imagens existem localmente
- Quantas imagens existem no GCS
- Interseção (mesmos nomes)
- Imagens só locais
- Imagens só no GCS
"""

import os
import sys
from pathlib import Path
from typing import Set, Dict
import logging
from tqdm import tqdm

try:
    from google.cloud import storage
except ImportError:
    print("Erro: google-cloud-storage não está instalado.")
    print("Execute: pip install google-cloud-storage")
    sys.exit(1)

from utils.config import GCS_BUCKET_NAME, GCS_FOLDER_NAME, RAW_IMAGES_DIR

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


class ImageComparator:
    """Classe para comparar imagens locais com GCS"""
    
    def __init__(self, bucket_name: str = "cart-production-assets", 
                 destination_folder: str = "test_product_images"):
        self.bucket_name = bucket_name
        self.destination_folder = destination_folder
        self.client = None
        self.bucket = None
        
    def _is_running_on_gcp(self) -> bool:
        """Verifica se está rodando em uma VM do Google Cloud Platform"""
        try:
            import requests
            response = requests.get(
                'http://metadata.google.internal/computeMetadata/v1/instance/',
                headers={'Metadata-Flavor': 'Google'},
                timeout=2
            )
            return response.status_code == 200
        except:
            return False
    
    def initialize_client(self, credentials_path: str = None) -> bool:
        """Inicializa o cliente do Google Cloud Storage"""
        try:
            if self._is_running_on_gcp():
                logger.info("Detectado ambiente GCP - usando credenciais padrão da VM")
                self.client = storage.Client()
            elif credentials_path and os.path.exists(credentials_path):
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
                logger.info(f"Usando credenciais do arquivo: {credentials_path}")
                self.client = storage.Client()
            else:
                logger.info("Tentando usar credenciais padrão do sistema")
                self.client = storage.Client()
            
            self.bucket = self.client.bucket(self.bucket_name)
            
            if not self.bucket.exists():
                logger.error(f"Bucket '{self.bucket_name}' não encontrado!")
                return False
                
            logger.info(f"Cliente inicializado. Bucket: {self.bucket_name}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao inicializar cliente: {e}")
            return False
    
    def get_local_images(self, images_dir: str) -> Set[str]:
        """Obtém conjunto de nomes de imagens locais"""
        images_path = Path(images_dir)
        
        if not images_path.exists():
            logger.error(f"Pasta de imagens não encontrada: {images_dir}")
            return set()
        
        # Extensões de imagem suportadas
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
        
        image_files = set()
        for file_path in images_path.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in image_extensions:
                image_files.add(file_path.name)
        
        logger.info(f"Encontradas {len(image_files)} imagens locais")
        return image_files
    
    def get_gcs_images(self) -> Set[str]:
        """Obtém conjunto de nomes de imagens no GCS"""
        try:
            logger.info(f"Listando imagens no GCS: {self.destination_folder}/")
            
            # Lista todos os blobs no prefixo especificado
            blobs = self.bucket.list_blobs(prefix=f"{self.destination_folder}/")
            
            image_files = set()
            for blob in tqdm(blobs, desc="Listando arquivos no GCS"):
                # Pega apenas o nome do arquivo (sem o caminho da pasta)
                file_name = blob.name.split('/')[-1]
                if file_name:  # Ignora se for apenas a pasta
                    image_files.add(file_name)
            
            logger.info(f"Encontradas {len(image_files)} imagens no GCS")
            return image_files
            
        except Exception as e:
            logger.error(f"Erro ao listar imagens no GCS: {e}")
            return set()
    
    def compare(self, local_dir: str) -> Dict:
        """
        Compara imagens locais com GCS
        
        Returns:
            Dicionário com análise completa
        """
        logger.info("Coletando imagens locais...")
        local_images = self.get_local_images(local_dir)
        
        logger.info("Coletando imagens do GCS...")
        gcs_images = self.get_gcs_images()
        
        # Análise
        intersection = local_images & gcs_images
        only_local = local_images - gcs_images
        only_gcs = gcs_images - local_images
        
        return {
            'local_images': local_images,
            'gcs_images': gcs_images,
            'intersection': intersection,
            'only_local': only_local,
            'only_gcs': only_gcs,
            'total_local': len(local_images),
            'total_gcs': len(gcs_images),
            'total_intersection': len(intersection),
            'total_only_local': len(only_local),
            'total_only_gcs': len(only_gcs),
        }
    
    def print_analysis(self, analysis: Dict):
        """Imprime análise detalhada"""
        print("\n" + "="*70)
        print("ANÁLISE DE COMPARAÇÃO: IMAGENS LOCAIS vs GOOGLE CLOUD STORAGE")
        print("="*70)
        
        print(f"\n📊 ESTATÍSTICAS GERAIS:")
        print(f"   • Total de imagens LOCAIS: {analysis['total_local']:,}")
        print(f"   • Total de imagens no GCS: {analysis['total_gcs']:,}")
        print(f"   • Total de imagens COMUNS: {analysis['total_intersection']:,}")
        
        if analysis['total_local'] > 0:
            pct_intersection = (analysis['total_intersection'] / analysis['total_local']) * 100
            print(f"   • Percentual já no GCS: {pct_intersection:.1f}%")
        
        print(f"\n🔍 DIFERENÇAS:")
        print(f"   • Imagens APENAS LOCAIS (não enviadas): {analysis['total_only_local']:,}")
        print(f"   • Imagens APENAS no GCS (não locais): {analysis['total_only_gcs']:,}")
        
        # Mostra algumas amostras
        if analysis['total_only_local'] > 0:
            print(f"\n📁 AMOSTRAS DE IMAGENS APENAS LOCAIS (primeiras 20):")
            for i, img in enumerate(sorted(list(analysis['only_local']))[:20], 1):
                print(f"   {i}. {img}")
            if analysis['total_only_local'] > 20:
                print(f"   ... e mais {analysis['total_only_local'] - 20} imagens")
        
        if analysis['total_only_gcs'] > 0:
            print(f"\n☁️  AMOSTRAS DE IMAGENS APENAS NO GCS (primeiras 20):")
            for i, img in enumerate(sorted(list(analysis['only_gcs']))[:20], 1):
                print(f"   {i}. {img}")
            if analysis['total_only_gcs'] > 20:
                print(f"   ... e mais {analysis['total_only_gcs'] - 20} imagens")
        
        if analysis['total_intersection'] > 0:
            print(f"\n✅ AMOSTRAS DE IMAGENS COMUNS (primeiras 10):")
            for i, img in enumerate(sorted(list(analysis['intersection']))[:10], 1):
                print(f"   {i}. {img}")
            if analysis['total_intersection'] > 10:
                print(f"   ... e mais {analysis['total_intersection'] - 10} imagens")
        
        print("\n" + "="*70)
        
        # Recomendações
        print("\n💡 RECOMENDAÇÕES:")
        if analysis['total_only_local'] > 0:
            print(f"   • Você tem {analysis['total_only_local']:,} imagens locais que ainda não foram enviadas ao GCS")
            print(f"   • Execute o script upload_files.py para enviar essas imagens")
        
        if analysis['total_only_gcs'] > 0:
            print(f"   • Existem {analysis['total_only_gcs']:,} imagens no GCS que não estão localmente")
            print(f"   • Isso é normal se você limpou a pasta local após uploads anteriores")
        
        if analysis['total_only_local'] == 0:
            print(f"   ✅ Todas as imagens locais já foram enviadas ao GCS!")
        
        print("="*70 + "\n")


def main():
    """Função principal"""
    # Configurações
    print(f"Iniciando comparação de imagens")
    print(f"Bucket: {GCS_BUCKET_NAME}")
    print(f"Pasta no GCS: {GCS_FOLDER_NAME}")
    print(f"Pasta local: {RAW_IMAGES_DIR}\n")
    
    # Inicializa o comparador
    comparator = ImageComparator(GCS_BUCKET_NAME, GCS_FOLDER_NAME)
    
    # Verifica credenciais
    credentials_path = None
    if not comparator._is_running_on_gcp():
        possible_credentials = [
            "credentials.json",
            "../credentials.json", 
            os.path.expanduser("~/.config/gcloud/credentials.json")
        ]
        
        for cred_path in possible_credentials:
            if os.path.exists(cred_path):
                credentials_path = cred_path
                break
    
    # Inicializa cliente
    if not comparator.initialize_client(credentials_path):
        print("Erro: Não foi possível inicializar o cliente do Google Cloud Storage")
        sys.exit(1)
    
    # Faz a comparação
    analysis = comparator.compare(str(RAW_IMAGES_DIR))
    
    # Mostra análise
    comparator.print_analysis(analysis)
    
    # Salva relatório em arquivo
    report_file = "comparison_report.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("### RELATÓRIO DE COMPARAÇÃO DO ENDPOINT NOVO\n")
        f.write(f"**Bucket:** {GCS_BUCKET_NAME}\n")
        f.write(f"**Pasta GCS:** {GCS_FOLDER_NAME}\n")
        f.write(f"**Pasta local:** {RAW_IMAGES_DIR}\n\n")
        
        f.write(f"**Total de imagens locais:** {analysis['total_local']}\n")
        f.write(f"**Total de imagens no GCS:** {analysis['total_gcs']}\n")
        f.write(f"**Total de imagens comuns:** {analysis['total_intersection']}\n")
        f.write(f"**Apenas locais:** {analysis['total_only_local']}\n")
        f.write(f"**Apenas no GCS:** {analysis['total_only_gcs']}\n\n")
        
        if analysis['only_local']:
            f.write("IMAGENS APENAS LOCAIS:\n")
            for img in sorted(analysis['only_local']):
                f.write(f"  - {img}\n")
            f.write("\n")
        
        if analysis['only_gcs']:
            f.write("IMAGENS APENAS NO GCS:\n")
            for img in sorted(analysis['only_gcs']):
                f.write(f"  - {img}\n")

    print(f"✅ Relatório completo salvo em: {report_file}")


if __name__ == "__main__":
    main()
