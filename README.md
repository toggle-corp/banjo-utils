# toggle-django-utils

Reusable Django utilities and management commands for Toggle projects.

---

## Features

- Shared management command: `wait_for_resources`
  — Wait for database, Redis, Minio (S3) resources to be available before startup

---

## Installation

**Using [uv](https://github.com/astral-sh/uv):**
```bash
uv pip install "git+ssh://git@github.com/toggle-corp/toggle-django-utils.git@main"
```

Or add to your `pyproject.toml`:
```toml
[project]
dependencies = [
    "toggle-django-utils",
]

[tool.uv.sources]
toggle-django-utils = { git = "ssh://git@github.com/toggle-corp/toggle-django-utils", branch = "main" }
```

---

## Setup in Django

1. **Add to `INSTALLED_APPS` in your Django project's `settings.py`:**

    ```python
    INSTALLED_APPS = [
        # ... your other apps ...
        "toggle_django_utils",
    ]
    ```

2. (Optional) If your `settings.py` uses custom configs, ensure `"toggle_django_utils"` remains in the app list.


---

## Usage

**Access the management command:**
```bash
python manage.py wait_for_resources --db --redis
```

**Command options:**
- `--db` &nbsp;&nbsp;&nbsp;&nbsp; Wait for database
- `--redis` &nbsp; Wait for Redis server
- `--minio` &nbsp; Wait for Minio (S3 storage)
- `--timeout` &nbsp; Set max wait time (seconds)

**Examples:**
```bash
python manage.py wait_for_resources --db --redis
python manage.py wait_for_resources --timeout 300 --minio
```

---

## Development

1. Clone the repository
2. Install as editable with uv:
    ```bash
    uv sync --all-groups --all-extras
    ```
3. Type checking
    ```bash
    uv run --all-groups --all-extras pyright
    ```
3. Running Tests
    ```bash
    uv run --all-groups --all-extras pytest
    ```

---

## License

Apache-2.0
