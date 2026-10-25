install:
	uv sync

project:
	uv run project

build:
	uv build

publish:
	uv publish --dry-run

package-install:
	uv tool install dist/*.whl

lint:
	uv run ruff check .

scheduler:
	uv run python -m valutatrade_hub.parser_service.scheduler