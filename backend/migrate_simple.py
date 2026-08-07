import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from passlib.context import CryptContext

URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@postgres:5432/ai_creative")

async def main():
    engine = create_async_engine(URL, echo=False)

    # Create users table if not exists
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR(32) NOT NULL
            )
        """))
        await conn.execute(text("""
            INSERT INTO alembic_version VALUES ('007')
            ON CONFLICT DO NOTHING
        """))

    print("Basic tables created, now running individual migration scripts...")

    # Run each migration
    from app.alembic.versions import (
        _001_initial as mig001, _002_add_ai_meta as mig002,
        _003_create_copywritings as mig003, _004_add_user_role as mig004,
        _005_create_prompt_tables as mig005, _006_add_prompt_owner_fields as mig006,
        _6ac6769ce0b2_add_user_workflow_access as mig007,
        _007_create_prompt_moderation_tables as mig008,
    )

    migrations = [mig001, mig002, mig003, mig004, mig005, mig006, mig007, mig008]
    for mig in migrations:
        try:
            await conn.run_sync(lambda c: mig.upgrade())
            print(f"  Applied {mig.revision}")
        except Exception as e:
            if "already" in str(e).lower() or "exist" in str(e).lower():
                print(f"  Skipped {mig.revision} (already exists)")
            else:
                print(f"  Error on {mig.revision}: {e}")
        await conn.commit()

    admin_password = os.getenv("MIGRATION_ADMIN_PASSWORD", "").strip()
    if admin_password:
        admin_username = os.getenv("MIGRATION_ADMIN_USERNAME", "admin").strip() or "admin"
        admin_email = os.getenv("MIGRATION_ADMIN_EMAIL", "admin@local.com").strip() or "admin@local.com"
        pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        hashed = pwd_ctx.hash(admin_password)

        async with engine.connect() as conn:
            await conn.execute(text("""
                INSERT INTO users (username, email, hashed_password, role, is_active)
                VALUES (:username, :email, :pwd, 'admin', true)
                ON CONFLICT DO NOTHING
            """), {"username": admin_username, "email": admin_email, "pwd": hashed})
            await conn.commit()

        print(f"\nAdmin user created: {admin_username}")
    else:
        print("\nAdmin user creation skipped; set MIGRATION_ADMIN_PASSWORD to enable it")

    await engine.dispose()

asyncio.run(main())
