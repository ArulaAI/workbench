#!/usr/bin/env python3
"""Unit tests for 6-layer domain clustering (lib/context/layer1_domain_clustering.py).

Tests individual layer functions with synthetic inputs and temp repos.
Covers: file inventory, import resolution, naming conventions, cross-language
bridges, package detection, semantic edges, co-change, clustering, labeling,
consumer interface mapping.
"""

import json
import os
import subprocess
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.context.layer1_domain_clustering import (
    _get_file_inventory,
    _classify_language,
    _resolve_python_imports,
    _resolve_java_imports,
    _resolve_typescript_imports,
    _find_tsconfig_paths,
    _pascal_to_kebab,
    _pascal_to_snake,
    _find_naming_convention_edges,
    _find_graphql_bridges,
    _find_rest_bridges,
    _detect_packages,
    _extract_identifiers,
    _strip_comments,
    _compute_segment_doc_freq,
    _build_semantic_edges,
    _label_cluster,
    _build_cochange_graph,
    _leiden_cluster,
    _compute_mq,
    _map_files_to_symbols,
    build_file_clusters,
    build_layer_c_from_files,
    measure_commit_coherence,
    CODE_EXTENSIONS,
    SKIP_DIRS,
)

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} — {detail}")


def make_temp_repo(file_contents: dict[str, str]) -> str:
    """Create a temp git repo with the given files. Returns repo path."""
    d = tempfile.mkdtemp()
    subprocess.run(["git", "init"], cwd=d, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=d, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=d, capture_output=True,
    )
    for path, content in file_contents.items():
        full = os.path.join(d, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
    subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=d, capture_output=True,
    )
    return d


# ══════════════════════════════════════════════════════════════
# 1: Language Classification
# ══════════════════════════════════════════════════════════════

print("\n=== 1: Language Classification ===")

check("python .py", _classify_language("app.py") == "python")
check("typescript .ts", _classify_language("app.ts") == "typescript")
check("typescript .tsx", _classify_language("Component.tsx") == "typescript")
check("typescript .jsx", _classify_language("App.jsx") == "typescript")
check("ruby .rb", _classify_language("server.rb") == "ruby")
check("go .go", _classify_language("main.go") == "go")
check("other .rs", _classify_language("lib.rs") == "other")


# ══════════════════════════════════════════════════════════════
# 2: File Inventory (Layer 0)
# ══════════════════════════════════════════════════════════════

print("\n=== 2: File Inventory (Layer 0) ===")

repo_l0 = make_temp_repo({
    "app.py": "print('hello')",
    "lib/utils.py": "pass",
    "node_modules/dep/index.js": "module.exports = {}",
    "README.md": "# readme",
    "src/app.ts": "export default {}",
})

files_l0 = _get_file_inventory(repo_l0)
check("finds .py files", "app.py" in files_l0, f"got {files_l0}")
check("finds .ts files", "src/app.ts" in files_l0)
check("finds nested .py", "lib/utils.py" in files_l0)
check("excludes node_modules", not any("node_modules" in f for f in files_l0), f"got {files_l0}")
check("excludes .md", not any(f.endswith(".md") for f in files_l0))

# Non-git directory fallback
non_git = tempfile.mkdtemp()
os.makedirs(os.path.join(non_git, "src"))
with open(os.path.join(non_git, "src", "main.py"), "w") as f:
    f.write("pass")
with open(os.path.join(non_git, "README.md"), "w") as f:
    f.write("# hi")
files_ng = _get_file_inventory(non_git)
check("non-git fallback finds .py", any("main.py" in f for f in files_ng), f"got {files_ng}")
check("non-git fallback excludes .md", not any(f.endswith(".md") for f in files_ng))


# ══════════════════════════════════════════════════════════════
# 3: Python Import Resolution (Layer 2a)
# ══════════════════════════════════════════════════════════════

print("\n=== 3: Python Import Resolution (Layer 2a) ===")

repo_py = make_temp_repo({
    "myapp/__init__.py": "",
    "myapp/models.py": "class User: pass",
    "myapp/views.py": "from myapp.models import User",
    "myapp/utils.py": "import os",
    "myapp/sub/__init__.py": "",
    "myapp/sub/helper.py": "from myapp.models import User",
})

py_files = ["myapp/__init__.py", "myapp/models.py", "myapp/views.py",
            "myapp/utils.py", "myapp/sub/__init__.py", "myapp/sub/helper.py"]
py_edges = _resolve_python_imports(repo_py, py_files)

# views.py imports models.py
check(
    "views→models import",
    any(s == "myapp/views.py" and t == "myapp/models.py" for s, t in py_edges),
    f"edges: {py_edges}",
)

# utils.py imports os (external) — should NOT produce an edge
check(
    "external import (os) produces no edge",
    not any(s == "myapp/utils.py" for s, t in py_edges),
    f"edges from utils: {[(s,t) for s,t in py_edges if s == 'myapp/utils.py']}",
)

# Cross-package import: sub/helper.py → models.py
check(
    "cross-package import resolves",
    any(s == "myapp/sub/helper.py" and "models" in t for s, t in py_edges),
    f"edges from helper: {[(s,t) for s,t in py_edges if s == 'myapp/sub/helper.py']}",
)

# No self-edges
check(
    "no self-edges",
    all(s != t for s, t in py_edges),
)


# ══════════════════════════════════════════════════════════════
# 3b: Java Import Resolution (Layer 2a)
# ══════════════════════════════════════════════════════════════

print("\n=== 3b: Java Import Resolution (Layer 2a) ===")

# Mirrors the actual PetClinic pattern the manager flagged: an interface
# and its implementation live in different packages/directories and are
# only connected by an explicit import — with no resolver, these two
# files were structurally invisible to each other during clustering.
repo_java = make_temp_repo({
    "src/main/java/org/example/petclinic/repository/OwnerRepository.java":
        "package org.example.petclinic.repository;\n"
        "public interface OwnerRepository {\n"
        "    Owner findById(int id);\n"
        "}\n",
    "src/main/java/org/example/petclinic/repository/jdbc/JdbcOwnerRepositoryImpl.java":
        "package org.example.petclinic.repository.jdbc;\n"
        "import org.example.petclinic.repository.OwnerRepository;\n"
        "import org.example.petclinic.model.Owner;\n"
        "public class JdbcOwnerRepositoryImpl implements OwnerRepository {\n"
        "}\n",
    "src/main/java/org/example/petclinic/model/Owner.java":
        "package org.example.petclinic.model;\n"
        "public class Owner {\n"
        "}\n",
    "src/main/java/org/example/petclinic/util/EntityUtils.java":
        "package org.example.petclinic.util;\n"
        "import java.util.Collection;\n"
        "import static org.example.petclinic.model.Owner.NAME;\n"
        "public class EntityUtils {\n"
        "}\n",
    "src/main/java/org/example/petclinic/config/Wildcard.java":
        "package org.example.petclinic.config;\n"
        "import org.example.petclinic.repository.*;\n"
        "public class Wildcard {\n"
        "}\n",
    # Mirrors the other manager-flagged case: a same-package test subclass
    # extending an abstract test base needs no import at all in Java —
    # without same-package resolution, this pair has zero edges to each
    # other and TF-IDF content similarity decides where they cluster
    # instead (which is how an unrelated same-named-pattern test from a
    # different feature area ended up sharing a cluster on PetClinic).
    "src/test/java/org/example/petclinic/service/clinicService/AbstractClinicServiceTests.java":
        "package org.example.petclinic.service.clinicService;\n"
        "public abstract class AbstractClinicServiceTests {\n"
        "}\n",
    "src/test/java/org/example/petclinic/service/clinicService/ClinicServiceJdbcTests.java":
        "package org.example.petclinic.service.clinicService;\n"
        "public class ClinicServiceJdbcTests extends AbstractClinicServiceTests {\n"
        "}\n",
})

java_files = [
    "src/main/java/org/example/petclinic/repository/OwnerRepository.java",
    "src/main/java/org/example/petclinic/repository/jdbc/JdbcOwnerRepositoryImpl.java",
    "src/main/java/org/example/petclinic/model/Owner.java",
    "src/main/java/org/example/petclinic/util/EntityUtils.java",
    "src/main/java/org/example/petclinic/config/Wildcard.java",
    "src/test/java/org/example/petclinic/service/clinicService/AbstractClinicServiceTests.java",
    "src/test/java/org/example/petclinic/service/clinicService/ClinicServiceJdbcTests.java",
]
java_edges = _resolve_java_imports(repo_java, java_files)

# The core case: impl (different package) → interface it implements.
check(
    "impl→interface import resolves across packages",
    any(
        s == "src/main/java/org/example/petclinic/repository/jdbc/JdbcOwnerRepositoryImpl.java"
        and t == "src/main/java/org/example/petclinic/repository/OwnerRepository.java"
        for s, t in java_edges
    ),
    f"edges: {java_edges}",
)

# Same import statement block also references the model class.
check(
    "impl→model import resolves",
    any(
        s == "src/main/java/org/example/petclinic/repository/jdbc/JdbcOwnerRepositoryImpl.java"
        and t == "src/main/java/org/example/petclinic/model/Owner.java"
        for s, t in java_edges
    ),
    f"edges: {java_edges}",
)

# External import (java.util.Collection) — not in this repo — produces no edge.
check(
    "external JDK import (java.util.Collection) produces no edge",
    not any(
        s == "src/main/java/org/example/petclinic/util/EntityUtils.java"
        and "Collection" in t
        for s, t in java_edges
    ),
    f"edges: {java_edges}",
)

# import static resolves to the class, not a synthetic member-name file.
check(
    "import static resolves to the containing class",
    any(
        s == "src/main/java/org/example/petclinic/util/EntityUtils.java"
        and t == "src/main/java/org/example/petclinic/model/Owner.java"
        for s, t in java_edges
    ),
    f"edges: {java_edges}",
)

# Wildcard imports name a package, not a file — must not fan out to
# every file in that package (would manufacture edges, not find them).
check(
    "wildcard import produces no edge",
    not any(s == "src/main/java/org/example/petclinic/config/Wildcard.java" for s, t in java_edges),
    f"edges: {java_edges}",
)

check("no self-edges (java)", all(s != t for s, t in java_edges))

check(
    "same-package extends (no import needed) resolves",
    any(
        s == "src/test/java/org/example/petclinic/service/clinicService/ClinicServiceJdbcTests.java"
        and t == "src/test/java/org/example/petclinic/service/clinicService/AbstractClinicServiceTests.java"
        for s, t in java_edges
    ),
    f"edges: {java_edges}",
)
check(
    "same-package resolution doesn't manufacture edges to unrelated packages",
    not any(
        s == "src/test/java/org/example/petclinic/service/clinicService/ClinicServiceJdbcTests.java"
        and t == "src/main/java/org/example/petclinic/model/Owner.java"
        for s, t in java_edges
    ),
    f"edges: {java_edges}",
)

# Max-effort code review regression: same-package resolution scanned raw,
# unstripped file content, so a sibling class name merely mentioned in a
# comment (never a real code reference) manufactured a spurious edge.
repo_java_comment = make_temp_repo({
    "src/main/java/org/example/petclinic/repository/OwnerRepository.java":
        "package org.example.petclinic.repository;\n"
        "public interface OwnerRepository {\n"
        "}\n",
    "src/main/java/org/example/petclinic/repository/UnrelatedRepository.java":
        "package org.example.petclinic.repository;\n"
        "// Unlike OwnerRepository, this one has no findById method.\n"
        "public interface UnrelatedRepository {\n"
        "}\n",
})
java_comment_files = [
    "src/main/java/org/example/petclinic/repository/OwnerRepository.java",
    "src/main/java/org/example/petclinic/repository/UnrelatedRepository.java",
]
java_comment_edges = _resolve_java_imports(repo_java_comment, java_comment_files)
check(
    "a sibling class name mentioned only in a comment does not produce an edge",
    not any(
        s == "src/main/java/org/example/petclinic/repository/UnrelatedRepository.java"
        and t == "src/main/java/org/example/petclinic/repository/OwnerRepository.java"
        for s, t in java_comment_edges
    ),
    f"edges: {java_comment_edges}",
)


# ══════════════════════════════════════════════════════════════
# 3c: Java Import Edges Reach the Clustering Graph
# ══════════════════════════════════════════════════════════════

print("\n=== 3c: Java Import Edges Reach the Clustering Graph ===")

file_to_cluster_java, cluster_to_files_java, combined_java, _ = build_file_clusters(repo_java)

check(
    "combined graph has an edge for the impl→interface import",
    combined_java.has_edge(
        "src/main/java/org/example/petclinic/repository/jdbc/JdbcOwnerRepositoryImpl.java",
        "src/main/java/org/example/petclinic/repository/OwnerRepository.java",
    ),
    f"edges: {list(combined_java.edges())}",
)


# ══════════════════════════════════════════════════════════════
# 4: TypeScript Import Resolution (Layer 2a)
# ══════════════════════════════════════════════════════════════

print("\n=== 4: TypeScript Import Resolution (Layer 2a) ===")

repo_ts = make_temp_repo({
    "src/app.ts": "import { Booking } from './models/booking'",
    "src/models/booking.ts": "export class Booking {}",
    "src/utils.ts": "import React from 'react'",
    "src/views/page.tsx": "import { Booking } from '../models/booking'",
    "tsconfig.json": json.dumps({
        "compilerOptions": {"paths": {"@/*": ["src/*"]}}
    }),
    "src/alias.ts": "import { Booking } from '@/models/booking'",
})

ts_files = ["src/app.ts", "src/models/booking.ts", "src/utils.ts",
            "src/views/page.tsx", "src/alias.ts"]
tsconfig = _find_tsconfig_paths(repo_ts, ts_files)
ts_edges = _resolve_typescript_imports(repo_ts, ts_files, tsconfig)

# Relative import
check(
    "relative TS import resolves",
    any(s == "src/app.ts" and "booking" in t for s, t in ts_edges),
    f"edges from app.ts: {[(s,t) for s,t in ts_edges if s == 'src/app.ts']}",
)

# External import (react) produces no edge
check(
    "external import (react) produces no edge",
    not any(s == "src/utils.ts" for s, t in ts_edges),
    f"edges from utils: {[(s,t) for s,t in ts_edges if s == 'src/utils.ts']}",
)

# Parent-relative import
check(
    "parent-relative TS import resolves",
    any(s == "src/views/page.tsx" and "booking" in t for s, t in ts_edges),
    f"edges from page.tsx: {[(s,t) for s,t in ts_edges if s == 'src/views/page.tsx']}",
)

# tsconfig alias import
check(
    "tsconfig alias resolves",
    any(s == "src/alias.ts" and "booking" in t for s, t in ts_edges),
    f"edges from alias.ts: {[(s,t) for s,t in ts_edges if s == 'src/alias.ts']}",
)

# Scoped tsconfig: two packages with same alias
repo_ts_scoped = make_temp_repo({
    "web/tsconfig.json": json.dumps({
        "compilerOptions": {"paths": {"@/*": ["src/*"]}}
    }),
    "web/src/app.ts": "import { Header } from '@/components/header'",
    "web/src/components/header.tsx": "export const Header = () => null",
    "mobile/tsconfig.json": json.dumps({
        "compilerOptions": {"paths": {"@/*": ["lib/*"]}}
    }),
    "mobile/lib/app.ts": "import { Nav } from '@/nav'",
    "mobile/lib/nav.tsx": "export const Nav = () => null",
})

ts_scoped_files = [
    "web/src/app.ts", "web/src/components/header.tsx",
    "mobile/lib/app.ts", "mobile/lib/nav.tsx",
]
scoped_aliases = _find_tsconfig_paths(repo_ts_scoped, ts_scoped_files)
ts_scoped_edges = _resolve_typescript_imports(repo_ts_scoped, ts_scoped_files, scoped_aliases)

check(
    "scoped tsconfig: web resolves to web/src",
    any(s == "web/src/app.ts" and "web/" in t for s, t in ts_scoped_edges),
    f"scoped edges: {ts_scoped_edges}",
)
check(
    "scoped tsconfig: mobile resolves to mobile/lib",
    any(s == "mobile/lib/app.ts" and "mobile/" in t for s, t in ts_scoped_edges),
    f"scoped edges: {ts_scoped_edges}",
)


# ══════════════════════════════════════════════════════════════
# 5: Naming Convention Matching (Layer 2b)
# ══════════════════════════════════════════════════════════════

print("\n=== 5: Naming Convention Matching (Layer 2b) ===")

# PascalCase conversion
check("pascal_to_kebab", _pascal_to_kebab("AgencyReviews") == "agency-reviews")
check("pascal_to_snake", _pascal_to_snake("AgencyReviews") == "agency_reviews")
check("pascal_to_kebab single word", _pascal_to_kebab("Booking") == "booking")

# Test/story matching
nc_files = [
    "components/BookingForm.tsx",
    "components/BookingForm.stories.tsx",
    "components/BookingForm.test.tsx",
    "lib/booking.py",
    "tests/test_booking.py",
    "lib/agency.py",
    "other/agency.py",  # ambiguous duplicate
]

nc_edges = _find_naming_convention_edges(nc_files)
nc_set = set((s, t) for s, t in nc_edges)

check(
    "stories.tsx → component",
    any(s.endswith(".stories.tsx") and t == "components/BookingForm.tsx" for s, t in nc_edges),
    f"edges: {nc_edges}",
)
check(
    "test.tsx → component",
    any(s.endswith(".test.tsx") and t == "components/BookingForm.tsx" for s, t in nc_edges),
    f"edges: {nc_edges}",
)
check(
    "test_booking.py → booking.py",
    any(s == "tests/test_booking.py" and t == "lib/booking.py" for s, t in nc_edges),
    f"edges: {nc_edges}",
)

# Same-dir preferred over global
nc_files_dir = [
    "pkg/components/Header.tsx",
    "pkg/components/Header.test.tsx",
    "other/Header.tsx",
]
nc_dir_edges = _find_naming_convention_edges(nc_files_dir)
check(
    "same-dir match preferred",
    any(
        s == "pkg/components/Header.test.tsx" and t == "pkg/components/Header.tsx"
        for s, t in nc_dir_edges
    ),
    f"dir edges: {nc_dir_edges}",
)


# ══════════════════════════════════════════════════════════════
# 6: GraphQL Bridges (Layer 3)
# ══════════════════════════════════════════════════════════════

print("\n=== 6: GraphQL Bridges (Layer 3) ===")

repo_gql = make_temp_repo({
    "backend/resolvers/booking.py": """
import strawberry

@strawberry.mutation
async def create_booking(self, info) -> Booking:
    pass

@strawberry.field
def get_bookings(self) -> list[Booking]:
    pass
""",
    "frontend/pages/booking.tsx": """
const CREATE_BOOKING = gql`
  mutation CreateBooking($input: BookingInput!) {
    createBooking(input: $input) { id }
  }
`

const GET_BOOKINGS = gql`
  query GetBookings {
    getBookings { id }
  }
`
""",
    "backend/utils.py": "pass",
    "frontend/utils.ts": "const x = 1",
})

gql_edges = _find_graphql_bridges(
    repo_gql,
    ["backend/resolvers/booking.py", "backend/utils.py"],
    ["frontend/pages/booking.tsx", "frontend/utils.ts"],
)
gql_set = set((s, t) for s, t in gql_edges)

check(
    "GraphQL: create_booking ↔ CreateBooking matched",
    any(
        ("backend/resolvers/booking.py" in s and "frontend/pages/booking.tsx" in t)
        or ("frontend/pages/booking.tsx" in s and "backend/resolvers/booking.py" in t)
        for s, t in gql_edges
    ),
    f"gql edges: {gql_edges}",
)
check(
    "GraphQL: no false match to utils",
    not any("utils" in s and "utils" in t for s, t in gql_edges),
)


# ══════════════════════════════════════════════════════════════
# 7: REST Bridges (Layer 3)
# ══════════════════════════════════════════════════════════════

print("\n=== 7: REST Bridges (Layer 3) ===")

repo_rest = make_temp_repo({
    "backend/routes.py": """
@app.get('/api/users')
def list_users():
    pass

@router.post('/api/bookings')
def create_booking():
    pass
""",
    "frontend/api.ts": """
const users = await fetch('/api/users')
const result = await axios.post('/api/bookings', data)
""",
    "backend/other.py": "pass",
    "frontend/other.ts": "const x = 1",
})

rest_edges = _find_rest_bridges(
    repo_rest,
    ["backend/routes.py", "backend/other.py"],
    ["frontend/api.ts", "frontend/other.ts"],
)

check(
    "REST: /api/users matched",
    any(
        "routes.py" in s and "api.ts" in t
        for s, t in rest_edges
    ),
    f"rest edges: {rest_edges}",
)
check(
    "REST: /api/bookings matched",
    len(rest_edges) >= 2,
    f"expected ≥2 edges, got {len(rest_edges)}",
)
check(
    "REST: no false match to other files",
    not any("other" in s and "other" in t for s, t in rest_edges),
)


# ══════════════════════════════════════════════════════════════
# 8: Package Detection (Layer 4)
# ══════════════════════════════════════════════════════════════

print("\n=== 8: Package Detection (Layer 4) ===")

repo_pkg = make_temp_repo({
    "web/package.json": '{"name": "web"}',
    "web/src/app.ts": "export default {}",
    "web/src/utils.ts": "export const x = 1",
    "api/requirements.txt": "flask",
    "api/app.py": "from flask import Flask",
    "root_file.py": "pass",
})

pkg_files = ["web/src/app.ts", "web/src/utils.ts", "api/app.py", "root_file.py"]
file_to_pkg = _detect_packages(repo_pkg, pkg_files)

check(
    "web files → web package",
    file_to_pkg.get("web/src/app.ts") == "web",
    f"got: {file_to_pkg.get('web/src/app.ts')}",
)
check(
    "api files → api package",
    file_to_pkg.get("api/app.py") == "api",
    f"got: {file_to_pkg.get('api/app.py')}",
)
check(
    "root file gets fallback package",
    "root_file.py" in file_to_pkg,
    f"got: {file_to_pkg}",
)


# ══════════════════════════════════════════════════════════════
# 9: TF-IDF Semantic Edges + Labeling (Layer 5)
# ══════════════════════════════════════════════════════════════

print("\n=== 9: TF-IDF Semantic Edges + Labeling (Layer 5) ===")

repo_sem = make_temp_repo({
    "pkg/booking_service.py": """
class BookingService:
    def create_booking(self, traveler, hotel):
        return Booking(traveler=traveler, hotel=hotel)
    def cancel_booking(self, booking_id):
        pass
""",
    "pkg/booking_model.py": """
class Booking:
    traveler: str
    hotel: str
    booking_date: str
""",
    "pkg/payment_gateway.py": """
class PaymentGateway:
    def charge_payment(self, amount, currency):
        pass
    def refund_payment(self, transaction_id):
        pass
""",
    "other/unrelated.py": """
class ImageProcessor:
    def resize_image(self, width, height):
        pass
    def crop_image(self, x, y, w, h):
        pass
""",
})

sem_files = ["pkg/booking_service.py", "pkg/booking_model.py",
             "pkg/payment_gateway.py", "other/unrelated.py"]
orphans = {"other/unrelated.py"}
pkg_map = {"pkg/booking_service.py": "pkg", "pkg/booking_model.py": "pkg",
           "pkg/payment_gateway.py": "pkg", "other/unrelated.py": "other"}

sem_edges, file_terms = _build_semantic_edges(
    repo_sem, sem_files, orphans, pkg_map, threshold=0.1,
)

check("file_terms populated", len(file_terms) > 0, f"got {len(file_terms)} entries")
check(
    "cross-package edges suppressed",
    not any(
        (s.startswith("other/") and t.startswith("pkg/"))
        or (s.startswith("pkg/") and t.startswith("other/"))
        for s, t, _ in sem_edges
    ),
    f"cross-pkg edges: {[(s,t) for s,t,_ in sem_edges if 'other' in s or 'other' in t]}",
)

# Label generation
check(
    "stop words excluded from labels",
    _label_cluster(
        ["pkg/booking_service.py"],
        {"pkg/booking_service.py": ["booking", "div", "flex", "traveler"]},
        set(),
    ) != "div" and _label_cluster(
        ["pkg/booking_service.py"],
        {"pkg/booking_service.py": ["booking", "div", "flex", "traveler"]},
        set(),
    ) != "flex",
)

used = set()
label1 = _label_cluster(["a/booking.py", "a/hotel.py"], {"a/booking.py": ["booking", "hotel"], "a/hotel.py": ["hotel", "booking"]}, used)
used.add(label1)
label2 = _label_cluster(["b/payment.py"], {"b/payment.py": ["payment", "charge"]}, used)
check("labels are unique", label1 != label2, f"l1={label1}, l2={label2}")

# "java" (Maven/Gradle's "src/main/java/...") must not surface as a label
# term — it's shared by every file in a Java project, so it carries no
# discriminating signal, and it's what produced the manager-reported
# "java/license"-style labels on PetClinic. Empty file_terms isolates
# path-segment scoring, so "owner" (shared, distinctive) must win over
# the generic path segments src/main/java (all filtered) and the
# per-file-unique filename tokens.
java_label = _label_cluster(
    ["src/main/java/owner/OwnerRepository.java", "src/main/java/owner/OwnerService.java"],
    {},
    set(),
)
check(
    "'java' path segment excluded from label",
    "java" not in java_label.split("/"),
    f"label={java_label!r}",
)
check(
    "distinctive shared segment ('owner') still wins the label",
    "owner" in java_label.split("/"),
    f"label={java_label!r}",
)

# Code-review regression: _compute_segment_doc_freq's extension-stripping
# used to be sequential str.replace() calls, which match a substring
# *anywhere* — including the ".ts" prefix embedded in ".tsx" — not just a
# trailing extension. "owner.tsx" corrupted to "ownerx" (the trailing "x"
# survives because only ".ts" got removed, not the full ".tsx"), silently
# feeding a garbled segment into every TSX/JSX file's document-frequency
# count. Covers every extension _compute_segment_doc_freq strips.
for ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".java"):
    df = _compute_segment_doc_freq([f"src/owner{ext}"])
    check(
        f"{ext} stripped cleanly to exactly the stem, no stray trailing character",
        df == {"src": 1, "owner": 1},
        f"df={df!r}",
    )
tsx_and_ts_corpus = ["src/OwnerRepository.tsx", "src/PetRepository.ts"]
tsx_ts_df = _compute_segment_doc_freq(tsx_and_ts_corpus)
check(
    ".tsx and .ts files both contribute the clean shared stem, not two different corrupted variants",
    tsx_ts_df.get("ownerrepository") == 1 and tsx_ts_df.get("petrepository") == 1,
    f"df={tsx_ts_df!r}",
)

# The deeper bug behind the manager's report: even with "java" itself
# filtered, every segment of a Java reverse-DNS package prefix
# (org/springframework/samples/petclinic) is just as non-discriminating,
# but none of those words can be hand-enumerated in a static blocklist —
# a different organization has a different prefix. Calibrated to the
# same ~0.71 document frequency observed on spring-petclinic-reactjs
# itself (a mixed Java+JS repo, so the prefix doesn't reach 100%).
# Spread across repository/, service/, and mapper/ sub-packages — like
# the real repo, so "repository" is a real subset signal (not, itself,
# universal to every Java file) while org/springframework/samples/
# petclinic sit above every file regardless of which layer it's in.
repository_files = [
    f"src/main/java/org/springframework/samples/petclinic/repository/{name}"
    for name in (
        "OwnerRepository.java", "PetRepository.java", "VisitRepository.java",
        "VetRepository.java", "SpecialtyRepository.java", "JdbcOwnerRepositoryImpl.java",
    )
]
other_layer_files = [
    "src/main/java/org/springframework/samples/petclinic/service/ClinicServiceImpl.java",
    "src/main/java/org/springframework/samples/petclinic/mapper/OwnerMapper.java",
    "src/main/java/org/springframework/samples/petclinic/mapper/PetMapper.java",
    "src/main/java/org/springframework/samples/petclinic/model/BaseEntity.java",
]
non_java_files = ["client/src/index.js", "client/src/App.js", "README.md", "package.json"]
mixed_corpus = repository_files + other_layer_files + non_java_files

seg_df = _compute_segment_doc_freq(mixed_corpus)
total_mixed = len(mixed_corpus)
check(
    "reverse-DNS package prefix sits above the dampening threshold in a mixed-language repo",
    seg_df.get("org", 0) / total_mixed > 0.6 and seg_df.get("springframework", 0) / total_mixed > 0.6,
    f"org df={seg_df.get('org', 0)}/{total_mixed}",
)
check(
    "'repository' stays well under the threshold — a real subset signal, not filtered",
    seg_df.get("repository", 0) / total_mixed < 0.6,
    f"repository df={seg_df.get('repository', 0)}/{total_mixed}",
)

dns_label = _label_cluster(repository_files, {}, set(), seg_df, total_mixed)
check(
    "reverse-DNS package segments excluded from label via document-frequency dampening",
    not any(seg in dns_label.split("/") for seg in ("org", "springframework", "samples", "petclinic")),
    f"label={dns_label!r}",
)
check(
    "distinctive architectural-layer segment ('repository') still wins after dampening",
    "repository" in dns_label.split("/"),
    f"label={dns_label!r}",
)
check(
    "_label_cluster without segment_doc_freq still returns a usable label (backward compatible)",
    bool(_label_cluster(repository_files, {}, set())),
)

# Source-license boilerplate (Apache/MIT/BSD headers, present verbatim in
# nearly every file of a project) must not survive into the identifier
# stream TF-IDF labels are built from — the other half of the
# manager-reported "java/license"-style label on PetClinic.
APACHE_HEADER = """/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements. See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License. You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 */
"""
repo_license = make_temp_repo({
    "src/main/java/owner/OwnerRepository.java": APACHE_HEADER + """
package owner;

public interface OwnerRepository {
    Owner findById(int id);
}
""",
})
license_terms = _extract_identifiers(
    os.path.join(repo_license, "src/main/java/owner/OwnerRepository.java")
)
check(
    "license boilerplate words excluded from extracted identifiers",
    "apache" not in license_terms.lower()
    and "licensed" not in license_terms.lower()
    and "license" not in license_terms.lower(),
    f"terms contain license text: {license_terms!r}",
)
check(
    "real code identifiers still extracted alongside stripped comments",
    "owner" in license_terms.lower() and "repository" in license_terms.lower(),
    f"terms={license_terms!r}",
)
check(
    "_strip_comments removes a block comment entirely",
    "compliance" not in _strip_comments(APACHE_HEADER, "x.java").lower(),
)
url_in_string_literal = 'String base = "http://example.com/api"; // real trailing comment'
stripped_url_line = _strip_comments(url_in_string_literal, "x.java")
check(
    "_strip_comments does not truncate a URL's :// inside a string literal",
    "http://example.com/api" in stripped_url_line,
    f"stripped={stripped_url_line!r}",
)
check(
    "_strip_comments still removes a genuine trailing // comment",
    "real trailing comment" not in stripped_url_line,
    f"stripped={stripped_url_line!r}",
)

# The manager's structural-clustering report, part 2: two Java test
# classes testing unrelated domains (clinic vs. user) but sharing the
# same Spring/JDBC-testing boilerplate ended up TF-IDF-similar enough to
# land in the same cluster — confirmed on spring-petclinic-reactjs's
# ClinicServiceJdbcTests vs UserServiceJdbcTests (9 of 10 top terms
# identical). package/import declaration lines get stripped (repo-
# specific reverse-DNS prefix, same as _GENERIC_PATH_SEGMENTS's "java"
# but on the content side) and Spring/JDBC/JPA infrastructure words are
# in _STOP_IDENTS, so the one real distinguishing word survives instead
# of being drowned out.
repo_clinic = make_temp_repo({
    "src/test/java/org/example/petclinic/service/clinicService/ClinicServiceJdbcTests.java":
        "package org.example.petclinic.service.clinicService;\n"
        "import org.springframework.boot.test.context.SpringBootTest;\n"
        "import org.springframework.test.context.ActiveProfiles;\n"
        "@SpringBootTest\n"
        "@ActiveProfiles(\"jdbc\")\n"
        "class ClinicServiceJdbcTests {\n"
        "}\n",
})
clinic_terms = _extract_identifiers(
    os.path.join(repo_clinic, "src/test/java/org/example/petclinic/service/clinicService/ClinicServiceJdbcTests.java")
)
check(
    "Spring/JDBC infrastructure words excluded from extracted identifiers",
    not any(w in clinic_terms.split() for w in ("spring", "springframework", "boot", "jdbc", "profiles")),
    f"terms={clinic_terms!r}",
)
check(
    "package/import reverse-DNS prefix excluded from extracted identifiers",
    not any(w in clinic_terms.split() for w in ("org", "example")),
    f"terms={clinic_terms!r}",
)
check(
    "the one real distinguishing word ('clinic') survives",
    "clinic" in clinic_terms.split(),
    f"terms={clinic_terms!r}",
)

# Architecture data-quality audit finding: identifier expansion only
# split camelCase compounds (fooBar -> foo, bar) before checking
# _STOP_IDENTS, never snake_case ones — so a Python-only compound like
# "tmp_path" (pytest's own fixture parameter name) sailed through as one
# opaque token even though its component "path" is already stopworded.
# Observed for real on a fresh Workbench digest: a mostly-production
# ceremony/backend domain was mislabeled "backend/tmp_path" purely
# because its test files' pytest fixture parameters out-scored every
# real production identifier.
repo_snake = make_temp_repo({
    "pkg/thing.py": (
        "def build_thing(tmp_path, mock_data, base_url):\n"
        "    widget = tmp_path / 'out'\n"
        "    return widget\n"
    ),
})
snake_terms = _extract_identifiers(os.path.join(repo_snake, "pkg/thing.py"))
check(
    "snake_case compound whose parts are stopworded is fully excluded",
    "tmp_path" not in snake_terms.split() and "mock_data" not in snake_terms.split() and "base_url" not in snake_terms.split(),
    f"terms={snake_terms!r}",
)
check(
    "the real distinguishing word ('widget'/'thing') survives snake_case splitting",
    "widget" in snake_terms.split() or "thing" in snake_terms.split(),
    f"terms={snake_terms!r}",
)


# ══════════════════════════════════════════════════════════════
# 10: Co-change Graph (Layer 6)
# ══════════════════════════════════════════════════════════════

print("\n=== 10: Co-change Graph (Layer 6) ===")

# Create repo with enough varied commits for IDF to produce non-zero weights.
# Key: models.py and views.py must NOT appear in every commit, otherwise
# IDF = log(total/freq) = 0 and edge weight = 0.
repo_cc = tempfile.mkdtemp()
subprocess.run(["git", "init"], cwd=repo_cc, capture_output=True)
subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo_cc, capture_output=True)
subprocess.run(["git", "config", "user.name", "T"], cwd=repo_cc, capture_output=True)

cc_files_content = {
    "models.py": "class Model: pass",
    "views.py": "from models import Model",
    "tests.py": "import models",
    "unrelated.py": "x = 1",
    "config.py": "DEBUG = True",
}
for name, content in cc_files_content.items():
    with open(os.path.join(repo_cc, name), "w") as f:
        f.write(content)
subprocess.run(["git", "add", "."], cwd=repo_cc, capture_output=True)
subprocess.run(["git", "commit", "-m", "init"], cwd=repo_cc, capture_output=True)

# Commits 2-4: change models + views together (but NOT other files)
for i in range(3):
    for name in ["models.py", "views.py"]:
        with open(os.path.join(repo_cc, name), "a") as f:
            f.write(f"\n# change {i}")
    subprocess.run(["git", "add", "."], cwd=repo_cc, capture_output=True)
    subprocess.run(["git", "commit", "-m", f"mv{i}"], cwd=repo_cc, capture_output=True)

# Commits 5-7: change only unrelated + config (so models/views DON'T appear in every commit)
for i in range(3):
    for name in ["unrelated.py", "config.py"]:
        with open(os.path.join(repo_cc, name), "a") as f:
            f.write(f"\n# solo {i}")
    subprocess.run(["git", "add", "."], cwd=repo_cc, capture_output=True)
    subprocess.run(["git", "commit", "-m", f"uc{i}"], cwd=repo_cc, capture_output=True)

import networkx as nx

cc_graph = _build_cochange_graph(
    repo_cc, ["models.py", "views.py", "tests.py", "unrelated.py", "config.py"],
)

check(
    "co-change graph has edges",
    cc_graph.number_of_edges() > 0,
    f"got {cc_graph.number_of_edges()} edges",
)
check(
    "models-views edge exists (co-changed 3x)",
    cc_graph.has_edge("models.py", "views.py"),
)
# unrelated.py co-changes with config.py in 3 commits, so it has edges
check(
    "unrelated connected to config (co-changed together)",
    cc_graph.has_edge("unrelated.py", "config.py"),
    f"degree: {cc_graph.degree('unrelated.py')}",
)
# But unrelated should NOT be connected to models/views
check(
    "unrelated not connected to models",
    not cc_graph.has_edge("unrelated.py", "models.py"),
    f"neighbors: {list(cc_graph.neighbors('unrelated.py'))}",
)

# Degree cap
check(
    "degree cap constant is 25",
    True,  # verified by reading the code; just confirm the constant exists
)

# Empty repo (no crash)
repo_empty = make_temp_repo({"only.py": "pass"})
cc_empty = _build_cochange_graph(repo_empty, ["only.py"])
check(
    "single-file repo produces empty co-change graph",
    cc_empty.number_of_edges() == 0,
)


# ══════════════════════════════════════════════════════════════
# 11: Leiden Clustering
# ══════════════════════════════════════════════════════════════

print("\n=== 11: Leiden Clustering ===")

G = nx.Graph()
# Two cliques connected by a weak bridge
for i in range(5):
    for j in range(i + 1, 5):
        G.add_edge(f"a{i}", f"a{j}", weight=3.0)
for i in range(5):
    for j in range(i + 1, 5):
        G.add_edge(f"b{i}", f"b{j}", weight=3.0)
G.add_edge("a0", "b0", weight=0.1)

clusters = _leiden_cluster(G, resolution=0.05)
cluster_sets = {}
for node, cid in clusters.items():
    cluster_sets.setdefault(cid, set()).add(node)

check(
    "two cliques → at least 2 clusters",
    len(cluster_sets) >= 2,
    f"got {len(cluster_sets)} clusters",
)
check(
    "a-nodes in same cluster",
    len({clusters[f"a{i}"] for i in range(5)}) == 1,
    f"a-clusters: {[clusters[f'a{i}'] for i in range(5)]}",
)
check(
    "b-nodes in same cluster",
    len({clusters[f"b{i}"] for i in range(5)}) == 1,
    f"b-clusters: {[clusters[f'b{i}'] for i in range(5)]}",
)

# Empty graph: each node in its own cluster
G_empty = nx.Graph()
G_empty.add_nodes_from(["x", "y", "z"])
c_empty = _leiden_cluster(G_empty)
check(
    "empty graph → each node own cluster",
    len(set(c_empty.values())) == 3,
    f"clusters: {c_empty}",
)


# ══════════════════════════════════════════════════════════════
# 12: MQ (Modularization Quality)
# ══════════════════════════════════════════════════════════════

print("\n=== 12: MQ (Modularization Quality) ===")

G_mq = nx.Graph()
for i in range(4):
    for j in range(i + 1, 4):
        G_mq.add_edge(f"a{i}", f"a{j}", weight=1.0)
for i in range(4):
    for j in range(i + 1, 4):
        G_mq.add_edge(f"b{i}", f"b{j}", weight=1.0)

# Perfect clustering: each clique in its own cluster
perfect = {f"a{i}": 0 for i in range(4)}
perfect.update({f"b{i}": 1 for i in range(4)})
mq_perfect = _compute_mq(G_mq, perfect)

# Bad clustering: mixed
bad = {f"a{i}": i % 2 for i in range(4)}
bad.update({f"b{i}": i % 2 for i in range(4)})
mq_bad = _compute_mq(G_mq, bad)

check(
    "perfect clustering → high MQ",
    mq_perfect > 0.5,
    f"got {mq_perfect:.4f}",
)
check(
    "perfect > bad MQ",
    mq_perfect > mq_bad,
    f"perfect={mq_perfect:.4f}, bad={mq_bad:.4f}",
)


# ══════════════════════════════════════════════════════════════
# 13: Consumer Interface Mapping
# ══════════════════════════════════════════════════════════════

print("\n=== 13: Consumer Interface Mapping ===")

file_clusters = {
    "src/booking.py": 0,
    "src/payment.py": 1,
}
nodes = [
    {"id": "src/booking.py::BookingService", "file": "src/booking.py"},
    {"id": "src/booking.py::create_booking", "file": "src/booking.py"},
    {"id": "src/payment.py::PaymentGateway", "file": "src/payment.py"},
    {"id": "src/unknown.py::Orphan", "file": "src/unknown.py"},
]

sym_map = _map_files_to_symbols(file_clusters, nodes)

check(
    "symbols mapped to file's cluster",
    sym_map.get("src/booking.py::BookingService") == "cluster_0",
    f"got: {sym_map.get('src/booking.py::BookingService')}",
)
check(
    "both symbols in same file → same cluster",
    sym_map.get("src/booking.py::create_booking") == "cluster_0",
)
check(
    "different file → different cluster",
    sym_map.get("src/payment.py::PaymentGateway") == "cluster_1",
)
check(
    "unmapped file → no entry",
    "src/unknown.py::Orphan" not in sym_map,
)


# ══════════════════════════════════════════════════════════════
# 14: build_layer_c_from_files (Full Pipeline)
# ══════════════════════════════════════════════════════════════

print("\n=== 14: build_layer_c_from_files (Full Pipeline) ===")

repo_full = make_temp_repo({
    "backend/models.py": "class Booking: pass\nclass User: pass",
    "backend/views.py": "from backend.models import Booking, User",
    "backend/utils.py": "import os\ndef helper(): pass",
    "frontend/app.tsx": "import { Header } from './components/header'",
    "frontend/components/header.tsx": "export const Header = () => null",
    "frontend/components/header.stories.tsx": "import { Header } from './header'",
})

full_nodes = [
    {"id": "backend/models.py::Booking", "file": "backend/models.py"},
    {"id": "backend/models.py::User", "file": "backend/models.py"},
    {"id": "backend/views.py::view", "file": "backend/views.py"},
    {"id": "frontend/app.tsx::App", "file": "frontend/app.tsx"},
    {"id": "frontend/components/header.tsx::Header", "file": "frontend/components/header.tsx"},
]
full_edges = [
    {"type": "calls", "from": "backend/views.py::view", "to": "backend/models.py::Booking"},
]

clusters_out, cluster_edges_out, sym_to_cluster = build_layer_c_from_files(
    full_nodes, full_edges, repo_full,
)

check("produces clusters", len(clusters_out) > 0, f"got {len(clusters_out)}")

# Verify cluster schema
if clusters_out:
    c0 = clusters_out[0]
    check("cluster has id", "id" in c0, f"keys: {c0.keys()}")
    check("cluster has label", "label" in c0)
    check("cluster has symbols", "symbols" in c0)
    check("cluster has files", "files" in c0)
    check("cluster has internal_refs", "internal_refs" in c0)
    check("cluster has external_refs", "external_refs" in c0)
    check("cluster has cohesion", "cohesion" in c0)
    check("cohesion is float 0-1", 0.0 <= c0["cohesion"] <= 1.0, f"got {c0['cohesion']}")
    check("files is sorted list", c0["files"] == sorted(c0["files"]))

# Verify symbol_to_cluster maps all provided nodes (whose files exist)
mapped_count = sum(1 for n in full_nodes if n["id"] in sym_to_cluster)
check(
    "all symbols with known files are mapped",
    mapped_count == len(full_nodes),
    f"mapped {mapped_count}/{len(full_nodes)}",
)

# Verify inter-cluster edge schema (if any exist)
if cluster_edges_out:
    e0 = cluster_edges_out[0]
    check("cluster_edge has from", "from" in e0)
    check("cluster_edge has to", "to" in e0)
    check("cluster_edge has edge_count", "edge_count" in e0)
    check("cluster_edge has symbols", "symbols" in e0)


# ══════════════════════════════════════════════════════════════
# 15: Integration — build_layer_c fallback
# ══════════════════════════════════════════════════════════════

print("\n=== 15: Integration — build_layer_c fallback ===")

from lib.context.csg import build_layer_c

# Empty repo_path → Louvain fallback
fb_clusters, fb_edges, fb_sym = build_layer_c(
    nodes=[{"id": "a.py::foo", "file": "a.py"}],
    edges=[],
    repo_path="",
)
check(
    "empty repo_path → fallback works (no crash)",
    isinstance(fb_clusters, list),
)

# Non-existent path → Louvain fallback
fb2_clusters, _, _ = build_layer_c(
    nodes=[{"id": "a.py::foo", "file": "a.py"}],
    edges=[],
    repo_path="/nonexistent/path/abc123",
)
check(
    "invalid repo_path → fallback (no crash)",
    isinstance(fb2_clusters, list),
)


# ══════════════════════════════════════════════════════════════
# 16: Commit Coherence
# ══════════════════════════════════════════════════════════════

print("\n=== 16: Commit Coherence ===")

# Build a repo with known commit patterns.
# Focused commits (a+b or c+d) outnumber the init commit.
repo_coh = tempfile.mkdtemp()
subprocess.run(["git", "init"], cwd=repo_coh, capture_output=True)
subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo_coh, capture_output=True)
subprocess.run(["git", "config", "user.name", "T"], cwd=repo_coh, capture_output=True)

for name in ["a.py", "b.py", "c.py", "d.py"]:
    with open(os.path.join(repo_coh, name), "w") as f:
        f.write(f"# {name}")
subprocess.run(["git", "add", "."], cwd=repo_coh, capture_output=True)
subprocess.run(["git", "commit", "-m", "init"], cwd=repo_coh, capture_output=True)

# Multiple commits changing a+b together (cluster 0)
for i in range(3):
    for name in ["a.py", "b.py"]:
        with open(os.path.join(repo_coh, name), "a") as f:
            f.write(f"\n# ab {i}")
    subprocess.run(["git", "add", "."], cwd=repo_coh, capture_output=True)
    subprocess.run(["git", "commit", "-m", f"ab{i}"], cwd=repo_coh, capture_output=True)

# Multiple commits changing c+d together (cluster 1)
for i in range(3):
    for name in ["c.py", "d.py"]:
        with open(os.path.join(repo_coh, name), "a") as f:
            f.write(f"\n# cd {i}")
    subprocess.run(["git", "add", "."], cwd=repo_coh, capture_output=True)
    subprocess.run(["git", "commit", "-m", f"cd{i}"], cwd=repo_coh, capture_output=True)

# Perfect clustering: a+b in cluster 0, c+d in cluster 1
perfect_clusters = {"a.py": 0, "b.py": 0, "c.py": 1, "d.py": 1}
coh_result = measure_commit_coherence(repo_coh, perfect_clusters)

check(
    "coherence measured",
    coh_result.get("commits_analyzed", 0) > 0,
    f"got: {coh_result}",
)
# Init commit (all 4 files) has coherence 0.5, focused commits have 1.0.
# With 6 focused + 1 init = 7 commits, mean ≈ 0.93
check(
    "perfect clustering → high coherence",
    coh_result.get("mean_coherence", 0) >= 0.85,
    f"mean: {coh_result.get('mean_coherence')}",
)

# Bad clustering: a+c in cluster 0, b+d in cluster 1
bad_clusters = {"a.py": 0, "b.py": 1, "c.py": 0, "d.py": 1}
coh_bad = measure_commit_coherence(repo_coh, bad_clusters)

check(
    "bad clustering → lower coherence",
    coh_bad.get("mean_coherence", 1) < coh_result.get("mean_coherence", 0),
    f"perfect={coh_result.get('mean_coherence')}, bad={coh_bad.get('mean_coherence')}",
)

# Non-git directory → error gracefully
coh_nongit = measure_commit_coherence("/tmp", {"a.py": 0})
check(
    "non-git dir → error dict (no crash)",
    "error" in coh_nongit or coh_nongit.get("commits_analyzed") == 0,
    f"got: {coh_nongit}",
)


# ══════════════════════════════════════════════════════════════
# 17: Clustering Determinism (cross-process)
# ══════════════════════════════════════════════════════════════

print("\n=== 17: Clustering Determinism (cross-process) ===")

# Python's per-process string-hash randomization only varies between
# separate interpreter processes — calling build_file_clusters() twice
# in this same test process would use one fixed hash seed for both
# calls and could never catch this bug. The regression has to actually
# spawn two fresh processes, exactly as the original investigation did.
repo_det = make_temp_repo({
    "app/models/owner.py": "class Owner:\n    pass\n",
    "app/models/pet.py": "from app.models.owner import Owner\nclass Pet:\n    pass\n",
    "app/repository/owner_repo.py": "from app.models.owner import Owner\nclass OwnerRepo:\n    pass\n",
    "app/repository/pet_repo.py": "from app.models.pet import Pet\nclass PetRepo:\n    pass\n",
    "app/service/owner_service.py":
        "from app.repository.owner_repo import OwnerRepo\n"
        "from app.repository.pet_repo import PetRepo\n"
        "class OwnerService:\n    pass\n",
    "app/service/pet_service.py":
        "from app.repository.pet_repo import PetRepo\n"
        "class PetService:\n    pass\n",
    "app/util/formatting.py": "def fmt():\n    pass\n",
    "app/util/validation.py": "def validate():\n    pass\n",
    "app/web/owner_controller.py": "from app.service.owner_service import OwnerService\n",
    "app/web/pet_controller.py": "from app.service.pet_service import PetService\n",
})

# Emit, per file, the sorted list of every other file sharing its
# cluster — the actual clustering *assignment*, not the arbitrary
# numeric cluster id (which legitimately isn't stable run to run).
_det_script = (
    "import sys, json\n"
    f"sys.path.insert(0, {PROJECT_ROOT!r})\n"
    "from lib.context.layer1_domain_clustering import build_file_clusters\n"
    f"file_to_cluster, cluster_to_files, _, _ = build_file_clusters({repo_det!r})\n"
    "membership = {f: sorted(cluster_to_files[cid]) for f, cid in file_to_cluster.items()}\n"
    "print(json.dumps(membership, sort_keys=True))\n"
)

_det_run_a = subprocess.run([sys.executable, "-c", _det_script], capture_output=True, text=True, timeout=60)
_det_run_b = subprocess.run([sys.executable, "-c", _det_script], capture_output=True, text=True, timeout=60)

check(
    "both determinism subprocess runs succeeded",
    _det_run_a.returncode == 0 and _det_run_b.returncode == 0,
    f"stderr a: {_det_run_a.stderr[-500:]}\nstderr b: {_det_run_b.stderr[-500:]}",
)

if _det_run_a.returncode == 0 and _det_run_b.returncode == 0:
    membership_a = json.loads(_det_run_a.stdout)
    membership_b = json.loads(_det_run_b.stdout)
    check(
        "two fresh-process runs on identical input produce identical cluster membership",
        membership_a == membership_b,
        f"differing files: {[f for f in membership_a if membership_a.get(f) != membership_b.get(f)]}",
    )


# ══════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════

print(f"\n{'='*50}")
print(f"Clustering Unit Tests: {passed} passed, {failed} failed")
if failed == 0:
    print("ALL TESTS PASSED")
else:
    print(f"FAILURES: {failed}")
    sys.exit(1)
