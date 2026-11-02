import json
from pathlib import Path

import pytest

from ui_test_poc.discovery.catalog import build_process_catalog
from ui_test_poc.discovery.coverage import build_coverage
from ui_test_poc.discovery.models import (
    matches_route,
    normalize_route,
    sanitize_url,
)
from ui_test_poc.discovery.reconcile import reconcile_graphs
from ui_test_poc.discovery.runtime_index import (
    _guard_request,
    load_runtime_config,
)
from ui_test_poc.discovery.source_index import build_source_graph
from ui_test_poc.schema import SCHEMAS_DIR


def test_normalizes_dynamic_routes_and_redacts_query_values():
    assert normalize_route("/users/:id/") == "/users/:param"
    assert normalize_route("/users/{userId}") == "/users/:param"
    assert matches_route("/users/:param", "/users/42")
    assert not matches_route("/users/:param", "/teams/42")
    assert sanitize_url(
        "https://example.test/search?keyword=secret&page=1#result"
    ) == "https://example.test/search?keyword=%5BREDACTED%5D&page=%5BREDACTED%5D"


def test_source_index_finds_react_routes_and_links(work_dir):
    repository = work_dir / "frontend"
    source_dir = repository / "src"
    source_dir.mkdir(parents=True)
    (source_dir / "router.tsx").write_text(
        """
const routes = [
  { path: '/login', name: 'Login', element: <LoginPage /> },
  { path: '/users/:id', component: UserPage },
];
<Route path="/orders" element={<OrderPage />} />
<Link to="/search">Search</Link>
router.push('/account');
""".strip(),
        encoding="utf-8",
    )

    result = build_source_graph(repository, work_dir / "source")

    paths = {route["normalized_path"] for route in result["routes"]}
    assert {"/login", "/users/:param", "/orders"} <= paths
    link_targets = {link["normalized_target"] for link in result["links"]}
    assert {"/search", "/account"} <= link_targets
    assert result["stats"]["filesScanned"] == 1
    assert (work_dir / "source" / "source-graph.json").is_file()


def test_reconcile_catalog_and_coverage_form_offline_pipeline(work_dir):
    source = {
        "schemaVersion": "1.0",
        "runId": "source-run",
        "warnings": [],
        "routes": [
            {
                "id": "source-login",
                "path": "/login",
                "normalized_path": "/login",
                "name": "Login",
                "component": "LoginPage",
                "source": {
                    "path": "src/router.tsx",
                    "line": 3,
                    "symbol": "LoginPage",
                },
                "kind": "route-jsx",
                "confidence": 0.9,
            },
            {
                "id": "source-search",
                "path": "/search",
                "normalized_path": "/search",
                "name": "Search",
                "component": "SearchPage",
                "source": {
                    "path": "src/router.tsx",
                    "line": 4,
                    "symbol": "SearchPage",
                },
                "kind": "route-jsx",
                "confidence": 0.9,
            },
        ],
    }
    runtime = {
        "schemaVersion": "1.0",
        "runId": "runtime-run",
        "warnings": [],
        "target": {"baseUrl": "https://example.test/"},
        "roles": [{"name": "anonymous"}],
        "pages": [
            _page("page-login", "/login", "observed"),
            _page("page-search", "/search", "observed"),
        ],
        "transitions": [
            {
                "id": "transition-login-search",
                "role": "anonymous",
                "fromPath": "/login",
                "toPath": "/search",
                "action": "link",
                "depth": 1,
                "observedAt": "2026-11-02T00:00:00Z",
            }
        ],
        "apiCalls": [
            {
                "id": "api-search",
                "role": "anonymous",
                "pagePath": "/search",
                "method": "GET",
                "url": "https://example.test/api/search?q=%5BREDACTED%5D",
                "status": 200,
                "resourceType": "fetch",
                "classification": "read-query",
                "observedAt": "2026-11-02T00:00:00Z",
            }
        ],
    }
    root = work_dir / "evidence"
    root.mkdir()
    _write_json(root / "source-graph.json", source)
    _write_json(root / "runtime-graph.json", runtime)

    reconciliation = reconcile_graphs(root, root, root)
    catalog = build_process_catalog(root, root)
    coverage = build_coverage(root, root, root)

    assert reconciliation["summary"]["matched"] == 2
    assert reconciliation["summary"]["sourceOnly"] == 0
    assert catalog["summary"]["matchedProcesses"] == 1
    assert catalog["processes"][0]["category"] == "search"
    assert coverage["routeCoverage"]["ratio"] == 1.0
    assert coverage["transitionCoverage"]["ratio"] == 1.0
    assert coverage["processCoverage"]["ratio"] == 1.0
    assert (root / "processes" / f"{catalog['processes'][0]['id']}.yaml").is_file()


def test_reconciliation_exposes_source_only_and_runtime_only(work_dir):
    source = {
        "schemaVersion": "1.0",
        "runId": "source-run",
        "warnings": [],
        "routes": [
            {
                "id": "source-account",
                "path": "/account",
                "normalized_path": "/account",
                "name": "Account",
                "component": "AccountPage",
                "source": {
                    "path": "src/router.tsx",
                    "line": 8,
                    "symbol": "AccountPage",
                },
                "kind": "route-jsx",
                "confidence": 0.8,
            }
        ],
    }
    runtime = {
        "schemaVersion": "1.0",
        "runId": "runtime-run",
        "warnings": [],
        "target": {"baseUrl": "https://example.test/"},
        "roles": [{"name": "anonymous"}],
        "pages": [_page("dynamic-page", "/dynamic/42", "observed")],
        "transitions": [],
        "apiCalls": [],
    }
    root = work_dir / "evidence"
    root.mkdir()
    _write_json(root / "source-graph.json", source)
    _write_json(root / "runtime-graph.json", runtime)

    result = reconcile_graphs(root, root, root)
    statuses = {record["status"] for record in result["records"]}

    assert statuses == {"source-only", "runtime-only"}


def test_runtime_config_rejects_mutation_exploration(work_dir, monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://example.test")
    config_path = work_dir / "discovery.yaml"
    config_path.write_text(
        """
target:
  baseUrlRef: APP_BASE_URL
safety:
  allowMutations: true
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="allowMutations"):
        load_runtime_config(config_path)


@pytest.mark.parametrize(
    "schema_name",
    [
        "discovery-config.schema.json",
        "source-graph.schema.json",
        "runtime-graph.schema.json",
        "reconciliation.schema.json",
        "process-catalog.schema.json",
        "coverage.schema.json",
        "discovery-manifest.schema.json",
    ],
)
def test_discovery_schema_files_are_valid_json(schema_name):
    parsed = json.loads(
        (SCHEMAS_DIR / schema_name).read_text(encoding="utf-8")
    )
    assert parsed["$schema"].endswith("2020-12/schema")


def test_runtime_request_guard_blocks_non_read_methods():
    calls = []
    blocked = []
    route = _FakeRoute("POST", "https://example.test/api/orders")

    _guard_request(
        route,
        calls,
        blocked,
        "anonymous",
        "/checkout",
    )

    assert route.aborted
    assert not route.continued
    assert blocked == ["POST https://example.test/api/orders"]
    assert calls[0].classification == "mutation"
    assert calls[0].status is None


def test_runtime_request_guard_allows_get():
    route = _FakeRoute("GET", "https://example.test/api/search?q=phone")

    _guard_request(route, [], [], "anonymous", "/search")

    assert route.continued
    assert not route.aborted


class _FakeRequest:
    def __init__(self, method, url):
        self.method = method
        self.url = url
        self.resource_type = "fetch"


class _FakeRoute:
    def __init__(self, method, url):
        self.request = _FakeRequest(method, url)
        self.aborted = False
        self.continued = False

    def abort(self):
        self.aborted = True

    def continue_(self):
        self.continued = True


def _page(page_id, path, status):
    return {
        "id": page_id,
        "role": "anonymous",
        "requestedUrl": f"https://example.test{path}",
        "finalUrl": f"https://example.test{path}",
        "path": path,
        "title": path,
        "status": status,
        "httpStatus": 200,
        "depth": 0,
        "observedAt": "2026-11-02T00:00:00Z",
        "snapshotPath": None,
        "consoleErrorCount": 0,
    }


def _write_json(path: Path, value):
    import json

    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
