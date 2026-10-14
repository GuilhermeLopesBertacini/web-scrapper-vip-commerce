"""
This module provides a class for managing communication with GCS buckets.
"""
import os
import glob
from multiprocessing import cpu_count
from concurrent.futures import ThreadPoolExecutor
from google.cloud.storage import Client, transfer_manager

class GSHelper:
    """
    Abstracts communication with Google Cloud Storage.
    Provides unified, cohesive methods for files and directories (prefixes).
    
    Note on GCS Architecture:
    GCS does not have real "directories". It uses a flat namespace.
    By convention, paths ending with '/' are treated as directories (prefixes).
    """

    def __init__(self, bucket_name: str, project: str):
        """
        Initializes the GS helper for a specific bucket.
        """
        self.bucket_name = bucket_name
        self.project = project
        self.client = Client(project)
        self.bucket = self.client.bucket(self.bucket_name)

    def list_items(self, prefix: str = "", full_path: bool = True) -> set[str]:
        """
        Lists items (files/blobs) within the GCS bucket.
        """
        try:
            blobs = self.bucket.list_blobs(prefix=prefix)
            if full_path:
                return {blob.name for blob in blobs}
            return {blob.name.split('/')[-1] for blob in blobs if blob.name.split('/')[-1]}
        except Exception as e:
            print(f"Error listing items in {self.bucket_name}/{prefix}: {e}")
            return set()

    def upload(self, local_path: str, cloud_path: str = "", skip_existing: bool = False) -> None:
        """
        Uploads a file or a directory to GCS.
        If local_path is a directory, uploads all its files recursively.
        If skip_existing is True, files that already exist remotely are ignored.
        """
        try:
            if os.path.isdir(local_path):
                # Collect all files recursively
                files = [f for f in glob.glob(os.path.join(local_path, '**', '*.*'), recursive=True) if os.path.isfile(f)]
                if not files:
                    print(f"No files found to upload in directory {local_path}")
                    return
                
                relative_files = [os.path.relpath(f, local_path) for f in files]
                
                # Cloud path as prefix
                prefix = cloud_path if cloud_path.endswith('/') or not cloud_path else cloud_path + '/'
                
                if skip_existing:
                    existing_blobs = self.list_items(prefix=prefix, full_path=True)
                    # Normalize remote names to compare with relative paths
                    existing_relative = {
                        b[len(prefix):] if b.startswith(prefix) else b 
                        for b in existing_blobs
                    }
                    
                    # Filter relative_files, keeping only those not in GCS
                    relative_files = [
                        f for f in relative_files 
                        if f.replace(os.sep, '/') not in existing_relative
                    ]
                    
                    if not relative_files:
                        print(f"All files already exist in {self.bucket_name}/{prefix}. Nothing to upload.")
                        return
                
                print(f"Uploading {len(relative_files)} files to {self.bucket_name}/{prefix}...")
                results = transfer_manager.upload_many_from_filenames(
                    self.bucket,
                    relative_files,
                    source_directory=local_path,
                    max_workers=cpu_count(),
                    blob_name_prefix=prefix
                )
                for name, result in zip(relative_files, results):
                    if isinstance(result, Exception):
                        print(f"Failed to upload {name}: {result}")
                print(f"Directory {local_path} uploaded to {self.bucket_name}/{prefix}")
                
            elif os.path.isfile(local_path):
                # If cloud_path is a directory, append filename
                if cloud_path.endswith('/'):
                    cloud_path = os.path.join(cloud_path, os.path.basename(local_path))
                elif not cloud_path:
                    cloud_path = os.path.basename(local_path)

                blob = self.bucket.blob(cloud_path)
                blob.upload_from_filename(local_path)
                print(f"File {local_path} uploaded to {self.bucket_name}/{cloud_path}")
            else:
                print(f"Local path {local_path} does not exist.")
                
        except Exception as e:
            print(f"Error uploading {local_path} to {self.bucket_name}: {e}")

    def download(self, cloud_path: str, local_path: str) -> None:
        """
        Downloads a file or a prefix (directory) from GCS.
        """
        try:
            # Treat as directory if path ends with '/'
            if cloud_path.endswith('/'):
                blobs = list(self.bucket.list_blobs(prefix=cloud_path))
                blob_names = [b.name for b in blobs]
                if not blob_names:
                    print(f"No files found with prefix {cloud_path}")
                    return
                
                os.makedirs(local_path, exist_ok=True)
                results = transfer_manager.download_many_to_path(
                    self.bucket, blob_names, destination_directory=local_path,
                    max_workers=cpu_count(), blob_name_prefix=cloud_path
                )
                for name, result in zip(blob_names, results):
                    if isinstance(result, Exception):
                        print(f"Failed to download {name}: {result}")
                print(f"Downloaded prefix {cloud_path} to {local_path}")
                
            else:
                blob = self.bucket.blob(cloud_path)
                if not blob.exists():
                    print(f"Blob {cloud_path} does not exist in {self.bucket_name}")
                    return
                
                # If local_path is a directory, append filename
                if os.path.isdir(local_path) or local_path.endswith('/'):
                    os.makedirs(local_path, exist_ok=True)
                    local_path = os.path.join(local_path, os.path.basename(cloud_path))
                else:
                    os.makedirs(os.path.dirname(local_path) or '.', exist_ok=True)
                
                blob.download_to_filename(local_path)
                print(f"File {cloud_path} downloaded to {local_path}")
                
        except Exception as e:
            print(f"Error downloading {cloud_path} from {self.bucket_name}: {e}")

    def delete(self, cloud_path: str) -> None:
        """
        Deletes a file or a prefix (directory) from GCS.
        """
        try:
            if cloud_path.endswith('/'):
                blobs = list(self.bucket.list_blobs(prefix=cloud_path))
                if not blobs:
                    print(f"No blobs found to delete under prefix {cloud_path}")
                    return

                def _delete_blob(b):
                    try:
                        b.delete()
                    except Exception as e:
                        print(f"Failed to delete {b.name}: {e}")

                # I/O bound tasks like HTTP requests scale well with many threads
                max_threads = min(32, (cpu_count() or 1) * 4)
                
                with ThreadPoolExecutor(max_workers=max_threads) as executor:
                    list(executor.map(_delete_blob, blobs))
                    
                print(f"Deleted prefix {cloud_path} from {self.bucket_name} ({len(blobs)} files)")
            else:
                blob = self.bucket.blob(cloud_path)
                if blob.exists():
                    blob.delete()
                    print(f"Deleted {cloud_path} from {self.bucket_name}")
                else:
                    print(f"Blob {cloud_path} does not exist in {self.bucket_name}")
        except Exception as e:
            print(f"Error deleting {cloud_path} from {self.bucket_name}: {e}")

    def move(self, cloud_path: str, dest_cloud_path: str = "", dest_bucket_name: str = None) -> None:
        """
        Moves a file or prefix (directory) to another location or bucket.
        """
        try:
            dest_bucket = self.client.bucket(dest_bucket_name) if dest_bucket_name else self.bucket
            
            if cloud_path.endswith('/'):
                if dest_cloud_path and not dest_cloud_path.endswith('/'):
                    dest_cloud_path += '/'
                    
                blobs = list(self.bucket.list_blobs(prefix=cloud_path))
                if not blobs:
                    print(f"No blobs found to move under prefix {cloud_path}")
                    return

                def _move_blob(blob):
                    try:
                        # Calculate new path preserving directory structure
                        relative_path = blob.name[len(cloud_path):]
                        new_blob_name = dest_cloud_path + relative_path
                        self.bucket.copy_blob(blob, dest_bucket, new_blob_name)
                        blob.delete()
                    except Exception as e:
                        print(f"Failed to move {blob.name}: {e}")

                max_threads = min(32, (cpu_count() or 1) * 4)
                
                with ThreadPoolExecutor(max_workers=max_threads) as executor:
                    list(executor.map(_move_blob, blobs))
                    
                print(f"Moved prefix {cloud_path} to {dest_bucket.name}/{dest_cloud_path} ({len(blobs)} files)")
            else:
                if dest_cloud_path.endswith('/'):
                    dest_cloud_path = dest_cloud_path + os.path.basename(cloud_path)
                elif not dest_cloud_path:
                    dest_cloud_path = os.path.basename(cloud_path)
                    
                blob = self.bucket.blob(cloud_path)
                if blob.exists():
                    self.bucket.copy_blob(blob, dest_bucket, dest_cloud_path)
                    blob.delete()
                    print(f"Moved {cloud_path} to {dest_bucket.name}/{dest_cloud_path}")
                else:
                    print(f"Blob {cloud_path} does not exist in {self.bucket_name}")
        except Exception as e:
            print(f"Error moving {cloud_path}: {e}")


if __name__ == "__main__":
    # Example usage
    import src.utils.config as CONSTANTS
    gs_helper = GSHelper(bucket_name=CONSTANTS.GCS_BUCKET_NAME, project=CONSTANTS.GCP_PROJECT)
    gs_helper.upload(cloud_path=CONSTANTS.GCS_FOLDER_NAME, local_path="/home/airis/web-scrapper-vip-commerce/data", skip_existing=False)
    # print("Starting to move images to new GCS path...")
    # gs_helper.move(cloud_path="public_urbanic/products_images/", dest_cloud_path="public_urbanic/images/products_images/")