.PHONY: install dev migrate seed up down revision

install:
	python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

dev:            ## run the API locally (expects Postgres on :5432 and a .env)
	uvicorn app.main:app --reload --port 8000

migrate:        ## apply migrations
	alembic upgrade head

revision:       ## autogenerate a migration: make revision m="message"
	alembic revision --autogenerate -m "$(m)"

seed:           ## load demo locations + users
	python -m seed

up:             ## full local stack (Postgres + API) via Docker
	docker-compose up --build

down:
	docker-compose down
