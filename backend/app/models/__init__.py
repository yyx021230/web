"""导入所有模型，供 Alembic 自动发现"""

from app.models.user import User, UserRole
from app.models.template import Template
from app.models.material import Material
from app.models.project import Project
from app.models.dify_workflow import DifyWorkflowConfig
from app.models.dify_run_log import DifyRunLog
from app.models.dify_task import DifyTask
from app.models.ai_task import AITask
from app.models.job import Job, JobAttempt, JobEvent, JobItem, JobStatus
from app.models.scheduler_lease import SchedulerLease
from app.models.ai_image_provider import AIImageProvider
from app.models.copywriting import Copywriting
from app.models.user_workflow import user_workflow_access
from app.models.prompt import PromptCategory, PromptExample
from app.models.prompt_moderation import PromptReport, PromptAuditLog
from app.models.xhs_environment import XHSEnvironment
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_creator_sync_row import XHSCreatorSyncRow
from app.models.xhs_account_note_browse_event import XHSAccountNoteBrowseEvent
from app.models.xhs_post import XHSPost
from app.models.xhs_schedule_setting import XHSScheduleSetting
from app.models.xhs_schedule_run_log import XHSScheduleRunLog
from app.models.xhs_account_sync_run import XHSAccountSyncRun, XHSAccountSyncRunItem
from app.models.xhs_report_refresh_run import (
    XHSReportRefreshRun as XHSReportRefreshRun,
)
from app.models.user_xhs_env import UserXHSEnvironment
from app.models.xhs_report import (
    XHSAdStatsDailyAccount,
    XHSAdStatsDailyBrand,
    XHSAdStatsDailyBuyer,
    XHSAdStatsDailyContentTag,
    XHSAdStatsDailyNote,
    XHSProfileStatDaily,
    XHSReportDaily,
    XHSReportToken,
)
from app.models.xhs_ad_account_assignment import XHSAdAccountBuyerAssignment, XHSAdAccountProfessionalMapping
from app.models.dashboard_snapshot import DashboardSnapshot
from app.models.vehicle_catalog import VehicleCatalog, VehicleModelImage
from app.models.scrape_review import (
    ScrapeTask,
    ScrapeTaskReviewer,
    ScrapeCandidate,
    ScrapeCandidateReview,
)
