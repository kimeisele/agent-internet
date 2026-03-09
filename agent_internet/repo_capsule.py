from __future__ import annotations

import ast
import subprocess
import tomllib
from pathlib import Path


def extract_repo_capsule(root: Path | str, *, max_items: int = 12) -> dict:
    repo_root = Path(root).resolve()
    pyproject = _load_pyproject(repo_root)
    counts = {
        "python_file_count": _count(repo_root, "*.py"),
        "test_file_count": _count(repo_root / "tests", "test_*.py"),
        "workflow_file_count": _count(repo_root / ".github" / "workflows", "*.y*ml"),
        "doc_file_count": _count(repo_root / "docs", "*.md") + int((repo_root / "README.md").exists()),
    }
    return {
        "kind": "agent_internet_repo_capsule",
        "version": 1,
        "identity": {
            "repo_name": pyproject.get("project", {}).get("name") or repo_root.name,
            "repo_slug": repo_root.name,
            "repo_root": str(repo_root),
            "git": {
                "branch": _git_output(repo_root, "rev-parse", "--abbrev-ref", "HEAD"),
                "head_sha": _git_output(repo_root, "rev-parse", "HEAD"),
                "origin_url": _git_output(repo_root, "remote", "get-url", "origin"),
            },
        },
        "overview": {
            "description": pyproject.get("project", {}).get("description") or _readme_summary(repo_root),
            "readme_summary": _readme_summary(repo_root),
        },
        "architecture": {
            "top_level": _top_level(repo_root, max_items=max_items),
            "package_roots": _package_roots(repo_root, max_items=max_items),
            "key_modules": _key_modules(repo_root, max_items=max_items),
        },
        "interfaces": {
            "cli_entrypoints": _cli_entrypoints(pyproject),
            "workflow_files": _relative_paths(repo_root / ".github" / "workflows", repo_root, "*.y*ml", max_items=max_items),
            "doc_files": _relative_paths(repo_root / "docs", repo_root, "*.md", max_items=max_items)
            + (["README.md"] if (repo_root / "README.md").exists() else []),
            "test_files": _relative_paths(repo_root / "tests", repo_root, "test_*.py", max_items=max_items),
        },
        "audit": {
            "counts": counts,
            "warnings": _warnings(repo_root, counts),
        },
        "provenance": {
            "generator": "agent_internet.repo_capsule.extract_repo_capsule",
            "sources": ["filesystem", "git", "pyproject.toml", "README.md"],
        },
    }


def _load_pyproject(root: Path) -> dict:
    path = root / "pyproject.toml"
    return tomllib.loads(path.read_text()) if path.exists() else {}


def _count(root: Path, pattern: str) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.rglob(pattern) if path.is_file())


def _git_output(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True, text=True)
        value = completed.stdout.strip()
        return value or None
    except Exception:
        return None


def _readme_summary(root: Path) -> str:
    path = root / "README.md"
    if not path.exists():
        return ""
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def _top_level(root: Path, *, max_items: int) -> list[str]:
    return [path.name for path in sorted(root.iterdir()) if not path.name.startswith(".")][:max_items]


def _package_roots(root: Path, *, max_items: int) -> list[str]:
    items = []
    for path in sorted(root.iterdir()):
        if path.is_dir() and not path.name.startswith(".") and (path / "__init__.py").exists():
            items.append(path.name)
    return items[:max_items]


def _key_modules(root: Path, *, max_items: int) -> list[dict]:
    modules: list[dict] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
            continue
        if rel.parts and rel.parts[0] in {"tests", ".venv"}:
            continue
        modules.append({"path": str(rel), "docstring": _module_docstring(path)})
        if len(modules) >= max_items:
            break
    return modules


def _module_docstring(path: Path) -> str:
    try:
        return ast.get_docstring(ast.parse(path.read_text())) or ""
    except Exception:
        return ""


def _cli_entrypoints(pyproject: dict) -> list[dict]:
    scripts = pyproject.get("project", {}).get("scripts", {}) or {}
    return [{"name": name, "target": target} for name, target in sorted(scripts.items())]


def _relative_paths(base: Path, root: Path, pattern: str, *, max_items: int) -> list[str]:
    if not base.exists():
        return []
    return [str(path.relative_to(root)) for path in sorted(base.rglob(pattern)) if path.is_file()][:max_items]


def _warnings(root: Path, counts: dict) -> list[str]:
    warnings = []
    if not (root / "README.md").exists():
        warnings.append("missing_readme")
    if counts["test_file_count"] == 0:
        warnings.append("missing_tests")
    if counts["workflow_file_count"] == 0:
        warnings.append("missing_workflows")
    if not (root / "pyproject.toml").exists():
        warnings.append("missing_pyproject")
    return warnings