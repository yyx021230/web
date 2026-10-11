"""User-authored drafts share the existing review and publication lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import warnings

from fastapi import HTTPException, UploadFile
from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.storage import get_storage
from app.config import settings
from app.models.hermes_workflow import HermesWorkflowPost, HermesWorkflowRun
from app.models.user import User
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_environment import XHSEnvironment
from app.schemas.hermes_workflow import HermesUploadPostCreate
from app.services.hermes_workflow_service import HermesWorkflowService
from app.utils.timezone import cst_now_naive

MAX_UPLOAD_BYTES = 3_000_000
logger = logging.getLogger(__name__)


def validate_image(data: bytes) -> tuple[str, str]:
    """Trust decoded bytes, not browser MIME or user-provided file extensions."""
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, '每张图片必须非空且不超过3MB')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                kind = image.format
                if kind not in {'PNG', 'JPEG', 'WEBP'} or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError()
                if image.width * image.height > 20_000_000:
                    raise ValueError()
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
    except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(400, '仅支持有效的静态PNG、JPEG、WebP图片，最大2000万像素') from None
    return {'PNG': ('.png', 'image/png'), 'JPEG': ('.jpg', 'image/jpeg'), 'WEBP': ('.webp', 'image/webp')}[kind]


async def create_upload_post(db: AsyncSession, user: User, request: HermesUploadPostCreate,
                             files: list[UploadFile], *, is_admin: bool = False) -> HermesWorkflowPost:
    maximum = min(9, max(1, settings.phone_cloud_publish_max_images))
    if not 1 <= len(files) <= maximum:
        raise HTTPException(400, f'请选择1至{maximum}张图片')
    env = await db.scalar(select(XHSEnvironment).where(
        XHSEnvironment.id == request.environment_id, XHSEnvironment.status == 'active'))
    owner_id = await db.scalar(select(UserXHSEnvironment.user_id).where(
        UserXHSEnvironment.environment_id == request.environment_id))
    if env is None or (not is_admin and owner_id != user.id):
        raise HTTPException(403, '只能为当前授权的账号上传图文')
    owner = await db.get(User, owner_id) if owner_id else None
    if owner is None or not owner.is_active:
        raise HTTPException(409, '请先为账号分配有效负责人')
    if not str(env.xhs_account_id or '').strip():
        raise HTTPException(409, '请先配置账号的小红书ID')
    if (len(request.title.encode('utf-16-le')) // 2 > 100
            or len(request.content.encode('utf-16-le')) // 2 > 2000):
        raise HTTPException(400, '标题或正文超过云手机接口限制，不能自动截断')
    images = []
    for file in files:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        ext, mime = await asyncio.to_thread(validate_image, data)
        images.append((data, ext, mime))
    fingerprint = hashlib.sha256(json.dumps([
        request.environment_id, request.title, request.content,
        [hashlib.sha256(data).hexdigest() for data, _, _ in images],
    ], ensure_ascii=False).encode()).hexdigest()
    key = hashlib.sha256(f'upload:{user.id}:{request.request_id}'.encode()).hexdigest()

    async def existing_post() -> HermesWorkflowPost | None:
        run = await db.scalar(select(HermesWorkflowRun).where(HermesWorkflowRun.run_key == key))
        if run is None:
            return None
        if run.parameters.get('upload_fingerprint') != fingerprint:
            raise HTTPException(409, '该上传标识已用于其他图文，请核查原草稿')
        return await db.scalar(select(HermesWorkflowPost).where(HermesWorkflowPost.run_id == run.id))

    existing = await existing_post()
    if existing is not None:
        return existing
    # Reserve the unique request before saving files. Concurrent/lost-response
    # retries return the same draft, never a second publication candidate.
    run = HermesWorkflowRun(
        run_key=key, source='user_upload', status='review_pending', requested_by=user.id,
        total_posts=1, generated_posts=1, finished_at=cst_now_naive(),
        parameters={'name': request.title, 'upload_fingerprint': fingerprint}, posts=[],
    )
    try:
        # No SAVEPOINT here: SQLite can release it before a physical outer BEGIN.
        # Keep the reservation and completed draft in the same real transaction.
        db.add(run)
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await existing_post()
        if existing is not None:
            return existing
        raise HTTPException(409, '草稿正在保存，请稍后刷新核查') from None
    storage = get_storage()
    urls = []
    try:
        for data, ext, mime in images:
            urls.append(await storage.save(data, f'image{ext}', mime, subdir=f'publish-drafts/{user.id}'))
    except Exception:
        await db.rollback()
        for url in urls:
            try:
                await storage.delete(url)
            except Exception:
                logger.warning('Failed to clean up an incomplete publication upload')
        raise HTTPException(503, '图片保存失败，请稍后以相同内容重试') from None
    post = HermesWorkflowPost(
        run_id=run.id, environment_id=env.id, owner_user_id=owner_id, slot=1,
        account_name=env.account_name, vehicle_model='自主上传', status='review_pending',
        title=request.title, content=request.content, image_url=urls[0], hard_pass=True,
        publish_status='not_requested', source_detail={
            'source_kind': 'user_upload', 'image_urls': urls, 'revision': 1,
            'validation_scope': 'file_integrity_only',
        },
    )
    db.add(post)
    HermesWorkflowService.append_event(post, 'upload', user.id, '上传图文草稿，等待人工确认',
                                      actor_name=user.display_name or user.username)
    await db.commit()
    await db.refresh(post)
    return post
