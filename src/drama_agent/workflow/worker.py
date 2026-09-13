"""后台 job worker：轮询领取 → 执行 → 心跳/终态；周期性回收僵尸。"""
import asyncio
import time
from sqlalchemy import select
from drama_agent.db import session as db_session
from drama_agent.db.models import Episode
from drama_agent.db.enums import LifecycleStatus, EventType, JobKind
from drama_agent.services import job_service, event_service, clip_service
from drama_agent.workflow import runner
import structlog

logger = structlog.get_logger()


class JobWorker:
    def __init__(self, instance_id: str, poll_interval: float = 2.0, heartbeat_timeout: int = 120):
        self.instance_id = instance_id
        self.poll_interval = poll_interval
        self.heartbeat_timeout = heartbeat_timeout
        self._running = False
        # 回收间隔取心跳超时的一半:太长则僵尸 job 干等,太短则空扫 DB。
        self.reap_interval = max(10.0, heartbeat_timeout / 2)

    async def run_forever(self) -> None:
        self._running = True
        await self._reap()
        last_reap = time.monotonic()
        while self._running:
            # **周期性**回收,不只在启动时:持有 job 的实例中途死掉(崩溃 / kill -9 /
            # 信号没送达导致的僵尸进程)时,那条 job 会一直停在 running,而本实例活着
            # 就永远等不到下一次启动 —— 界面上就是"一直启动中"。
            if time.monotonic() - last_reap >= self.reap_interval:
                await self._reap()
                last_reap = time.monotonic()
            async with db_session.AsyncSessionLocal() as s:
                job = await job_service.claim_next(s, owner=self.instance_id)
            if job is None:
                await asyncio.sleep(self.poll_interval)
                continue
            await self._process(job)

    async def _reap(self) -> None:
        """回收心跳超时的 job。失败不能掀掉 worker 循环 —— 回收是旁路,
        它挂掉只该少一次清理,不该让整个实例停止领取新任务。

        判死的 job 要在这里按 kind 收尾业务实体:这条路径下没有任何 runner 在跑,
        _process 的异常处理(_fail_entity)不会被触发,只能由 reap 自己标终态,
        否则业务实体永远停在 running(界面上"生成中"却没有任何入口能解)。
        """
        try:
            async with db_session.AsyncSessionLocal() as s:
                reaped, failed_jobs = await job_service.reap_stale(s, self.heartbeat_timeout)
            if reaped:
                logger.info("reaped stale jobs", count=reaped)
            for job in failed_jobs:
                await self._fail_reaped_entity(job)
        except Exception as e:  # noqa: BLE001 — 旁路失败不阻断主循环
            logger.warning("reap failed", error=str(e))

    async def _fail_reaped_entity(self, job: dict) -> None:
        """只收尾 CLIP:它 max_attempts=1,一次心跳超时就会判死,是常态窗口
        (生成动辄几分钟,心跳超时通常 120s)。其余 kind 的同类缺口(Episode 侧,
        max_attempts=3,需连崩三次才碰到)尚未收敛。
        """
        if job["kind"] == JobKind.CLIP.value:
            await clip_service.mark_failed(
                job["episode_id"], "worker 中断且重试已尽：生成未完成")

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
            # 带上异常类型与 traceback:只记 str(e) 时 KeyError 只会留下一个裸键名
            # (如 'project_id'),既看不出哪一行、也分不清是哪个字典 —— 排查时只能靠猜。
            logger.warning("job failed", job_id=job_id, kind=job.get("kind"),
                           error=f"{type(e).__name__}: {e}", exc_info=True)
            # 退避:按尝试次数指数退避(封顶 30s),避免瞬时故障在数秒内耗尽重试。
            # 睡眠期间 job 仍为 running、心跳继续(hb_task 尚未取消),不会被 reap。
            await asyncio.sleep(min(2.0 * (2 ** job["attempts"]), 30.0))
            async with db_session.AsyncSessionLocal() as s:
                # attempts 判定读 DB 真值(见 fail_or_requeue),不用领取时的快照
                outcome = await job_service.fail_or_requeue(s, job_id, str(e))
                if outcome == "failed":
                    await self._fail_entity(
                        s, job["episode_id"], job.get("project_id", ""), str(e)
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

    async def _fail_entity(self, s, episode_id: str, project_id: str, error: str) -> None:
        """job 终态失败时把 Episode 标 FAILED + 落错误,避免僵尸 running。"""
        row = (await s.execute(
            select(Episode).where(Episode.id == episode_id)
        )).scalar_one_or_none()
        if row:
            row.status = LifecycleStatus.FAILED.value
            row.error_message = error
            await s.flush()
        await event_service.append_event(
            s, episode_id, EventType.ERROR, {"message": error}, project_id=project_id
        )
