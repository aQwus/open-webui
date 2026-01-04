import logging
from typing import Optional
from open_webui.config import COMPOSIO_API_KEY, ATTIO_AUTH_CONFIG_ID, NOTION_AUTH_CONFIG_ID

log = logging.getLogger(__name__)


class ComposioService:
    """Service for managing Composio integrations and OAuth connections."""
    
    def __init__(self):
        self.api_key = COMPOSIO_API_KEY
        self.attio_auth_config_id = ATTIO_AUTH_CONFIG_ID
        self.notion_auth_config_id = NOTION_AUTH_CONFIG_ID
        self.client = None
        self._enabled = False
        
        # Try to import and initialize Composio
        if not self.api_key:
            log.info("Composio not configured (COMPOSIO_API_KEY missing)")
            return
            
        try:
            from composio import Composio
            # toolkit_versions parameter is supported in composio-core>=0.10.0
            self.client = Composio(
                api_key=self.api_key,
                toolkit_versions={"attio": "20251222_00", "notion": "20251222_01"}
            )
            self._enabled = True
            log.info("Composio client initialized successfully")
        except ImportError:
            log.warning("composio-core not installed. Composio integration will be disabled.")
            log.info("To enable Composio: pip install composio-core")
        except Exception as e:
            log.error(f"Failed to initialize Composio client: {e}")

    
    def is_enabled(self) -> bool:
        """Check if Composio service is enabled and configured."""
        return self._enabled and self.client is not None
    
    def initiate_connection(self, user_id: str, auth_config_id: str) -> Optional[dict]:
        """
        Initiate OAuth connection for a user.
        
        Args:
            user_id: Unique identifier for the user (stored in Supabase)
            auth_config_id: Composio auth config ID for the integration
            
        Returns:
            Dictionary with redirect_url and connection request details
            
        Raises:
            Exception if Composio is not enabled or API call fails
        """
        if not self.is_enabled():
            raise Exception("Composio service not enabled")
        
        try:
            connection_request = self.client.connected_accounts.initiate(
                user_id=user_id,
                auth_config_id=auth_config_id,
            )
            
            log.info(f"Initiated connection for user {user_id}, auth config {auth_config_id}")
            
            return {
                "redirect_url": connection_request.redirect_url,
                "connection_id": connection_request.id,
                "status": "pending"
            }
        except Exception as e:
            log.error(f"Failed to initiate connection: {e}")
            raise Exception(f"Failed to initiate connection: {str(e)}")
    
    
    def check_connection_status(self, user_id: str, auth_config_id: str) -> dict:
        """
        Check if user has an active connection for specific auth config.
        
        Args:
            user_id: User ID used to create the connection
            auth_config_id: Auth config ID to check for (e.g., Attio or Notion)
            
        Returns:
            Dictionary with connection status
        """
        if not self.is_enabled():
            return {"connected": False, "error": "Composio service not enabled"}
        
        try:
            # Get all connected accounts for this user
            connections = self.client.connected_accounts.list(user_ids=[user_id])
            
            # Find connection matching the auth_config_id
            for item in connections.items:
                # Check auth_config.id, not item.id
                if item.auth_config.id == auth_config_id:
                    log.info(f"Found active connection for user {user_id}, auth_config {auth_config_id}: {item.status}")
                    return {
                        "connected": True,
                        "connection_id": item.id,  # this is the connection_id (ca_xxx)
                        "status": item.status
                    }
            
            # No matching connection found
            return {"connected": False}
                
        except Exception as e:
            log.error(f"Failed to check connection status: {e}")
            return {"connected": False, "error": str(e)}


# Initialize global Composio service instance
composio_service = ComposioService()
