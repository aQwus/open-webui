import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from open_webui.config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

log = logging.getLogger(__name__)

class SupabaseService:
    """Service for syncing document metadata to Supabase."""
    
    def __init__(self):
        self.supabase_url = SUPABASE_URL
        self.supabase_key = SUPABASE_SERVICE_ROLE_KEY
        self.client = None
        self._enabled = bool(self.supabase_url and self.supabase_key)
        
        if self._enabled:
            try:
                from supabase import create_client, Client
                self.client: Client = create_client(self.supabase_url, self.supabase_key)
                log.info("Supabase client initialized successfully")
            except ImportError:
                log.error("supabase-py not installed. Install with: pip install supabase")
                self._enabled = False
            except Exception as e:
                log.error(f"Failed to initialize Supabase client: {e}")
                self._enabled = False
        else:
            log.info("Supabase not configured (SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing)")
    
    def is_enabled(self) -> bool:
        """Check if Supabase service is enabled and configured."""
        return self._enabled and self.client is not None
    
    def validate_connection(self) -> bool:
        """
        Validate Supabase connection by attempting a simple query.
        Returns True if connection is valid, False otherwise.
        """
        if not self.is_enabled():
            return False
        
        try:
            # Try to query the doc_metadata table (limit 0 for quick check)
            response = self.client.table('doc_metadata').select('id').limit(1).execute()
            log.info("Supabase connection validated successfully")
            return True
        except Exception as e:
            log.error(f"Supabase connection validation failed: {e}")
            return False
    
    def check_document_exists(self, document_id: str) -> bool:
        """
        Check if a document exists in Supabase.
        
        Args:
            document_id: UUID of the document
            
        Returns:
            True if document exists, False otherwise
        """
        if not self.is_enabled():
            return False
        
        try:
            response = self.client.table('doc_metadata').select('id').eq('id', document_id).execute()
            exists = len(response.data) > 0
            log.debug(f"Document {document_id} exists in Supabase: {exists}")
            return exists
        except Exception as e:
            log.error(f"Error checking document existence in Supabase: {e}")
            return False
    
    def insert_document_metadata(self, doc_data: Dict[str, Any]) -> bool:
        """
        Insert document metadata into Supabase with upsert strategy.
        Extracts gemini_file_id and gemini_store_id to separate columns.
        
        Args:
            doc_data: Dictionary containing:
                - id: UUID
                - user_id: string
                - user_email: string
                - filename: string
                - path: string
                - meta: JSON object (may contain gemini_file_id, gemini_store_id)
                - created_at: nanosecond timestamp
                - updated_at: nanosecond timestamp
                
        Returns:
            True if successful, raises Exception otherwise
        """
        if not self.is_enabled():
            log.warning("Supabase not enabled, skipping metadata insert")
            raise Exception("Supabase service not enabled")
        
        try:
            # Convert nanosecond timestamps to ISO format
            created_at_iso = self._convert_timestamp(doc_data.get('created_at'))
            updated_at_iso = self._convert_timestamp(doc_data.get('updated_at'))
            
            # Extract Gemini IDs (check top-level first, then meta for backward compatibility)
            meta = doc_data.get('meta', {})
            gemini_file_id = doc_data.get('gemini_file_id') or meta.get('gemini_file_id')
            gemini_store_id = doc_data.get('gemini_store_id') or meta.get('gemini_store_id')
            
            # Remove Gemini IDs from meta (now stored as separate columns)
            clean_meta = {k: v for k, v in meta.items() 
                         if k not in ['gemini_file_id', 'gemini_store_id']}
            
            # Prepare data for Supabase
            supabase_data = {
                'id': doc_data['id'],
                'user_id': doc_data['user_id'],
                'user_email': doc_data.get('user_email', ''),
                'filename': doc_data['filename'],
                'path': doc_data.get('path', ''),
                'source': doc_data.get('source', 'manual'),  # Add source column
                'gemini_file_id': gemini_file_id,  # Separate column (nullable)
                'gemini_store_id': gemini_store_id,  # Separate column (nullable)
                'meta': clean_meta,  # Cleaned meta without Gemini IDs
                'created_at': created_at_iso,
                'updated_at': updated_at_iso
            }
            
            # Upsert (insert or update on conflict)
            response = self.client.table('doc_metadata').upsert(supabase_data).execute()
            
            log.info(f"Successfully synced document {doc_data['id']} to Supabase")
            return True
            
        except Exception as e:
            log.error(f"Failed to insert document metadata to Supabase: {e}")
            raise Exception(f"Supabase sync failed: {str(e)}")
    
    def list_user_documents(self, user_id: str) -> List[Dict]:
        """
        List all documents for a user from Supabase.
        
        Args:
            user_id: User ID to filter documents
            
        Returns:
            List of document dictionaries, raises Exception on error
        """
        if not self.is_enabled():
            log.warning("Supabase not enabled")
            raise Exception("Document service temporarily unavailable")
        
        try:
            response = (self.client.table('doc_metadata')
                .select('*')
                .eq('user_id', user_id)
                .order('created_at', desc=True)
                .execute())
            
            log.info(f"Retrieved {len(response.data)} documents for user {user_id}")
            return response.data
            
        except Exception as e:
            log.error(f"Failed to list documents from Supabase: {e}")
            raise Exception(f"Failed to retrieve documents: {str(e)}")
    
    def get_document_by_id(self, document_id: str) -> Optional[Dict]:
        """
        Get a single document by ID from Supabase.
        
        Args:
            document_id: UUID of the document
            
        Returns:
            Document dictionary or None if not found, raises Exception on error
        """
        if not self.is_enabled():
            log.warning("Supabase not enabled")
            raise Exception("Document service temporarily unavailable")
        
        try:
            response = (self.client.table('doc_metadata')
                .select('*')
                .eq('id', document_id)
                .execute())
            
            if len(response.data) > 0:
                log.debug(f"Found document {document_id} in Supabase")
                return response.data[0]
            else:
                log.debug(f"Document {document_id} not found in Supabase")
                return None
                
        except Exception as e:
            log.error(f"Failed to get document from Supabase: {e}")
            raise Exception(f"Failed to retrieve document: {str(e)}")
    
    def delete_document_metadata(self, document_id: str) -> bool:
        """
        Delete document metadata from Supabase.
        
        Args:
            document_id: UUID of the document to delete
            
        Returns:
            True if successful (including if document didn't exist), False on error
        """
        if not self.is_enabled():
            log.warning("Supabase not enabled, skipping metadata delete")
            return False
        
        try:
            response = self.client.table('doc_metadata').delete().eq('id', document_id).execute()
            log.info(f"Successfully deleted document {document_id} from Supabase")
            return True
            
        except Exception as e:
            log.error(f"Failed to delete document metadata from Supabase: {e}")
            raise Exception(f"Supabase delete failed: {str(e)}")
    
    def _convert_timestamp(self, ns_timestamp: Optional[int]) -> str:
        """
        Convert nanosecond timestamp to ISO 8601 format for Supabase.
        
        Args:
            ns_timestamp: Timestamp in nanoseconds
            
        Returns:
            ISO 8601 formatted timestamp string
        """
        if not ns_timestamp:
            return datetime.utcnow().isoformat()
        
        # Convert nanoseconds to seconds
        seconds = ns_timestamp / 1_000_000_000
        dt = datetime.utcfromtimestamp(seconds)
        return dt.isoformat()
    

    
    def get_user_sync_status(self, user_id: str, source: str) -> tuple[Optional[str], Optional[str]]:
        """
        Get sync status and last sync timestamp for a connection source.
        
        Args:
            user_id: User ID from auth table
            source: Connection source name (e.g., 'attio', 'notion')
            
        Returns:
            Tuple of (sync_status, last_sync) or (None, None) if not found
        """
        if not self.is_enabled():
            return (None, None)
        
        try:
            status_column = f"{source}_sync_status"
            last_sync_column = f"{source}_last_sync"
            
            response = (self.client.table('users')
                .select(f"{status_column}, {last_sync_column}")
                .eq('user_id', user_id)
                .limit(1)
                .execute())
            
            if response.data and len(response.data) > 0:
                data = response.data[0]
                sync_status = data.get(status_column)
                last_sync = data.get(last_sync_column)
                log.debug(f"Sync status for {source}: {sync_status}, last sync: {last_sync}")
                return (sync_status, last_sync)
            else:
                log.debug(f"No sync status found for user {user_id}, source {source}")
                return (None, None)
                
        except Exception as e:
            log.error(f"Error getting sync status for {source}: {e}")
            return (None, None)
    
    def update_user_sync_status(self, user_id: str, source: str, status: str, last_sync: Optional[datetime] = None) -> bool:
        """
        Update sync status and optionally last sync timestamp for a connection.
        
        Args:
            user_id: User ID from auth table
            source: Connection source name (e.g., 'attio', 'notion')
            status: Sync status - 'in_progress', 'success', or 'failed'
            last_sync: Optional timestamp to set (defaults to now())
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_enabled():
            return False
        
        try:
            status_column = f"{source}_sync_status"
            last_sync_column = f"{source}_last_sync"
            
            update_data = {status_column: status}
            
            # Only update last_sync if provided or status is success
            if last_sync:
                update_data[last_sync_column] = last_sync.isoformat()
            elif status == 'success':
                update_data[last_sync_column] = datetime.utcnow().isoformat()
            
            response = (self.client.table('users')
                .update(update_data)
                .eq('user_id', user_id)
                .execute())
            
            log.info(f"Updated sync status for {source}: {status}")
            return True
            
        except Exception as e:
            log.error(f"Failed to update sync status for {source}: {e}")
            return False
    
    def get_connection_context_metadata(self, user_id: str, source: str) -> Optional[Dict]:
        """
        Get connection context metadata (for synced data like Attio notes).
        
        Args:
            user_id: User ID
            source: Connection source ('attio', 'notion', etc.)
            
        Returns:
            Document metadata dict or None if not found
        """
        if not self.is_enabled():
            return None
        
        try:
            response = (self.client.table('doc_metadata')
                .select('*')
                .eq('user_id', user_id)
                .eq('source', source)
                .limit(1)
                .execute())
            
            if response.data and len(response.data) > 0:
                log.debug(f"Found connection context for {source}")
                return response.data[0]
            else:
                log.debug(f"No connection context found for {source}")
                return None
                
        except Exception as e:
            log.error(f"Error getting connection context for {source}: {e}")
            return None
    
    def upsert_connection_context_metadata(self, user_id: str, user_email: str, source: str, 
                                           gemini_file_id: str, gemini_store_id: str, 
                                           connection_id: str, count: int) -> bool:
        """
        Upsert connection context metadata (synced notes, pages, etc).
        
        Args:
            user_id: User ID
            user_email: User email
            source: Connection source ('attio', 'notion')
            gemini_file_id: Gemini file ID containing all context
            gemini_store_id: Gemini store ID
            connection_id: Composio connection ID
            count: Number of items synced (notes, pages, etc.)
            
        Returns:
            True if successful, raises Exception otherwise
        """
        if not self.is_enabled():
            raise Exception("Supabase service not enabled")
        
        try:
            # Check if context already exists
            existing = self.get_connection_context_metadata(user_id, source)
            
            filename = f"{source}_context"
            
            supabase_data = {
                'user_id': user_id,
                'user_email': user_email,
                'filename': filename,
                'path': '',  # Empty for connection context
                'source': source,
                'gemini_file_id': gemini_file_id,
                'gemini_store_id': gemini_store_id,
                'meta': {
                    'connection_id': connection_id,
                    'count': count
                },
                'updated_at': datetime.utcnow().isoformat()
            }
            
            if existing:
                # Update existing record
                supabase_data['id'] = existing['id']
                response = (self.client.table('doc_metadata')
                    .update(supabase_data)
                    .eq('id', existing['id'])
                    .execute())
                log.info(f"Updated connection context for {source}")
            else:
                # Insert new record
                import uuid
                supabase_data['id'] = str(uuid.uuid4())
                supabase_data['created_at'] = datetime.utcnow().isoformat()
                response = (self.client.table('doc_metadata')
                    .insert(supabase_data)
                    .execute())
                log.info(f"Created connection context for {source}")
            
            return True
            
        except Exception as e:
            log.error(f"Failed to upsert connection context for {source}: {e}")
            raise Exception(f"Failed to save connection context: {str(e)}")
    
    def get_user_gdocs_sync_with_count(self, user_id: str) -> Dict:
        """
        Get Google Docs sync status with document count.
        
        Args:
            user_id: User ID
            
        Returns:
            Dict with {status, last_sync, docs_count}
        """
        if not self.is_enabled():
            return {"status": None, "last_sync": None, "docs_count": 0}
        
        try:
            # Get sync status from users table
            sync_status, last_sync = self.get_user_sync_status(user_id, 'gdocs')
            
            # Count gdocs documents from doc_metadata table
            response = (self.client.table('doc_metadata')
                .select('id', count='exact')
                .eq('user_id', user_id)
                .eq('source', 'gdocs')
                .execute())
            
            docs_count = response.count if hasattr(response, 'count') else 0
            
            return {
                "status": sync_status,
                "last_sync": last_sync,
                "docs_count": docs_count
            }
            
        except Exception as e:
            log.error(f"Error getting gdocs sync status with count: {e}")
            return {"status": None, "last_sync": None, "docs_count": 0}


# Initialize global Supabase service instance
supabase_service = SupabaseService()
