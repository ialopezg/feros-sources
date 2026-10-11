# 0008: Publish the site only from published releases

Status: Accepted (2026-10-10)

Supersedes: ADR 0003 (publication trigger and public snapshot semantics).
Refines: ADR 0007 (publication of a release also updates the public site).

## Context

ADR 0003 published the latest approved `main` to GitHub Pages. This exposes
catalog, registry, and device changes before an official version is released.
FeROS Builder and other consumers require a stable public catalog that changes
only through an explicit release decision.

## Decision

- GitHub Pages remains publicly available between releases.
- `.github/workflows/pages.yml` runs on the GitHub `release.published` event,
  not on pushes to `main` or manual workflow dispatch.
- The workflow checks out the published release tag and validates the catalog,
  repository registry, and device manifests from that commit.
- The release tag must match `v<catalog_version>`; prereleases are excluded.
- `scripts/build_site.py` publishes only the catalog-listed manifests and the
  registry, catalog, metadata, and index page from the tagged snapshot.
- The site's commit metadata identifies the tagged commit, not the workflow's
  default-branch commit.
- A deployment refuses to run if its tag is no longer the latest published
  stable release. Pages deployments are serialized.
- Draft releases, edits to drafts, and subsequent development on `main` do not
  modify the public site.

## Consequences

- The public site represents the last successfully deployed published stable
  release, not the latest development state.
- Publishing a release triggers deployment; if deployment fails, the prior site
  remains served and the failure must be resolved.
- The preexisting site deployed under ADR 0003 is a bootstrap snapshot. It
  remains public until replaced by the first release-based deployment; it is
  not retroactively an official release.
- Checksums detect changed content but do not authenticate the publisher.
- Release tags and the published website must remain consistent; retroactively
  moving published tags is prohibited.
