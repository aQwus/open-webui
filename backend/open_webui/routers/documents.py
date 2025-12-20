import logging
import os
import uuid
import time
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)

from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.files import FileForm, FileModel, Files
from open_webui.storage.provider import Storage
from open_webui.utils.auth import get_verified_user
from open_webui.services.gemini_service import gemini_service
from open_webui.services.supabase_service import supabase_service

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()

# File upload constraints
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB in bytes
ALLOWED_EXTENSIONS = {
    "pdf",      # PDF documents
    "txt",      # Plain text
    "md",       # Markdown
    "html",     # HTML
    "htm",      # HTML alternative extension
    "csv",      # CSV files
    "docx",     # Word documents
}


def validate_file(file: UploadFile) -> tuple[bool, Optional[str]]:
    """
    Validate file type and size.
    Returns (is_valid, error_message)
    """
    # Get file extension
    filename = file.filename
    if not filename:
        return False, "Filename is required"
    
    file_extension = os.path.splitext(filename)[1].lower()
    # Remove the leading dot
    file_extension = file_extension[1:] if file_extension else ""
    
    # Check if extension is allowed
    if file_extension not in ALLOWED_EXTENSIONS:
        # Provide specific error messages for common unsupported types
        if file_extension in {"xlsx", "xls", "xlsm", "xlsb"}:
            return False, "Excel files (.xlsx, .xls) are not supported. Please upload PDF, TXT, MD, HTML, CSV, or DOCX files."
        elif file_extension in {"ppt", "pptx"}:
            return False, "PowerPoint files are not supported. Please upload PDF, TXT, MD, HTML, CSV, or DOCX files."
        elif file_extension in {"jpg", "jpeg", "png", "gif", "bmp", "svg"}:
            return False, "Image files are not supported. Please upload PDF, TXT, MD, HTML, CSV, or DOCX files."
        else:
            return False, f"File type '.{file_extension}' is not supported. Please upload PDF, TXT, MD, HTML, CSV, or DOCX files."
    
    return True, None


############################
# Upload Document
############################


@router.post("/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(get_verified_user),
):
    """
    Upload a document with file type and size validation.
    Files are stored in documents/{user_id}/ directory.
    """
    log.info(f"Uploading document: {file.filename} for user: {user.id}")
    
    # Validate file type
    is_valid, error_message = validate_file(file)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(error_message),
        )
    
    try:
        # Validate file size
        file_size = 0
        file.file.seek(0, 2)  # Seek to end
        file_size = file.file.tell()  # Get position (file size)
        file.file.seek(0)  # Reset to beginning
        
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size exceeds maximum allowed size of {MAX_FILE_SIZE / (1024 * 1024):.0f}MB",
            )
        
        # Validate file type (before saving to filesystem)
        SUPPORTED_EXTENSIONS = {'.pdf', '.txt', '.md', '.html', '.htm', '.csv', '.docx'}
        
        filename = file.filename
        file_ext = Path(filename).suffix.lower()
        
        if file_ext not in SUPPORTED_EXTENSIONS:
            # Determine specific error message
            if file_ext in {'.xlsx', '.xls', '.xlsm', '.xlsb'}:
                error_msg = "Excel files (.xlsx, .xls) are not supported. Please upload PDF, TXT, MD, HTML, CSV, or DOCX files."
            elif file_ext in {'.ppt', '.pptx'}:
                error_msg = "PowerPoint files are not supported. Please upload PDF, TXT, MD, HTML, CSV, or DOCX files."
            elif file_ext in {'.jpg', '.jpeg', '.png', '.gif', '.bmp'}:
                error_msg = "Image files are not supported. Please upload PDF, TXT, MD, HTML, CSV, or DOCX files."
            else:
                error_msg = f"File type '{file_ext}' is not supported. Please upload PDF, TXT, MD, HTML, CSV, or DOCX files."
            
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=error_msg,
            )
        
        # Generate unique file ID and path
        file_id = str(uuid.uuid4())
        
        # Reset file pointer for storage
        await file.seek(0)
        
        # Prepare file metadata
        unsanitized_filename = file.filename
        filename = os.path.basename(unsanitized_filename)
        file_extension = os.path.splitext(filename)[1].lower()[1:]
        
        # Sanitize filename to remove non-ASCII characters (for filesystem and Gemini)
        # This prevents encoding errors when uploading to Gemini
        safe_filename_base = os.path.splitext(filename)[0]  # Get name without extension
        safe_filename_base = safe_filename_base.encode('ascii', 'ignore').decode('ascii')
        
        # If entire filename was non-ASCII, use a fallback
        if not safe_filename_base:
            safe_filename_base = "document"
        
        # Reconstruct filename with original extension
        safe_filename = f"{safe_filename_base}.{file_extension}"
        
        # Generate unique ID and create storage filename
        file_id = str(uuid.uuid4())
        storage_filename = f"{file_id}_{safe_filename}"  # Use sanitized filename
        
        # Store file in documents/{user_id}/ directory
        file_path = f"documents/{user.id}/{storage_filename}"
        
        # Ensure the directory exists before uploading
        from open_webui.config import UPLOAD_DIR
        full_dir_path = Path(UPLOAD_DIR) / "documents" / user.id
        full_dir_path.mkdir(parents=True, exist_ok=True)
        
        # Upload to storage
        Storage.upload_file(
            file.file,
            file_path,
            {
                "OpenWebUI-User-Email": user.email,
                "OpenWebUI-User-Id": user.id,
                "OpenWebUI-User-Name": user.name,
                "OpenWebUI-File-Id": file_id,
            },
        )
        
        # ====================================================================
        # TRANSACTIONAL UPLOAD FLOW: Gemini → Supabase → Local DB
        # Order changed to get Gemini IDs first before storing metadata
        # Any failure triggers complete rollback including filesystem cleanup
        # ====================================================================
        
        # Step 1: Upload to Gemini File Storage (get IDs first)
        log.info(f"Step 1/3: Uploading document {file_id} to Gemini")
        gemini_file_id = None
        gemini_store_id = None
        
        if gemini_service.is_enabled():
            try:
                gemini_result = gemini_service.upload_file_to_gemini(
                    file_path=file_path,
                    filename=safe_filename,  # Use sanitized filename
                    user_id=user.id,
                    document_id=file_id
                )
                
                if gemini_result:
                    gemini_file_id, gemini_store_id = gemini_result
                    log.info(f"✓ Step 1/3: Successfully uploaded to Gemini: {gemini_file_id}")
                else:
                    raise Exception("Gemini upload returned None")
                    
            except Exception as e:
                log.error(f"✗ Step 1/3 failed: {e}")
                
                # ROLLBACK: Delete file from filesystem
                try:
                    Storage.delete_file(file_path)
                    log.info(f"Rolled back: Deleted file from filesystem: {file_path}")
                except Exception as rollback_error:
                    log.error(f"CRITICAL: Filesystem rollback failed: {rollback_error}")
                
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=ERROR_MESSAGES.DEFAULT(f"Gemini upload failed: {str(e)}"),
                )
        else:
            log.warning("Gemini service not enabled, skipping step 1/3")
        
        # Step 2: Sync to Supabase (with Gemini IDs)
        log.info(f"Step 2/3: Syncing document {file_id} to Supabase")
        if supabase_service.is_enabled():
            try:
                supabase_data = {
                    'id': file_id,
                    'user_id': user.id,
                    'user_email': user.email,
                    'filename': safe_filename,  # Use sanitized filename
                    'path': file_path,
                    'meta': {
                        "name": safe_filename,  # Use sanitized filename
                        "content_type": file.content_type or "application/octet-stream",
                        "size": file_size,
                        "source": "documents",
                        "gemini_file_id": gemini_file_id,
                        "gemini_store_id": gemini_store_id,
                    },
                    'created_at': int(time.time() * 1_000_000_000),  # nanoseconds
                    'updated_at': int(time.time() * 1_000_000_000),
                }
                
                supabase_service.insert_document_metadata(supabase_data)
                log.info(f"✓ Step 2/3: Successfully synced to Supabase")
                
            except Exception as e:
                log.error(f"✗ Step 2/3 failed: {e}")
                
                # ROLLBACK: Delete from Gemini
                try:
                    if gemini_file_id and gemini_store_id:
                        gemini_service.delete_document_from_gemini(
                            gemini_file_id=gemini_file_id,
                            gemini_store_id=gemini_store_id
                        )
                        log.info(f"Rolled back: Deleted document from Gemini")
                except Exception as rollback_error:
                    log.error(f"CRITICAL: Gemini rollback failed: {rollback_error}")
                
                # ROLLBACK: Delete file from filesystem
                try:
                    Storage.delete_file(file_path)
                    log.info(f"Rolled back: Deleted file from filesystem: {file_path}")
                except Exception as rollback_error:
                    log.error(f"CRITICAL: Filesystem rollback failed: {rollback_error}")
                
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=ERROR_MESSAGES.DEFAULT(f"Supabase sync failed: {str(e)}"),
                )
        else:
            log.warning("Supabase not enabled, skipping step 2/3")
        
        # Step 3: Save to Local DB (with all IDs)
        log.info(f"Step 3/3: Saving document {file_id} to local database")
        try:
            file_item = Files.insert_new_file(
                user.id,
                FileForm(
                    id=file_id,
                    filename=safe_filename,  # Use sanitized filename
                    path=file_path,
                    user_email=user.email,
                    data={},
                    meta={
                        "name": safe_filename,  # Use sanitized filename
                        "content_type": file.content_type or "application/octet-stream",
                        "size": file_size,
                        "source": "documents",
                        "gemini_file_id": gemini_file_id,
                        "gemini_store_id": gemini_store_id,
                    },
                ),
            )
            
            if not file_item:
                raise Exception("Failed to insert file into database")
            
            log.info(f"✓ Step 3/3: Successfully saved to local DB")
            
        except Exception as e:
            log.error(f"✗ Step 3/3 failed: {e}")
            
            # ROLLBACK: Delete from Supabase
            try:
                if supabase_service.is_enabled():
                    supabase_service.delete_document_metadata(file_id)
                    log.info(f"Rolled back: Deleted document from Supabase")
            except Exception as rollback_error:
                log.error(f"CRITICAL: Supabase rollback failed: {rollback_error}")
            
            # ROLLBACK: Delete from Gemini
            try:
                if gemini_file_id and gemini_store_id:
                    gemini_service.delete_document_from_gemini(
                        gemini_file_id=gemini_file_id,
                        gemini_store_id=gemini_store_id
                    )
                    log.info(f"Rolled back: Deleted document from Gemini")
            except Exception as rollback_error:
                log.error(f"CRITICAL: Gemini rollback failed: {rollback_error}")
            
            # ROLLBACK: Delete file from filesystem
            try:
                Storage.delete_file(file_path)
                log.info(f"Rolled back: Deleted file from filesystem: {file_path}")
            except Exception as rollback_error:
                log.error(f"CRITICAL: Filesystem rollback failed: {rollback_error}")
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=ERROR_MESSAGES.DEFAULT(f"Failed to save document to database: {str(e)}"),
            )
        
        # SUCCESS: All steps completed
        log.info(f"✓ Document {file_id} successfully uploaded to all systems")
        return {
            "id": file_item.id,
            "filename": file_item.filename,
            "size": file_size,
            "content_type": file.content_type,
            "created_at": file_item.created_at,
            "message": "Document uploaded successfully",
        }
            
    except HTTPException:
        raise
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Error uploading document"),
        )


############################
# List Documents
############################


@router.get("/")
async def list_documents(user=Depends(get_verified_user)):
    """
    Get all documents for the current user.
    Returns only files with source='documents' tag.
    """
    try:
        # Get all files for the user
        all_files = Files.get_files_by_user_id(user.id)
        
        # Filter only documents (files with source='documents' in meta)
        documents = [
            {
                "id": file.id,
                "filename": file.meta.get("name", file.filename) if file.meta else file.filename,
                "size": file.meta.get("size", 0) if file.meta else 0,
                "content_type": file.meta.get("content_type", "") if file.meta else "",
                "created_at": file.created_at,
                "updated_at": file.updated_at,
            }
            for file in all_files
            if file.meta and file.meta.get("source") == "documents"
        ]
        
        # Sort by created_at descending (newest first)
        documents.sort(key=lambda x: x["created_at"], reverse=True)
        
        return documents
        
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Error fetching documents"),
        )


############################
# Delete Document
############################


@router.delete("/{document_id}")
async def delete_document(document_id: str, user=Depends(get_verified_user)):
    """
    Delete a document by ID.
    Only the owner can delete their documents.
    """
    try:
        # Get the file
        file = Files.get_file_by_id(document_id)
        
        if not file:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ERROR_MESSAGES.NOT_FOUND,
            )
        
        # Check if file belongs to user and is a document
        if file.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ERROR_MESSAGES.NOT_FOUND,
            )
        
        # Verify it's a document (has source='documents' tag)
        if not (file.meta and file.meta.get("source") == "documents"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ERROR_MESSAGES.NOT_FOUND,
            )
        
        
        # ====================================================================
        # TRANSACTIONAL DELETE FLOW: Supabase → Gemini → Local DB
        # Missing records are lenient (warnings), actual errors are fatal
        # ====================================================================
        
        # Step 1: Delete from Supabase
        log.info(f"Step 1/3: Deleting document {document_id} from Supabase")
        supabase_existed = False
        
        if supabase_service.is_enabled():
            try:
                # Check existence first
                supabase_existed = supabase_service.check_document_exists(document_id)
                
                if supabase_existed:
                    supabase_service.delete_document_metadata(document_id)
                    log.info(f"✓ Step 1/3: Successfully deleted from Supabase")
                else:
                    log.warning(f"Document {document_id} not found in Supabase, continuing...")
                    
            except Exception as e:
                log.error(f"✗ Step 1/3 failed: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=ERROR_MESSAGES.DEFAULT(f"Supabase delete failed: {str(e)}"),
                )
        else:
            log.warning("Supabase not enabled, skipping step 1/3")
        
        # Step 2: Delete from Gemini File Storage
        log.info(f"Step 2/3: Deleting document {document_id} from Gemini")
        metadata = file.meta if hasattr(file, 'meta') and file.meta else {}
        gemini_file_id = metadata.get('gemini_file_id')
        gemini_store_id = metadata.get('gemini_store_id')
        
        if gemini_file_id and gemini_store_id:
            gemini_existed = gemini_service.check_document_exists(
                gemini_file_id=gemini_file_id,
                gemini_store_id=gemini_store_id
            )
            
            if gemini_existed:
                try:
                    gemini_deleted = gemini_service.delete_document_from_gemini(
                        gemini_file_id=gemini_file_id,
                        gemini_store_id=gemini_store_id
                    )
                    
                    if not gemini_deleted:
                        raise Exception("Gemini deletion returned False")
                    
                    log.info(f"✓ Step 2/3: Successfully deleted from Gemini")
                    
                except Exception as e:
                    log.error(f"✗ Step 2/3 failed: {e}")
                    
                    # ROLLBACK: Restore to Supabase if we deleted from there
                    if supabase_existed and supabase_service.is_enabled():
                        try:
                            restore_data = {
                                'id': file.id,
                                'user_id': file.user_id,
                                'user_email': file.user_email if hasattr(file, 'user_email') else '',
                                'filename': file.filename,
                                'path': file.path or '',
                                'meta': file.meta,
                                'created_at': file.created_at,
                                'updated_at': file.updated_at,
                            }
                            supabase_service.insert_document_metadata(restore_data)
                            log.info(f"Rolled back: Restored document {document_id} to Supabase")
                        except Exception as rollback_error:
                            log.error(f"CRITICAL: Supabase rollback failed: {rollback_error}")
                    
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=ERROR_MESSAGES.DEFAULT(f"Gemini delete failed: {str(e)}"),
                    )
            else:
                log.warning(f"Document {document_id} not found in Gemini, continuing...")
        else:
            log.info(f"No Gemini metadata for document {document_id}, skipping Gemini deletion")
        
        # Step 3: Delete from local storage and database
        log.info(f"Step 3/3: Deleting document {document_id} from local storage")
        
        # Delete file from storage
        try:
            Storage.delete_file(file.path)
            log.info(f"Successfully deleted file from local storage: {file.path}")
        except Exception as e:
            log.error(f"Error deleting file from storage: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=ERROR_MESSAGES.DEFAULT("Error deleting file from local storage"),
            )
        
        # Delete from database
        result = Files.delete_file_by_id(document_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=ERROR_MESSAGES.DEFAULT("Error deleting document from database"),
            )
        
        log.info(f"✓ Document {document_id} successfully deleted from all systems")
        return {"message": "Document deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Error deleting document"),
        )
