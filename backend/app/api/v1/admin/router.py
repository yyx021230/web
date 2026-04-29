"""Admin router - registers all admin endpoints"""
from fastapi import APIRouter

from app.api.v1.admin.stats import router as stats_router
from app.api.v1.admin.users import router as users_router
from app.api.v1.admin.materials import router as materials_router
from app.api.v1.admin.resources import router as resources_router
from app.api.v1.admin.workflows import router as admin_workflows_router
from app.api.v1.admin.prompts import router as admin_prompts_router

router = APIRouter()

router.include_router(stats_router, prefix="/stats", tags=["管理-统计"])
router.include_router(users_router, prefix="/users", tags=["管理-用户"])
router.include_router(materials_router, prefix="/materials", tags=["管理-素材"])
router.include_router(resources_router, prefix="/resources", tags=["管理-资源"])
router.include_router(admin_workflows_router, prefix="/workflows", tags=["管理-工作流"])
router.include_router(admin_prompts_router, prefix="/prompts", tags=["管理-提示词"])
