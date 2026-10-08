.PHONY: up down venv install seed eval test api web

up:
	docker compose up --build

down:
	docker compose down

venv:
	cd apps/api && python -m venv venv

install:
	cd apps/api && pip install -r requirements.txt

seed:
	python scripts/seed_demo.py drop-not-null-users

eval:
	python evals/run_eval.py

test:
	pytest tests -q

api:
	cd apps/api && uvicorn app.main:app --reload --port 8000

web:
	cd apps/web && npm run dev
