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
from open_webui.storage.provider import Storage, R2StorageProvider
from open_webui.config import UPLOAD_DIR
from open_webui.utils.auth import get_verified_user
from open_webui.services.gemini_service import gemini_service
from open_webui.services.supabase_service import supabase_service

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()

# Initialize R2 storage for documents
try:
    r2_storage = R2StorageProvider()
    log.info("R2 storage initialized successfully for documents")
except Exception as e:
    log.error(f"Failed to initialize R2 storage: {e}")
    r2_storage = None

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
        
        # ====================================================================
        # TRANSACTIONAL UPLOAD FLOW: R2 → Gemini → Supabase (No Local DB)
        # Documents stored in R2 and Supabase for persistence
        # Any failure triggers complete rollback
        # ====================================================================
        
        # Check R2 availability
        if not r2_storage:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Storage service temporarily unavailable. Please try again later.",
            )
        
        # Additional R2 file size check (5GB limit)
        MAX_R2_FILE_SIZE = 5 * 1024 * 1024 * 1024  # 5GB
        if file_size > MAX_R2_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File exceeds 5GB storage limit. Please upload a smaller file.",
            )
        
        # Step 1: Upload to R2 Storage
        log.info(f"Step 1/3: Uploading document {file_id} to R2")
        r2_file_contents = None
        
        try:
            r2_file_contents, r2_path = r2_storage.upload_file(
                file.file,
                file_path,
                {
                    "OpenWebUI-User-Email": user.email,
                    "OpenWebUI-User-Id": user.id,
                    "OpenWebUI-File-Id": file_id,
                },
            )
            log.info(f"✓ Step 1/3: Successfully uploaded to R2: {file_path}")
            
        except Exception as e:
            log.error(f"✗ Step 1/3 failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload document to storage: {str(e)}",
            )
        
        # Step 2: Upload to Gemini File Storage (get IDs)
        log.info(f"Step 2/3: Uploading document {file_id} to Gemini")
        gemini_file_id = None
        gemini_store_id = None
        
        if gemini_service.is_enabled():
            try:
                # Save R2 file contents to temp for Gemini upload
                temp_file_path = Path(UPLOAD_DIR) / storage_filename
                with open(temp_file_path, "wb") as f:
                    f.write(r2_file_contents)
                
                gemini_result = gemini_service.upload_file_to_gemini(
                    file_path=str(temp_file_path),
                    filename=safe_filename,  # Use sanitized filename
                    user_id=user.id,
                    document_id=file_id
                )
                
                # Clean up temp file
                if temp_file_path.exists():
                    temp_file_path.unlink()
                
                if gemini_result:
                    gemini_file_id, gemini_store_id = gemini_result
                    log.info(f"✓ Step 2/3: Successfully uploaded to Gemini: {gemini_file_id}")
                else:
                    raise Exception("Gemini upload returned None")
                    
            except Exception as e:
                log.error(f"✗ Step 2/3 failed: {e}")
                
                # ROLLBACK: Delete file from R2
                try:
                    r2_storage.delete_file(file_path)
                    log.info(f"Rolled back: Deleted file from R2: {file_path}")
                except Exception as rollback_error:
                    log.error(f"CRITICAL: R2 rollback failed: {rollback_error}")
                
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to upload document to storage: {str(e)}",
                )
        else:
            log.warning("Gemini service not enabled, skipping step 2/3")
        
        # Step 3: Save to Supabase (with Gemini IDs) - ONLY metadata storage
        log.info(f"Step 3/3: Saving document {file_id} to Supabase")
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
                log.info(f"✓ Step 3/3: Successfully saved to Supabase")
                
            except Exception as e:
                log.error(f"✗ Step 3/3 failed: {e}")
                
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
                
                # ROLLBACK: Delete file from R2
                try:
                    r2_storage.delete_file(file_path)
                    log.info(f"Rolled back: Deleted file from R2: {file_path}")
                except Exception as rollback_error:
                    log.error(f"CRITICAL: R2 rollback failed: {rollback_error}")
                
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to save document metadata: {str(e)}",
                )
        else:
            # Supabase is REQUIRED for documents
            log.error("Supabase not enabled - cannot save document metadata")
            
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
            
            # ROLLBACK: Delete file from R2
            try:
                r2_storage.delete_file(file_path)
                log.info(f"Rolled back: Deleted file from R2: {file_path}")
            except Exception as rollback_error:
                log.error(f"CRITICAL: R2 rollback failed: {rollback_error}")
            
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Document service temporarily unavailable. Please try again later.",
            )
        
        # SUCCESS: All steps completed
        log.info(f"✓ Document {file_id} successfully uploaded and saved")
        return {
            "id": file_id,
            "filename": safe_filename,
            "size": file_size,
            "content_type": file.content_type or "application/octet-stream",
            "created_at": int(time.time() * 1_000_000_000),
            "message": "Document uploaded successfully",
        }
            
    except HTTPException:
        raise
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error uploading document",
        )


############################
# List Documents
############################


@router.get("/")
async def list_documents(user=Depends(get_verified_user)):
    """
    Get all documents for the current user from Supabase.
    Returns documents ordered by created_at descending.
    """
    try:
        # Query Supabase for user's documents
        documents_data = supabase_service.list_user_documents(user.id)
        
        # Transform Supabase response to match frontend expectations
        documents = []
        for doc in documents_data:
            meta = doc.get('meta', {})
            documents.append({
                "id": doc['id'],
                "filename": meta.get("name", doc['filename']),
                "size": meta.get("size", 0),
                "content_type": meta.get("content_type", ""),
                "created_at": doc['created_at'],
                "updated_at": doc['updated_at'],
            })
        
        return documents
        
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to retrieve documents. Please try again later.",
        )


############################
# Delete Document
############################


@router.delete("/{document_id}")
async def delete_document(document_id: str, user=Depends(get_verified_user)):
    """
    Delete a document by ID from Supabase, Gemini, and filesystem.
    Only the owner can delete their documents.
    """
    try:
        # ====================================================================
        # TRANSACTIONAL DELETE FLOW: Fetch Supabase → Delete Supabase → Delete Gemini → Delete Filesystem
        # Supabase is source of truth for document metadata
        # ====================================================================
        
        # Step 1: Fetch document from Supabase
        log.info(f"Fetching document {document_id} from Supabase")
        
        if not supabase_service.is_enabled():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Document service temporarily unavailable. Please try again later.",
            )
        
        document = supabase_service.get_document_by_id(document_id)
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )
        
        # Check ownership
        if document['user_id'] != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )
        
        # Extract data for deletion and potential rollback
        gemini_file_id = document.get('gemini_file_id')  # From column, not meta
        gemini_store_id = document.get('gemini_store_id')  # From column, not meta
        file_path = document.get('path')
        
        # Save document data for potential rollback
        document_backup = document.copy()
        
        # Step 2: Delete from Supabase
        log.info(f"Step 1/3: Deleting document {document_id} from Supabase")
        try:
            supabase_service.delete_document_metadata(document_id)
            log.info(f"✓ Step 1/3: Successfully deleted from Supabase")
        except Exception as e:
            log.error(f"✗ Step 1/3 failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete document metadata: {str(e)}",
            )
        
        # Step 3: Delete from Gemini File Storage
        log.info(f"Step 2/3: Deleting document {document_id} from Gemini")
        
        if gemini_file_id and gemini_store_id:
            # Check if document exists in Gemini
            gemini_exists = gemini_service.check_document_exists(
                gemini_file_id=gemini_file_id,
                gemini_store_id=gemini_store_id
            )
            
            if gemini_exists:
                try:
                    gemini_deleted = gemini_service.delete_document_from_gemini(
                        gemini_file_id=gemini_file_id,
                        gemini_store_id=gemini_store_id
                    )
                    
                    if not gemini_deleted:
                        raise Exception("Gemini deletion returnedFalse")
                    
                    log.info(f"✓ Step 2/3: Successfully deleted from Gemini")
                    
                except Exception as e:
                    log.error(f"✗ Step 2/3 failed: {e}")
                    
                    # ROLLBACK: Restore to Supabase using backup data
                    try:
                        supabase_service.insert_document_metadata(document_backup)
                        log.info(f"Rolled back: Restored document {document_id} to Supabase")
                    except Exception as rollback_error:
                        log.error(f"CRITICAL: Supabase rollback failed: {rollback_error}")
                    
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to delete from storage: {str(e)}",
                    )
            else:
                log.warning(f"Document {document_id} not found in Gemini (NULL IDs or missing), skipping")
        else:
            log.info(f"No Gemini IDs for document {document_id}, skipping Gemini deletion")
        
        # Step 3: Delete from R2 Storage (LENIENT - no rollback if fails)
        log.info(f"Step 3/3: Deleting document {document_id} from R2")
        
        if file_path and r2_storage:
            try:
                r2_storage.delete_file(file_path)
                log.info(f"Successfully deleted file from R2: {file_path}")
            except Exception as e:
                log.warning(f"R2 deletion failed, but continuing: {e}")
                # Don't raise - user still sees success (per user requirement)
                # File remains in R2 but removed from Supabase/Gemini
        else:
            log.warning(f"No file path or R2 storage unavailable for document {document_id}")
        
        log.info(f"✓ Document {document_id} successfully deleted")
        return {"message": "Document deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error deleting document",
        )
