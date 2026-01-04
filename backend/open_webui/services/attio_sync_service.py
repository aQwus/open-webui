import logging
import os  
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple

from open_webui.config import UPLOAD_DIR, ATTIO_RECORDS_LIST_LIMIT, ATTIO_RECORDS_NOTES_LIMIT
from open_webui.services.composio_service import composio_service
from open_webui.services.gemini_service import gemini_service
from open_webui.services.supabase_service import supabase_service

log = logging.getLogger(__name__)


class AttioSyncService:
    """Service for syncing Attio notes to Gemini File Storage."""
    
    def __init__(self):
        self.composio = composio_service
        self.gemini = gemini_service
        self.supabase = supabase_service
    
    def sync_attio_notes(self, openwebui_user_id: str, user_email: str, attio_user_id: str) -> dict:
        """Main sync orchestrator for Attio notes."""
        temp_file_path = None
        gemini_file_id = None
        gemini_store_id = None
        
        try:
            log.info("Starting Attio sync for user %s", openwebui_user_id)
            self.supabase.update_user_sync_status(openwebui_user_id, 'attio', 'in_progress')
            # Step 1: Fetch all notes from Attio (with retry for connection propagation)
            log.info("Step 1/5: Fetching notes from Attio")
            
            # Retry logic for "No connected account" error (connection propagation delay)
            max_retries = 3
            retry_delays = [10, 20, 30]  # seconds between retries
            notes_data = None
            notes_count = 0
            
            for attempt in range(max_retries):
                try:
                    notes_data, notes_count = self._fetch_all_notes_from_attio(attio_user_id)
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
            
            if notes_count == 0:
                log.info("No notes found in Attio")
                self.supabase.update_user_sync_status(openwebui_user_id, 'attio', 'success')
                return {"status": "success", "notes_count": 0, "error": None}
            
            log.info("Step 1/5: Fetched %d note(s) from Attio", notes_count)
            
            log.info("Step 2/5: Creating context file for Gemini")
            temp_file_path = self._create_gemini_context_file(notes_data)
            log.info("Step 2/5: Created temp file: %s", temp_file_path)
            
            log.info("Step 3/5: Getting Gemini store")
            gemini_store_id = self._get_or_create_user_store(openwebui_user_id)
            log.info("Step 3/5: Using Gemini store: %s", gemini_store_id)
            
            log.info("Step 4/5: Uploading to Gemini File Storage")
            gemini_result = self.gemini.upload_file_to_gemini(
                file_path=temp_file_path,
                filename="attio_context.txt",
                user_id=openwebui_user_id,
                document_id=str(uuid.uuid4())
            )
            
            if not gemini_result:
                raise Exception("Gemini upload failed")
            
            gemini_file_id, gemini_store_id = gemini_result
            log.info("Step 4/5: Uploaded to Gemini: %s", gemini_file_id)
            
            log.info("Step 5/5: Saving metadata to Supabase")
            from open_webui.config import ATTIO_AUTH_CONFIG_ID
            connection_status = self.composio.check_connection_status(attio_user_id, ATTIO_AUTH_CONFIG_ID)
            connection_id = connection_status.get('connection_id', '')
            
            self.supabase.upsert_connection_context_metadata(
                user_id=openwebui_user_id,
                user_email=user_email,
                source='attio',
                gemini_file_id=gemini_file_id,
                gemini_store_id=gemini_store_id,
                connection_id=connection_id,
                count=notes_count
            )
            log.info("Step 5/5: Saved metadata to Supabase")
            
            self.supabase.update_user_sync_status(openwebui_user_id, 'attio', 'success')
            log.info("Attio sync completed successfully: %d notes synced", notes_count)
            return {"status": "success", "notes_count": notes_count, "error": None}
            
        except Exception as e:
            log.error("Attio sync failed: %s", e, exc_info=True)
            self.supabase.update_user_sync_status(openwebui_user_id, 'attio', 'failed')
            
            if gemini_file_id and gemini_store_id:
                try:
                    self.gemini.delete_document_from_gemini(gemini_file_id, gemini_store_id)
                    log.info("Cleaned up Gemini file after failure")
                except Exception as cleanup_error:
                    log.error("Failed to cleanup Gemini file: %s", cleanup_error)
            
            return {"status": "failed", "notes_count": 0, "error": str(e)}
            
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                    log.debug("Cleaned up temp file: %s", temp_file_path)
                except Exception as e:
                    log.warning("Failed to cleanup temp file: %s", e)
    
    def _fetch_all_notes_from_attio(self, attio_user_id: str, resume_state: Optional[Dict] = None) -> Tuple[List[Dict], int]:
        """Fetch all notes from Attio across all record types with pagination."""
        object_types = ["people", "companies", "deals"]
        all_records_with_notes = []
        total_notes = 0
        
        start_index = 0
        start_offset = 0
        if resume_state:
            try:
                start_index = object_types.index(resume_state.get('object_type', ''))
                start_offset = resume_state.get('offset', 0)
                log.info("Resuming from %s at offset %d", object_types[start_index], start_offset)
            except ValueError:
                log.warning("Invalid resume state, starting from beginning")
        
        for obj_idx, object_type in enumerate(object_types):
            if obj_idx < start_index:
                continue
            
            offset = start_offset if obj_idx == start_index else 0
            log.info("Processing %s (starting at offset %d)", object_type, offset)
            
            while True:
                try:
                    log.debug("Fetching %s records at offset %d", object_type, offset)
                    
                    list_response = self.composio.client.tools.execute(
                        "ATTIO_LIST_RECORDS",
                        user_id=attio_user_id,
                        arguments={
                            "object_type": object_type,
                            "limit": ATTIO_RECORDS_LIST_LIMIT,
                            "offset": offset
                        }
                    )
                    
                    if not list_response.get("successful"):
                        error_msg = list_response.get('error', 'Unknown error')
                        log.error("Failed to fetch %s: %s", object_type, error_msg)
                        break
                    
                    records = list_response.get("data", {}).get("data", [])
                    
                    if not records:
                        log.debug("No more records for %s", object_type)
                        break
                    
                    log.debug("Processing %d %s records", len(records), object_type)
                    
                    for record in records:
                        # Debug: Log the full record ID structure
                        record_full_id = record.get("id")
                        record_id = record_full_id.get("record_id") if isinstance(record_full_id, dict) else record_full_id
                        
                        log.debug(
                            "Processing record - full_id: %s, extracted record_id: %s",
                            record_full_id, record_id
                        )
                        
                        values = record.get("values", {})
                        record_name = None
                        name_values = values.get("name", [])
                        
                        if name_values:
                            entry = name_values[0]
                            record_name = entry.get("value") or entry.get("full_name")
                        
                        try:
                            # For ATTIO_LIST_NOTES, use just the record_id string, not the full id object
                            log.debug(
                                "Calling ATTIO_LIST_NOTES with parent_object=%s, parent_record_id=%s",
                                object_type, record_id
                            )
                            
                            notes_response = self.composio.client.tools.execute(
                                "ATTIO_LIST_NOTES",
                                user_id=attio_user_id,
                                arguments={
                                    "parent_object": object_type,
                                    "parent_record_id": record_id,
                                    "limit": ATTIO_RECORDS_NOTES_LIMIT
                                }
                            )
                            
                            if notes_response.get("successful"):
                                notes = notes_response.get("data", {}).get("data", [])
                                
                                if notes:
                                    processed_notes = []
                                    for note in notes:
                                        processed_notes.append({
                                            "title": note.get("title", ""),
                                            "content_plaintext": note.get("content_plaintext", "")
                                        })
                                    
                                    all_records_with_notes.append({
                                        "object_type": object_type,
                                        "record_id": record_id,
                                        "record_name": record_name or "Unnamed",
                                        "notes": processed_notes
                                    })
                                    
                                    total_notes += len(processed_notes)
                                    log.debug("Found %d note(s) for %s '%s'", len(processed_notes), object_type, record_name)
                        
                        except Exception as note_error:
                            log.warning("Error fetching notes for %s: %s", record_id, note_error)
                            continue
                    
                    offset += ATTIO_RECORDS_LIST_LIMIT
                    
                except Exception as e:
                    error_str = str(e)
                    
                    # Handle rate limiting
                    if "429" in error_str or "rate limit" in error_str.lower():
                        log.warning("Rate limit hit, waiting 2 seconds...")
                        time.sleep(2)
                        continue
                    # Handle "No connected account" error
                    elif "1803" in error_str or "No connected account" in error_str:
                        log.error("No connected account found for attio_user_id %s - connection may be stale", attio_user_id)
                        # Don't continue to other object types, return immediately
                        raise Exception(f"Attio connection not found or expired for user ID {attio_user_id}. Please reconnect your Attio account.")
                    else:
                        log.error("Error fetching %s at offset %d: %s", object_type, offset, e)
                        # Return partial results on failure
                        return (all_records_with_notes, total_notes)
        
        log.info("Completed fetching notes: %d total notes from %d records", total_notes, len(all_records_with_notes))
        return (all_records_with_notes, total_notes)
    
    def _create_gemini_context_file(self, notes_data: List[Dict]) -> str:
        """Create a text file with all notes formatted for Gemini."""
        temp_filename = "attio_context_{}.txt".format(uuid.uuid4())
        temp_file_path = os.path.join(UPLOAD_DIR, temp_filename)
        
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            for record in notes_data:
                object_type = record['object_type'].capitalize()
                record_name = record['record_name']
                
                f.write("=== [{}] {} ===\n\n".format(object_type, record_name))
                
                for note in record['notes']:
                    title = note.get('title', '')
                    content = note.get('content_plaintext', '')
                    
                    if title:
                        f.write("Note: {}\n".format(title))
                    
                    if content:
                        f.write("{}\n".format(content))
                    
                    f.write("\n---\n\n")
        
        log.info("Created context file with %d records", len(notes_data))
        return temp_file_path
    
    def _get_or_create_user_store(self, openwebui_user_id: str) -> str:
        """Get existing Gemini store or create new one for user."""
        gemini_store_id = self.gemini.get_or_create_file_search_store(openwebui_user_id)
        return gemini_store_id


# Initialize global Attio sync service instance
attio_sync_service = AttioSyncService()
