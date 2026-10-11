# FeROS Sources — local developer commands (GNU Make + Python 3.11+)
PYTHON ?= python

.PHONY: validate site clean version-bump release-tag release-status release-publish

validate:
	$(PYTHON) scripts/validate.py

site: validate
	$(PYTHON) scripts/build_site.py

clean:
	$(PYTHON) -c "import shutil; shutil.rmtree('dist', ignore_errors=True)"

# Prepare on a feature branch; review and merge before tagging.
version-bump:
	$(PYTHON) scripts/version.py bump --type "$(BUMP)"

# Tag approved main; does not push, package, draft or publish.
release-tag:
	$(PYTHON) scripts/version.py tag $(if $(VERSION),--version "$(VERSION)",)

release-status:
	$(PYTHON) scripts/release.py status

release-publish:
	$(PYTHON) scripts/release.py publish
