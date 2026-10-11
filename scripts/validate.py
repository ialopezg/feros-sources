#!/usr/bin/env python3
"""Validate the FeROS Sources tree. Standard library only (Python 3.11+).

Fails on anything the project has not explicitly approved:
  * files outside the allowlist, binaries, executables, oversized files
  * device manifests not listed in catalog.toml
  * catalog entries whose hash, path, id or metadata do not match the manifest
  * duplicate ids, unsafe paths, executable-looking keys in manifests
"""
import hashlib
import re
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_FILE_BYTES = 256 * 1024
SKIP_DIRS = {".git", "_site", "dist"}

ALLOWED_ROOT_FILES = {
    "CODE_OF_CONDUCT.md", "COLLABORATORS.md", "CONTRIBUTING.md", "LICENSE",
    "README.md", "SECURITY.md", "STABILITY.md", "THIRD_PARTY.md",
    "VERSIONING.md", "CHANGELOG.md", "RELEASE.md", "Makefile",
    ".gitattributes", ".gitignore",
}
ALLOWED_PATTERNS = [
    re.compile(r"docs/[A-Za-z0-9._-]+\.md"),
    re.compile(r"docs/adr/[A-Za-z0-9._-]+\.md"),
    re.compile(r"src/(official|experimental)/[a-z0-9-]+/[a-z0-9][a-z0-9.-]*\.toml"),
    re.compile(r"src/(repository|catalog)\.toml"),
    re.compile(r"scripts/(validate|build_site|release|package)\.py"),
    re.compile(r"\.github/CODEOWNERS"),
    re.compile(r"\.github/workflows/[A-Za-z0-9._-]+\.yml"),
    re.compile(r"\.github/rulesets/[A-Za-z0-9._-]+\.json"),
]
FORBIDDEN_KEYS = {"command", "commands", "exec", "execute", "shell", "script",
                  "scripts", "hook", "hooks", "run", "pre_install", "post_install"}
DEVICE_FIELDS = ["id", "name", "brand", "model", "architecture", "cpu", "kind",
                 "version", "support", "installable"]
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def tracked_files():
    """Yield (path, posix-relative-path) for tracked files.

    Uses `git ls-files` when available, so ignored or untracked local files
    (IDE folders, caches) do not affect the result. Falls back to walking the
    tree, which is what a fresh archive without .git needs.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            check=True, capture_output=True).stdout
        rels = sorted(r for r in out.decode("utf-8").split("\0") if r)
        for rel in rels:
            p = ROOT / rel
            if p.is_file() or p.is_symlink():
                yield p, rel
        return
    except (OSError, subprocess.CalledProcessError):
        pass
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.is_file() or p.is_symlink():
            yield p, rel.as_posix()


def check_tree() -> list[str]:
    manifests = []
    for p, rel in tracked_files():
        if p.is_symlink():
            err(f"{rel}: symlinks are not allowed")
            continue
        allowed = rel in ALLOWED_ROOT_FILES or any(r.fullmatch(rel) for r in ALLOWED_PATTERNS)
        if not allowed:
            err(f"{rel}: path is not in the approved layout")
            continue
        if p.stat().st_size > MAX_FILE_BYTES:
            err(f"{rel}: exceeds {MAX_FILE_BYTES} bytes")
        if p.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            err(f"{rel}: executable bit is not allowed")
        data = p.read_bytes()
        if b"\x00" in data:
            err(f"{rel}: binary content is not allowed")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            err(f"{rel}: not valid UTF-8")
        if b"\r" in data:
            err(f"{rel}: must use LF line endings (hashes depend on exact bytes)")
        if re.fullmatch(r"src/(official|experimental)/[^/]+/[^/]+\.toml", rel):
            manifests.append(rel)
    return manifests


def load(rel: str):
    try:
        return tomllib.loads((ROOT / rel).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        err(f"{rel}: invalid TOML ({e})")
        return None


def walk_keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in FORBIDDEN_KEYS:
                err(f"{path}{k}: executable-style key is not allowed in manifests")
            walk_keys(v, f"{path}{k}.")
    elif isinstance(obj, list):
        for v in obj:
            walk_keys(v, path)


def safe_rel_path(value: str) -> bool:
    return (isinstance(value, str) and value != "" and "\\" not in value
            and "://" not in value and not value.startswith("/")
            and ".." not in value.split("/"))


def check_repository():
    data = load("src/repository.toml")
    if data is None:
        return
    if data.get("schema_version") != 1:
        err("repository.toml: schema_version must be 1")
    seen = set()
    for r in data.get("repositories", []):
        url = r.get("url", "")
        if not url.startswith("https://github.com/"):
            err(f"repository.toml: unexpected repository url {url!r}")
        if url in seen:
            err(f"repository.toml: duplicate repository {url}")
        seen.add(url)


def check_catalog(manifests: list[str]):
    cat = load("src/catalog.toml")
    if cat is None:
        return
    if cat.get("schema_version") != "1.0":
        err("catalog.toml: schema_version must be \"1.0\"")
    if not SEMVER.match(str(cat.get("catalog_version", ""))):
        err("catalog.toml: catalog_version must be MAJOR.MINOR.PATCH")
    devices = cat.get("devices", [])
    ids, listed = set(), set()
    for d in devices:
        did = d.get("id", "<missing id>")
        if did in ids:
            err(f"catalog.toml: duplicate device id {did}")
        ids.add(did)
        if not ID_RE.match(str(did)):
            err(f"catalog.toml: invalid id {did!r}")
        manifest = d.get("manifest", "")
        if not safe_rel_path(manifest):
            err(f"catalog.toml[{did}]: unsafe manifest path {manifest!r}")
            continue
        listed.add(manifest)
        mp = ROOT / "src" / manifest
        if not mp.is_file():
            err(f"catalog.toml[{did}]: manifest {manifest} does not exist")
            continue
        if not SHA256.match(str(d.get("sha256", ""))):
            err(f"catalog.toml[{did}]: sha256 must be 64 lowercase hex digits")
        elif hashlib.sha256(mp.read_bytes()).hexdigest() != d["sha256"]:
            err(f"catalog.toml[{did}]: sha256 does not match {manifest} "
                "(a published manifest changed; publish a new version and update the hash)")
        parts = manifest.split("/")
        if len(parts) != 3 or parts[0] not in ("official", "experimental"):
            err(f"catalog.toml[{did}]: manifest must live in official/ or experimental/<brand>/")
            continue
        if parts[0] != d.get("support"):
            err(f"catalog.toml[{did}]: support={d.get('support')!r} does not match directory {parts[0]}/")
        if parts[1] != d.get("brand"):
            err(f"catalog.toml[{did}]: brand={d.get('brand')!r} does not match directory {parts[1]}/")
        if parts[2] != f"{did}.toml":
            err(f"catalog.toml[{did}]: filename must be {did}.toml")
        if d.get("installable") is not False:
            err(f"catalog.toml[{did}]: installable must be false (contract 1.0)")
        if d.get("kind") not in ("virtual", "physical"):
            err(f"catalog.toml[{did}]: kind must be virtual or physical")
        if d.get("support") not in ("official", "experimental"):
            err(f"catalog.toml[{did}]: support must be official or experimental")
        if not SEMVER.match(str(d.get("version", ""))):
            err(f"catalog.toml[{did}]: version must be MAJOR.MINOR.PATCH")

        m = load(f"src/{manifest}")
        if m is None:
            continue
        walk_keys(m, f"{manifest}:")
        if m.get("schema_version") != "1.0":
            err(f"{manifest}: schema_version must be \"1.0\"")
        dev = m.get("device", {})
        for f in DEVICE_FIELDS:
            if f not in dev:
                err(f"{manifest}: missing device.{f}")
            elif f != "installable" and f in d and dev[f] != d[f]:
                err(f"{manifest}: device.{f}={dev[f]!r} differs from catalog ({d[f]!r})")
        if dev.get("installable") is not False:
            err(f"{manifest}: device.installable must be false (contract 1.0)")

    for m in manifests:
        if m.removeprefix("src/") not in listed:
            err(f"{m}: manifest is not listed in catalog.toml (unapproved addition)")


def main() -> int:
    manifests = check_tree()
    check_repository()
    check_catalog(manifests)
    if errors:
        print(f"FAILED: {len(errors)} problem(s)")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: tree, repository registry, catalog and manifests are consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
