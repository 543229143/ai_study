"""日志采集策略：广扫 vs 单服务深入。"""
from __future__ import annotations

LOG_SIZE_PER_APP = 500
# focused 双查：异常保底条数（ERROR/Exception 通常远少于此，不必与全级别同量）
LOG_SIZE_ERROR_GUARD = 50


def resolve_log_collect_profile(ctx: dict, apps: list[str]) -> str:
    """focused=单服务全级别；broad=多服务广扫偏异常。"""
    explicit = (ctx.get("log_collect_profile") or "").strip().lower()
    if explicit in {"focused", "broad"}:
        return explicit
    if len(apps) <= 1:
        return "focused"
    return "broad"


def log_params_for_profile(profile: str, *, size: int | None = None) -> dict:
    size = size or LOG_SIZE_PER_APP
    if profile == "broad":
        return {
            "log_collect_profile": "broad",
            "log_size_per_app": size,
            "log_errors_only": True,
            "log_error_guard_size": LOG_SIZE_ERROR_GUARD,
        }
    return {
        "log_collect_profile": "focused",
        "log_size_per_app": size,
        "log_errors_only": False,
        "log_error_guard_size": LOG_SIZE_ERROR_GUARD,
    }


def apply_log_profile_to_ctx(ctx: dict, apps: list[str]) -> None:
    profile = resolve_log_collect_profile(ctx, apps)
    params = log_params_for_profile(profile)
    ctx.update(params)


def collect_kwargs_from_ctx(ctx: dict) -> dict:
    return {
        "size": int(ctx.get("log_size_per_app") or LOG_SIZE_PER_APP),
        "errors_only": bool(ctx.get("log_errors_only", False)),
        "error_guard_size": int(ctx.get("log_error_guard_size") or LOG_SIZE_ERROR_GUARD),
    }
