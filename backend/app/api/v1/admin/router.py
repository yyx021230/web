"""Admin router - registers all admin endpoints"""
from fastapi import APIRouter

from app.api.v1.admin.stats import router as stats_router
from app.api.v1.admin.users import router as users_router
from app.api.v1.admin.materials import router as materials_router
from app.api.v1.admin.resources import router as resources_router
from app.api.v1.admin.workflows import router as admin_workflows_router
from app.api.v1.admin.prompts import router as admin_prompts_router
from app.api.v1.admin.car_models import router as admin_car_models_router
from app.api.v1.admin.xhs import router as admin_xhs_router
from app.api.v1.admin.ai_image import router as admin_ai_image_router
from app.api.v1.admin.copy_review import router as admin_copy_review_router
from app.api.v1.admin.reliability import router as admin_reliability_router
from app.api.v1.admin.hermes_workflows import router as admin_hermes_workflows_router

router = APIRouter()

router.include_router(stats_router, prefix="/stats", tags=["管理-统计"])
router.include_router(users_router, prefix="/users", tags=["管理-用户"])
router.include_router(materials_router, prefix="/materials", tags=["管理-素材"])
router.include_router(resources_router, prefix="/resources", tags=["管理-资源"])
router.include_router(admin_workflows_router, prefix="/workflows", tags=["管理-工作流"])
router.include_router(admin_hermes_workflows_router, prefix="/hermes-workflows", tags=["管理-Hermes工作流"])
router.include_router(admin_prompts_router, prefix="/prompts", tags=["管理-提示词"])
router.include_router(admin_car_models_router, prefix="/car-models", tags=["管理-车型库"])
router.include_router(admin_xhs_router, tags=["管理-小红书"])
router.include_router(admin_ai_image_router, prefix="/ai-image", tags=["管理-AI生图"])
router.include_router(admin_copy_review_router, tags=["管理-抓取审核"])
router.include_router(
    admin_reliability_router,
    prefix="/reliability",
    tags=["管理-任务可靠性"],
)
