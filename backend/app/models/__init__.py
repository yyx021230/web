"""导入所有模型，供 Alembic 自动发现"""

from app.models.user import User
from app.models.template import Template
from app.models.material import Material
from app.models.project import Project
from app.models.dify_workflow import DifyWorkflowConfig
from app.models.dify_run_log import DifyRunLog
from app.models.dify_task import DifyTask
from app.models.ai_task import AITask
from app.models.copywriting import Copywriting
from app.models.user_workflow import user_workflow_access
from app.models.prompt import PromptCategory, PromptExample
from app.models.prompt_moderation import PromptReport, PromptAuditLog
