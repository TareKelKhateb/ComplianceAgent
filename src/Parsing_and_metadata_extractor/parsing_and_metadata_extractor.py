

import os
import json
import logging
import requests
import hashlib
from urllib.parse import urlparse
from typing import Any, Optional
from pathlib import Path

from src.Scrapper.ScrapperClient import ScrapperClient, ScrapperClientError


class ParsingMetaDataExtractor:
    
    def __init__(self, 
                 temp_download_dir: str = "./temp_pdfs", 
                 client: Optional[ScrapperClient] = None):
        """
        Initializes the extractor.
        
        Args:
            client: An optional ScrapperClient instance. If not provided, 
                    a default instance will be created. This allows for dependency 
                    injection during unit testing.
        """
        # 1. Logging Setup (Class-level only, no basicConfig)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s — %(levelname)s — %(message)s",
            )
        
        self.logger = logging.getLogger(__name__)
        
        # 2. Upper Layer API Configuration
        # Use the injected client, or instantiate a new one if none was provided
        self.client = client or ScrapperClient()
        
        # ==========================================
        # 3. Local File System Configuration
        # ==========================================
        self.temp_download_dir = temp_download_dir
        

        # ==========================================
        # 4. Storage Layer Configuration
        # ==========================================
        # TODO: Implement database connections
        

    def fetch_incoming_data(self, url: str, is_crawl: bool = False, limit: int = 1) -> list[Any] | None:
        """
        Step 1: Call the upper layer API to extract metadata from a target URL.
        """
        mode = f"crawl (limit={limit})" if is_crawl else "single-page scrape"
        self.logger.info("▶  Starting %s for: %s", mode, url)
        
        data = None

        try:
            data = self.client.extract_data(url=url, is_crawl=is_crawl, limit=limit)

            if data:
                self.logger.info("✅  Extraction successful — %d record(s) returned.", len(data))
                # Replaced print with logger.debug for consistency
                self.logger.debug("Extracted Payload:\n%s", json.dumps(data, indent=2, ensure_ascii=False))
            else:
                self.logger.warning("⚠️  Extraction returned no data for: %s", url)

        except ScrapperClientError as e:
            self.logger.error("❌  ScrapperClientError: %s", e)
            
        return data


    def fetch_existing_metadata(self, file_url: str) -> dict | None:
        """
        Step 2: Call the storage layer API to get the current metadata 
        (specifically the last known hash) for a specific file using its URL.
        
        Args:
            file_url (str): The URL of the PDF to check in the database.
            
        Returns:
            dict | None: A dictionary containing the latest version's metadata, 
                         or None if this URL has never been saved before.
        """
        pass


    def download_pdf(self, file_url: str, file_name: str, save_directory: str) -> bytes:
        """
        Step 3.1: Download the PDF file using the provided URL.
        Streams it safely to the specified directory, then returns the raw bytes for hashing.
        
        Args:
            pdf_url (str): The direct link to the PDF document.
            file_name (str): The desired name for the file (e.g., "CBE_Law_194.pdf").
            save_directory (str): The target folder path to save the file.
            
        Returns:
            bytes: The binary content of the PDF file. Returns empty bytes (b"") if it fails.
        """
        print(f"[*] Downloading PDF: {file_url}")
        
        # 1. File Extension Check
        if not file_name.lower().endswith('.pdf'):
            file_name += '.pdf'
            
        # 2. Directory Management: Ensure the exact save location exists
        os.makedirs(save_directory, exist_ok=True)
        local_file_path = os.path.join(save_directory, file_name)
        
        # 3. Sanitize the headers to bypass bot protection
        download_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/pdf,application/xhtml+xml,text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.cbe.org.eg/"
        }

        try:
            # 4. Execute the download using stream=True
            with requests.get(file_url, headers=download_headers, timeout=30, stream=True) as response:
                response.raise_for_status() 
                
                # --- MLOPS SAFETY CHECK ---
                content_type = response.headers.get('Content-Type', '').lower()
                if 'application/pdf' not in content_type:
                    print(f"    [!] Download blocked: Server returned '{content_type}' instead of a PDF.")
                    return b""
                # --------------------------
                
                # Write to disk in 8KB chunks.
                with open(local_file_path, 'wb') as file:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            file.write(chunk)
            
                # 5. Read the saved file back into memory to return the bytes
                with open(local_file_path, 'rb') as file:
                    pdf_bytes = file.read()
                    
                print(f"    [+] Successfully downloaded ({len(pdf_bytes)} bytes) to {local_file_path}")
                return pdf_bytes
            
        except requests.exceptions.RequestException as e:
            print(f"    [Error] Failed to download {file_url}: {e}")
            return b""
            



    def calculate_hash(self, file_content: bytes) -> str:
        """
        Step 3.2: Compute a SHA-256 cryptographic hash for the downloaded file 
        to track changes.
        
        Args:
            file_content (bytes): The raw binary content of the PDF file.
            
        Returns:
            str: The hexadecimal representation of the SHA-256 hash. 
                 Returns an empty string if the file content is empty.
        """
        # Safety check: if the download failed and returned empty bytes, return an empty hash
        # Safety check
        if not file_content:
            self.logger.warning("⚠️ Warning: Empty file content provided for hashing.")
            return ""

        self.logger.debug("▶ Calculating SHA-256 hash...")
        
        hasher = hashlib.sha256()
        hasher.update(file_content)
        final_hash = hasher.hexdigest()
        
        self.logger.info("✅ Hash calculated: %s...%s", final_hash[:8], final_hash[-8:])
        return final_hash
    
    

    def has_file_changed(self, new_hash: str, old_hash: str) -> bool:
        """
        Step 3.3: Compare the newly calculated hash with the hash from the storage layer.
        
        Args:
            new_hash (str): The SHA-256 hash of the newly downloaded file.
            old_hash (str): The SHA-256 hash of the most recent version in the database.
                            Can be None or an empty string if the file is brand new.
            
        Returns:
            bool: True if the file is new or has changed. False if it is identical 
                  or if the new hash is invalid (e.g., failed download).
        """
        # Edge Case 1: The download failed, so we have no new hash to compare.
        # We return False so the pipeline doesn't try to store a broken/empty file.
        if not new_hash:
            print("    [-] Invalid or empty new hash. Skipping comparison.")
            return False

        # Edge Case 2: There is no old hash. This means the file was never in the 
        # database before (fetch_existing_metadata returned None). 
        if not old_hash:
            print("    [+] No previous version exists. Marking as a new file.")
            return True

        # Main Logic: Simply compare the two strings
        has_changed = (new_hash != old_hash)

        if has_changed:
            print(f"    [+] Change detected! Hash changed from {old_hash[:8]}... to {new_hash[:8]}...")
        else:
            print("    [-] Hash matches the existing version. No changes detected.")

        return has_changed


    def store_new_version(self, pdf_metadata: dict, file_content: bytes, new_hash: str, is_update: bool = False) -> bool:
        """
        Step 3.4: Save the PDF and update the database.
        If it's an update, explicitly sets the old version's `is_last` flag to False 
        before inserting the new version with `is_last` set to True.
        """
        pass

    def process_pipeline(self, target_url: str, is_crawl: bool = False, limit: int = 1):
        """
        Main Orchestrator: Takes the target URL, fetches the 2D list of metadata, 
        then iterates through each page and each PDF with robust, file-level error handling.
        """
        pass

       

        