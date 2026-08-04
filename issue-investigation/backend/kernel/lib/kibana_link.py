"""构建 Kibana Discover 深链（dev/sit test 集群）。"""
from __future__ import annotations

from urllib.parse import quote


def _filter_rison(index: str, field: str, value: str, *, disabled: bool = False) -> str:
    dis = "!t" if disabled else "!f"
    return (
        "('$state':(store:appState),"
        f"meta:(alias:!n,disabled:{dis},index:{index},key:{field},negate:!f,"
        f"params:(query:{value}),type:phrase),"
        f"query:(match_phrase:({field}:{value})))"
    )


def build_discover_url(
    base_url: str,
    *,
    index: str = "filebeat",
    namespace: str,
    container: str,
    query: str,
    time_from: str = "now-3d",
    time_to: str = "now",
) -> str:
    """
    生成与用户提供的 kibana-test Discover URL 同构的深链。
    namespace: dev / sit
    container: lps-service 等
    query: traceId / orderNo / 关键词
    """
    base = base_url.rstrip("/")
    q = query.replace("'", "\\'")
    filters = ",".join([
        _filter_rison(index, "k8s_pod_namespace", namespace, disabled=False),
        _filter_rison(index, "docker_container", container, disabled=False),
    ])
    _a = (
        f"(columns:!(docker_container,message),"
        f"filters:!({filters}),"
        f"hideChart:!t,"
        f"index:{index},"
        f"interval:auto,"
        f"query:(language:kuery,query:{q}),"
        f"rowsPerPage:250,"
        f"sort:!(!('@timestamp',desc)),"
        f"viewMode:documents)"
    )
    _g = f"(filters:!(),refreshInterval:(pause:!t,value:5000),time:(from:{time_from},to:{time_to}))"
    hash_part = f"#/?_g={quote(_g, safe='()!,')}&_a={quote(_a, safe='()!,')}"
    return f"{base}/app/discover{hash_part}"
