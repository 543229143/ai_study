"""
环境连接配置读取（references/env-connections.json）。

Java 对照：类似读取 application-{profile}.yml 里的 datasource / nacos 段，
本模块只负责 dev/sit，禁止 prod。
"""
from __future__ import annotations

import json
import re
from typing import Any

from lib.common import skill_root


def load_connections() -> dict[str, Any]:
    """加载整份 env-connections.json，返回 dict（类似 Map<String,Object>）。"""
    path = skill_root() / "references" / "env-connections.json"
    if not path.is_file():
        raise RuntimeError(f"缺少环境连接配置: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_env_block(env: str) -> dict[str, Any]:
    """取某一环境节点，如 dev / sit。"""
    data = load_connections()
    block = data.get(env)
    if not block:
        raise RuntimeError(f"env-connections.json 中缺少 '{env}' 节点")
    return block


def get_logs_config(env: str) -> dict[str, Any]:
    """ES / Kibana 连接信息（logs 段）。"""
    block = get_env_block(env)
    logs = block.get("logs") or {}
    if not logs.get("k8s_namespace"):
        raise RuntimeError(f"请填写 env-connections.json → {env}.logs.k8s_namespace")
    return logs


def get_nacos_config(env: str) -> dict[str, Any]:
    """
    Nacos 连接信息；tenant 固定等于 env（dev→dev namespace）。

    返回 base_url, username, password, tenant。
    """
    block = get_env_block(env)
    nacos = block.get("nacos") or {}
    missing = [k for k in ("base_url", "username", "password") if not nacos.get(k)]
    if missing:
        raise RuntimeError(f"请填写 env-connections.json → {env}.nacos.{missing[0]}")
    out = dict(nacos)
    out["tenant"] = env
    return out


def get_mysql_config(env: str) -> dict[str, Any]:
    """MySQL 只读连接；含生产 host 关键字则抛异常。"""
    block = get_env_block(env)
    mysql = block.get("mysql") or {}
    missing = [k for k in ("host", "user", "password") if not mysql.get(k)]
    if missing:
        raise RuntimeError(f"请填写 env-connections.json → {env}.mysql.{missing[0]}")
    host = mysql["host"]
    if any(k in str(host).lower() for k in ("prod", "production", "online", "release")):
        raise RuntimeError(f"检测到生产库 host，禁止: {host}")
    return {
        "host": host,
        "port": int(mysql.get("port") or 3306),
        "user": mysql["user"],
        "password": mysql["password"],
    }


def get_schema_name(env: str, schema_key: str) -> str:
    """把逻辑 schema 名（lcs/goa）映射为实际库名。"""
    block = get_env_block(env)
    schemas = block.get("schemas") or {}
    name = schemas.get(schema_key) or schema_key
    if not name:
        raise RuntimeError(f"请填写 env-connections.json → {env}.schemas.{schema_key}")
    return name


def resolve_sql_placeholders(sql: str, env: str, app_cfg: dict[str, Any], biz_key: str) -> str:
    """
    替换 SQL 模板占位符：{{schema}}、{{schema:hub}}、{{biz_key}}。

    在 Mapper 推断出的 SQL 上调用，避免写死库名。
    """
    primary = app_cfg.get("primary_schema") or "public"

    def repl_schema(match: re.Match) -> str:
        key = match.group(1) or primary
        return get_schema_name(env, key)

    out = re.sub(r"\{\{schema:([a-zA-Z0-9_]+)\}\}", repl_schema, sql)
    out = out.replace("{{schema}}", get_schema_name(env, primary))
    out = out.replace("{{biz_key}}", biz_key)
    return out


def validate_env_config(env: str) -> list[str]:
    """启动前检查配置完整性，返回问题列表（空列表=通过）。"""
    issues: list[str] = []
    try:
        logs = get_logs_config(env)
        if not logs.get("es_host"):
            issues.append(f"{env}.logs.es_host（可选，空则仅 Kibana 链接）")
    except RuntimeError as e:
        issues.append(str(e))
    try:
        get_nacos_config(env)
    except RuntimeError as e:
        issues.append(str(e))
    try:
        get_mysql_config(env)
    except RuntimeError as e:
        issues.append(str(e))
    return issues
