run:
	uv run uvicorn main:app --reload --host 0.0.0.0 --port 8001 --reload-exclude '*.log'
