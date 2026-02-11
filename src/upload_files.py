#!/usr/bin/env python3
"""
Script para fazer upload de imagens para Google Cloud Storage
Faz upload de todas as imagens da pasta src/assets/raw_images 
para o bucket "cart-production-assets" na pasta "jaguare_product_images"
"""

import os
import sys
from pathlib import Path
from typing import List, Optional
import logging
from tqdm import tqdm

try:
    from google.cloud import storage
    from google.cloud.exceptions import GoogleCloudError
except ImportError:
    print("Erro: google-cloud-storage não está instalado.")
    print("Execute: pip install google-cloud-storage")
    sys.exit(1)


# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('upload_log.txt'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ImageUploader:
    """Classe para gerenciar upload de imagens para Google Cloud Storage"""
    
    def __init__(self, bucket_name: str = "cart-production-assets", 
                 destination_folder: str = "test_product_images"):
        self.bucket_name = bucket_name
        self.destination_folder = destination_folder
        self.client = None
        self.bucket = None
        
    def _is_running_on_gcp(self) -> bool:
        """
        Verifica se está rodando em uma VM do Google Cloud Platform
        
        Returns:
            True se estiver rodando em GCP, False caso contrário
        """
        try:
            import requests
            # Tenta acessar o metadata server do GCP
            response = requests.get(
                'http://metadata.google.internal/computeMetadata/v1/instance/',
                headers={'Metadata-Flavor': 'Google'},
                timeout=2
            )
            return response.status_code == 200
        except:
            return False
    
    def initialize_client(self, credentials_path: Optional[str] = None) -> bool:
        """
        Inicializa o cliente do Google Cloud Storage
        
        Args:
            credentials_path: Caminho para o arquivo de credenciais JSON (opcional)
            
        Returns:
            True se inicializado com sucesso, False caso contrário
        """
        try:
            # Verifica se está rodando em uma VM do GCP
            if self._is_running_on_gcp():
                logger.info("Detectado ambiente Google Cloud Platform - usando credenciais padrão da VM")
                self.client = storage.Client()
            elif credentials_path and os.path.exists(credentials_path):
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
                logger.info(f"Usando credenciais do arquivo: {credentials_path}")
                self.client = storage.Client()
            else:
                # Tenta usar credenciais padrão (gcloud auth application-default)
                logger.info("Tentando usar credenciais padrão do sistema")
                self.client = storage.Client()
            
            self.bucket = self.client.bucket(self.bucket_name)
            
            # Testa se o bucket existe
            if not self.bucket.exists():
                logger.error(f"Bucket '{self.bucket_name}' não encontrado!")
                return False
                
            logger.info(f"Cliente inicializado com sucesso. Bucket: {self.bucket_name}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao inicializar cliente: {e}")
            logger.error("Dicas de troubleshooting:")
            logger.error("1. Se estiver em VM do GCP: verifique se o service account tem permissões para o bucket")
            logger.error("2. Se estiver local: execute 'gcloud auth application-default login'")
            logger.error("3. Ou forneça um arquivo de credenciais JSON")
            return False
    
    def get_image_files(self, images_dir: str) -> List[Path]:
        """
        Obtém lista de arquivos de imagem na pasta especificada
        
        Args:
            images_dir: Caminho para a pasta de imagens
            
        Returns:
            Lista de caminhos para arquivos de imagem
        """
        images_path = Path(images_dir)
        
        if not images_path.exists():
            logger.error(f"Pasta de imagens não encontrada: {images_dir}")
            return []
        
        # Extensões de imagem suportadas
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
        
        image_files = []
        for file_path in images_path.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in image_extensions:
                image_files.append(file_path)
        
        logger.info(f"Encontrados {len(image_files)} arquivos de imagem em {images_dir}")
        return sorted(image_files)
    
    def upload_file(self, local_file_path: Path, remote_file_name: str) -> bool:
        """
        Faz upload de um arquivo para o Google Cloud Storage
        
        Args:
            local_file_path: Caminho local do arquivo
            remote_file_name: Nome do arquivo no storage
            
        Returns:
            True se o upload foi bem-sucedido, False caso contrário
        """
        try:
            # Caminho completo no storage
            blob_name = f"{self.destination_folder}/{remote_file_name}"
            blob = self.bucket.blob(blob_name)
            
            # Verifica se o arquivo já existe
            if blob.exists():
                logger.info(f"Arquivo já existe no storage: {blob_name}")
                return True
            
            # Faz o upload
            blob.upload_from_filename(str(local_file_path))
            logger.info(f"Upload realizado: {local_file_path.name} -> {blob_name}")
            return True
            
        except GoogleCloudError as e:
            logger.error(f"Erro do Google Cloud ao fazer upload de {local_file_path.name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Erro inesperado ao fazer upload de {local_file_path.name}: {e}")
            return False
    
    def upload_all_images(self, images_dir: str) -> dict:
        """
        Faz upload de todas as imagens da pasta especificada
        
        Args:
            images_dir: Caminho para a pasta de imagens
            
        Returns:
            Dicionário com estatísticas do upload
        """
        image_files = self.get_image_files(images_dir)
        
        if not image_files:
            logger.warning("Nenhum arquivo de imagem encontrado para upload")
            return {"total": 0, "success": 0, "failed": 0, "skipped": 0}
        
        stats = {"total": len(image_files), "success": 0, "failed": 0, "skipped": 0}
        
        logger.info(f"Iniciando upload de {len(image_files)} imagens...")
        
        # Barra de progresso
        with tqdm(total=len(image_files), desc="Uploading images") as pbar:
            for image_file in image_files:
                try:
                    success = self.upload_file(image_file, image_file.name)
                    if success:
                        stats["success"] += 1
                    else:
                        stats["failed"] += 1
                        
                except Exception as e:
                    logger.error(f"Erro ao processar {image_file.name}: {e}")
                    stats["failed"] += 1
                
                pbar.update(1)
        
        return stats
    
    def print_summary(self, stats: dict):
        """Imprime resumo do upload"""
        print("\n" + "="*50)
        print("RESUMO DO UPLOAD")
        print("="*50)
        print(f"Total de arquivos: {stats['total']}")
        print(f"Uploads bem-sucedidos: {stats['success']}")
        print(f"Uploads falharam: {stats['failed']}")
        print(f"Arquivos ignorados: {stats['skipped']}")
        print(f"Taxa de sucesso: {(stats['success']/stats['total']*100):.1f}%")
        print("="*50)


def main():
    """Função principal"""
    # Configurações
    BUCKET_NAME = "cart-production-assets"
    DESTINATION_FOLDER = "violeta_product_images"
    
    # Caminho para a pasta de imagens (relativo ao script)
    script_dir = Path(__file__).parent
    images_dir = script_dir / "assets" / "raw_images"
    
    print(f"Iniciando upload de imagens para Google Cloud Storage")
    print(f"Bucket: {BUCKET_NAME}")
    print(f"Pasta de destino: {DESTINATION_FOLDER}")
    print(f"Pasta de origem: {images_dir}")
    
    # Inicializa o uploader
    uploader = ImageUploader(BUCKET_NAME, DESTINATION_FOLDER)
    
    # Verifica se existe arquivo de credenciais (apenas se não estiver em GCP)
    credentials_path = None
    if not uploader._is_running_on_gcp():
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
    if not uploader.initialize_client(credentials_path):
        print("Erro: Não foi possível inicializar o cliente do Google Cloud Storage")
        if uploader._is_running_on_gcp():
            print("Você está em uma VM do GCP. Verifique se o service account da VM tem permissões para o bucket.")
            print("Execute: gcloud compute instances describe NOME_DA_VM --zone=SUA_ZONE --format='value(serviceAccounts[0].email)'")
        else:
            print("Verifique suas credenciais:")
            print("1. Execute: gcloud auth application-default login")
            print("2. Ou forneça um arquivo credentials.json")
        sys.exit(1)
    
    # Faz upload das imagens
    stats = uploader.upload_all_images(str(images_dir))
    
    # Mostra resumo
    uploader.print_summary(stats)
    
    # Código de saída baseado no sucesso
    if stats["failed"] == 0:
        print("✅ Todos os uploads foram realizados com sucesso!")
        sys.exit(0)
    else:
        print("⚠️  Alguns uploads falharam. Verifique o log para mais detalhes.")
        sys.exit(1)


if __name__ == "__main__":
    main()
