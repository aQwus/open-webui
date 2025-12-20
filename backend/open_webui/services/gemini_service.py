import logging
import os
import time
import requests
import mimetypes
from pathlib import Path
from typing import Optional, Tuple

from google import genai
from google.genai import types

from open_webui.config import GEMINI_API_KEY, TOP_K, GEMINI_MODEL1, GEMINI_MODEL2, GEMINI_MODEL3
from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


class GeminiService:
    """
    Service for integrating with Gemini File Storage and embeddings.
    Handles file uploads, embedding generation, and file management per user.
    """

    def __init__(self):
        """Initialize Gemini client with API key."""
        if not GEMINI_API_KEY:
            log.warning("GEMINI_API_KEY not configured. Gemini integration disabled.")
            self.client = None
            return

        try:
            self.client = genai.Client(api_key=GEMINI_API_KEY)
            log.info("Gemini client initialized successfully")
        except Exception as e:
            log.error(f"Failed to initialize Gemini client: {e}")
            self.client = None

    def is_enabled(self) -> bool:
        """Check if Gemini integration is enabled."""
        return self.client is not None

    def find_file_search_store(self, user_id: str) -> Optional[str]:
        """
        Find an existing file search store for a specific user (does NOT create).
        
        Args:
            user_id: User ID to find store for
            
        Returns:
            Store name (ID) if found, None otherwise
        """
        if not self.is_enabled():
            return None

        store_name = f"{user_id}_file_search_store"
        
        try:
            # List stores and find existing one
            for store in self.client.file_search_stores.list():
                if hasattr(store, 'display_name') and store.display_name == store_name:
                    log.debug(f"Found existing file search store: {store.name}")
                    return store.name
            
            # Store not found
            log.debug(f"No file search store found for user {user_id}")
            return None
            
        except Exception as e:
            log.error(f"Error finding file search store for user {user_id}: {e}")
            return None

    def get_or_create_file_search_store(self, user_id: str) -> Optional[str]:
        """
        Get or create a file search store for a specific user.
        
        Args:
            user_id: User ID to create store for
            
        Returns:
            Store name (ID) if successful, None otherwise
        """
        if not self.is_enabled():
            return None

        store_name = f"{user_id}_file_search_store"
        
        try:
            # Try to find existing store first
            existing_store = self.find_file_search_store(user_id)
            if existing_store:
                log.info(f"Found existing file search store: {existing_store}")
                return existing_store
            
            # Create new store if not found
            file_search_store = self.client.file_search_stores.create(
                config=types.CreateFileSearchStoreConfig(
                    display_name=store_name
                )
            )
            log.info(f"Created new file search store: {file_search_store.name}")
            return file_search_store.name
            
        except Exception as e:
            log.error(f"Error getting/creating file search store for user {user_id}: {e}")
            return None

    def upload_file_to_gemini(
        self,
        file_path: str,
        filename: str,
        user_id: str,
        document_id: str
    ) -> Optional[Tuple[str, str]]:
        """
        Upload a file to Gemini File Storage for a specific user.
        
        Args:
            file_path: Relative path to file in storage
            filename: Original filename
            user_id: User ID for isolation
            document_id: Document ID for traceability
            
        Returns:
            Tuple of (gemini_file_id, gemini_store_id) if successful, None otherwise
        """
        if not self.is_enabled():
            log.warning("Gemini client not initialized")
            return None

        try:
            # Get or create user's file search store
            store_id = self.get_or_create_file_search_store(user_id)
            if not store_id:
                log.error(f"Failed to get file search store for user {user_id}")
                return None

            # Read file from local storage
            from open_webui.config import UPLOAD_DIR
            full_file_path = os.path.join(UPLOAD_DIR, file_path)
            
            if not os.path.exists(full_file_path):
                log.error(f"File not found at {full_file_path}")
                return None

            # Detect MIME type from file extension
            mime_type, _ = mimetypes.guess_type(full_file_path)
            if not mime_type:
                # Default to application/octet-stream if can't detect
                mime_type = "application/octet-stream"
                log.warning(f"Could not detect MIME type for {full_file_path}, using {mime_type}")

            # Sanitize filename to remove non-ASCII characters for Gemini
            # Replace common Unicode characters with ASCII equivalents
            safe_filename = filename.encode('ascii', 'ignore').decode('ascii')
            if not safe_filename:
                # If entire filename was non-ASCII, use a safe default
                safe_filename = f"document_{document_id}"
            
            log.info(f"Sanitized filename for Gemini: {safe_filename}")

            # Upload file to file search store with chunking config
            operation = self.client.file_search_stores.upload_to_file_search_store(
                file=full_file_path,
                file_search_store_name=store_id,
                config={
                    'display_name': safe_filename,  # Use ASCII-safe filename
                    'mime_type': mime_type,
                    'chunking_config': {
                        'white_space_config': {
                            'max_tokens_per_chunk': 500,
                            'max_overlap_tokens': 100
                        }
                    }
                }
            )
            
            # Extract doc ID from operation.name immediately
            # Format: "fileSearchStores/{store}/upload/operations/{doc-id}"
            gemini_file_id = operation.name.split('/')[-1]
            log.info(f"Upload operation started: {operation.name}")
            log.info(f"Extracted doc ID: {gemini_file_id}")

            # Wait for operation to complete using polling
            while not operation.done:
                time.sleep(2)
                operation = self.client.operations.get(operation)
            
            log.info(f"Upload operation completed: {operation.name}")
            return (gemini_file_id, store_id)

        except Exception as e:
            log.error(f"Error uploading file to Gemini: {e}")
            return None

    def retrieve_context(self, user_query: str, user_id: str) -> Optional[str]:
        """
        Retrieve relevant context from Gemini File Storage for a user query.
        Uses file search with model fallback on 503 errors.
        
        Args:
            user_query: The user's question/prompt
            user_id: User ID for fetching their file search store
            
        Returns:
            Retrieved context as string, or None if retrieval fails/no documents
        """
        if not self.is_enabled():
            return None

        try:
            # Find user's file search store (do NOT create)
            store_name = self.find_file_search_store(user_id)
            if not store_name:
                log.info(f"No file search store found for user {user_id}, skipping context retrieval silently")
                return None

            # Try models in order with 503 retry logic
            models = [GEMINI_MODEL1, GEMINI_MODEL2, GEMINI_MODEL3]
            
            for model in models:
                try:
                    log.info(f"Attempting context retrieval with model: {model}")
                    
                    response = self.client.models.generate_content(
                        model=model,
                        contents=f"What context is found in the documents for the following query: {user_query}",
                        config=types.GenerateContentConfig(
                            tools=[
                                types.Tool(
                                    file_search=types.FileSearch(
                                        file_search_store_names=[store_name],
                                        top_k=TOP_K
                                    )
                                )
                            ]
                        )
                    )
                    
                    # Successfully retrieved context
                    context = response.text
                    log.info(f"Context retrieved successfully with model {model}")
                    log.info(f"Context preview: {context[:200]}...")  # Log first 200 chars
                    return context
                    
                except Exception as e:
                    error_str = str(e)
                    
                    # Check for 503 error
                    if "503" in error_str or "overloaded" in error_str.lower():
                        log.warning(f"Model {model} returned 503 (overloaded), trying next model")
                        continue  # Try next model
                    else:
                        # Non-503 error, log and fail
                        log.error(f"Context retrieval failed with model {model}: {e}")
                        continue # Try next model
            
            # All models failed with 503
            log.error("All Gemini models failed (503 overloaded), proceeding without context")
            return None
            
        except Exception as e:
            log.error(f"Unexpected error during context retrieval: {e}")
            return None

    def check_document_exists(self, gemini_file_id: str, gemini_store_id: str) -> bool:
        """
        Check if a document exists in Gemini File Storage.
        
        Args:
            gemini_file_id: The Gemini document ID
            gemini_store_id: The Gemini store ID
            
        Returns:
            True if document exists, False otherwise
        """
        if not self.is_enabled():
            log.warning("Gemini client not initialized, cannot check document")
            return False

        try:
            # Step 1: Check if store exists
            store_found = False
            for store in self.client.file_search_stores.list():
                if store.name == gemini_store_id:
                    store_found = True
                    log.info(f"Found file search store: {gemini_store_id}")
                    
                    # Step 2: Check if document exists in this store
                    expected_doc_name = f"{gemini_store_id}/documents/{gemini_file_id}"
                    
                    for doc in self.client.file_search_stores.documents.list(parent=store.name):
                        if doc.name == expected_doc_name:
                            log.info(f"Document exists in Gemini: {expected_doc_name}")
                            return True
                    
                    # Store found but document not in it
                    log.info(f"Document not found in store: {expected_doc_name}")
                    return False
            
            if not store_found:
                log.info(f"File search store not found: {gemini_store_id}")
                return False
            
            return False
                
        except Exception as e:
            log.error(f"Error checking if document exists in Gemini: {e}")
            return False

    def delete_document_from_gemini(self, gemini_file_id: str, gemini_store_id: str) -> bool:
        """
        Delete a document from Gemini File Storage.
        
        Args:
            gemini_file_id: The Gemini document ID
            gemini_store_id: The Gemini store ID
            
        Returns:
            True if deletion successful, False otherwise
        """
        if not self.is_enabled():
            log.warning("Gemini client not initialized, cannot delete document")
            return False

        try:
            
            # Construct document path
            # gemini_store_id is already the full store path (e.g., "fileSearchStores/{store-id}")
            # gemini_file_id is just the document ID
            doc_name = f"{gemini_store_id}/documents/{gemini_file_id}"
            
            # Construct deletion URL with force flag
            url = f"https://generativelanguage.googleapis.com/v1beta/{doc_name}?force=true"
            headers = {"x-goog-api-key": GEMINI_API_KEY}
            
            log.info(f"Attempting to delete document from Gemini: {doc_name}")
            
            # Send DELETE request
            response = requests.delete(url, headers=headers)
            
            if response.status_code == 200:
                log.info(f"Successfully deleted document from Gemini: {doc_name}")
                return True
            else:
                log.error(f"Failed to delete document from Gemini. Status: {response.status_code}, Response: {response.text}")
                return False
                
        except Exception as e:
            log.error(f"Error deleting document from Gemini: {e}")
            return False


# Singleton instance
gemini_service = GeminiService()
