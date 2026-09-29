# bluetti-bt-connect-lib 2.0.1

Maintenance release. **No code or behaviour changes** - the library is
identical to 2.0.0, so there is nothing to update in Home Assistant.

## Changes

- **PyPI project links now point to the new GitHub account**
  (`https://github.com/Ellmondo/bluetti-bt-connect-lib`). PyPI only reads
  links from a published release, so 2.0.0 kept showing the old username.
- **Release workflow updated to current GitHub Actions** (`checkout@v7`,
  `setup-python@v7`, `upload-artifact@v7`, `download-artifact@v8`), which run
  on Node.js 24 and clear the Node.js 20 deprecation warnings.
- **Runners pinned to `ubuntu-24.04`** instead of `ubuntu-latest`, so the
  build environment only changes when the workflow is deliberately updated.
