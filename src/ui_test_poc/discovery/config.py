from __future__ import annotations

from pathlib import Path
from typing import Any

from ..schema import validate_or_raise
from .catalog import build_process_catalog
from .coverage import build_coverage
from .models import new_run_id, write_json
from .reconcile import reconcile_graphs
from .runtime_index import explore_runtime, load_runtime_config
from .schema import DISCOVERY_MANIFEST_SCHEMA_PATH
from .source_index import build_source_graph


def run_discovery(
    config_path: str | Path,
    output_root: str | Path | None = None,
    *,
    headless: bool = True,
) -> dict[str, Any]:
    path = Path(config_path).resolve()
    config = load_runtime_config(path)
    run_id = new_run_id()
    root = (
        Path(output_root).resolve()
        if output_root
        else resolve_config_path(
            str(config.get("outputRoot", "artifacts/discovery")),
            path,
        )
        / run_id
    )
    root.mkdir(parents=True, exist_ok=True)
    source_config = dict(config.get("source") or {})
    repository = Path(source_config.get("repository", "."))
    if not repository.is_absolute():
        repository = (path.parent / repository).resolve()

    source = build_source_graph(
        repository,
        root,
        include=source_config.get("include"),
        exclude=source_config.get("exclude"),
    )
    runtime = explore_runtime(
        config,
        root,
        source_graph_path=root / "source-graph.json",
        headless=headless,
    )
    reconciliation = reconcile_graphs(root, root, root)
    catalog = build_process_catalog(
        root,
        root,
        maxDepth=int(config.get("catalog", {}).get("maxDepth", 6)),
    )
    coverage = build_coverage(root, root, root)
    manifest = {
        "schemaVersion": "1.0",
        "runId": run_id,
        "generatedAt": coverage["generatedAt"],
        "status": "review-required",
        "configPath": str(path),
        "outputDir": str(root),
        "source": {
            "status": source["status"],
            "stats": source["stats"],
        },
        "runtime": {
            "status": runtime["status"],
            "stats": runtime["stats"],
        },
        "reconciliation": reconciliation["summary"],
        "catalog": catalog["summary"],
        "coverage": {
            "route": coverage["routeCoverage"],
            "transition": coverage["transitionCoverage"],
            "role": coverage["roleCoverage"],
            "process": coverage["processCoverage"],
        },
        "caveats": [
            "本结果用于发现业务流程和覆盖缺口，不替代权威 UI 回归结论。",
            "默认只执行只读导航，不自动触发写操作、支付或权限变更。",
        ],
    }
    validate_or_raise(
        manifest,
        DISCOVERY_MANIFEST_SCHEMA_PATH,
        "Discovery Manifest",
    )
    write_json(root / "manifest.json", manifest)
    return manifest


def resolve_config_path(value: str, config_path: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (Path(config_path).resolve().parent / path).resolve()
