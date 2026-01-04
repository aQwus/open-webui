import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, List, Tuple

from open_webui.config import UPLOAD_DIR, NOTION_LIST_LIMIT
from open_webui.services.composio_service import composio_service
from open_webui.services.gemini_service import gemini_service
from open_webui.services.supabase_service import supabase_service

log = logging.getLogger(__name__)

# Notion API rate limit: 3 requests per second
NOTION_RATE_LIMIT_DELAY = 0.5  # 500ms between calls (2 req/sec, safe buffer)


def handle_rate_limit(func):
    """
    Decorator to handle Notion API rate limiting with exponential backoff.
    
    Notion has a rate limit of ~3 requests per second.
    If we hit 429, retry with exponential backoff: 1s, 2s, 4s, 8s (max 5 retries)
    """
    def wrapper(*args, **kwargs):
        max_retries = 5
        base_delay = 1.0  # Start with 1 second
        
        for attempt in range(max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_str = str(e)
                
                # Check if it's a rate limit error
                is_rate_limit = (
                    "429" in error_str or 
                    "rate limit" in error_str.lower() or
                    "too many requests" in error_str.lower()
                )
                
                if is_rate_limit and attempt < max_retries:
                    # Exponential backoff: 1s, 2s, 4s, 8s, 16s
                    wait_time = base_delay * (2 ** attempt)
                    log.warning(
                        "Rate limit hit (attempt %d/%d). Waiting %.1fs before retry...",
                        attempt + 1, max_retries + 1, wait_time
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    # Not a rate limit error, or retries exhausted
                    raise
        
        # Should never reach here, but just in case
        raise Exception("Max retries exceeded for rate limit")
    
    return wrapper


class NotionSyncService:
    def __init__(self):
        self.composio = composio_service
        self.gemini = gemini_service
        self.supabase = supabase_service

    def sync_notion_pages(
        self,
        openwebui_user_id: str,
        user_email: str,
        notion_user_id: str
    ) -> Dict[str, any]:
        """
        Sync Notion workspace pages to Gemini File Storage for RAG.
        
        Args:
            openwebui_user_id: OpenWebUI user ID
            user_email: User's email
            notion_user_id: Notion connection user ID (same as openwebui_user_id)
        
        Returns:
            Dict with status, pages_count, and error (if any)
        """
        try:
            log.info("Starting Notion sync for user %s", openwebui_user_id)
            self.supabase.update_user_sync_status(openwebui_user_id, 'notion', 'in_progress')
            
            # Step 1: Fetch all pages from Notion (with retry for connection propagation)
            log.info("Step 1/5: Fetching pages from Notion")
            
            # Retry logic for "No connected account" error (connection propagation delay)
            max_retries = 3
            retry_delays = [10, 20, 30]  # seconds between retries
            pages_data = None
            pages_count = 0
            
            for attempt in range(max_retries):
                try:
                    pages_data, pages_count = self._fetch_all_pages_from_notion(notion_user_id)
                    break  # Success, exit retry loop
                except Exception as e:
                    error_str = str(e)
                    # Check if it's the "No connected account" error
                    if ("1803" in error_str or "No connected account" in error_str) and attempt < max_retries - 1:
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
            
            if pages_count == 0:
                log.info("No pages found in Notion")
                self.supabase.update_user_sync_status(openwebui_user_id, 'notion', 'success')
                return {"status": "success", "pages_count": 0, "error": None}
            
            log.info("Step 1/5: Fetched %d page(s) from Notion", pages_count)
            
            # Step 2: Create context file for Gemini
            log.info("Step 2/5: Creating context file for Gemini")
            temp_file_path = self._create_gemini_context_file(pages_data)
            log.info("Step 2/5: Created temp file: %s", temp_file_path)
            
            # Step 3: Get or create Gemini store
            log.info("Step 3/5: Getting Gemini store")
            gemini_store_id = self._get_or_create_user_store(openwebui_user_id)
            log.info("Step 3/5: Using Gemini store: %s", gemini_store_id)
            
            # Step 4: Upload to Gemini File Storage
            log.info("Step 4/5: Uploading to Gemini File Storage")
            gemini_result = self.gemini.upload_file_to_gemini(
                file_path=temp_file_path,
                filename="notion_context.txt",
                user_id=openwebui_user_id,
                document_id=str(uuid.uuid4())
            )
            
            if not gemini_result:
                raise Exception("Gemini upload failed")
            
            gemini_file_id, gemini_store_id = gemini_result
            log.info("Step 4/5: Uploaded to Gemini: %s", gemini_file_id)
            
            # Step 5: Save metadata to Supabase
            log.info("Step 5/5: Saving metadata to Supabase")
            
            # Get connection_id from connection status
            connection_status = self.composio.check_connection_status(notion_user_id, self.composio.notion_auth_config_id)
            connection_id = connection_status.get('connection_id', '')
            
            self.supabase.upsert_connection_context_metadata(
                user_id=openwebui_user_id,
                user_email=user_email,
                source='notion',
                gemini_file_id=gemini_file_id,
                gemini_store_id=gemini_store_id,
                connection_id=connection_id,
                count=pages_count
            )
            log.info("Step 5/5: Saved metadata to Supabase")
            
            # Update sync status to success
            self.supabase.update_user_sync_status(openwebui_user_id, 'notion', 'success')
            
            # Cleanup temp file
            try:
                os.unlink(temp_file_path)
            except Exception as e:
                log.warning("Failed to cleanup temp file: %s", e)
            
            log.info("Notion sync completed successfully: %d pages synced", pages_count)
            return {"status": "success", "pages_count": pages_count, "error": None}
            
        except Exception as e:
            log.error("Notion sync failed: %s", e, exc_info=True)
            self.supabase.update_user_sync_status(openwebui_user_id, 'notion', 'failed')
            
            # Cleanup uploaded file if it exists
            if 'gemini_file_id' in locals():
                try:
                    self.gemini.delete_file(gemini_file_id)
                    log.info("Cleaned up Gemini file after failure")
                except Exception as cleanup_error:
                    log.error("Failed to cleanup Gemini file: %s", cleanup_error)
            
            return {"status": "failed", "pages_count": 0, "error": str(e)}

    @handle_rate_limit
    def _fetch_all_pages_from_notion(self, notion_user_id: str) -> Tuple[List[Dict], int]:
        """
        Fetch all pages from Notion workspace and their content.
        
        Returns:
            Tuple of (pages_data, total_pages_count)
            pages_data: List of {page_id, title, content}
        """
        log.info("Fetching pages from Notion workspace")
        
        try:
            # Fetch pages using NOTION_FETCH_DATA
            pages_response = self.composio.client.tools.execute(
                "NOTION_FETCH_DATA",
                user_id=notion_user_id,
                arguments={
                    "get_databases": False,
                    "get_pages": True,
                    "page_size": NOTION_LIST_LIMIT
                }
            )
            
            if not pages_response.get("successful"):
                error_msg = pages_response.get("error", "Unknown error")
                raise Exception(f"Failed to fetch pages from Notion: {error_msg}")
            
            # Extract pages from response
            values = pages_response.get("data", {}).get("values", [])
            results = pages_response.get("data", {}).get("results", [])
            
            if not values:
                log.info("No pages found in Notion workspace")
                return ([], 0)
            
            log.info("Found %d pages in Notion workspace", len(values))
            
            # Process each page
            pages_data = []
            for idx, value in enumerate(values):
                page_id = value.get("id")
                page_title = value.get("title", "Untitled")
                
                # Find corresponding result to check archived/in_trash status
                page_result = next((r for r in results if r.get("id") == page_id), {})
                
                # Skip archived or trashed pages
                if page_result.get("archived", False) or page_result.get("in_trash", False):
                    log.debug("Skipping archived/trashed page: %s", page_title)
                    continue
                
                log.debug("Fetching content for page: %s (ID: %s)", page_title, page_id)
                
                try:
                    # Add delay between page content fetches to avoid rate limiting
                    if idx > 0:  # Don't delay before first page
                        time.sleep(NOTION_RATE_LIMIT_DELAY)
                    
                    page_content = self._fetch_page_content(notion_user_id, page_id, page_title)
                    pages_data.append({
                        "page_id": page_id,
                        "title": page_title,
                        "content": page_content
                    })
                except Exception as page_error:
                    log.warning("Error fetching content for page %s: %s", page_title, page_error)
                    continue
            
            log.info("Successfully fetched content for %d pages", len(pages_data))
            return (pages_data, len(pages_data))
            
        except Exception as e:
            error_str = str(e)
            # Handle "No connected account" error - preserve error code for retry logic
            if "1803" in error_str or "No connected account" in error_str:
                log.error("No connected account found for notion_user_id %s - connection may be stale", notion_user_id)
                # Preserve error code 1803 so retry logic can catch it
                raise Exception(f"[1803] Notion connection not found or expired for user ID {notion_user_id}. Please reconnect your Notion account.")
            else:
                log.error("Error fetching pages from Notion: %s", e)
                raise

    @handle_rate_limit
    def _fetch_page_content(self, notion_user_id: str, page_id: str, page_title: str) -> str:
        """
        Fetch all blocks from a Notion page and convert to text.
        
        Args:
            notion_user_id: User ID for Composio
            page_id: Notion page ID
            page_title: Page title for header
        
        Returns:
            Formatted page content as string
        """
        try:
            # Fetch all blocks from page (recursive=True gets nested blocks)
            blocks_response = self.composio.client.tools.execute(
                "NOTION_FETCH_ALL_BLOCK_CONTENTS",
                user_id=notion_user_id,
                arguments={
                    "block_id": page_id,
                    "recursive": True
                }
            )
            
            if not blocks_response.get("successful"):
                error_msg = blocks_response.get("error", "Unknown error")
                raise Exception(f"Failed to fetch blocks: {error_msg}")
            
            # Extract text from blocks
            page_text = self._extract_page_text(blocks_response)
            
            # Format with title header
            formatted_content = f"# Page Title: {page_title}\n\n{page_text}"
            
            return formatted_content
            
        except Exception as e:
            log.error("Error fetching page content for %s: %s", page_id, e)
            raise

    def _extract_rich_text(self, rich_text_array) -> str:
        """
        Safely extracts plain_text from a rich_text array.
        """
        if not rich_text_array:
            return ""
        
        return "".join(
            text_obj.get("plain_text", "")
            for text_obj in rich_text_array
            if isinstance(text_obj, dict)
        )

    def _extract_block_text(self, block) -> str:
        """
        Extracts readable text from a single Notion block.
        """
        block_type = block.get("type")
        
        if not block_type:
            return ""
        
        block_data = block.get(block_type)
        if not block_data:
            return ""
        
        # Most textual blocks use rich_text
        if "rich_text" in block_data:
            return self._extract_rich_text(block_data["rich_text"])
        
        # Special cases
        if block_type == "to_do":
            text = self._extract_rich_text(block_data.get("rich_text", []))
            checked = block_data.get("checked", False)
            return f"[{'x' if checked else ' '}] {text}"
        
        if block_type == "code":
            code_text = self._extract_rich_text(block_data.get("rich_text", []))
            language = block_data.get("language", "")
            return f"\n```{language}\n{code_text}\n```\n"
        
        return ""

    def _extract_page_text(self, notion_block_response) -> str:
        """
        Converts NOTION_FETCH_ALL_BLOCK_CONTENTS response
        into a single string suitable for RAG embedding.
        """
        blocks = notion_block_response.get("data", {}).get("results", [])
        
        page_text_parts = []
        
        for block in blocks:
            text = self._extract_block_text(block)
            if text.strip():
                page_text_parts.append(text.strip())
        
        return "\n\n".join(page_text_parts)

    def _create_gemini_context_file(self, pages_data: List[Dict]) -> str:
        """
        Create a single text file combining all Notion pages.
        
        Args:
            pages_data: List of {page_id, title, content}
        
        Returns:
            Path to temporary file
        """
        temp_file = tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.txt',
            delete=False,
            encoding='utf-8'
        )
        
        try:
            for i, page in enumerate(pages_data):
                # Write page content
                temp_file.write(page["content"])
                
                # Add separator between pages (except after last page)
                if i < len(pages_data) - 1:
                    temp_file.write("\n\n---\n\n")
            
            temp_file.close()
            return temp_file.name
            
        except Exception as e:
            temp_file.close()
            try:
                os.unlink(temp_file.name)
            except:
                pass
            raise Exception(f"Failed to create context file: {e}")


    def _get_or_create_user_store(self, openwebui_user_id: str) -> str:
        """Get existing Gemini store or create new one for user."""
        gemini_store_id = self.gemini.get_or_create_file_search_store(openwebui_user_id)
        return gemini_store_id


# Singleton instance
notion_sync_service = NotionSyncService()
