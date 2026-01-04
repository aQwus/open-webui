import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel

from open_webui.models.users import Users
from open_webui.services.composio_service import composio_service
from open_webui.services.supabase_service import supabase_service
from open_webui.services.attio_sync_service import attio_sync_service
from open_webui.services.notion_sync_service import notion_sync_service
from open_webui.config import ATTIO_AUTH_CONFIG_ID, NOTION_AUTH_CONFIG_ID
from open_webui.utils.auth import get_verified_user

log = logging.getLogger(__name__)

router = APIRouter()


############################
# Data Models
############################

class ConnectionStatusResponse(BaseModel):
    """Response model for connection status"""
    attio: dict
    notion: dict


class InitiateConnectionResponse(BaseModel):
    """Response model for initiating connection"""
    redirect_url: str
    connection_id: str | None = None
    status: str


class CheckConnectionResponse(BaseModel):
    """Response model for checking connection"""
    connected: bool
    connection_id: str | None = None
    status: str | None = None
    error: str | None = None


############################
# API Endpoints
############################

@router.get("/status", response_model=ConnectionStatusResponse)
async def get_connection_status(user=Depends(get_verified_user)):
    """
    Get connection status for all integrations (Attio, Notion).
    
    Returns connection status for each integration.
    """
    try:
        # All connections use OpenWebUI user.id directly for Composio authentication
        # No separate integration_user_id columns needed in database
        
        # Get Attio connection status
        attio_status = {"connected": False}
        if ATTIO_AUTH_CONFIG_ID:
            connection_status = composio_service.check_connection_status(user.id, ATTIO_AUTH_CONFIG_ID)
            attio_status = connection_status
        
        # Get Notion connection status
        notion_status = {"connected": False}
        if NOTION_AUTH_CONFIG_ID:
            connection_status = composio_service.check_connection_status(user.id, NOTION_AUTH_CONFIG_ID)
            notion_status = connection_status
        
        return ConnectionStatusResponse(
            attio=attio_status,
            notion=notion_status
        )
    except Exception as e:
        log.error(f"Error getting connection status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get connection status: {str(e)}"
        )


@router.post("/attio/initiate", response_model=InitiateConnectionResponse)
async def initiate_attio_connection(user=Depends(get_verified_user)):
    """
    Initiate Attio OAuth connection flow.
    
    Returns redirect URL for OAuth authentication.
    """
    try:
        if not composio_service.is_enabled():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Composio service is not configured"
            )
        
        if not ATTIO_AUTH_CONFIG_ID:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Attio auth configuration not set"
            )
        
        
        # Use OpenWebUI user.id directly for all connections
        # Check if already connected
        connection_status = composio_service.check_connection_status(user.id, ATTIO_AUTH_CONFIG_ID)
        if connection_status.get('connected'):
            return InitiateConnectionResponse(
                redirect_url="",
                connection_id=connection_status.get('connection_id'),
                status="already_connected"
            )
        
        # Initiate connection with Composio using user.id
        connection_data = composio_service.initiate_connection(user.id, ATTIO_AUTH_CONFIG_ID)
        
        return InitiateConnectionResponse(**connection_data)
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error initiating Attio connection: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate Attio connection: {str(e)}"
        )


@router.get("/attio/check", response_model=CheckConnectionResponse)
async def check_attio_connection(
    background_tasks: BackgroundTasks,
    user=Depends(get_verified_user)
):
    """
    Check if Attio connection is complete.
    
    Used by frontend polling to detect when OAuth flow is completed.
    Triggers background sync on first successful connection.
    """
    try:
        # Use OpenWebUI user.id directly
        # Check connection status with Composio
        connection_status = composio_service.check_connection_status(user.id, ATTIO_AUTH_CONFIG_ID)
        
        return CheckConnectionResponse(**connection_status)
        
    except Exception as e:
        log.error(f"Error checking Attio connection: {e}")
        return CheckConnectionResponse(
            connected=False,
            error=str(e)
        )


@router.get("/attio/sync-status")
async def get_attio_sync_status(user=Depends(get_verified_user)):
    """
    Get Attio sync status for the current user.
    
    Returns:
        - status: 'in_progress', 'success', 'failed', or None
        - last_sync: ISO timestamp of last successful sync
        - notes_count: Number of notes synced
    """
    try:
        # Get sync status from Supabase
        sync_status, last_sync = supabase_service.get_user_sync_status(user.id, 'attio')
        
        # Get connection context metadata for notes count
        context_meta = supabase_service.get_connection_context_metadata(user.id, 'attio')
        notes_count = 0
        if context_meta:
            notes_count = context_meta.get('meta', {}).get('count', 0)
        
        return {
            "status": sync_status,
            "last_sync": last_sync,
            "notes_count": notes_count
        }
        
    except Exception as e:
        log.error(f"Error getting sync status: {e}")
        return {
            "status": None,
            "last_sync": None,
            "notes_count": 0
        }


@router.post("/attio/trigger-sync")
async def trigger_attio_sync(
    background_tasks: BackgroundTasks,
    user=Depends(get_verified_user)
):
    """
    Manually trigger Attio sync after OAuth completion.
    
    Called by frontend after popup window closes to ensure permissions are granted.
    """
    try:
        # Use OpenWebUI user.id directly
        # Verify connection is active
        connection_status = composio_service.check_connection_status(user.id, ATTIO_AUTH_CONFIG_ID)
        
        if not connection_status.get('connected'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Attio connection not active"
            )
        
        # Check if already syncing or synced
        sync_status, _ = supabase_service.get_user_sync_status(user.id, 'attio')
        
        if sync_status == 'in_progress':
            return {"message": "Sync already in progress", "status": "in_progress"}
        
        # Trigger sync in background (pass user.id as integration_user_id)
        log.info(f"Manually triggering Attio sync for user {user.id}")
        background_tasks.add_task(
            attio_sync_service.sync_attio_notes,
            user.id,
            user.email,
            user.id  # Use user.id for Composio authentication
        )
        
        return {"message": "Sync triggered successfully", "status": "triggered"}
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error triggering Attio sync: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger sync: {str(e)}"
        )


############################
# Notion Connection Endpoints
############################

@router.post("/notion/initiate", response_model=InitiateConnectionResponse)
async def initiate_notion_connection(user=Depends(get_verified_user)):
    """
    Initiate Notion OAuth connection flow via Composio.
    
    Returns redirect URL for user to authenticate with Notion.
    """
    try:
        if not composio_service.is_enabled():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Composio service is not configured"
            )
        
        if not NOTION_AUTH_CONFIG_ID:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Notion auth configuration not set"
            )
        
        # Use OpenWebUI user.id directly for all connections
        # Check if already connected
        connection_status = composio_service.check_connection_status(user.id, NOTION_AUTH_CONFIG_ID)
        if connection_status.get('connected'):
            return InitiateConnectionResponse(
                redirect_url="",
                connection_id=connection_status.get('connection_id'),
                status="already_connected"
            )
        
        # Initiate connection with Composio using user.id
        connection_data = composio_service.initiate_connection(user.id, NOTION_AUTH_CONFIG_ID)
        
        log.info(f"Notion connection initiated for user {user.id}")
        
        return InitiateConnectionResponse(**connection_data)
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error initiating Notion connection: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate Notion connection: {str(e)}"
        )


@router.get("/notion/check", response_model=CheckConnectionResponse)
async def check_notion_connection(
    background_tasks: BackgroundTasks,
    user=Depends(get_verified_user)
):
    """
    Check if Notion connection is complete.
    
    Used by frontend polling to detect when OAuth flow is completed.
    """
    try:
        # Use OpenWebUI user ID directly as notion_user_id
        notion_user_id = user.id
        
        # Check connection status with Composio
        connection_status = composio_service.check_connection_status(notion_user_id, NOTION_AUTH_CONFIG_ID)
        
        return CheckConnectionResponse(**connection_status)
        
    except Exception as e:
        log.error(f"Error checking Notion connection: {e}")
        return CheckConnectionResponse(
            connected=False,
            error=str(e)
        )


@router.post("/notion/trigger-sync")
async def trigger_notion_sync(
    background_tasks: BackgroundTasks,
    user=Depends(get_verified_user)
):
    """
    Manually trigger Notion sync after OAuth completion.
    
    Called by frontend after popup window closes to ensure permissions are granted.
    """
    try:
        # Use OpenWebUI user ID directly as notion_user_id
        notion_user_id = user.id
        
        # Verify connection is active
        connection_status = composio_service.check_connection_status(notion_user_id, NOTION_AUTH_CONFIG_ID)
        
        if not connection_status.get('connected'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Notion connection not active"
            )
        
        # Check if already syncing or synced
        sync_status, _ = supabase_service.get_user_sync_status(user.id, 'notion')
        
        if sync_status == 'in_progress':
            return {"message": "Sync already in progress", "status": "in_progress"}
        
        # Trigger sync in background
        log.info(f"Manually triggering Notion sync for user {user.id}")
        background_tasks.add_task(
            notion_sync_service.sync_notion_pages,
            user.id,
            user.email,
            notion_user_id
        )
        
        return {"message": "Sync triggered successfully", "status": "triggered"}
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error triggering Notion sync: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger sync: {str(e)}"
        )


@router.get("/notion/sync-status")
async def get_notion_sync_status(user=Depends(get_verified_user)):
    """
    Get current Notion sync status and metadata.
    
    Returns:
        status: 'not_started', 'in_progress', 'success', or 'failed'
        last_sync: Timestamp of last successful sync
        pages_count: Number of pages synced
    """
    try:
        # Get sync status from users table
        sync_status, last_sync = supabase_service.get_user_sync_status(user.id, 'notion')
        
        # Get metadata from connection_context_metadata
        metadata = supabase_service.get_connection_context_metadata(user.id, 'notion')
        
        return {
            "status": sync_status or "not_started",
            "last_sync": last_sync,
            "pages_count": metadata.get('count', 0) if metadata else 0
        }
        
    except Exception as e:
        log.error(f"Error getting Notion sync status: {e}")
        return {
            "status": "error",
            "last_sync": None,
            "pages_count": 0
        }

