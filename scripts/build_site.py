#!/usr/bin/env python3
"""Build the static site published at https://ialopezg.github.io/feros-sources.

Standard library only (Python 3.11+). Run scripts/validate.py first.

The site is a snapshot of the checked-out commit. Only files that the catalog
lists (plus repository.toml and catalog.toml) are published, so a manifest that
is not approved in catalog.toml can never reach the site. No timestamps are
written: the output depends only on the commit.
"""
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "src"
OUT = ROOT / "dist" / "site"
REPO = os.environ.get("GITHUB_REPOSITORY", "ialopezg/feros-sources")
def resolve_commit() -> str:
    if commit := os.environ.get("GITHUB_SHA"):
        return commit
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


COMMIT = resolve_commit()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    catalog_path = SOURCE / "catalog.toml"
    catalog = tomllib.loads(catalog_path.read_text(encoding="utf-8"))
    devices = catalog.get("devices", [])

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    published = ["repository.toml", "catalog.toml"]
    published += sorted(d["manifest"] for d in devices)
    for rel in published:
        src, dst = SOURCE / rel, OUT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

    files = [{"path": rel, "sha256": sha256(OUT / rel),
              "bytes": (OUT / rel).stat().st_size} for rel in published]
    meta = {
        "source": f"https://github.com/{REPO}",
        "commit": COMMIT,
        "catalog_version": catalog.get("catalog_version"),
        "schema_version": catalog.get("schema_version"),
        "files": files,
    }
    (OUT / "site.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    esc = html.escape
    rows = "\n".join(
        "      <tr><td><code>{id}</code></td><td>{name}</td><td>{brand}</td>"
        "<td>{model}</td><td>{version}</td><td>{support}</td>"
        '<td><a href="{manifest}">manifest</a></td></tr>'.format(
            **{k: esc(str(d.get(k, ""))) for k in
               ("id", "name", "brand", "model", "version", "support", "manifest")})
        for d in devices) or '      <tr><td colspan="7">No devices.</td></tr>'
    short = esc(COMMIT[:12])
    commit_link = (f'<a href="https://github.com/{esc(REPO)}/commit/{esc(COMMIT)}">{short}</a>'
                   if COMMIT != "unknown" else "unknown")
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>FeROS Sources</title>
  <style>
    body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 56rem; margin: 2rem auto; padding: 0 1rem; }}
    table {{ border-collapse: collapse; width: 100%; display: block; overflow-x: auto; }}
    th, td {{ text-align: left; padding: .35rem .6rem; border-bottom: 1px solid #8884; }}
    .note {{ padding: .6rem .9rem; border-left: 4px solid #c80; background: #8881; }}
  </style>
</head>
<body>
  <h1>FeROS Sources</h1>
  <p>Versioned sources of supported platforms for the FeROS ecosystem.</p>
  <p class="note">This site reflects the last successfully deployed published
  FeROS Sources release. Development changes on <code>main</code> and draft
  releases do not update it. Checksums detect changes; they are not digital
  signatures.</p>
  <p>Commit {commit_link}, catalog version {esc(str(catalog.get("catalog_version")))},
  schema {esc(str(catalog.get("schema_version")))}.</p>
  <h2>Files</h2>
  <ul>
    <li><a href="repository.toml">repository.toml</a>: recognized official sources</li>
    <li><a href="catalog.toml">catalog.toml</a>: device index</li>
    <li><a href="site.json">site.json</a>: commit and SHA-256 of every file published here</li>
  </ul>
  <h2>Devices</h2>
  <table>
    <thead><tr><th>ID</th><th>Name</th><th>Brand</th><th>Model</th><th>Version</th><th>Support</th><th>File</th></tr></thead>
    <tbody>
{rows}
    </tbody>
  </table>
  <p><a href="https://github.com/{esc(REPO)}">Source repository</a></p>
</body>
</html>
"""
    (OUT / "index.html").write_text(page, encoding="utf-8")
    print(f"Built {OUT} from commit {COMMIT[:12]}: {len(published)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
