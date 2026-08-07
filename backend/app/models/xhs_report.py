from sqlalchemy import Column, Float, Integer, String, DateTime, func, Date, JSON, UniqueConstraint, Index
from app.db.base import Base


class XHSReportToken(Base):
    __tablename__ = "xhs_report_tokens"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(String(64), unique=True, nullable=False, index=True, comment="广告账户ID")
    account_name = Column(String(255), nullable=False, index=True, comment="账号名称")
    token = Column(String(1024), nullable=True, comment="Access-Token")
    token_status = Column(String(32), nullable=True, comment="成功/失败")
    token_message = Column(String(1024), nullable=True, comment="token接口返回信息")
    token_timestamp = Column(String(64), nullable=True, comment="token接口时间戳")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())


class XHSReportDaily(Base):
    __tablename__ = "xhs_report_daily"

    id = Column(Integer, primary_key=True, index=True)
    report_type = Column(String(16), nullable=False, index=True, comment="simple/standard/creative")
    account_id = Column(String(64), nullable=False, index=True, comment="广告账户ID")
    account_name = Column(String(255), nullable=False, index=True, comment="账号名称")
    report_date = Column(Date, nullable=False, index=True, comment="报表日期")
    campaign_id = Column(String(128), nullable=False, index=True, server_default="", comment="计划ID/缓存行唯一键")
    payload = Column(JSON, nullable=False, comment="该日期该账号的完整行数据")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())


class XHSProfileStatDaily(Base):
    __tablename__ = "xhs_profile_stat_daily"
    __table_args__ = (
        UniqueConstraint("stat_date", "channel_account_name", name="uq_xhs_profile_stat_daily_account_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    stat_date = Column(Date, nullable=False, index=True, comment="统计日期")
    channel_account_name = Column(String(255), nullable=False, index=True, comment="渠道账号，已去掉【小红书】前缀")
    channel_account_key = Column(String(255), nullable=False, default="", index=True, comment="渠道账号归一化匹配键")

    total_visits = Column(Integer, nullable=False, default=0, comment="总访问数")
    leads = Column(Integer, nullable=False, default=0, comment="客资数")
    natural_source_count = Column(Integer, nullable=False, default=0, comment="自然来源数")
    ad_paid_count = Column(Integer, nullable=False, default=0, comment="广告付费数")
    natural_openings = Column(Integer, nullable=False, default=0, comment="自然来源开口数")
    ad_openings = Column(Integer, nullable=False, default=0, comment="广告开口数")
    natural_leads = Column(Integer, nullable=False, default=0, comment="自然来源客资数")
    special_natural_leads = Column(Integer, nullable=False, default=0, comment="特殊自然来源数")
    ad_leads = Column(Integer, nullable=False, default=0, comment="广告客资数")
    direct_private_count = Column(Integer, nullable=False, default=0, comment="直接进私数")
    private_leads = Column(Integer, nullable=False, default=0, comment="进私留资数")
    comment_users = Column(Integer, nullable=False, default=0, comment="评论用户数")
    comment_leads = Column(Integer, nullable=False, default=0, comment="评论留资数")
    xhs_ad_leads = Column(Integer, nullable=False, default=0, comment="小红书广告")
    natural_opening_conversion_rate = Column(Float, nullable=False, default=0.0, comment="自然开口转化率")
    ad_opening_conversion_rate = Column(Float, nullable=False, default=0.0, comment="广告开口转化率")
    comment_lead_rate = Column(Float, nullable=False, default=0.0, comment="评论留资率")
    private_lead_rate = Column(Float, nullable=False, default=0.0, comment="进私留资率")

    payload = Column(JSON, nullable=False, comment="接口返回原始行")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())


class XHSAdStatsDailyAccount(Base):
    __tablename__ = "xhs_ad_stats_daily_account"
    __table_args__ = (
        UniqueConstraint("stat_date", "report_type", "account_id", name="uq_xhs_ad_stats_daily_account_key"),
        Index("ix_xhs_ad_stats_daily_account_date_type", "stat_date", "report_type"),
        Index("ix_xhs_ad_stats_daily_account_buyer_date", "buyer_user_id", "stat_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    stat_date = Column(Date, nullable=False, index=True)
    report_type = Column(String(16), nullable=False, index=True)
    account_id = Column(String(64), nullable=False, index=True)
    account_name = Column(String(255), nullable=False, default="")
    buyer_user_id = Column(Integer, nullable=True, index=True)
    buyer_name = Column(String(255), nullable=False, default="")
    fee = Column(Float, nullable=False, default=0.0)
    impression = Column(Float, nullable=False, default=0.0)
    click = Column(Float, nullable=False, default=0.0)
    message_consult = Column(Float, nullable=False, default=0.0)
    openings = Column(Float, nullable=False, default=0.0)
    conversion = Column(Float, nullable=False, default=0.0)
    interaction = Column(Float, nullable=False, default=0.0)
    comment = Column(Float, nullable=False, default=0.0)
    special_natural_leads = Column(Float, nullable=False, default=0.0)
    row_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())


class XHSAdStatsDailyBuyer(Base):
    __tablename__ = "xhs_ad_stats_daily_buyer"
    __table_args__ = (
        UniqueConstraint("stat_date", "report_type", "buyer_user_id", name="uq_xhs_ad_stats_daily_buyer_key"),
        Index("ix_xhs_ad_stats_daily_buyer_date_type", "stat_date", "report_type"),
    )

    id = Column(Integer, primary_key=True, index=True)
    stat_date = Column(Date, nullable=False, index=True)
    report_type = Column(String(16), nullable=False, index=True)
    buyer_user_id = Column(Integer, nullable=True, index=True)
    buyer_name = Column(String(255), nullable=False, default="")
    account_count = Column(Integer, nullable=False, default=0)
    fee = Column(Float, nullable=False, default=0.0)
    impression = Column(Float, nullable=False, default=0.0)
    click = Column(Float, nullable=False, default=0.0)
    message_consult = Column(Float, nullable=False, default=0.0)
    openings = Column(Float, nullable=False, default=0.0)
    conversion = Column(Float, nullable=False, default=0.0)
    interaction = Column(Float, nullable=False, default=0.0)
    comment = Column(Float, nullable=False, default=0.0)
    special_natural_leads = Column(Float, nullable=False, default=0.0)
    row_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())


class XHSAdStatsDailyBrand(Base):
    __tablename__ = "xhs_ad_stats_daily_brand"
    __table_args__ = (
        UniqueConstraint("stat_date", "report_type", "account_id", "brand", name="uq_xhs_ad_stats_daily_brand_key"),
        Index("ix_xhs_ad_stats_daily_brand_date_type", "stat_date", "report_type"),
        Index("ix_xhs_ad_stats_daily_brand_buyer_date", "buyer_user_id", "stat_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    stat_date = Column(Date, nullable=False, index=True)
    report_type = Column(String(16), nullable=False, index=True)
    account_id = Column(String(64), nullable=False, index=True)
    account_name = Column(String(255), nullable=False, default="")
    buyer_user_id = Column(Integer, nullable=True, index=True)
    buyer_name = Column(String(255), nullable=False, default="")
    brand = Column(String(120), nullable=False, index=True)
    fee = Column(Float, nullable=False, default=0.0)
    impression = Column(Float, nullable=False, default=0.0)
    click = Column(Float, nullable=False, default=0.0)
    conversion = Column(Float, nullable=False, default=0.0)
    interaction = Column(Float, nullable=False, default=0.0)
    row_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())


class XHSAdStatsDailyNote(Base):
    __tablename__ = "xhs_ad_stats_daily_note"
    __table_args__ = (
        UniqueConstraint("stat_date", "report_type", "account_id", "note_id", name="uq_xhs_ad_stats_daily_note_key"),
        Index("ix_xhs_ad_stats_daily_note_date_type", "stat_date", "report_type"),
        Index("ix_xhs_ad_stats_daily_note_buyer_date", "buyer_user_id", "stat_date"),
        Index("ix_xhs_ad_stats_daily_note_tag", "primary_content_tag", "secondary_content_tag"),
    )

    id = Column(Integer, primary_key=True, index=True)
    stat_date = Column(Date, nullable=False, index=True)
    report_type = Column(String(16), nullable=False, index=True)
    account_id = Column(String(64), nullable=False, index=True)
    account_name = Column(String(255), nullable=False, default="")
    buyer_user_id = Column(Integer, nullable=True, index=True)
    buyer_name = Column(String(255), nullable=False, default="")
    note_id = Column(String(128), nullable=False, index=True)
    note_title = Column(String(500), nullable=False, default="")
    xhs_account_name = Column(String(255), nullable=False, default="")
    primary_content_tag = Column(String(80), nullable=False, default="", index=True)
    secondary_content_tag = Column(String(120), nullable=False, default="", index=True)
    fee = Column(Float, nullable=False, default=0.0)
    impression = Column(Float, nullable=False, default=0.0)
    click = Column(Float, nullable=False, default=0.0)
    message_consult = Column(Float, nullable=False, default=0.0)
    openings = Column(Float, nullable=False, default=0.0)
    conversion = Column(Float, nullable=False, default=0.0)
    interaction = Column(Float, nullable=False, default=0.0)
    row_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())


class XHSAdStatsDailyContentTag(Base):
    __tablename__ = "xhs_ad_stats_daily_content_tag"
    __table_args__ = (
        UniqueConstraint("stat_date", "report_type", "account_id", "primary_content_tag", "secondary_content_tag", name="uq_xhs_ad_stats_daily_content_tag_key"),
        Index("ix_xhs_ad_stats_daily_content_tag_date_type", "stat_date", "report_type"),
        Index("ix_xhs_ad_stats_daily_content_tag_buyer_date", "buyer_user_id", "stat_date"),
        Index("ix_xhs_ad_stats_daily_content_tag_tags", "primary_content_tag", "secondary_content_tag"),
    )

    id = Column(Integer, primary_key=True, index=True)
    stat_date = Column(Date, nullable=False, index=True)
    report_type = Column(String(16), nullable=False, index=True)
    account_id = Column(String(64), nullable=False, index=True)
    account_name = Column(String(255), nullable=False, default="")
    buyer_user_id = Column(Integer, nullable=True, index=True)
    buyer_name = Column(String(255), nullable=False, default="")
    primary_content_tag = Column(String(80), nullable=False, default="", index=True)
    secondary_content_tag = Column(String(120), nullable=False, default="", index=True)
    fee = Column(Float, nullable=False, default=0.0)
    conversion = Column(Float, nullable=False, default=0.0)
    click = Column(Float, nullable=False, default=0.0)
    interaction = Column(Float, nullable=False, default=0.0)
    row_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())
