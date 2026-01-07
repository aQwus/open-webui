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
            
            # Step 2: Get Gemini store (shared across all docs)
            log.info("Step 2/5: Getting Gemini store")
            gemini_store_id = self._get_or_create_user_store(openwebui_user_id)
            log.info("Step 2/5: Using Gemini store: %s", gemini_store_id)
            
            # Step 3: Get connection_id for metadata
            connection_status = self.composio.check_connection_status(notion_user_id, self.composio.notion_auth_config_id)
            connection_id = connection_status.get('connection_id', '')
            
            # Step 4: Process each page individually
            log.info("Step 3/5: Processing and uploading pages")
            successful_uploads = 0
            failed_uploads = 0
            
            for idx, page in enumerate(pages_data):
                try:
                    page_id = page['page_id']
                    page_title = page['title']
                    page_content = page['content']
                    created_time = page.get('created_time')
                    last_edited_time = page.get('last_edited_time')
                    
                    log.debug("Processing page %d/%d: %s", idx + 1, pages_count, page_title)
                    
                    # Create temp file for THIS page only
                    temp_file_path = self._create_page_file(page_title, page_content)
                    
                    try:
                        # Upload to Gemini (unique file per page)
                        gemini_result = self.gemini.upload_file_to_gemini(
                            file_path=temp_file_path,
                            filename=f"notion_{page_id}.txt",
                            user_id=openwebui_user_id,
                            document_id=str(uuid.uuid4())
                        )
                        
                        if not gemini_result:
                            raise Exception("Gemini upload failed")
                        
                        gemini_file_id, _ = gemini_result
                        
                        # Save metadata to Supabase (individual row)
                        self.supabase.insert_document_metadata({
                            'id': str(uuid.uuid4()),
                            'user_id': openwebui_user_id,
                            'user_email': user_email,
                            'filename': page_title,
                            'path': '',  # No R2 storage
                            'source': 'notion',
                            'gemini_file_id': gemini_file_id,
                            'gemini_store_id': gemini_store_id,
                            'doc_id': page_id,  # New column for Notion page ID
                            'meta': {
                                'connection_id': connection_id,
                                'created_time': created_time,
                                'last_edited_time': last_edited_time,
                            }
                        })
                        
                        successful_uploads += 1
                        
                    finally:
                        # Cleanup temp file
                        if temp_file_path and os.path.exists(temp_file_path):
                            try:
                                os.remove(temp_file_path)
                            except Exception as e:
                                log.warning("Failed to cleanup temp file: %s", e)
                                
                except Exception as page_error:
                    failed_uploads += 1
                    log.error(f"Failed to upload page {page['title']}: {page_error}")
                    continue  # Continue with next page
            
            # Update sync status
            final_status = 'success' if successful_uploads > 0 else 'failed'
            if successful_uploads == 0 and pages_count > 0:
                 final_status = 'failed'
            
            self.supabase.update_user_sync_status(openwebui_user_id, 'notion', final_status)
            
            log.info("Notion sync completed: %d succeeded, %d failed", successful_uploads, failed_uploads)
            return {"status": final_status, "pages_count": successful_uploads, "error": None}
            
        except Exception as e:
            log.error("Notion sync failed: %s", e, exc_info=True)
            self.supabase.update_user_sync_status(openwebui_user_id, 'notion', 'failed')
            return {"status": "failed", "pages_count": 0, "error": str(e)}

    @handle_rate_limit
    def _fetch_all_pages_from_notion(self, notion_user_id: str) -> Tuple[List[Dict], int]:
        """
        Fetch all top-level pages from Notion workspace using search with pagination.
        
        Returns:
            Tuple of (pages_data, total_pages_count)
            pages_data: List of {page_id, title, content, created_time, last_edited_time}
        """
        log.info("Fetching pages from Notion workspace using search")
        
        pages_data = []
        next_cursor = None
        has_more = True
        
        try:
            while has_more:
                arguments = {
                    "direction": "descending",
                    "page_size": 100
                }
                if next_cursor:
                    arguments["start_cursor"] = next_cursor

                # Search for pages
                search_response = self.composio.client.tools.execute(
                    "NOTION_SEARCH_NOTION_PAGE",
                    user_id=notion_user_id,
                    arguments=arguments
                )
                
                if not search_response.get("successful"):
                    error_msg = search_response.get("error", "Unknown error")
                    raise Exception(f"Failed to fetch pages from Notion: {error_msg}")
                
                data = search_response.get("data", {})
                results = data.get("results", [])
                
                # Update pagination cursors
                has_more = data.get("has_more", False)
                next_cursor = data.get("next_cursor")
                
                if not results:
                    # If results are empty but has_more is true (rare), just break to avoid infinite loop
                    if has_more and not results:
                         log.warning("Notion returned has_more=True but empty results. Stopping pagination.")
                         break
                    if not has_more:
                        break
                
                log.info(f"Fetched batch of {len(results)} items from Notion")

                for page in results:
                    # We only want pages, not databases
                    if page.get("object") != "page":
                        continue

                    # Filter: Only process top-level pages (parent type is workspace)
                    # Use 'workspace' string check - safe even if parent dict is missing
                    parent = page.get("parent", {})
                    # For some pages parent might be workspace: True or just type: workspace
                    is_workspace_parent = parent.get("type") == "workspace" or parent.get("workspace") is True
                    
                    if not is_workspace_parent:
                        # Skip child pages (they will be fetched recursively via content fetch of the parent)
                        continue

                    page_id = page.get("id")
                    
                    # Check archived/trash status
                    if page.get("archived", False) or page.get("in_trash", False):
                        continue

                    # TITLE EXTRACTION (Robust handling for nested properties)
                    page_title = "Untitled"
                    try:
                        props = page.get("properties", {})
                        # Search for property of type 'title'
                        title_prop = None
                        if "title" in props and props["title"].get("type") == "title":
                            title_prop = props["title"]
                        else:
                            # Fallback: search values for type 'title'
                            for val in props.values():
                                if val.get("type") == "title":
                                    title_prop = val
                                    break
                        
                        if title_prop:
                            title_array = title_prop.get("title", [])
                            if title_array and len(title_array) > 0:
                                page_title = title_array[0].get("plain_text", "Untitled")
                    except Exception as e:
                        log.warning(f"Error extracting title for page {page_id}: {e}")

                    # Fetch content for this top-level page
                    log.debug("Fetching content for page: %s (ID: %s)", page_title, page_id)
                    try:
                         # Fetch page content (recursive, so it gets children too)
                        page_content = self._fetch_page_content(notion_user_id, page_id, page_title)
                        
                        pages_data.append({
                            "page_id": page_id,
                            "title": page_title,
                            "content": page_content,
                            "created_time": page.get("created_time"),
                            "last_edited_time": page.get("last_edited_time")
                        })
                        
                        # Add a small delay between content fetches to be safe
                        time.sleep(NOTION_RATE_LIMIT_DELAY)
                        
                    except Exception as page_error:
                        log.warning("Error fetching content for page %s: %s", page_title, page_error)
                        continue
            
            log.info("Successfully fetched %d top-level pages from Notion", len(pages_data))
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

    def _create_page_file(self, page_title: str, page_content: str) -> str:
        """
        Create a temporary file for a single Notion page.
        
        Args:
            page_title: Page title
            page_content: Full page content (already formatted with title)
        
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
            temp_file.write(page_content)
            temp_file.close()
            return temp_file.name
        except Exception as e:
            temp_file.close()
            try:
                os.unlink(temp_file.name)
            except:
                pass
            raise Exception(f"Failed to create page file for '{page_title}': {e}")


    def _get_or_create_user_store(self, openwebui_user_id: str) -> str:
        """Get existing Gemini store or create new one for user."""
        gemini_store_id = self.gemini.get_or_create_file_search_store(openwebui_user_id)
        return gemini_store_id


# Singleton instance
notion_sync_service = NotionSyncService()
