"""后台 job worker：轮询领取 → 执行 → 心跳/终态；启动时回收僵尸。"""
import asyncio
from sqlalchemy import select
from drama_agent.db import session as db_session
from drama_agent.db.models import Episode, Script
from drama_agent.db.enums import LifecycleStatus, EventType, JobKind
from drama_agent.services import job_service, event_service
from drama_agent.workflow import runner
import structlog

logger = structlog.get_logger()

SCRIPT_KINDS = {JobKind.SCRIPT_START.value, JobKind.SCRIPT_RESUME.value}


class JobWorker:
    def __init__(self, instance_id: str, poll_interval: float = 2.0, heartbeat_timeout: int = 120):
        self.instance_id = instance_id
        self.poll_interval = poll_interval
        self.heartbeat_timeout = heartbeat_timeout
        self._running = False

    async def run_forever(self) -> None:
        self._running = True
        async with db_session.AsyncSessionLocal() as s:
            reaped = await job_service.reap_stale(s, self.heartbeat_timeout)
            if reaped:
                logger.info("reaped stale jobs on startup", count=reaped)
        while self._running:
            async with db_session.AsyncSessionLocal() as s:
                job = await job_service.claim_next(s, owner=self.instance_id)
            if job is None:
                await asyncio.sleep(self.poll_interval)
                continue
            await self._process(job)

    async def stop(self) -> None:
        self._running = False

    async def _process(self, job: dict) -> None:
        job_id = job["id"]
        hb_task = asyncio.create_task(self._heartbeat_loop(job_id))
        try:
            await runner.run_job(job)
            async with db_session.AsyncSessionLocal() as s:
                await job_service.mark_succeeded(s, job_id)
        except Exception as e:
            logger.warning("job failed", job_id=job_id, error=str(e))
            # 退避:按尝试次数指数退避(封顶 30s),避免瞬时故障在数秒内耗尽重试。
            # 睡眠期间 job 仍为 running、心跳继续(hb_task 尚未取消),不会被 reap。
            await asyncio.sleep(min(2.0 * (2 ** job["attempts"]), 30.0))
            async with db_session.AsyncSessionLocal() as s:
                # attempts 判定读 DB 真值(见 fail_or_requeue),不用领取时的快照
                outcome = await job_service.fail_or_requeue(s, job_id, str(e))
                if outcome == "failed":
                    is_script = job["kind"] in SCRIPT_KINDS
                    await self._fail_entity(
                        s, job["episode_id"], job.get("project_id", ""), str(e), is_script=is_script
                    )
        finally:
            hb_task.cancel()

    async def _heartbeat_loop(self, job_id: str) -> None:
        try:
            while True:
                await asyncio.sleep(max(1.0, self.heartbeat_timeout / 4))
                async with db_session.AsyncSessionLocal() as s:
                    await job_service.heartbeat(s, job_id)
        except asyncio.CancelledError:
            pass

    async def _fail_entity(
        self, s, entity_id: str, project_id: str, error: str, *, is_script: bool
    ) -> None:
        """job 终态失败时把实体(Script/Episode)标 FAILED + 落错误,避免僵尸 running。"""
        row: Script | Episode | None
        if is_script:
            row = (await s.execute(
                select(Script).where(Script.id == entity_id)
            )).scalar_one_or_none()
        else:
            row = (await s.execute(
                select(Episode).where(Episode.id == entity_id)
            )).scalar_one_or_none()
        if row:
            row.status = LifecycleStatus.FAILED.value
            row.error_message = error
            await s.flush()
        await event_service.append_event(
            s, entity_id, EventType.ERROR, {"message": error}, project_id=project_id
        )
