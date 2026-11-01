.PHONY: setup up down logs load restore train test legacy
setup:     ; python scripts/generate_env.py
up:        ; docker compose up -d --build
down:      ; docker compose down
logs:      ; docker compose logs -f api consumer producer
load:      ; docker compose --profile tools run --rm loader          # needs creditcard.csv in this folder
restore:   ; docker compose up -d db && sleep 8 && docker compose exec -T db sh -c 'pg_restore --no-owner -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' < upi_fraud_backup.dump && docker compose up -d --build
train:     ; docker compose --profile tools run --rm trainer          # writes a new version into ./models
legacy:    ; python -m ml.import_legacy --model fraud_model.pkl --features features.pkl
test:      ; python -m pytest
