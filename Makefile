# Local dev commands — requires `make` (winget install GnuWin32.Make or use WSL)
# For PowerShell equivalents see the README.

.PHONY: dev dev-down train tune forecast test logs clean

# ── Dev / local ────────────────────────────────────────────────────────────────

dev:
	docker compose up -d

dev-down:
	docker compose down

logs:
	docker compose logs -f gas-listener

# ── Model operations ───────────────────────────────────────────────────────────

train:
	python train.py

tune:
	python train.py --tune

forecast:
	python forecast.py

# ── Tests ──────────────────────────────────────────────────────────────────────

test:
	pytest tests/ -v

# ── Cleanup ────────────────────────────────────────────────────────────────────

clean:
	docker compose down -v
