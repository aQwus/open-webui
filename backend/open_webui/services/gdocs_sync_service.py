import logging
import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple

from open_webui.config import UPLOAD_DIR, GDOCS_SEARCH_MAX_RESULTS
from open_webui.services.composio_service import composio_service
from open_webui.services.gemini_service import gemini_service
from open_webui.services.supabase_service import supabase_service

log = logging.getLogger(__name__)


class GDocsSyncService:
    """Service for syncing Google Docs to Gemini File Storage."""
    
    def __init__(self):
        self.composio = composio_service
        self.gemini = gemini_service
        self.supabase = supabase_service
    
    def sync_gdocs(self, openwebui_user_id: str, user_email: str, gdocs_user_id: str) -> dict:
        """Main sync orchestrator for Google Docs."""
        try:
            log.info("Starting Google Docs sync for user %s", openwebui_user_id)
            self.supabase.update_user_sync_status(openwebui_user_id, 'gdocs', 'in_progress')
            
            # Step 1: Fetch all documents from Google Docs (with pagination and retry)
            log.info("Step 1/4: Fetching documents from Google Docs")
            
            # Retry logic for "No connected account" error (connection propagation delay)
            max_retries = 3
            retry_delays = [10, 20, 30]  # seconds between retries
            all_docs = None
            docs_count = 0
            
            for attempt in range(max_retries):
                try:
                    all_docs, docs_count = self._fetch_all_documents_with_pagination(gdocs_user_id)
                    break  # Success, exit retry loop
                except Exception as e:
                    error_str = str(e)
                    # Check if it's the "No connected account" error
                    if ("[1803]" in error_str or "No connected account" in error_str) and attempt < max_retries - 1:
                        wait_time = retry_delays[attempt]
                        log.warning(
                            "Attempt %d/%d: Connection not ready yet. "
                            "OAuth may still be propagating. Waiting %ds before retry...",
                            attempt + 1, max_retries, wait_time
                        )
                        time.sleep(wait_time)
                        continue  # Retry
                    else:
                        # Either it's a different error, or we've exhausted retries
                        raise
            
            if docs_count == 0:
                log.info("No documents found in Google Docs")
                self.supabase.update_user_sync_status(openwebui_user_id, 'gdocs', 'success')
                return {"status": "success", "docs_count": 0, "error": None}
            
            log.info("Step 1/4: Fetched %d document(s) from Google Docs", docs_count)
            
            # Step 2: Get Gemini store (shared across all docs)
            log.info("Step 2/4: Getting Gemini store")
            gemini_store_id = self._get_or_create_user_store(openwebui_user_id)
            log.info("Step 2/4: Using Gemini store: %s", gemini_store_id)
            
            # Step 3: Get connection_id for metadata
            from open_webui.config import GDOCS_AUTH_CONFIG_ID
            connection_status = self.composio.check_connection_status(gdocs_user_id, GDOCS_AUTH_CONFIG_ID)
            connection_id = connection_status.get('connection_id', '')
            
            # Step 4: Process each document individually
            log.info("Step 3/4: Processing and uploading documents")
            successful_uploads = 0
            failed_uploads = 0
            
            for idx, doc in enumerate(all_docs):
                try:
                    doc_id = doc['id']
                    doc_name = doc['name']
                    created_time = doc['createdTime']
                    modified_time = doc['modifiedTime']
                    
                    log.debug("Processing doc %d/%d: %s", idx + 1, docs_count, doc_name)
                    
                    # Skip non-native Google Docs (Google Drive files start with '1-')
                    if doc_id.startswith('1-'):
                        log.warning("Skipping Google Drive file (not a native Doc): %s (ID: %s)", doc_name, doc_id)
                        continue
                    
                    # Fetch doc content
                    doc_content = self._fetch_document_content(gdocs_user_id, doc_id)
                    
                    if not doc_content or not doc_content.strip():
                        log.warning("Empty content for doc %s, skipping", doc_name)
                        continue
                    
                    # Upload to Gemini as individual file
                    temp_file_path = None
                    try:
                        temp_file_path = self._create_doc_file(doc_name, doc_content)
                        
                        gemini_result = self.gemini.upload_file_to_gemini(
                            file_path=temp_file_path,
                            filename=f"gdoc_{doc_id}.txt",
                            user_id=openwebui_user_id,
                            document_id=str(uuid.uuid4())
                        )
                        
                        if not gemini_result:
                            raise Exception("Gemini upload failed")
                        
                        gemini_file_id, _ = gemini_result
                        log.debug("Uploaded to Gemini: %s", gemini_file_id)
                        
                        # Save metadata to Supabase
                        self.supabase.insert_document_metadata({
                            'id': str(uuid.uuid4()),
                            'user_id': openwebui_user_id,
                            'user_email': user_email,
                            'filename': doc_name,
                            'path': '',  # No R2 storage for gdocs
                            'source': 'gdocs',
                            'gemini_file_id': gemini_file_id,
                            'gemini_store_id': gemini_store_id,
                            'doc_id': doc_id,  # Add doc_id column
                            'meta': {
                                'createdTime': created_time,
                                'modifiedTime': modified_time,
                                'connection_id': connection_id
                            }
                        })
                        
                        successful_uploads += 1
                        log.debug("Successfully processed doc: %s", doc_name)
                        
                    finally:
                        # Cleanup temp file
                        if temp_file_path and os.path.exists(temp_file_path):
                            try:
                                os.remove(temp_file_path)
                            except Exception as e:
                                log.warning("Failed to cleanup temp file: %s", e)
                
                except Exception as doc_error:
                    failed_uploads += 1
                    log.error("Error processing doc %s: %s", doc.get('name', 'unknown'), doc_error)
                    # Continue to next doc instead of failing entire sync
                    continue
            
            log.info("Step 4/4: Completed processing. Success: %d, Failed: %d", successful_uploads, failed_uploads)
            
            # Update sync status
            if successful_uploads == 0 and failed_uploads > 0:
                self.supabase.update_user_sync_status(openwebui_user_id, 'gdocs', 'failed')
                return {"status": "failed", "docs_count": 0, "error": "All documents failed to process"}
            else:
                self.supabase.update_user_sync_status(openwebui_user_id, 'gdocs', 'success')
                log.info("Google Docs sync completed successfully: %d docs synced", successful_uploads)
                return {
                    "status": "success", 
                    "docs_count": successful_uploads, 
                    "error": None if failed_uploads == 0 else f"{failed_uploads} docs failed"
                }
        
        except Exception as e:
            log.error("Google Docs sync failed: %s", e, exc_info=True)
            self.supabase.update_user_sync_status(openwebui_user_id, 'gdocs', 'failed')
            return {"status": "failed", "docs_count": 0, "error": str(e)}
    
    def _fetch_all_documents_with_pagination(self, gdocs_user_id: str) -> Tuple[List[Dict], int]:
        """
        Fetch all documents from Google Docs with pagination and deduplication.
        
        Uses time offset to handle docs with identical modifiedTime.
        Deduplicates by doc ID to prevent processing duplicates.
        """
        seen_doc_ids = set()
        all_docs = []
        next_page_token = True  # Start as True to enter loop
        last_modified_time = None
        
        log.info("Fetching documents from Google Docs workspace")
        
        while next_page_token:
            try:
                # Build search arguments
                arguments = {
                    "include_trashed": False,
                    "max_results": GDOCS_SEARCH_MAX_RESULTS,
                    "order_by": "modifiedTime asc"
                }
                
                # Add modified_after if we have a previous page
                if last_modified_time:
                    # Subtract 1 second to handle docs with identical timestamps
                    offset_time = datetime.fromisoformat(last_modified_time.replace('Z', '+00:00')) - timedelta(seconds=1)
                    arguments["modified_after"] = offset_time.isoformat()
                    log.debug("Fetching page with modified_after: %s", arguments["modified_after"])
                
                # Execute search with rate limit handling
                search_response = self._execute_with_retry(
                    "GOOGLEDOCS_SEARCH_DOCUMENTS",
                   gdocs_user_id,
                    arguments
                )
                
                if not search_response.get("successful"):
                    error_msg = search_response.get("error", "Unknown error")
                    raise Exception(f"Failed to search Google Docs: {error_msg}")
                
                # Extract files from response
                files = search_response.get("data", {}).get("files", [])
                next_page_token = search_response.get("data", {}).get("next_page_token")
                
                if not files:
                    log.debug("No more documents found")
                    break
                
                log.debug("Fetched %d documents in this page", len(files))
                
                # Process and deduplicate files
                for file in files:
                    doc_id = file.get("id")
                    
                    # Deduplicate by ID
                    if doc_id not in seen_doc_ids:
                        seen_doc_ids.add(doc_id)
                        all_docs.append(file)
                        last_modified_time = file.get("modifiedTime")
                    else:
                        log.debug("Skipping duplicate doc ID: %s", doc_id)
                
                # Stop if no more pages
                if not next_page_token:
                    break
                    
            except Exception as e:
                error_str = str(e)
                # Handle "No connected account" error - preserve error code for retry logic
                if "[1803]" in error_str or "No connected account" in error_str:
                    log.error("No connected account found for gdocs_user_id %s - connection may be stale", gdocs_user_id)
                    raise Exception(f"[1803] Google Docs connection not found or expired for user ID {gdocs_user_id}. Please reconnect your Google account.")
                else:
                    log.error("Error fetching documents from Google Docs: %s", e)
                    raise
        
        log.info("Completed fetching documents: %d total docs (after deduplication)", len(all_docs))
        return (all_docs, len(all_docs))
    
    def _fetch_document_content(self, gdocs_user_id: str, doc_id: str) -> str:
        """
        Fetch content of a single Google Doc by ID.
        
        Args:
            gdocs_user_id: User ID for Composio
            doc_id: Google Doc ID
        
        Returns:
            Extracted plain text content
        """
        try:
            # Fetch doc with rate limit handling
            doc_response = self._execute_with_retry(
                "GOOGLEDOCS_GET_DOCUMENT_BY_ID",
                gdocs_user_id,
                {"id": doc_id}
            )
            
            if not doc_response.get("successful"):
                error_msg = doc_response.get("error", "Unknown error")
                raise Exception(f"Failed to fetch document: {error_msg}")
            
            # Extract text from response
            doc_data = doc_response.get("data", {})
            text_content = self._extract_text_from_gdoc(doc_data)
            
            return text_content
            
        except Exception as e:
            log.error("Error fetching document content for %s: %s", doc_id, e)
            raise
    
    def _extract_text_from_gdoc(self, doc_response: dict) -> str:
        """
        Extracts all visible text from a Google Docs document
        returned by GOOGLEDOCS_GET_DOCUMENT_BY_ID.
        Args:
            doc_response: Response from GOOGLEDOCS_GET_DOCUMENT_BY_ID
        
        Returns:
            Plain text content
        """
        text_chunks = []
        
        body = doc_response.get("body", {})
        content = body.get("content", [])
        
        for block in content:
            paragraph = block.get("paragraph")
            if not paragraph:
                continue
            
            for element in paragraph.get("elements", []):
                text_run = element.get("textRun")
                if text_run and "content" in text_run:
                    text_chunks.append(text_run["content"])
        
        return "".join(text_chunks)
    
    def _execute_with_retry(self, tool_name: str, user_id: str, arguments: dict) -> dict:
        """
        Execute Composio tool with retry logic for both connection propagation and rate limiting.
        
        Handles:
        - Error 1803: Connection propagation (10s, 20s, 30s retries)
        - Error 429: Rate limiting (10s, 20s, 30s, 60s, 120s retries)
        
        Args:
            tool_name: Composio tool name
            user_id: User ID
            arguments: Tool arguments
        
        Returns:
            Tool execution response
        """
        max_retries = 5
        delays = [10, 20, 30, 60, 120]  # Escalating delays for rate limits
        
        for attempt in range(max_retries):
            try:
                response = self.composio.client.tools.execute(
                    tool_name,
                    user_id=user_id,
                    arguments=arguments
                )
                return response
                
            except Exception as e:
                error_str = str(e).lower()
                
                # Check error type
                is_rate_limit = (
                    "429" in str(e) or
                    "rate limit" in error_str or
                    "too many requests" in error_str or
                    "quota exceeded" in error_str
                )
                is_conn_error = "[1803]" in str(e) or "no connected account" in error_str
                
                # Retry if it's a known retriable error and we have retries left
                if (is_rate_limit or is_conn_error) and attempt < max_retries - 1:
                    wait_time = delays[attempt]
                    error_type = "Rate limit" if is_rate_limit else "Connection"
                    log.warning(
                        "%s error (attempt %d/%d). Waiting %ds before retry...",
                        error_type, attempt + 1, max_retries, wait_time
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    # Not retriable or retries exhausted
                    raise
        
        raise Exception("Max retries exceeded")
    
    def _create_doc_file(self, doc_name: str, doc_content: str) -> str:
        """
        Create a temporary text file for a single Google Doc.
        
        Args:
            doc_name: Document name (for metadata in file)
            doc_content: Document text content
        
        Returns:
            Path to temporary file
        """
        temp_filename = f"gdoc_{uuid.uuid4()}.txt"
        temp_file_path = os.path.join(UPLOAD_DIR, temp_filename)
        
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            # Add document title as header
            f.write(f"# Google Doc: {doc_name}\n\n")
            f.write(doc_content)
        
        log.debug("Created temp file: %s", temp_file_path)
        return temp_file_path
    
    def _get_or_create_user_store(self, openwebui_user_id: str) -> str:
        """Get existing Gemini store or create new one for user."""
        gemini_store_id = self.gemini.get_or_create_file_search_store(openwebui_user_id)
        return gemini_store_id


# Initialize global Google Docs sync service instance
gdocs_sync_service = GDocsSyncService()
