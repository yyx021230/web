from sqlalchemy import Boolean, Column, Integer, String, DateTime, func, Text
from app.db.base import Base


class XHSEnvironment(Base):
    __tablename__ = "xhs_environments"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(String(100), unique=True, nullable=False, index=True, comment="云登环境ID")
    account_name = Column(String(200), nullable=False, comment="云登账号名称")
    profile_url = Column(String(1000), comment="用于账号数据采集的小红书个人主页链接")
    sync_cloud_session_id = Column(String(100), comment="云登开放平台 sessionId")
    sync_cloud_api_key = Column(String(255), comment="云登开放平台 apiKey")
    sync_cloud_update_config = Column(Text, comment="账号数据同步前云登开放平台实例指纹更新参数(JSON)")
    sync_browser_start_config = Column(Text, comment="账号数据同步时云登浏览器启动参数(JSON)")
    xhs_account_id = Column(String(100), index=True, comment="小红书账号ID")
    login_phone_number = Column(String(30), comment="小红书手机号登录号码")
    xhs_account_type = Column(
        String(40),
        nullable=False,
        default="enterprise_professional",
        server_default="enterprise_professional",
        index=True,
        comment="小红书账号类型: enterprise_professional/enterprise_employee/personal",
    )
    is_sync_runner = Column(Boolean, nullable=False, default=False, server_default="false", comment="是否作为账号数据同步环境")
    notes = Column(String(500), comment="备注")
    proxy_info = Column(String(500), comment="代理信息")
    group_name = Column(String(200), comment="分组名称")
    labels = Column(String(500), comment="标签(逗号分隔)")
    department = Column(String(20), nullable=False, default="xhs", server_default="xhs", index=True, comment="账号部门: xhs/brand")
    status = Column(String(20), nullable=False, default="active", comment="active/inactive")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
