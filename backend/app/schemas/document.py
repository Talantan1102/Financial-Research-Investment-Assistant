# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

from typing import Any

from pydantic import BaseModel


class DeleteDocumentsRequest(BaseModel):
    """请求模型：删除文档"""

    document_ids: list[str]


class RetrieveDocumentsRequest(BaseModel):
    """请求模型：检索文档"""

    question: str
    document_ids: list[str] | None = None


class DocumentResponse(BaseModel):
    """文档基本信息响应模型"""

    id: str
    name: str
    type: str
    size: int
    status: str | None = None
    run: str | None = None
    progress: float | None = None
    chunk_count: int | None = None
    token_count: int | None = None
    create_time: int | None = None
    update_time: int | None = None
    created_by: str | None = None
    index_name: str | None = None
    json_file_path: str | None = None


class ProcessingDetails(BaseModel):
    """文档处理详情"""

    document_count: int
    es_inserted: bool
    json_file_path: str


class UploadDocumentResponse(BaseModel):
    """上传文档响应模型"""

    status: str
    message: str
    document: dict[str, Any] | None = None
    document_id: str | None = None
    upload_response: dict[str, Any] | None = None
    processing_details: ProcessingDetails | None = None


class DocumentListResponse(BaseModel):
    """文档列表响应模型"""

    code: int
    data: dict[str, Any]


class DeleteDocumentsResponse(BaseModel):
    """删除文档响应模型"""

    code: int
    message: str
    data: dict[str, Any]
