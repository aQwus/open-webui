import logging
from datetime import datetime
from typing import Optional, Dict, Any
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
        
        Args:
            doc_data: Dictionary containing:
                - id: UUID
                - user_id: string
                - user_email: string
                - filename: string
                - path: string
                - meta: JSON object
                - created_at: nanosecond timestamp
                - updated_at: nanosecond timestamp
                
        Returns:
            True if successful, False otherwise
        """
        if not self.is_enabled():
            log.warning("Supabase not enabled, skipping metadata insert")
            return False
        
        try:
            # Convert nanosecond timestamps to ISO format
            created_at_iso = self._convert_timestamp(doc_data.get('created_at'))
            updated_at_iso = self._convert_timestamp(doc_data.get('updated_at'))
            
            # Prepare data for Supabase
            supabase_data = {
                'id': doc_data['id'],
                'user_id': doc_data['user_id'],
                'user_email': doc_data.get('user_email', ''),
                'filename': doc_data['filename'],
                'path': doc_data.get('path', ''),
                'meta': doc_data.get('meta', {}),
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


# Initialize global Supabase service instance
supabase_service = SupabaseService()
