#!/usr/bin/env python3
"""Prepare a catalog version bump or tag an approved release (stdlib only)."""

import argparse
from datetime import date
from pathlib import Path
import re
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'src' / 'catalog.toml'
CHANGELOG = ROOT / 'CHANGELOG.md'
VERSION_RE = re.compile(r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$')


def git(*args: str) -> str:
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True, stderr=subprocess.PIPE).strip()


def require_clean() -> None:
    if git('status', '--porcelain'):
        raise ValueError('Working tree must be clean, including untracked files')


def current_version() -> str:
    version = tomllib.loads(CATALOG.read_text(encoding='utf-8'))['catalog_version']
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise ValueError(f'Invalid catalog_version: {version!r}')
    return version


def prepare(bump: str) -> None:
    branch = git('branch', '--show-current')
    if not branch or branch == 'main':
        raise ValueError('Prepare version bumps on a feature branch, not main')
    require_clean()
    old = current_version()
    major, minor, patch = map(int, old.split('.'))
    if bump == 'major':
        new = f'{major + 1}.0.0'
    elif bump == 'minor':
        new = f'{major}.{minor + 1}.0'
    else:
        new = f'{major}.{minor}.{patch + 1}'
    content = CATALOG.read_text(encoding='utf-8')
    pattern = re.compile(r'(?m)^(catalog_version\s*=\s*)"' + re.escape(old) + r'"(\s*)$')
    updated, count = pattern.subn(lambda m: f'{m.group(1)}"{new}"{m.group(2)}', content)
    if count != 1:
        raise ValueError('Expected exactly one catalog_version assignment')
    CATALOG.write_text(updated, encoding='utf-8', newline='\n')
    print(f'Prepared {old} -> {new} in src/catalog.toml')
    print(f'Update CHANGELOG.md with a dated ## [{new}] - YYYY-MM-DD entry, review, commit and merge.')
    print('No commit, tag, push or release was created.')


def tag_release(version: str | None) -> None:
    if git('branch', '--show-current') != 'main':
        raise ValueError('Tagging requires the local main branch')
    require_clean()
    git('fetch', 'origin', 'main', '--tags')
    head = git('rev-parse', 'HEAD')
    remote_main = git('rev-parse', 'refs/remotes/origin/main')
    if head != remote_main:
        raise ValueError('Local main differs from origin/main; synchronize before tagging')
    actual = current_version()
    if version is not None and version != actual:
        raise ValueError(f'Requested version {version} differs from catalog {actual}')
    version = actual
    changelog = CHANGELOG.read_text(encoding='utf-8')
    matches = re.findall(r'^## \[' + re.escape(version) + r'\] - (\d{4}-\d{2}-\d{2})$', changelog, re.M)
    if len(matches) != 1:
        raise ValueError(f'Expected one dated CHANGELOG.md entry for {version}')
    release_date = date.fromisoformat(matches[0])
    if release_date > date.today():
        raise ValueError('Changelog release date is in the future')
    name = f'v{version}'
    if git('tag', '--list', name):
        raise ValueError(f'Local tag {name} already exists')
    if git('ls-remote', '--tags', 'origin', f'refs/tags/{name}', f'refs/tags/{name}^{{}}'):
        raise ValueError(f'Remote tag {name} already exists')
    print(f'Tagging approved commit {head[:12]} as {name}')
    if input(f'Type {name} to confirm: ').strip() != name:
        raise ValueError('Cancelled')
    subprocess.run(['git', 'tag', '-a', name, '-m', f'FeROS Sources {name}'], cwd=ROOT, check=True)
    print(f'Created local annotated tag {name}. Push explicitly: git push origin {name}')
    print('Then run the Release candidate workflow on main with this tag.')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    bump = sub.add_parser('bump', help='Prepare a version bump for review')
    bump.add_argument('--type', choices=('major', 'minor', 'patch'), required=True)
    tag = sub.add_parser('tag', help='Tag the approved main commit')
    tag.add_argument('--version', help='Must match src/catalog.toml; defaults to catalog version')
    args = parser.parse_args()
    try:
        if args.command == 'bump':
            prepare(args.type)
        else:
            tag_release(args.version)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f'Version operation failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
