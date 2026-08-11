# DISCO release playbook

Use this checklist for every release. **Do not skip the review step.**

Concept DOI (always cite this): https://doi.org/10.5281/zenodo.19999239  
PyPI: https://pypi.org/project/disco-astronomy/  
Docs: https://astrojorgeluis.github.io/disco-astronomy/

## Before you commit

1. Activate `disco-v1` and run tests:
   ```bash
   cd DISCO_Source_Git
   pytest -q tests
   ```
2. Build the GUI (required for the wheel and for `disco-start gui`):
   ```bash
   cd DISCO_Source_Git/client
   npm ci && npm run build
   # Use npm run build — NOT build:disco — on v1
   ```
3. Smoke the GUI: `disco-start gui` (note the printed URL; port may be >8000).
4. Review `git status` / `git diff`. Confirm version is bumped everywhere:
   - `DISCO_Source_Git/pyproject.toml`
   - `CITATION.cff`
   - `DISCO_Source_Git/docs/source/conf.py`
   - `DISCO_Source_Git/docs/source/changelog.rst`
   - README citation blocks

## Commit & PR (only when you say so)

Suggested message:

```
Release v1.2.4: GUI/CLI polish, robustness, and docs sync for conference demo
```

```bash
git add -A
git status   # re-check: no .cursor/, no .env, no random *.fits uploads
git commit -m "$(cat <<'EOF'
Release v1.2.4: GUI/CLI polish, robustness, and docs sync for conference demo

EOF
)"
git push -u origin HEAD
gh pr create --base main --title "Release v1.2.4" --body "…"
```

Merge the PR to `main`.

## GitHub Release → Zenodo

After merge on `main`:

```bash
git checkout main && git pull
gh release create v1.2.4 \
  --title "DISCO v1.2.4" \
  --notes-file - <<'EOF'
## Summary
GUI polish (empty state, persistent visualization), CLI path/--yes/CSV unit labels,
backend robustness, docs sync, tests + CI.

## Install
```bash
pip install -U disco-astronomy==1.2.4
```

Concept DOI: https://doi.org/10.5281/zenodo.19999239
EOF
```

Zenodo should ingest the new version under the concept DOI within minutes.
Verify at https://doi.org/10.5281/zenodo.19999239.

## PyPI

From a clean tree with static assets already built:

```bash
cd DISCO_Source_Git
python -m pip install build twine
rm -rf dist build *.egg-info
python -m build
unzip -l dist/*.whl | grep -E 'static/index.html|disco_model_stable.pth'
twine check dist/*
# Optional: twine upload --repository testpypi dist/*
twine upload dist/*
pip install -U disco-astronomy==1.2.4
disco-start --help
```

## Docs (GitHub Pages)

Build Sphinx and deploy with your existing Pages workflow (or):

```bash
cd DISCO_Source_Git/docs
pip install -r requirements.txt
make html
# publish build/html to gh-pages as you usually do
```

Confirm https://astrojorgeluis.github.io/disco-astronomy/ shows **1.2.4**.

## Post-release sanity

- [ ] PyPI version visible
- [ ] Zenodo version listed under concept DOI
- [ ] Docs site version matches
- [ ] `CITATION.cff` date-released matches the release day
