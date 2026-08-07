from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func

from app.db.base import Base


class ScrapeTask(Base):
    __tablename__ = "scrape_tasks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    source = Column(String(50), nullable=False, default="keyword", index=True)
    status = Column(String(20), nullable=False, default="draft", index=True)
    reviewer_mode = Column(String(20), nullable=False, default="shared_pool")
    source_config = Column(JSON, default={})
    max_items = Column(Integer, nullable=False, default=50)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    last_error = Column(Text)
    saved_path = Column(String(500))
    run_meta = Column(JSON, default={})

    candidate_count = Column(Integer, nullable=False, default=0)
    pending_count = Column(Integer, nullable=False, default=0)
    approved_count = Column(Integer, nullable=False, default=0)
    rejected_count = Column(Integer, nullable=False, default=0)
    needs_second_review_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ScrapeTaskReviewer(Base):
    __tablename__ = "scrape_task_reviewers"
    __table_args__ = (
        UniqueConstraint("task_id", "user_id", name="uq_scrape_task_reviewer"),
    )

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("scrape_tasks.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())


class ScrapeCandidate(Base):
    __tablename__ = "scrape_candidates"
    __table_args__ = (
        UniqueConstraint("task_id", "external_id", name="uq_scrape_candidate_task_external"),
    )

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("scrape_tasks.id"), nullable=False, index=True)
    external_id = Column(String(120), nullable=False)
    source = Column(String(50), nullable=False, default="keyword", index=True)
    source_keyword = Column(String(255))
    post_url = Column(String(500))

    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    author = Column(String(255))
    publish_date = Column(Date, index=True)
    copy_type = Column(String(50), index=True)
    brand = Column(String(100), index=True)

    likes = Column(Integer, nullable=False, default=0)
    comments = Column(Integer, nullable=False, default=0)
    collects = Column(Integer, nullable=False, default=0)
    shares = Column(Integer, nullable=False, default=0)
    views = Column(Integer, nullable=False, default=0)

    review_status = Column(String(20), nullable=False, default="pending", index=True)
    reviewer_id = Column(Integer, ForeignKey("users.id"), index=True)
    review_note = Column(Text)
    reviewed_at = Column(DateTime)
    copywriting_id = Column(Integer, ForeignKey("copywritings.id"), index=True)

    raw_payload = Column(JSON, default={})
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ScrapeCandidateReview(Base):
    __tablename__ = "scrape_candidate_reviews"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("scrape_tasks.id"), nullable=False, index=True)
    candidate_id = Column(Integer, ForeignKey("scrape_candidates.id"), nullable=False, index=True)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(20), nullable=False, index=True)
    note = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
