from pydantic import BaseModel, Field
from typing import Optional


class DifyWorkflowCreate(BaseModel):
    api_key: str = Field(..., min_length=10, description="Dify API Key")
    base_url: Optional[str] = Field(None, description="Dify 实例地址（默认 http://8.163.58.214/v1）")
    app_name: str = Field(..., description="工作流名称")
    app_type: str = Field(..., description="应用类型: workflow/chat/completion")
    description: Optional[str] = Field(None, description="描述")
    inputs_schema: Optional[dict] = Field(None, description="输入字段定义（可选，不传则自动从 Dify 获取）")


class DifyWorkflowUpdate(BaseModel):
    api_key: Optional[str] = Field(None, min_length=10, description="Dify API Key")
    app_name: Optional[str] = None
    app_type: Optional[str] = None
    description: Optional[str] = None
    inputs_schema: Optional[dict] = None
    base_url: Optional[str] = None
    is_enabled: Optional[bool] = None


class WorkflowRunRequest(BaseModel):
    inputs: dict = Field(..., description="工作流输入参数")
    response_mode: str = Field(default="blocking", description="响应模式: blocking/streaming")


class WorkflowRunResponse(BaseModel):
    task_id: str
    status: str
    outputs: Optional[dict] = None
    error: Optional[str] = None


class WorkflowLogResponse(BaseModel):
    id: int
    workflow_id: int
    status: str
    inputs: dict
    outputs: dict
    error: Optional[str]
    started_at: str
    finished_at: Optional[str]
    elapsed_ms: Optional[float]

    model_config = {"from_attributes": True}
