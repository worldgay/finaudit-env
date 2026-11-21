# All targets delegate to finaudit/tasks.py (the same runner is used as `make`
# inside the Docker image, where GNU make is not installed).
PY ?= python3.11

.PHONY: install test episodes trajectories check jury demo report docker-build docker-check

install:
	$(PY) -m pip install --no-index --find-links vendor/wheels -r requirements.lock -r requirements-dev.lock

test:
	$(PY) -m finaudit.tasks test

episodes:
	$(PY) -m finaudit.tasks episodes

trajectories:
	$(PY) -m finaudit.tasks trajectories

check:
	$(PY) -m finaudit.tasks check

jury:
	$(PY) -m finaudit.tasks jury

demo:
	$(PY) -m finaudit.tasks demo

report:
	$(PY) -m finaudit.tasks report

docker-build:
	docker build -t finaudit .

docker-check: docker-build
	docker run --rm --network none --cpus 2 --memory 4g finaudit make check
