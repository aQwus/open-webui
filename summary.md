# OpenWebUI Project - Complete Development History

**Project:** OpenWebUI (Rebranded as "Hippo")  
**Tech Stack:** Python, FastAPI, Svelte, Docker, Gemini API, Supabase  
**Purpose:** AI chat interface with document RAG using Gemini File Storage

---

## Table of Contents
1. [Phase 1: Rebranding](#phase-1-rebranding-open-webui-to-hippo)
2. [Phase 2: Document Management UI](#phase-2-document-management-ui)
3. [Phase 3: Gemini File Storage Integration](#phase-3-gemini-file-storage-integration)
4. [Phase 4: Gemini RAG Implementation](#phase-4-gemini-rag-implementation)
5. [Phase 5: Gemini Deletion Flow](#phase-5-gemini-deletion-flow)
6. [Phase 6: UI/UX Improvements](#phase-6-uiux-improvements)
7. [Phase 7: Supabase Metadata Sync](#phase-7-supabase-metadata-sync)
8. [Phase 8: File Validation & Unicode Fixes](#phase-8-file-validation--unicode-fixes)
9. [Deployment Preparation](#deployment-preparation)
10. [Lessons Learned & Common Mistakes](#lessons-learned--common-mistakes)

---

## Phase 1: Rebranding Open WebUI to "Hippo"

### Goal
Replace all instances of "Open WebUI" with "Hippo" and update logos.

### Changes Made

#### 1. Backend Configuration
**File:** `backend/open_webui/env.py`
```python
WEBUI_NAME = "Hippo"  # Changed from "Open WebUI"
```

#### 2. Frontend Dynamic Text Updates
**Files Modified:**
- `src/routes/+layout.svelte` - Notification titles use `{$WEBUI_NAME}`
- `src/lib/components/channel/Channel.svelte` - Page titles use `{$WEBUI_NAME}`
- `backend/open_webui/main.py` - PWA manifest uses `app.state.WEBUI_NAME`

#### 3. Logo Replacements
**Logo Details:**
- Source: `hippo.png` (1024x1024, square, non-transparent)
- Styling: Circular using CSS `rounded-full` class
- Favicons: Generated multiple sizes (favicon.png, favicon-96x96.png, favicon-dark.png, favicon.ico)

**Files Replaced:**
- `static/logo.png`
- `static/favicon.svg`
- `static/static/` directory (11 files including various icon sizes)
- `favicon.ico` (both `static/` and `static/static/`)

### Issues Encountered

#### Issue 1.1: Docker Build Cache Corruption
**Problem:** Build errors after logo changes due to cache corruption.

**Solution:**
```bash
docker system prune -a -f
docker-compose up --build --no-cache
```

#### Issue 1.2: Browser Favicon Cache
**Problem:** Old logo persisting in browser despite rebuilds.

**Solutions Provided:**
- Hard refresh: Ctrl+Shift+R / Cmd+Shift+R
- Clear site data in DevTools
- Clear Chrome favicon cache: `chrome://favicon/`

**Lesson:** Browser caching is aggressive for favicons; always test in incognito mode.

---

## Phase 2: Document Management UI

### Goal
Create a dedicated document manager separate from knowledge files, with upload/list/delete functionality.

### Implementation Details

#### 1. Backend Routes
**File:** `backend/open_webui/routers/documents.py`

**Endpoints Created:**
- `POST /api/v1/documents/upload` - Upload document
- `GET /api/v1/documents/` - List user's documents
- `DELETE /api/v1/documents/{document_id}` - Delete document

**Key Features:**
- File validation (type, size)
- Storage in `documents/{user_id}/` directory
- Metadata stored with special tag: `source="documents"`
- Filtering by source tag to separate from knowledge files

#### 2. Frontend Component
**File:** `src/lib/components/layout/Sidebar/DocumentsModal.svelte`

**Features:**
- Modal-based UI
- File drag-and-drop upload
- Document list with delete buttons
- File size/type display
- Empty state handling

#### 3. Storage Structure
```
documents/
  └── {user_id}/
      └── {file_id}_{filename}
```

### Issues Encountered

#### Issue 2.1: File Type Validation Location
**Problem:** Initial validation function was generic, not specific to documents.

**Solution:** Created dedicated validation in documents.py with `ALLOWED_EXTENSIONS`.

**Learning:** Keep validation close to the route that uses it for clarity.

---

## Phase 3: Gemini File Storage Integration

### Goal
Upload documents to Gemini File Storage for RAG capabilities using the new File Search Store API.

### Architecture

#### Gemini File Search Store Concept
- Each user gets their own File Search Store
- Store ID format: `fileSearchStores/{store_id}`
- Documents uploaded to store for embedding
- Enables semantic search across user's documents

### Implementation Details

#### 1. Gemini Service Creation
**File:** `backend/open_webui/services/gemini_service.py`

**Methods Implemented:**
```python
class GeminiService:
    def __init__(self):
        # Initialize Gemini client with API key
    
    def get_or_create_file_search_store(self, user_id: str):
        # Create/retrieve user's file search store
        # Uses display_name: f"User_{user_id}_Documents"
    
    def upload_file_to_gemini(self, file_path, filename, user_id, document_id):
        # Upload file to user's store
        # Returns (gemini_file_id, gemini_store_id)
```

#### 2. Configuration
**File:** `backend/open_webui/config.py`
```python
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
```

#### 3. Upload Flow Integration
**File:** `backend/open_webui/routers/documents.py`
- After file saved to storage
- Upload to Gemini
- Store `gemini_file_id` and `gemini_store_id` in metadata

### Issues Encountered

#### Issue 3.1: Gemini API Client Initialization
**Problem:** SDK method naming confusion between `genai.Client()` and `genai.GenerativeModel()`.

**Solution:** Use `genai.Client(api_key=...)` for File Search Store operations.

**Learning:** Always check latest Gemini Python SDK docs; API evolves frequently.

#### Issue 3.2: Store ID Format Confusion
**Problem:** Not understanding when to include `fileSearchStores/` prefix.

**Solution:**
- API returns full path: `fileSearchStores/{id}`
- Store complete string in database
- Use directly when calling Gemini API

**Learning:** Don't manipulate Gemini resource IDs; store and use as-is.

---

## Phase 4: Gemini RAG Implementation

### Goal
Retrieve context from Gemini File Storage based on user queries and inject into chat completions.

### Implementation Details

#### 1. Environment Configuration
**File:** `backend/open_webui/config.py`
```python
TOP_K = int(os.environ.get("TOP_K", "5"))  # Number of chunks to retrieve
GEMINI_MODEL1 = os.environ.get("MODEL1", "gemini-2.5-flash")
GEMINI_MODEL2 = os.environ.get("MODEL2", "gemini-2.5-flash-lite")
GEMINI_MODEL3 = os.environ.get("MODEL3", "gemini-2.0-flash")
```

**Why 3 Models?** Fallback strategy for 503 errors (rate limiting).

#### 2. Context Retrieval Method
**File:** `backend/open_webui/services/gemini_service.py`

```python
def find_file_search_store(self, user_id: str):
    # Find store WITHOUT creating if doesn't exist
    # Returns None if not found
    
def retrieve_context(self, user_query: str, user_id: str):
    # 1. Find user's store (don't create)
    # 2. Try Model 1 with retry on 503
    # 3. If fails, try Model 2
    # 4. If fails, try Model 3
    # 5. Return context or None
```

**Key Design Decision:** Don't create store during retrieval to avoid orphan stores.

#### 3. Chat Completion Integration
**File:** `backend/open_webui/routers/openai.py`

**Injection Point:**
```python
# Before sending to model
if user_query:
    context = gemini_service.retrieve_context(user_query, user.id)
    if context:
        # Augment user message with context
        augmented_query = f"{user_query}\n\nRelevant Context:\n{context}"
```

### Issues Encountered

#### Issue 4.1: 503 Rate Limiting
**Problem:** Gemini File Search frequently returns 503 during high load.

**Solution:** Implemented retry with exponential backoff (2s, 4s, 8s) and model fallback.

**Learning:** Always implement retry logic for external APIs; have fallback models.

#### Issue 4.2: Creating Stores on Retrieval
**Problem:** `get_or_create_file_search_store()` was creating empty stores during search.

**Solution:** Created separate `find_file_search_store()` that only searches, doesn't create.

**Learning:** Separate read and write operations; don't auto-create resources on reads.

---

## Phase 5: Gemini Deletion Flow

### Goal
Delete documents from Gemini File Storage when user deletes from UI.

### Challenges
Gemini SDK doesn't provide a direct delete method for documents in File Search Stores.

### Solution: REST API Approach

#### 1. Document Existence Check
**Method:** `check_document_exists(gemini_file_id, gemini_store_id)`

**Approach:**
```python
# Use REST API to list documents in store
url = f"{self.base_url}/{gemini_store_id}/documents"
response = requests.get(url)

# Check if doc_id exists in response
for doc in documents:
    if doc['name'].endswith(gemini_file_id):
        return True
return False
```

#### 2. Document Deletion
**Method:** `delete_document_from_gemini(gemini_file_id, gemini_store_id)`

**Approach:**
```python
# Force delete using REST API
url = f"{self.base_url}/{gemini_store_id}/documents/{gemini_file_id}?force=true"
response = requests.delete(url)
```

**`force=true` Flag:** Deletes document AND its chunks from vector database.

### Issues Encountered

#### Issue 5.1: Double Prefix Error
**Problem:** URL became `fileSearchStores/fileSearchStores/{id}`

**Cause:** `gemini_store_id` already contains full path, but code was adding prefix again.

**Solution:** Use `gemini_store_id` directly since it already includes `fileSearchStores/`.

**Learning:** Always log constructed URLs when debugging API calls.

#### Issue 5.2: Deletion Not Working Without Force Flag
**Problem:** Document deleted but chunks remained in vector store.

**Solution:** Always use `?force=true` to ensure complete cleanup.

**Learning:** Read API documentation carefully for cleanup flags.

---

## Phase 6: UI/UX Improvements

### 6.1 Document Deletion Feedback

**Problem:** No feedback during deletion; users could double-click delete button.

**Solution:**
**File:** `src/lib/components/layout/Sidebar/DocumentsModal.svelte`

**Changes:**
1. Toast notification during deletion
2. Disable delete button while loading
3. Translucent loading overlay with spinner
4. Success/error toast on completion

**Code:**
```javascript
deleting = true;
toast.loading("Deleting document...");

// After deletion
toast.success("Document deleted");
deleting = false;
```

### 6.2 Arena Model Hiding

**Problem:** Arena Model showing in model dropdown unnecessarily.

**Solution:**
**File:** `docker-compose.yaml`
```yaml
environment:
  - ENABLE_EVALUATION_ARENA_MODELS=false
```

### 6.3 Active Users Count (Admin Only)

**Problem:** Active Users count visible to all users.

**Solution:**
**File:** `src/lib/components/layout/Sidebar/UserMenu.svelte`
```svelte
{#if showActiveUsers && $user?.role === 'admin'}
    <!-- Active Users display -->
{/if}
```

**Learning:** Always check user permissions before displaying sensitive info.

---

## Phase 7: Supabase Metadata Sync

### Goal
Sync document metadata to Supabase with strict transactional behavior and rollback support across three systems: Local DB, Supabase, Gemini File Storage.

### Requirements
1. **Upload Flow:** Gemini → Supabase → Local DB (with rollback)
2. **Delete Flow:** Supabase → Gemini → Local DB (lenient for missing records)
3. **User Email Storage:** Add `user_email` column for new uploads
4. **Timestamp Conversion:** Nanoseconds → ISO format for Supabase
5. **Startup Validation:** Verify Supabase connection on Docker startup

### Implementation Details

#### 1. Supabase Service Creation
**File:** `backend/open_webui/services/supabase_service.py`

**Class Structure:**
```python
class SupabaseService:
    def __init__(self):
        # Initialize from env vars
        
    def is_enabled(self) -> bool:
        # Check if config exists
        
    def validate_connection(self) -> bool:
        # Test connection on startup
        
    def check_document_exists(self, document_id: str) -> bool:
        # Check if doc in Supabase
        
    def insert_document_metadata(self, doc_data: Dict) -> bool:
        # Upsert metadata
        
    def delete_document_metadata(self, document_id: str) -> bool:
        # Delete by ID
        
    def _convert_timestamp(self, ns_timestamp: int) -> str:
        # Convert nanoseconds to ISO 8601
```

#### 2. Database Schema Update
**File:** `backend/open_webui/internal/migrations/999_add_user_email_to_files.py`

```python
def migrate(migrator, database):
    migrator.add_fields(
        'file',
        user_email=pw.CharField(max_length=255, null=True)
    )
```

**Why Nullable?** Existing documents don't have user_email; only new uploads will populate it.

#### 3. File Model Update
**File:** `backend/open_webui/models/files.py`

**Changes:**
```python
class File(Base):
    user_email = Column(String, nullable=True)  # For Supabase sync

class FileModel(BaseModel):
    user_email: Optional[str] = None
```

#### 4. Upload Flow Implementation
**File:** `backend/open_webui/routers/documents.py`

**Transaction Order:**
```python
# Step 1: Upload to Gemini (get IDs first)
gemini_result = gemini_service.upload_file_to_gemini(...)
if not gemini_result:
    # ROLLBACK: Delete filesystem file
    Storage.delete_file(file_path)
    raise HTTPException("Gemini upload failed")

gemini_file_id, gemini_store_id = gemini_result

# Step 2: Sync to Supabase (with Gemini IDs)
try:
    supabase_service.insert_document_metadata({
        'id': file_id,
        'user_email': user.email,
        'meta': {'gemini_file_id': gemini_file_id, ...}
    })
except:
    # ROLLBACK: Delete Gemini + Filesystem
    gemini_service.delete_document_from_gemini(...)
    Storage.delete_file(file_path)
    raise HTTPException("Supabase sync failed")

# Step 3: Save to Local DB (with all IDs)
try:
    Files.insert_new_file(...)
except:
    # ROLLBACK: Delete Supabase + Gemini + Filesystem
    supabase_service.delete_document_metadata(file_id)
    gemini_service.delete_document_from_gemini(...)
    Storage.delete_file(file_path)
    raise HTTPException("Local DB save failed")
```

**Why This Order?**
- Need Gemini IDs before storing metadata
- Can't save to Local DB without Gemini IDs
- Must maintain consistency across all 3 systems

#### 5. Delete Flow Implementation

**Transaction Order:**
```python
# Step 1: Check and delete from Supabase
supabase_exists = supabase_service.check_document_exists(file_id)
if supabase_exists:
    try:
        supabase_service.delete_document_metadata(file_id)
    except:
        raise HTTPException("Supabase delete failed")
else:
    log.warning(f"Document {file_id} not found in Supabase")

# Step 2: Check and delete from Gemini
if gemini_file_id and gemini_store_id:
    gemini_exists = gemini_service.check_document_exists(...)
    if gemini_exists:
        try:
            gemini_service.delete_document_from_gemini(...)
        except:
            # ROLLBACK: Restore Supabase if we deleted from it
            if supabase_existed:
                supabase_service.insert_document_metadata(file_data)
            raise HTTPException("Gemini delete failed")
    else:
        log.warning(f"Document not found in Gemini")

# Step 3: Delete from Filesystem
Storage.delete_file(file_path)

# Step 4: Delete from Local DB
Files.delete_file_by_id(file_id)
```

**Key Design: Lenient Deletion**
- Missing records in Supabase/Gemini → Log warning, continue
- Only actual errors → Fail and rollback
- Local DB delete always executes

#### 6. Startup Validation
**File:** `backend/open_webui/main.py`

```python
from open_webui.services.supabase_service import supabase_service

if supabase_service.is_enabled():
    if supabase_service.validate_connection():
        log.info("✓ Supabase connection validated successfully")
    else:
        log.error("✗ Supabase connection validation failed")
```

#### 7. Docker Configuration
**File:** `docker-compose.yaml`

```yaml
environment:
  - SUPABASE_URL=${SUPABASE_URL}
  - SUPABASE_SERVICE_ROLE_KEY=${SUPABASE_SERVICE_ROLE_KEY}
```

### Issues Encountered

#### Issue 7.1: FileUpdateForm AttributeError
**Problem:**
```python
AttributeError: 'dict' object has no attribute 'hash'
```

**Cause:** Passing dict to `update_file_by_id()` instead of FileUpdateForm.

**Original Code:**
```python
Files.update_file_by_id(file_id, {'meta': updated_meta})
```

**Fixed Code:**
```python
from open_webui.models.files import FileUpdateForm
Files.update_file_by_id(file_id, FileUpdateForm(meta=updated_meta))
```

**Learning:** Always check function signatures for expected types; don't assume dict works everywhere.

#### Issue 7.2: Wrong Upload Flow Order
**Problem:** Tried Local DB → Supabase → Gemini but couldn't get Gemini IDs for earlier steps.

**Solution:** Changed to Gemini → Supabase → Local DB to get IDs first.

**Learning:** Analyze data dependencies before designing transaction order.

---

## Phase 8: File Validation & Unicode Fixes

### 8.1 File Type Validation

**Problem:** Excel files (.xlsx) causing Gemini API errors:
```
400 INVALID_ARGUMENT: MIME type must be in valid format
```

**Root Cause:** Gemini File Search only supports specific file types.

**Supported Types:**
- ✅ PDF (.pdf)
- ✅ Plain Text (.txt)
- ✅ Markdown (.md)
- ✅ HTML (.html, .htm)
- ✅ CSV (.csv)
- ✅ Word (.docx)
- ❌ Excel (.xlsx, .xls)
- ❌ PowerPoint (.ppt, .pptx)
- ❌ Images (.jpg, .png, etc.)

**Solution:**
**File:** `backend/open_webui/routers/documents.py`

```python
ALLOWED_EXTENSIONS = {
    "pdf", "txt", "md", "html", "htm", "csv", "docx"
}

def validate_file(file: UploadFile):
    file_extension = os.path.splitext(filename)[1].lower()[1:]
    
    if file_extension not in ALLOWED_EXTENSIONS:
        # Specific error messages
        if file_extension in {"xlsx", "xls", "xlsm", "xlsb"}:
            return False, "Excel files (.xlsx, .xls) are not supported. Please upload PDF, TXT, MD, HTML, CSV, or DOCX files."
        elif file_extension in {"ppt", "pptx"}:
            return False, "PowerPoint files are not supported..."
        elif file_extension in {"jpg", "jpeg", "png", "gif"}:
            return False, "Image files are not supported..."
        else:
            return False, f"File type '.{file_extension}' is not supported..."
```

**Validation Timing:** Before saving to filesystem (prevents orphan files).

**Learning:** Validate early; provide specific user-friendly error messages.

### 8.2 Unicode Filename Handling

**Problem:**
```
'ascii' codec can't encode character '\u2014' in position 42: ordinal not in range(128)
```

**Example:** Filename "WONE — Concept Note.pdf" (contains em dash `—`)

**Where It Broke:**
1. ❌ Filesystem path (when saving file)
2. ❌ Gemini API call (when uploading)
3. ❌ Logging (when printing filename)

**Solution: Three-Part Fix**

#### Part 1: Sanitize Before Filesystem Save
**File:** `backend/open_webui/routers/documents.py`

```python
# Get filename without extension
safe_filename_base = os.path.splitext(filename)[0]

# Remove non-ASCII characters
safe_filename_base = safe_filename_base.encode('ascii', 'ignore').decode('ascii')

# Fallback if entire filename was non-ASCII
if not safe_filename_base:
    safe_filename_base = "document"

# Reconstruct with extension
safe_filename = f"{safe_filename_base}.{file_extension}"

# Use in storage path
storage_filename = f"{file_id}_{safe_filename}"
```

**Result:** "WONE — Concept Note.pdf" → "WONE  Concept Note.pdf" (em dash removed)

#### Part 2: Use Sanitized Filename Everywhere
**Locations Updated:**
- Storage.upload_file() path
- Gemini upload filename parameter  
- Supabase metadata (filename and meta.name fields)
- Local DB metadata (filename and meta.name fields)

#### Part 3: Remove Unicode from Logging
**File:** `backend/open_webui/services/gemini_service.py`

**Before:**
```python
log.info(f"Original filename: {filename}")  # ❌ Causes encoding error
log.info(f"Sanitized filename: {safe_filename}")
```

**After:**
```python
log.info(f"Sanitized filename for Gemini: {safe_filename}")  # ✅ Only log safe version
```

**Why Logging Failed:** Python's logging module writes to stdout in ASCII by default.

**Complete Fix Locations:**
- `routers/documents.py` lines 144-158 (sanitization)
- `routers/documents.py` lines 193, 231, 234, 283, 290 (usage)
- `services/gemini_service.py` lines 153-160 (logging fix)

**Learning:**
1. Always sanitize filenames before filesystem operations
2. Non-ASCII characters can break logging too, not just API calls
3. Test with unicode filenames (em dash, accents, CJK characters)

---

## Deployment Preparation

### Target Platform: Render.com

### Dockerfile Analysis

**File:** `Dockerfile`

✅ **Already Render-Ready:**
- Port configuration: `PORT=8080` (line 60)
- Exposed port: `EXPOSE 8080` (line 170)
- Healthcheck: `HEALTHCHECK CMD curl --silent --fail http://localhost:${PORT:-8080}/health` (line 172)
- No hardcoded ports

**No Changes Needed!**

### File Cleanup

#### .gitignore Updates
**Added:**
```gitignore
# Gemini Antigravity artifacts
.gemini/
```

**Why:** Don't commit AI conversation artifacts.

#### .dockerignore
**Already Good:**
- Excludes `.env`
- Excludes `node_modules`
- Excludes `backend/data/*`
- Excludes database files

### Environment Variables for Render

**Required in Render Dashboard:**
```bash
# Core
WEBUI_SECRET_KEY=<auto-generate>

# Gemini
GEMINI_API_KEY=<your-key>
TOP_K=5
MODEL1=gemini-2.5-flash
MODEL2=gemini-2.5-flash-lite
MODEL3=gemini-2.0-flash

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<your-key>
```

### Persistent Storage

**Critical:** Configure persistent disk for `/app/backend/data`

**Why:** SQLite database and uploaded files need to persist across deploys.

**Render Configuration:**
```yaml
disk:
  name: data
  mountPath: /app/backend/data
  sizeGB: 10
```

---

## Lessons Learned & Common Mistakes

### 1. Docker & Caching

#### Lesson: Docker Build Cache Can Corrupt
**Problem:** Build failures after changes.

**Solutions:**
```bash
# Clean everything
docker system prune -a -f

# Force clean build
docker-compose up --build --no-cache
```

**When to use:** After major dependency changes or mysterious build errors.

#### Lesson: Browser Caching Is Aggressive
**Problem:** Favicon/logo changes not visible.

**Test Strategy:**
1. Always test in incognito mode first
2. Hard refresh: Ctrl+Shift+R
3. Clear site data for localhost
4. Check `chrome://favicon/` cache

### 2. API Integration

#### Lesson: Always Implement Retry Logic
**Context:** Gemini File Search returns 503 frequently.

**Pattern:**
```python
for attempt in range(max_retries):
    try:
        result = api_call()
        return result
    except 503Error:
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)  # Exponential backoff
            continue
        raise
```

**Apply to:** All external API calls (Gemini, Supabase, etc.)

#### Lesson: Have Fallback Resources
**Context:** Multiple Gemini models for fallback.

**Pattern:**
```python
models = [MODEL1, MODEL2, MODEL3]
for model in models:
    try:
        result = call_with_model(model)
        return result
    except:
        continue
raise Exception("All models failed")
```

#### Lesson: Don't Auto-Create on Read Operations
**Context:** Creating file search stores during retrieval.

**Bad:**
```python
def retrieve_context(user_id):
    store = get_or_create_store(user_id)  # ❌ Creates empty stores
    return search(store)
```

**Good:**
```python
def retrieve_context(user_id):
    store = find_store(user_id)  # ✅ Only searches
    if not store:
        return None
    return search(store)
```

### 3. API Resource IDs

#### Lesson: Don't Manipulate Gemini Resource IDs
**Context:** Store IDs come as `fileSearchStores/{id}`.

**Bad:**
```python
# Extracting and storing just the ID
store_id = full_path.split('/')[-1]  # ❌
# Later causes double prefix: fileSearchStores/fileSearchStores/{id}
```

**Good:**
```python
# Store complete path as returned
gemini_store_id = response.name  # fileSearchStores/{id} ✅
# Use directly in API calls
```

**Rule:** Store resource IDs exactly as returned by API.

### 4. Transaction Management

#### Lesson: Analyze Data Dependencies First
**Context:** Upload flow ordering.

**Process:**
1. List what data each step needs
2. Identify dependencies (Step B needs output from Step A)
3. Order steps based on dependencies
4. Design rollback for each step

**Example:**
```
Local DB needs: user_id, filename
Supabase needs: user_id, filename, gemini_file_id ← dependency!
Gemini needs: file_path

→ Order: Gemini (produces IDs) → Supabase (uses IDs) → Local DB (uses IDs)
```

#### Lesson: Rollback in Reverse Order
**Pattern:**
```python
try:
    step_1()
    try:
        step_2()
        try:
            step_3()
        except:
            rollback_step_2()
            rollback_step_1()
            raise
    except:
        rollback_step_1()
        raise
except:
    # All rolled back
    raise
```

#### Lesson: Lenient Deletes, Strict Creates
**Context:** Delete flow for Supabase/Gemini.

**Philosophy:**
- **Create:** Strict - any failure = abort
- **Delete:** Lenient - missing record = warning, continue

**Reason:** Better to have orphan metadata than fail deletion entirely.

### 5. Unicode & Internationalization

#### Lesson: Test with Non-ASCII Characters
**Characters to test:**
- Em dash: —
- En dash: –
- Accents: é, ñ, ü
- CJK: 中文, 日本語, 한국어
- Emoji: 📄 🚀

**Test Points:**
1. Filename upload
2. File save to disk
3. API calls with filename
4. Logging filename
5. Database storage

#### Lesson: Sanitize Early
**Pattern:**
```python
# Get user input
raw_filename = user_input

# Sanitize immediately
safe_filename = sanitize(raw_filename)

# Use safe version everywhere
save_to_disk(safe_filename)
call_api(safe_filename)
log(safe_filename)
store_in_db(safe_filename)
```

#### Lesson: Logging Can Fail on Unicode
**Problem:** `log.info(f"File: {unicode_string}")` can crash.

**Solution:** Only log ASCII-safe strings.

### 6. Type Safety

#### Lesson: Don't Assume Dict Works Everywhere
**Context:** FileUpdateForm error.

**Check:**
```python
# Before assuming
Files.update_file_by_id(id, {'key': 'value'})  # Might fail!

# Check function signature
def update_file_by_id(id: str, form: FileUpdateForm):
    ...

# Use correct type
Files.update_file_by_id(id, FileUpdateForm(key='value'))  # ✅
```

**Rule:** Always check what type a function expects, especially for Pydantic models.

### 7. Error Messages

#### Lesson: Provide Specific, Actionable Errors
**Bad:**
```python
raise HTTPException(400, "Invalid file")
```

**Good:**
```python
if file_ext in {'xlsx', 'xls'}:
    raise HTTPException(
        415,
        "Excel files (.xlsx, .xls) are not supported. Please upload PDF, TXT, MD, HTML, CSV, or DOCX files."
    )
```

**Template:**
```
{What's wrong} + {Why} + {What to do instead}
```

### 8. Validation Timing

#### Lesson: Validate Before Side Effects
**Context:** File type validation.

**Bad Flow:**
```python
save_to_filesystem(file)  # Side effect first
validate(file)            # Validation after
                         # → Orphan file if validation fails
```

**Good Flow:**
```python
validate(file)           # Validation first
save_to_filesystem(file) # Side effect after
                        # → Clean failure if invalid
```

**Rule:** All validation before any state changes.

### 9. Debugging Strategy

#### Lesson: Log URLs When Debugging APIs
**Context:** Double prefix error in Gemini deletion.

**Pattern:**
```python
log.info(f"Calling URL: {url}")  # Always log constructed URLs
response = requests.delete(url)
log.info(f"Response: {response.status_code}")
```

**Helps catch:** URL construction bugs, path issues, double prefixes.

#### Lesson: Structured Logging for Transactions
**Pattern:**
```python
log.info(f"Step 1/3: Uploading to Gemini")
try:
    result = upload()
    log.info(f"✓ Step 1/3: Success")
except:
    log.error(f"✗ Step 1/3: Failed - {error}")
```

**Benefits:**
- Easy to trace which step failed
- Clear success/failure status
- Helps debugging rollback issues

### 10. Environment Variables

#### Lesson: Document All Required Env Vars
**Location:** Create `.env.example`:

```bash
# Required
GEMINI_API_KEY=your-key-here
SUPABASE_URL=https://project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-key-here

# Optional (with defaults)
TOP_K=5
MODEL1=gemini-2.5-flash
```

**Include:** Which are required, which have defaults, example values.

---

## Common Mistakes to Avoid

### ❌ Don't: Hardcode Ports
```python
EXPOSE 8080  # ❌ If deploying to platforms with dynamic ports
```
✅ **Instead:** Use `${PORT}` environment variable.

### ❌ Don't: Auto-Create Resources on Read
```python
store = get_or_create_store(user_id)  # ❌ Creates empty stores
```
✅ **Instead:** Separate `find()` and `create()` methods.

### ❌ Don't: Commit .env Files
✅ **Instead:** Add to `.gitignore`, use `.env.example` for templates.

### ❌ Don't: Ignore Browser Caching When Testing UI
✅ **Instead:** Always test in incognito mode first.

### ❌ Don't: Use Raw Filenames in Paths
```python
file_path = f"uploads/{filename}"  # ❌ Unicode breaks this
```
✅ **Instead:** Sanitize first: `safe_filename = sanitize(filename)`.

### ❌ Don't: Assume Dict Works for Pydantic Models
```python
Model.update(id, {'key': 'value'})  # ❌ Might need ModelForm
```
✅ **Instead:** Check function signature, use proper types.

### ❌ Don't: Validate After Side Effects
```python
save_file(); validate();  # ❌ Orphan file if invalid
```
✅ **Instead:** Validate first: `validate(); save_file();`.

### ❌ Don't: Fail Deletes on Missing Records
```python
if not exists_in_db(id):
    raise Exception("Not found")  # ❌ Too strict
```
✅ **Instead:** Log warning, continue: `log.warning("Not found"); continue`.

### ❌ Don't: Use Generic Error Messages
```python
raise Exception("Invalid file")  # ❌ Not actionable
```
✅ **Instead:** Be specific: "Excel files not supported. Use PDF, TXT, or DOCX."

### ❌ Don't: Skip Rollback Planning
✅ **Instead:** For each transaction step, plan the rollback before implementing.

---

## Quick Reference

### File Locations
```
backend/
├── open_webui/
│   ├── config.py                          # Environment variables
│   ├── main.py                            # Startup validation
│   ├── routers/
│   │   └── documents.py                   # Document upload/delete
│   ├── services/
│   │   ├── gemini_service.py              # Gemini integration
│   │   └── supabase_service.py            # Supabase integration
│   ├── models/
│   │   └── files.py                       # File model
│   └── internal/
│       └── migrations/
│           └── 999_add_user_email_to_files.py

frontend/
└── src/
    ├── routes/
    │   └── +layout.svelte                 # Branding
    └── lib/
        └── components/
            ├── channel/
            │   └── Channel.svelte         # Branding
            └── layout/
                └── Sidebar/
                    ├── DocumentsModal.svelte  # Document UI
                    └── UserMenu.svelte    # Admin checks
```

### Environment Variables
```bash
# Gemini
GEMINI_API_KEY=
TOP_K=5
MODEL1=gemini-2.5-flash
MODEL2=gemini-2.5-flash-lite
MODEL3=gemini-2.0-flash

# Supabase
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=

# App
WEBUI_NAME=Hippo
WEBUI_SECRET_KEY=
```

### Docker Commands
```bash
# Clean rebuild
docker system prune -a -f
docker-compose up --build --no-cache

# Regular rebuild
docker-compose up --build -d

# View logs
docker-compose logs -f

# Restart only
docker-compose restart
```

### Testing Checklist
- [ ] Upload PDF → Verify in all 3 systems
- [ ] Upload with Unicode filename → Verify sanitization
- [ ] Try Excel upload → Verify rejection
- [ ] Delete document → Verify removed from all 3
- [ ] Test in incognito mode → Verify UI changes
- [ ] Check startup logs → Verify Supabase connection

---


**Last Updated:** December 22, 2024  
**Status:** Production Ready with Persistent Storage (R2 + Supabase)  
**Next Session:** Load this file to catch up on context immediately.

---

## Phase 9: Supabase-Only Metadata Storage Migration

### Goal
Migrate document metadata from local SQLite database to Supabase as the sole source of truth, eliminating local DB dependency for documents.

### Problem Context
- Documents were stored in 3 places: Local DB → Gemini → Supabase
- Local DB was causing issues with Docker container restarts (data loss)
- Need persistence across deployments

### Implementation Strategy

#### **Upload Flow Change**
**Before:** Gemini → Supabase → Local DB  
**After:** Gemini → Supabase (Local DB removed entirely)

#### **List Documents**
**Before:** Query Local DB (`Files.get_files_by_user_id`)  
**After:** Query Supabase (`supabase_service.list_user_documents`)

#### **Delete Flow**
**Before:** Supabase → Gemini → Local DB  
**After:** Supabase (fetch metadata) → Supabase (delete) → Gemini (delete + rollback) → Filesystem (lenient)

### Changes Made

#### 1. Supabase Service Enhancements
**File:** `backend/open_webui/services/supabase_service.py`

**Key Updates:**
```python
def insert_document_metadata(self, doc_data: dict):
    # Extract gemini_file_id and gemini_store_id to COLUMNS (not meta JSON)
    gemini_file_id = meta.get('gemini_file_id')
    gemini_store_id = meta.get('gemini_store_id')
    
    # Clean meta - remove Gemini IDs (now in columns)
    clean_meta = {k: v for k, v in meta.items() 
                 if k not in ['gemini_file_id', 'gemini_store_id']}
    
    supabase_data = {
        'gemini_file_id': gemini_file_id,  # Separate column
        'gemini_store_id': gemini_store_id,  # Separate column
        'meta': clean_meta  # Cleaned JSON
    }
```

**New Methods Added:**
- `list_user_documents(user_id)` - Returns all docs for user, ordered by created_at DESC
- `get_document_by_id(document_id)` - Fetches single document metadata

**Why Separate Columns?**
- Direct access to Gemini IDs without JSON parsing
- Nullable columns allow NULL when Gemini upload fails
- Faster queries, better indexing

#### 2. Upload Flow (`documents.py`)
**File:** `backend/open_webui/routers/documents.py`

**New 2-Step Flow:**
```python
# Step 1: Upload to Gemini
gemini_result = gemini_service.upload_file_to_gemini(...)

# Step 2: Save to Supabase (ONLY metadata storage)
supabase_service.insert_document_metadata({
    'id': file_id,
    'user_id': user.id,
    'gemini_file_id': gemini_file_id,  # From Step 1
    'gemini_store_id': gemini_store_id,  # From Step 1
    'meta': {...}  # WITHOUT Gemini IDs
})

# Local DB step REMOVED completely
```

**Rollback Logic:**
```python
# If Supabase fails:
try:
    supabase_service.insert_document_metadata(...)
except:
    # Delete from Gemini (rollback)
    gemini_service.delete_document_from_gemini(...)
    # Delete from filesystem (rollback)
    Storage.delete_file(file_path)
    raise
```

#### 3. List Documents Endpoint
**Before:**
```python
all_files = Files.get_files_by_user_id(user.id)
documents = [f for f in all_files if f.meta.get('source') == 'documents']
```

**After:**
```python
documents_data = supabase_service.list_user_documents(user.id)
# Transform to match frontend expectations
documents = [{
    "id": doc['id'],
    "filename": meta.get("name", doc['filename']),
    "size": meta.get("size", 0),
    ...
}]
```

#### 4. Delete Flow
**Before:** Fetch from Local DB, delete from all 3 systems

**After:**
```python
# Step 1: Fetch from Supabase (source of truth)
document = supabase_service.get_document_by_id(document_id)
gemini_file_id = document.get('gemini_file_id')  # From column!
gemini_store_id = document.get('gemini_store_id')  # From column!

# Step 2: Delete from Supabase
supabase_service.delete_document_metadata(document_id)

# Step 3: Delete from Gemini (with Supabase rollback)
try:
    gemini_service.delete_document_from_gemini(...)
except:
    # ROLLBACK: Restore to Supabase
    supabase_service.insert_document_metadata(document_backup)
    raise

# Step 4: Delete from filesystem (lenient)
try:
    Storage.delete_file(file_path)
except:
    log.warning("File cleanup failed, continuing...")  # No error to user
```

### Important Decisions & Follow-up Questions

**Q: Keep local `file` table?**  
**A:** YES - Other features (knowledge base, RAG) still use it. Only documents moved to Supabase.

**Q: Make gemini_file_id and gemini_store_id nullable in Supabase?**  
**A:** YES - Upload might fail at Gemini step. NULL allowed, metadata still saved.

**Q: Rollback guardrails?**  
**A:** 
- Gemini failure → Delete from filesystem
- Supabase failure → Delete from Gemini + filesystem
- Filesystem deletion lenient (log warning, don't fail)

**Q: Migration to clean old records?**  
**A:** Created `1000_cleanup_document_metadata.py` but user decided NOT to run it (preserve historical data). Migration file deleted. Old records harmless - just orphaned data ignored by new code.

### Supabase Schema

**Table:** `doc_metadata`

```sql
CREATE TABLE doc_metadata (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    user_email TEXT,
    filename TEXT NOT NULL,
    path TEXT,
    gemini_file_id TEXT,  -- NULLABLE, separate column
    gemini_store_id TEXT,  -- NULLABLE, separate column
    meta JSONB,  -- No longer contains Gemini IDs
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Testing Results
- ✅ Upload: Document saved to Gemini + Supabase
- ✅ List: Fetches from Supabase correctly
- ✅ Delete: Removes from Supabase → Gemini → Filesystem
- ✅ Rollback: Gemini failure properly cleans up filesystem

### Common Mistakes to Avoid
1. ❌ Don't query Local DB for documents - use `supabase_service.list_user_documents()`
2. ❌ Don't try to get Gemini IDs from `meta` JSON - use columns `gemini_file_id`, `gemini_store_id`
3. ❌ Don't insert documents to Local DB - flow is Gemini → Supabase only
4. ❌ Don't forget to extract Gemini IDs to columns when inserting to Supabase

---

## Phase 10: Cloudflare R2 Storage Integration

### Goal
Migrate document file storage from local filesystem to Cloudflare R2 for persistence across Docker deployments.

### Problem Context
- Local filesystem storage lost on Docker container restart
- Need persistent file storage like metadata (Supabase)
- Cloudflare R2 is S3-compatible, cost-effective

### Implementation Strategy

#### **Storage Architecture**
**Before:** Local Filesystem → Gemini → Supabase (metadata)  
**After:** **Cloudflare R2** → Gemini → Supabase (metadata)

**Why R2?**
- S3-compatible (can reuse boto3 infrastructure)
- Persistent across deployments
- Free egress bandwidth
- Low cost

#### **Scope Decision**
**Q: R2 for all files or just documents?**  
**A:** Documents only initially. Knowledge base/RAG files stay local (can expand later with 1-line code change).

### Configuration

#### R2 Credentials
**File:** `.env`
```bash
R2_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=xxxxxxxx
R2_SECRET_ACCESS_KEY=xxxxxxxx
R2_BUCKET=openwebui-docs
R2_REGION=auto
```

#### Config Variables
**File:** `backend/open_webui/config.py`
```python
R2_ENDPOINT = os.environ.get("R2_ENDPOINT", None)
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", None)
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", None)
R2_BUCKET = os.environ.get("R2_BUCKET", None)
R2_REGION = os.environ.get("R2_REGION", "auto")
```

### Changes Made

#### 1. R2StorageProvider Class
**File:** `backend/open_webui/storage/provider.py`

```python
class R2StorageProvider(StorageProvider):
    """Cloudflare R2 Storage (S3-compatible)"""
    
    def __init__(self):
        # Validate credentials
        if not all([R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET]):
            raise RuntimeError("R2 storage requires all credentials")
        
        # Initialize boto3 S3 client
        self.s3_client = boto3.client(
            "s3",
            region_name=R2_REGION,
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        )
        self.bucket_name = R2_BUCKET
    
    def upload_file(self, file, filename, tags):
        """Upload directly to R2"""
        contents = file.read()
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=filename,  # Storage-agnostic path
            Body=contents,
        )
        return contents, filename  # Return path
    
    def delete_file(self, file_path):
        """Delete from R2"""
        self.s3_client.delete_object(
            Bucket=self.bucket_name,
            Key=file_path
        )
    
    def get_file(self, file_path):
        """Download from R2 to temp (for serving)"""
        local_path = f"{UPLOAD_DIR}/{file_path.split('/')[-1]}"
        self.s3_client.download_file(self.bucket_name, file_path, local_path)
        return local_path
```

**Why S3-compatible?**
- R2 implements S3 API
- Reuse existing boto3 code
- Easy to switch providers later

#### 2. Upload Flow with R2
**File:** `backend/open_webui/routers/documents.py`

**New 3-Step Flow:**
```python
# Import
from open_webui.storage.provider import R2StorageProvider
from open_webui.config import UPLOAD_DIR

# Initialize R2 for documents
r2_storage = R2StorageProvider()

# Upload Flow
@router.post("/")
async def upload_document(file: UploadFile, user):
    file_path = f"documents/{user.id}/{file_id}_{filename}"
    
    # Check R2 availability
    if not r2_storage:
        raise HTTPException(503, "Storage unavailable")
    
    # File size validation (5GB R2 limit)
    MAX_R2_FILE_SIZE = 5 * 1024 * 1024 * 1024  # 5GB
    if file_size > MAX_R2_FILE_SIZE:
        raise HTTPException(413, "File exceeds 5GB storage limit")
    
    # Step 1: Upload to R2
    try:
        r2_file_contents, r2_path = r2_storage.upload_file(
            file.file, file_path, tags
        )
        log.info(f"✓ Step 1/3: Uploaded to R2")
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {e}")
    
    # Step 2: Upload to Gemini (using R2 contents)
    try:
        # Save to temp for Gemini
        temp_path = Path(UPLOAD_DIR) / storage_filename
        temp_path.write_bytes(r2_file_contents)
        
        gemini_result = gemini_service.upload_file_to_gemini(
            file_path=str(temp_path), ...
        )
        
        # Cleanup temp
        temp_path.unlink()
        
        log.info(f"✓ Step 2/3: Uploaded to Gemini")
    except Exception as e:
        # ROLLBACK: Delete from R2
        r2_storage.delete_file(file_path)
        raise HTTPException(500, f"Gemini upload failed: {e}")
    
    # Step 3: Save to Supabase
    try:
        supabase_service.insert_document_metadata(...)
        log.info(f"✓ Step 3/3: Saved to Supabase")
    except Exception as e:
        # ROLLBACK: Delete from Gemini
        gemini_service.delete_document_from_gemini(...)
        # ROLLBACK: Delete from R2
        r2_storage.delete_file(file_path)
        raise HTTPException(500, f"Metadata save failed: {e}")
```

**Complete Rollback Chain:**
```
R2 → Gemini → Supabase
 ↑      ↑         ↑
 └──────┴─────────┴── Any failure deletes from all previous steps
```

#### 3. Delete Flow with R2
**File:** `backend/open_webui/routers/documents.py`

```python
# Step 1: Fetch from Supabase
document = supabase_service.get_document_by_id(document_id)
file_path = document.get('path')

# Step 2: Delete from Supabase
supabase_service.delete_document_metadata(document_id)

# Step 3: Delete from Gemini (with rollback)
try:
    gemini_service.delete_document_from_gemini(...)
except:
    # Rollback: Restore to Supabase
    supabase_service.insert_document_metadata(document_backup)
    raise

# Step 4: Delete from R2 (LENIENT - per user request)
try:
    r2_storage.delete_file(file_path)
    log.info("Deleted from R2")
except Exception as e:
    log.warning(f"R2 delete failed, continuing: {e}")
    # Don't raise - user still sees success
    # File orphaned in R2 but removed from Supabase/Gemini
```

**Why Lenient R2 Delete?**
- User request: Don't fail delete if R2 has issues
- Document already removed from Supabase/Gemini (primary sources)
- Orphaned R2 files can be cleaned up later

### Important Decisions & Follow-up Questions

**Q: Duplicate filenames?**  
**A:** Already handled! File path includes UUID:
```python
storage_filename = f"{uuid.uuid4()}_{filename}"
# Example: "abc-123_report.pdf"
```

**Q: File serving/downloads?**  
**A:** Not needed for documents currently. If needed later, use `r2_storage.get_file()` which downloads from R2 to temp.

**Q: Path format in Supabase?**  
**A:** Storage-agnostic: `documents/user123/uuid_filename.pdf`  
This IS the R2 key directly. No special mapping needed.

**Q: Fetched files downloaded on every login?**  
**A:** NO! Downloads are **on-demand only**:
```python
file_path = r2_storage.get_file(doc.path)  # ONLY when file accessed
```
For documents, this never happens (no download feature yet).

**Q: If we expand R2 to all files later?**  
**A:** One-line change:
```python
# storage/provider.py line 376
Storage = R2StorageProvider()  # Instead of LocalStorageProvider()
```
No R2 server changes needed.

**Q: Max file size?**  
**A:** 
- 100MB limit (existing validation)
- 5GB R2 limit (new validation with error toast)
- Both enforced, user sees friendly message

**Q: R2 unavailable on startup?**  
**A:** Log error but continue. First upload will fail with 503 error toast.

### File Flow Summary

**Upload:**
```
User → FastAPI → R2 (save file)
              → Gemini (upload file from R2 contents)
              → Supabase (save metadata)
```

**List:**
```
User → FastAPI → Supabase (query metadata)
              → Frontend (display list)
```

**Delete:**
```
User → FastAPI → Supabase (fetch metadata + delete)
              → Gemini (delete file)
              → R2 (delete file, lenient)
```

### Debugging Tips

**R2 upload fails with "UPLOAD_DIR not defined":**
```python
# Solution: Add import
from open_webui.config import UPLOAD_DIR
```

**R2 initialization fails:**
```python
# Check credentials in .env
R2_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=openwebui-docs
```

**File not found in R2:**
- Check file_path matches R2 key format
- Verify path stored in Supabase is correct
- Ensure R2 bucket name matches config

### Testing Results
- ✅ Upload: File stored in R2, metadata in Supabase
- ✅ Rollback: R2 deleted if Gemini fails
- ✅ Delete: File removed from R2 (lenient)
- ✅ 5GB validation: Shows error toast
- ⏳ Pending: Test R2 unavailable scenario

### Current Architecture

```
┌─────────────────────────────────────────────────┐
│            Document Upload Flow                  │
├─────────────────────────────────────────────────┤
│                                                  │
│  1. User uploads file                            │
│     ↓                                            │
│  2. Save to Cloudflare R2 (persistent)          │
│     ↓                                            │
│  3. Upload to Gemini (from R2 contents)         │
│     ↓                                            │
│  4. Save metadata to Supabase (persistent)      │
│                                                  │
│  Rollback: Any failure → delete from all prior  │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│            Data Storage Locations                │
├─────────────────────────────────────────────────┤
│                                                  │
│  📄 Files: Cloudflare R2 (S3-compatible)        │
│  🔍 RAG: Gemini File Storage                    │
│  📊 Metadata: Supabase PostgreSQL               │
│  🚫 Local DB: NOT used for documents            │
│                                                  │
└─────────────────────────────────────────────────┘
```

### Common Mistakes to Avoid
1. ❌ Don't use `Storage.upload_file()` for documents - use `r2_storage.upload_file()`
2. ❌ Don't forget UPLOAD_DIR import when using temp files
3. ❌ Don't fail delete if R2 delete fails - it's lenient
4. ❌ Don't query Local DB for document files - they're in R2
5. ❌ Don't forget to cleanup temp files after Gemini upload

### Next Steps to Consider
- [ ] Monitor R2 storage usage
- [ ] Implement R2 orphan file cleanup
- [ ] Expand R2 to all files (knowledge base, RAG)
- [ ] Add R2 signed URLs for direct downloads
- [ ] Implement multipart upload for >5GB files

---

**Docker Rebuild Required After Changes:**
```bash
# Full rebuild
docker-compose up --build -d

# Restart only (if backend code changed)
docker-compose restart
```

**Environment Variables Checklist:**
```bash
# Supabase
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...

# Cloudflare R2
R2_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=openwebui-docs
R2_REGION=auto

# Gemini
GEMINI_API_KEY=...
```



---

## Phase 9: Composio Integration - Attio and Notion Sync

### Goal
Integrate Composio SDK for OAuth-based connections to Attio and Notion, fetching data from these platforms and syncing to Gemini File Storage for RAG context.

### Architecture Overview

#### User ID Standardization
**Decision:** All Composio connections use OpenWebUI `user.id` directly, no separate `integration_user_id` columns.

**Rationale:**
- Simpler database schema
- One user identifier across all systems
- Eliminates sync complexity
- Easier to debug and maintain

#### Data Flow
```
User → OAuth Flow → Composio Connection (user.id)
  ↓                           ↓
Composio API            Connection Metadata
  ↓                           ↓
Fetch Data (Attio/Notion)   Supabase (sync_status)
  ↓                           ↓
Create Context File      Update Status
  ↓                           ↓
Upload to Gemini        Save Metadata
  ↓                           ↓
RAG Enabled             Complete
```

### Composio Service
**File:** `backend/open_webui/services/composio_service.py`

**Purpose:** Wrapper around Composio SDK for OAuth and data operations

**Key Methods:**
```python
class ComposioService:
    def initiate_connection(user_id, auth_config_id) -> dict:
        # Returns: {redirect_url, connection_id, status}
    
    def check_connection_status(user_id, auth_config_id) -> dict:
        # Returns: {connected, connection_id, status}
```

**Auth Configs:**
- `ATTIO_AUTH_CONFIG_ID` - Attio OAuth configuration
- `NOTION_AUTH_CONFIG_ID` - Notion OAuth configuration

### Integration Endpoints
**File:** `backend/open_webui/routers/connections.py`

#### Connection Status
```python
GET /api/connections/status
# Returns status for all integrations (Attio, Notion)
# Uses user.id directly - no database lookup
```

#### Attio Endpoints
```python
POST /api/connections/attio/initiate
# Initiates OAuth, returns InitiateConnectionResponse
# {redirect_url, connection_id, status}

GET /api/connections/attio/check  
# Polls connection status during OAuth
# Returns CheckConnectionResponse

POST /api/connections/attio/trigger-sync
# Manually triggers sync after OAuth
# Adds background task for attio_sync_service

GET /api/connections/attio/sync-status
# Returns {status, last_sync, notes_count}
```

#### Notion Endpoints
```python  
POST /api/connections/notion/initiate
GET /api/connections/notion/check
POST /api/connections/notion/trigger-sync  
GET /api/connections/notion/sync-status
# Same pattern as Attio
```

### Attio Sync Service
**File:** `backend/open_webui/services/attio_sync_service.py`

**Composio Tool Calls:**
```python
# 1. List Records
ATTIO_LIST_RECORDS(
    object_type="people" | "companies" | "deals",
    limit=50,
    offset=0
)
# Returns: {data: {data: [{id, values}]}}

# 2. List Notes per Record  
ATTIO_LIST_NOTES(
    parent_object="people",
    parent_record_id="uuid",
    limit=200
)
# Returns: {data: {data: [{title, content_plaintext}]}}
```

**Data Structure:**
```python
# Fetched Format
{
    "object_type": "people",
    "record_id": "...",
    "record_name": "John Doe",
    "notes": [
        {"title": "...", "content_plaintext": "..."}
    ]
}

# Context File Format (.txt)
=== [People] John Doe ===

Note: Meeting Notes
Discussed project timeline...

---

=== [Companies] Acme Corp ===
...
```

**Retry Logic:**
- **Trigger:** Error code 1803 or "No connected account"
- **Delays:** 10s, 20s, 30s (3 retries)
- **Total Grace Period:** 63 seconds for connection propagation

### Notion Sync Service  
**File:** `backend/open_webui/services/notion_sync_service.py`

**Composio Tool Calls:**
```python
# 1. Fetch Pages
NOTION_FETCH_DATA(
    get_databases=False,
    get_pages=True,
    page_size=100
)
# Returns: {
#   data: {
#     values: [{id, title}],
#     results: [{id, archived, in_trash}]
#   }
# }

# 2. Fetch Page Content
NOTION_FETCH_ALL_BLOCK_CONTENTS(
    block_id="page_id",
    recursive=True
)
# Returns: {data: {results: [blocks]}}
```

**Data Structure:**
```python
# Fetched Format
{
    "page_id": "...",
    "title": "Project Roadmap",
    "content": "# Page Title: Project Roadmap\n\n..."
}

# Context File Format (.txt)
# Page Title: Project Roadmap

## Q1 Goals
- Launch MVP
- Acquire 100 users

---

# Page Title: Team Notes
...
```

**Rate Limit Handling:**

**Problem:** Notion API has 3 requests/second limit

**Solution 1 - Proactive:**
- 0.5 second delays between API calls
- Effective rate: 2 req/sec (safe buffer)

**Solution 2 - Reactive (Exponential Backoff):**
```python
@handle_rate_limit  # Decorator
def _fetch_page_content(...):
    # Auto-retries on 429 errors
    # Delays: 1s, 2s, 4s, 8s, 16s (5 retries)
```

**Error Detection:**
- HTTP 429
- "rate limit" in error message
- "too many requests" in error message

### Storage and Metadata

#### Supabase Tables

**1. `users` table columns:**
```sql
-- Sync Status Columns
attio_sync_status TEXT         -- 'in_progress' | 'success' | 'failed'
attio_last_sync TIMESTAMP
notion_sync_status TEXT  
notion_last_sync TIMESTAMP

-- Note: NO integration_user_id columns!
-- All connections use user_id directly
```

**2. `doc_metadata` table:**
```sql
id UUID PRIMARY KEY
user_id UUID
user_email TEXT
filename TEXT
source TEXT                    -- 'attio' | 'notion' | 'manual'
gemini_file_id TEXT           -- Gemini file ID
gemini_store_id TEXT          -- Gemini store ID  
connection_id TEXT            -- Composio connection ID
meta JSONB                     -- {count: number_of_notes/pages}
created_at TIMESTAMP
updated_at TIMESTAMP
```

#### Gemini File Storage

**Store Creation:**
```python
gemini_service.get_or_create_file_search_store(user_id)
# Creates: "{user_id}_file_search_store"
# Shared across manual docs, Attio, and Notion
# Auto-finds existing or creates new
```

**File Upload:**
```python
gemini_service.upload_file_to_gemini(
    file_path="/tmp/attio_context.txt",
    filename="attio_context.txt",
    user_id=user_id,
    document_id=uuid.uuid4()
)
# Returns: (gemini_file_id, gemini_store_id)
```

### Major Bugs Found and Solutions

#### Bug 1: Notion OAuth 404 Error
**Problem:** OAuth popup showed 404 instead of Composio authentication page

**Root Cause:**
```python
# Bad - extracting redirect_url as string
redirect_url = composio_service.initiate_connection(user_id, config_id)
return {"redirect_url": redirect_url}  # Wrong type
```

**Solution:**
```python
# Good - return full response object
connection_data = composio_service.initiate_connection(user_id, config_id)
return InitiateConnectionResponse(**connection_data)
# {redirect_url, connection_id, status}
```

#### Bug 2: Retry Logic Not Working
**Problem:** Notion sync failed immediately with error 1803, no retries attempted

**Root Cause:**
```python
# Original exception loses error code
if "1803" in str(e):
    raise Exception(f"Connection expired")  # Lost 1803!

# Retry logic can't detect it
if "1803" in error_str:  # Never matches
    retry()
```

**Solution:**
```python
# Preserve error code
raise Exception(f"[1803] Connection expired")  # Keeps code!
```

#### Bug 3: Gemini Store Method Not Found
**Problem:** `'GeminiService' object has no attribute 'list_user_stores'`

**Root Cause:**
```python
# Attio used Supabase lookup (worked)
existing = supabase.get_connection_context_metadata(user_id, 'manual')

# Notion tried non-existent method
stores = gemini.list_user_stores(user_id)  # Doesn't exist!
```

**Solution:**
```python
# Both now use Gemini's built-in method
gemini_store_id = self.gemini.get_or_create_file_search_store(user_id)
# Handles find + create automatically
```

#### Bug 4: notion_user_id Column Doesn't Exist
**Problem:** `column users.notion_user_id does not exist`

**Root Cause:**
- Code tried to get/store `notion_user_id` from database
- Column was never created (unlike `attio_user_id` which existed)

**Solution:** Eliminated separate user ID columns entirely
```python
# Old - database lookup
notion_user_id = supabase.get_user_integration_id(user.id, 'notion')

# New - use user.id directly
notion_user_id = user.id
```

### Exception Handling Patterns

#### Connection Propagation Errors
**Error Code:** 1803 - "No connected account found"

**Cause:** OAuth completes but connection not yet propagated in Composio

**Handling:**
```python
max_retries = 3
retry_delays = [10, 20, 30]

for attempt in range(max_retries):
    try:
        data = fetch_from_api(user_id)
        break
    except Exception as e:
        if "1803" in str(e) and attempt < max_retries - 1:
            time.sleep(retry_delays[attempt])
            continue
        raise
```

#### Rate Limit Errors
**Error Code:** 429 - "Too Many Requests"

**Handling:**
```python
@handle_rate_limit
def api_call():
    # Exponential backoff: 1s, 2s, 4s, 8s, 16s
    # Detects: 429, "rate limit", "too many requests"
    pass
```

#### General API Errors
**Best Practice:**
- Log full error with context
- Update sync_status to 'failed'
- Cleanup partial uploads
- Return user-friendly message

```python
try:
    sync_data()
except Exception as e:
    log.error(f"Sync failed: {e}", exc_info=True)
    supabase.update_user_sync_status(user_id, source, 'failed')
    if gemini_file_id:
        gemini.delete_file(gemini_file_id)
    return {"status": "failed", "error": str(e)}
```

### Frontend Integration
**File:** `src/lib/components/layout/Sidebar/ConnectionsModal.svelte`

**OAuth Flow:**
1. User clicks "Connect"
2. Call `/initiate` endpoint → get redirect_url
3. Open popup with redirect_url
4. Poll `/check` endpoint every 2s (max 30 times = 60s)
5. When connected, close popup
6. Wait 3 seconds (permissions propagation)
7. Call `/trigger-sync` endpoint
8. Poll `/sync-status` endpoint for progress

**Key Pattern:**
```javascript
// Delay before triggering sync
setTimeout(async () => {
    await triggerNotionSync($user.token);
    pollSyncStatus();
}, 3000);  // 3 second delay
```

### Environment Variables

```bash
# Composio
COMPOSIO_API_KEY=...

# Attio
ATTIO_AUTH_CONFIG_ID=...
ATTIO_RECORDS_LIST_LIMIT=50
ATTIO_RECORDS_NOTES_LIMIT=200

# Notion  
NOTION_AUTH_CONFIG_ID=...
NOTION_LIST_LIMIT=100

# Also requires GEMINI_API_KEY and SUPABASE_* vars
```

### Common Mistakes to Avoid

1. ❌ **Don't use separate integration_user_id** - Use user.id directly
2. ❌ **Don't lose error codes in exceptions** - Preserve [1803] for retry logic
3. ❌ **Don't call non-existent Gemini methods** - Use get_or_create_file_search_store()
4. ❌ **Don't trigger sync immediately** - Wait 3-10s for OAuth propagation
5. ❌ **Don't ignore rate limits** - Add proactive delays + retry logic
6. ❌ **Don't forget retry on 1803** - Connection needs time to propagate
7. ❌ **Don't use UUID for integration IDs** - OpenWebUI user.id is the UUID
8. ❌ **Don't store duplicate data** - One Gemini store per user (shared across sources)

### Testing Checklist

**OAuth Flow:**
- [ ] Popup opens with valid URL (not 404)
- [ ] User can authenticate successfully
- [ ] Popup closes after auth
- [ ] Connection status updates correctly

**Sync Process:**
- [ ] Sync starts after connection
- [ ] Status shows "in_progress"
- [ ] Retries on 1803 errors
- [ ] Handles rate limits gracefully
- [ ] Updates to "success" when complete
- [ ] Shows correct count in UI

**Error Handling:**
- [ ] Graceful failure messages
- [ ] Cleanup on errors
- [ ] Status updates to "failed"
- [ ] Logs include full context

### Performance Considerations

**Rate Limits:**
- Notion: 3 req/sec → Use 0.5s delays (2 req/sec effective)
- Attio: Higher limit → No delays needed

**Large Workspaces:**
- Notion 500+ pages: ~250 seconds (0.5s delay × 500)
- Background processing prevents UI blocking
- Consider pagination for very large sets

**Gemini Upload:**
- Combine all content into single file per source
- More efficient than individual uploads
- Easier to manage and delete

### Next Steps

**Completed:**
✅ User ID standardization
✅ Notion OAuth integration
✅ Retry logic for connection propagation
✅ Rate limit handling
✅ Gemini store management

**Future Enhancements:**
- [ ] Add more integrations (Slack, Google Drive, etc.)
- [ ] Implement incremental sync (delta updates)
- [ ] Add sync scheduling (daily/weekly)
- [ ] Support workspace selection for Notion
- [ ] Add connection health monitoring
- [ ] Implement circuit breaker pattern

### Key Learnings

1. **Composio Connection IDs:** Use user.id directly, not separate UUIDs
2. **OAuth Timing:** Always wait 3-10s before first API call after OAuth
3. **Error Codes Matter:** Preserve error codes like [1803] through exception chain
4. **Rate Limiting:** Proactive (delays) + Reactive (retry) = robust
5. **Gemini Stores:** One store per user, shared across all sources
6. **Testing:** Always test OAuth in incognito to avoid cache issues
7. **Exponential Backoff:** Better than fixed delays for rate limits
8. **Metadata Storage:** Supabase for status/timestamps, Gemini for content

---


## Phase 9: Google Docs Integration

### Goal
Sync Google Docs from a user's account to Gemini File Storage for RAG, managing metadata in Supabase.

### Architecture
1.  **Backend Service:** \GDocsSyncService\ (\services/gdocs_sync_service.py\)
    *   Orchestrates the sync process.
    *   Uses **Composio** SDK to search and fetch documents from Google Docs.
    *   Uses **GeminiService** to upload content to Google's GenAI File Storage.
    *   Uses **SupabaseService** to store metadata and sync status.
2.  **Frontend Interface:** \ConnectionsModal.svelte\
    *   Adds Google Docs to the existing connection list (Attio, Notion).
    *   Handles OAuth initiation via Composio.
    *   Displays sync status and document counts.

### Implementation Details
*   **Composio Integration:**
    *   Tools used: \GOOGLEDOCS_SEARCH_DOCUMENTS\, \GOOGLEDOCS_GET_DOCUMENT_BY_ID\.
    *   Authentication: Uses \GDOCS_AUTH_CONFIG_ID\.
*   **Sync Logic:**
    *   **Pagination:** Fetches all docs using \
ext_page_token\.
    *   **Deduplication:** Tracks seen IDs to avoid duplicates.
    *   **Rate Limiting:** Implements retry logic with exponential backoff for 429 errors.
    *   **Connection Propagation:** Retries on 1803 (\No connected account\) errors to allow time for OAuth propagation.
*   **Metadata Storage:**
    *   Stores \gemini_file_id\, \gemini_store_id\, \source='gdocs'\ in Supabase \doc_metadata\ table.

### Issues Encountered & Fixes

#### Issue 9.1: Svelte 5 Runes Mode Error
**Problem:** Build failed with \Cannot use 'export let' in runes mode\.
**Cause:** \ConnectionsModal.svelte\ was using old Svelte 4 syntax while the project is configured for Svelte 5.
**Solution:**
*   Converted \export let show = false;\ to \$props().show = false\.
*   Ensured compatibility with the new Runes system.

#### Issue 9.2: Backend Authentication Failure
**Problem:** Backend rejected requests with \ValueError: not enough values to unpack\.
**Cause:** Frontend API calls in \connections.ts\ were sending an incomplete Authorization header: \Bearer \ (missing the token).
**Solution:**
*   Updated \connections.ts\ to correctly interpolate the token: \\Authorization: \Bearer \ \\.

#### Issue 9.3: Silent Frontend Failure (Missing Base URL)
**Problem:** \Failed to initiate connection\ error in UI, with NO logs in the backend.
**Cause:** Frontend fetch calls were missing the \${WEBUI_API_BASE_URL}\ prefix.
**Effect:** Requests were hitting the frontend server (browser URL) instead of the backend API, resulting in 404s that looked like silent failures.
**Solution:**
*   Prepended \${WEBUI_API_BASE_URL}\ to all Google Docs fetch URLs in \connections.ts\.

#### Issue 9.4: Missing Configuration Environment Variable
**Problem:** Backend raised \HTTPException\ because \GDOCS_AUTH_CONFIG_ID\ was missing.
**Solution:**
*   Added \GDOCS_AUTH_CONFIG_ID\ to \.env\ and \config.py\.
*   Improved error logging in \outers/connections.py\ to explicitly log when this variable is missing.

#### Issue 9.5: Missing Metadata in Supabase
**Problem:** Rows created in \doc_metadata\ had empty \gemini_file_id\, \gemini_store_id\, and \source\ columns.
**Cause:**
1.  \supabase_service.py\ was looking for IDs inside a nested \meta\ dictionary, but \gdocs_sync_service.py\ was passing them at the top level.
2.  \source\ field was missing from the Supabase insert payload.
**Solution:**
*   Updated \supabase_service.py\ to check both top-level and nested \meta\ for compatibility.
*   Added \source\ field to the insert payload.

#### Issue 9.6: \Invalid Request Data\ for Google Drive Files
**Problem:** Sync failed for some files with \Invalid request data\.
**Cause:** The \GOOGLEDOCS_SEARCH_DOCUMENTS\ tool returns both native Google Docs and other Google Drive files. Drive file IDs start with \1-\ and cannot be fetched as text documents.
**Solution:**
*   Added a check in \gdocs_sync_service.py\ to skip IDs starting with \1-\, creating a \ailsafe\ to continue syncing valid docs.

### Follow-up Questions & Answers

#### Q: How do we ensure manual uploads are labeled correctly?
**Request:** Ensure \Documents\ modal uploads use \source='manual'\.
**Solution:**
1.  Updated \supabase_service.py\ to default \source\ to \'manual'\ if not provided.
2.  Verified that \documents.py\ (manual upload route) explicitly sets \source='manual'\.
3.  Verified that sync services (\gdocs\, \ttio\, \
otion\) explicitly set their respective sources.

### Agent Tool Usage & Response Structure
*   **Tools:** The agent uses tools like \iew_file\, \eplace_file_content\, \un_command\ (for Docker), and \grep_search\.
*   **Pattern:**
    1.  **Validation:** Always verify file content before editing.
    2.  **Atomic Edits:** Make specific, targeted changes rather than rewriting huge files to avoid context loss.
    3.  **Verification:** Use \grep\ or manual review to confirm changes were applied correctly.
    4.  **Feedback Loop:** Use \
otify_user\ to communicate requires actions (like checking \.env\ vars) that the agent cannot do itself.

