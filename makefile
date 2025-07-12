run:
	uv run uvicorn main:app --reload --host localhost --port 8001 --reload-exclude '*.log'
