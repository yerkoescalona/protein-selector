.PHONY: env test lint typecheck check serve clean

# Base env + the validate extra (rdkit/meeko/...) + the webapp deps group --
# what `make test`/`make serve` below both need. `uv sync` alone (no flags)
# stays intentionally lighter; this target is the "give me everything" one.
env:
	uv sync --extra validate --group webapp

test:
	uv run --extra validate pytest -q

lint:
	uv run ruff check .

typecheck:
	uv run ty check

# The full pre-commit gate this repo's .claude/CLAUDE.md calls for, run
# together, in the same order.
check: lint typecheck test

# Local dev server for the Dash app (PLAN.md §14). Needs the validate extra
# too -- webapp/data.py's report join reads parameterizability results.
serve:
	uv run --extra validate --group webapp python app/app.py

clean:
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +
