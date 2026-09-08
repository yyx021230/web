from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.templates import router as templates_router
from app.api.v1.materials import router as materials_router
from app.api.v1.projects import router as projects_router
from app.api.v1.ai_image import router as ai_image_router
from app.api.v1.workflows import router as workflows_router
from app.api.v1.car_models import router as car_models_router
from app.api.v1.copywritings import router as copywritings_router
from app.api.v1.prompts import router as prompts_router
from app.api.v1.xhs import router as xhs_router
from app.api.v1.hermes_workflows import router as hermes_workflows_router
from app.api.v1.admin.router import router as admin_router

router = APIRouter()

router.include_router(auth_router, prefix="/auth", tags=["认证"])
router.include_router(templates_router, prefix="/templates", tags=["模板"])
router.include_router(materials_router, prefix="/materials", tags=["素材"])
router.include_router(projects_router, prefix="/projects", tags=["项目"])
router.include_router(ai_image_router, prefix="/ai-image", tags=["AI 生图"])
router.include_router(workflows_router, prefix="/workflows", tags=["Dify 工作流"])
router.include_router(hermes_workflows_router, prefix="/hermes-workflows", tags=["Hermes 内容工作流"])
router.include_router(car_models_router, prefix="/car-models", tags=["车型库"])
router.include_router(copywritings_router, prefix="/copywritings", tags=["文案库"])
router.include_router(prompts_router, prefix="/prompts", tags=["提示词"])
router.include_router(xhs_router, tags=["小红书发布"])
router.include_router(admin_router, prefix="/admin", tags=["管理后台"])
