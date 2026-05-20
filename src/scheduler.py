from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path

from models import Config
from models import ScheduledJob, ScheduledJobStatus, SchedulerState
from utils import file_info, load_model, log, project_root, sha256_text, write_json


def scheduler_state_path() -> Path:
    return project_root() / "output" / "scheduler" / "jobs.json"


def load_scheduler_state(path: Path | None = None) -> SchedulerState:
    state_path = path or scheduler_state_path()
    if not state_path.exists():
        return SchedulerState()
    return load_model(state_path, SchedulerState)


def save_scheduler_state(state: SchedulerState, path: Path | None = None) -> Path:
    state_path = path or scheduler_state_path()
    write_json(state_path, state.model_dump(mode="json"))
    return state_path


def _resolve_project_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return project_root() / path


def _pdf_fingerprint(path: Path) -> str:
    stat = path.stat()
    return sha256_text(f"{path.resolve()}:{stat.st_size}:{int(stat.st_mtime)}")


def _title_from_pdf(path: Path) -> str:
    return path.stem.replace("-", " ").replace("_", " ").strip().title()


def _next_schedule_date(state: SchedulerState, config: Config) -> datetime:
    hour, minute = [int(part) for part in config.scheduler_publish_time.split(":")]
    now = datetime.now()
    base = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    scheduled_dates = [job.scheduled_for for job in state.jobs if job.scheduled_for]
    if scheduled_dates:
        return max(scheduled_dates) + timedelta(days=config.scheduler_interval_days)
    if base < now:
        return base + timedelta(days=config.scheduler_interval_days)
    return base


def organize_queue(config: Config, dry_run: bool = False) -> list[ScheduledJob]:
    state = load_scheduler_state()
    queue_dir = _resolve_project_path(config.scheduler_queue_dir)
    queue_dir.mkdir(parents=True, exist_ok=True)
    known = {job.pdf_fingerprint for job in state.jobs if job.pdf_fingerprint}
    created: list[ScheduledJob] = []
    for pdf_path in sorted(queue_dir.glob("*.pdf")):
        fingerprint = _pdf_fingerprint(pdf_path)
        if fingerprint in known:
            continue
        scheduled_for = _next_schedule_date(state, config)
        job_id = uuid.uuid4().hex[:12]
        relative_pdf = str(pdf_path.relative_to(project_root())) if pdf_path.is_relative_to(project_root()) else str(pdf_path)
        job = ScheduledJob(
            job_id=job_id,
            pdf=relative_pdf,
            title=_title_from_pdf(pdf_path),
            duration=config.target_duration_minutes,
            scheduled_for=scheduled_for,
            pdf_fingerprint=fingerprint,
            output_root=f"output/jobs/{job_id}",
            publish=config.scheduler_default_publish,
        )
        created.append(job)
        state.jobs.append(job)
        known.add(fingerprint)
        log(f"Organizado: {job.job_id} | {job.scheduled_for:%Y-%m-%d %H:%M} | {job.title}")
    if created and not dry_run:
        state_path = save_scheduler_state(state)
        log(f"Plan editorial guardado: {file_info(state_path)}")
    if not created:
        log(f"No hay PDFs nuevos en {queue_dir}")
    return created


def add_job(
    pdf: str,
    title: str,
    duration: int,
    publish: bool = True,
    youtube_dry_run: bool = False,
    force: bool = False,
    privacy_status: str | None = None,
    youtube_title: str | None = None,
    youtube_description: str | None = None,
    youtube_tags: str | None = None,
    scheduled_for: datetime | None = None,
    output_root: str | None = None,
) -> ScheduledJob:
    state = load_scheduler_state()
    job = ScheduledJob(
        job_id=uuid.uuid4().hex[:12],
        pdf=pdf,
        title=title,
        duration=duration,
        scheduled_for=scheduled_for,
        output_root=output_root,
        publish=publish,
        youtube_dry_run=youtube_dry_run,
        force=force,
        privacy_status=privacy_status,
        youtube_title=youtube_title,
        youtube_description=youtube_description,
        youtube_tags=youtube_tags,
    )
    state.jobs.append(job)
    state_path = save_scheduler_state(state)
    log(f"Trabajo agregado: {job.job_id} | {job.title} | {job.pdf}")
    log(f"Cola guardada: {file_info(state_path)}")
    return job


def list_jobs() -> SchedulerState:
    state = load_scheduler_state()
    if not state.jobs:
        log("No hay trabajos en la cola.")
        return state
    for job in state.jobs:
        suffix = f" | error={job.last_error}" if job.last_error else ""
        scheduled = job.scheduled_for.strftime("%Y-%m-%d %H:%M") if job.scheduled_for else "sin fecha"
        log(
            f"{job.job_id} | {job.status.value:<9} | {scheduled} | intentos={job.attempts} | "
            f"publish={'yes' if job.publish else 'no'} | dry_run={'yes' if job.youtube_dry_run else 'no'} | "
            f"{job.title} | {job.pdf}{suffix}"
        )
    return state


def reset_failed_jobs() -> int:
    state = load_scheduler_state()
    count = 0
    now = datetime.now()
    for job in state.jobs:
        if job.status == ScheduledJobStatus.failed:
            job.status = ScheduledJobStatus.pending
            job.updated_at = now
            job.last_error = None
            count += 1
    save_scheduler_state(state)
    log(f"Trabajos fallidos devueltos a pending: {count}")
    return count


def pending_jobs(limit: int | None = None, due_only: bool = False) -> list[ScheduledJob]:
    now = datetime.now()
    jobs = [
        job
        for job in load_scheduler_state().jobs
        if job.status == ScheduledJobStatus.pending and (not due_only or job.scheduled_for is None or job.scheduled_for <= now)
    ]
    if limit is not None:
        return jobs[:limit]
    return jobs


def update_job(updated_job: ScheduledJob) -> None:
    state = load_scheduler_state()
    for index, job in enumerate(state.jobs):
        if job.job_id == updated_job.job_id:
            state.jobs[index] = updated_job
            save_scheduler_state(state)
            return
    raise RuntimeError(f"No existe el trabajo en la cola: {updated_job.job_id}")


def mark_running(job: ScheduledJob) -> ScheduledJob:
    now = datetime.now()
    job.status = ScheduledJobStatus.running
    job.attempts += 1
    job.started_at = now
    job.updated_at = now
    job.finished_at = None
    job.last_error = None
    update_job(job)
    return job


def mark_succeeded(job: ScheduledJob, youtube_url: str | None = None) -> ScheduledJob:
    now = datetime.now()
    job.status = ScheduledJobStatus.succeeded
    job.finished_at = now
    job.updated_at = now
    job.last_error = None
    if youtube_url:
        job.youtube_url = youtube_url
    update_job(job)
    return job


def mark_failed(job: ScheduledJob, error: Exception) -> ScheduledJob:
    now = datetime.now()
    job.status = ScheduledJobStatus.failed
    job.finished_at = now
    job.updated_at = now
    job.last_error = str(error)
    update_job(job)
    return job
