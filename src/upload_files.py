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

from src.utils.config import GCS_BUCKET_NAME, GCS_FOLDER_NAME, RAW_IMAGES_DIR

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
    
    def get_remote_blob_names(self) -> set:
        """
        Obtém conjunto de nomes de arquivos que já existem no storage remoto
        
        Returns:
            Set com nomes dos arquivos que já existem remotamente
        """
        try:
            blobs = self.client.list_blobs(self.bucket_name, prefix=self.destination_folder + '/')
            # Extrai apenas o nome do arquivo (sem o prefixo do diretório)
            remote_files = set()
            for blob in blobs:
                # Remove o prefixo do diretório do nome do blob
                file_name = blob.name.replace(f"{self.destination_folder}/", "")
                if file_name:  # Ignora o diretório em si
                    remote_files.add(file_name)
            
            logger.info(f"Encontrados {len(remote_files)} arquivos remotos em {self.destination_folder}")
            return remote_files
        except Exception as e:
            logger.error(f"Erro ao listar blobs remotos: {e}")
            return set()
    
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
            # if blob.exists():
            #     logger.info(f"Arquivo já existe no storage: {blob_name}")
            #     return True
            
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
        Faz upload apenas de arquivos que não existem remotamente (diferença de sets)
        
        Args:
            images_dir: Caminho para a pasta de imagens
            
        Returns:
            Dicionário com estatísticas do upload
        """
        # Lista arquivos locais
        image_files = self.get_image_files(images_dir)
        
        if not image_files:
            logger.warning("Nenhum arquivo de imagem encontrado para upload")
            return {"total": 0, "success": 0, "failed": 0, "skipped": 0}
        
        # Lista arquivos remotos
        logger.info("Listando arquivos remotos...")
        remote_files = self.get_remote_blob_names()
        
        # Cria sets para comparação
        local_file_names = {f.name for f in image_files}
        
        # Diferença de sets: arquivos que existem localmente mas não remotamente
        files_to_upload = local_file_names - remote_files
        files_already_exist = local_file_names & remote_files
        
        # Filtra apenas os arquivos que precisam ser enviados
        image_files_to_upload = [f for f in image_files if f.name in files_to_upload]
        
        # Estatísticas
        stats = {
            "total": len(image_files),
            "success": 0,
            "failed": 0,
            "skipped": len(files_already_exist)
        }
        
        # Log da análise
        print("\n" + "="*60)
        print("ANÁLISE DE ARQUIVOS")
        print("="*60)
        print(f"📁 Arquivos locais encontrados: {len(local_file_names)}")
        print(f"☁️  Arquivos remotos existentes: {len(remote_files)}")
        print(f"✅ Arquivos já sincronizados: {len(files_already_exist)}")
        print(f"📤 Arquivos a fazer upload: {len(files_to_upload)}")
        print("="*60 + "\n")
        
        if files_already_exist:
            logger.info(f"Arquivos que já existem remotamente (serão ignorados): {sorted(files_already_exist)}")
        
        if not image_files_to_upload:
            logger.info("✅ Todos os arquivos já existem remotamente. Nenhum upload necessário.")
            return stats
        
        logger.info(f"Iniciando upload de {len(image_files_to_upload)} imagens novas...")
        
        # Barra de progresso
        with tqdm(total=len(image_files_to_upload), desc="Uploading images") as pbar:
            for image_file in image_files_to_upload:
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
    print(f"Iniciando upload de imagens para Google Cloud Storage")
    print(f"Bucket: {GCS_BUCKET_NAME}")
    print(f"Pasta de destino: {GCS_FOLDER_NAME}")
    print(f"Pasta de origem: {RAW_IMAGES_DIR}")

    confirmation = input("Deseja continuar? (s/n): ").strip().lower()
    if confirmation != 's':
        print("Upload cancelado pelo usuário.")
        sys.exit(0)
    
    # Inicializa o uploader
    uploader = ImageUploader(GCS_BUCKET_NAME, GCS_FOLDER_NAME)
    
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
    stats = uploader.upload_all_images(str(RAW_IMAGES_DIR))
    
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
