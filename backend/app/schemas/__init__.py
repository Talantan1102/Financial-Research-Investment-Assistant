# Document schemas package

from .chat import (
    AttachmentListResponse,
    AttachmentResponse,
    ChatRequest,
    ChatResponse,
    ChatWithAttachmentsRequest,
    LegacySessionResponse,
    MessageCreate,
    MessageResponse,
    RetrievedDocument,
    SessionCreate,
    SessionResponse,
    SessionUpdate,
    SessionWithMessagesResponse,
)
from .document import (
    DeleteDocumentsRequest,
    DeleteDocumentsResponse,
    DocumentListResponse,
    DocumentResponse,
    RetrieveDocumentsRequest,
    UploadDocumentResponse,
)
from .knowledge import (
    DocumentResponse as KBDocumentResponse,
)
from .knowledge import (
    DocumentUploadResponse as KBDocumentUploadResponse,
)
from .knowledge import (
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
    KnowledgeBaseWithDocuments,
)
from .search import SearchResultItem, WebSearchRequest, WebSearchResponse

__all__ = [
    # Document schemas
    "DeleteDocumentsRequest",
    "RetrieveDocumentsRequest",
    "DocumentResponse",
    "UploadDocumentResponse",
    "DocumentListResponse",
    "DeleteDocumentsResponse",
    # Search schemas
    "WebSearchRequest",
    "SearchResultItem",
    "WebSearchResponse",
    # Chat schemas
    "ChatRequest",
    "RetrievedDocument",
    "ChatResponse",
    "SessionCreate",
    "SessionUpdate",
    "SessionResponse",
    "SessionWithMessagesResponse",
    "MessageCreate",
    "MessageResponse",
    "LegacySessionResponse",
    "AttachmentResponse",
    "AttachmentListResponse",
    "ChatWithAttachmentsRequest",
    # Knowledge Base schemas
    "KnowledgeBaseCreate",
    "KnowledgeBaseUpdate",
    "KnowledgeBaseResponse",
    "KnowledgeBaseWithDocuments",
    "KBDocumentResponse",
    "KBDocumentUploadResponse",
]
