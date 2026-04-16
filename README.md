# Banjo utils

Reusable Django utilities and management commands for Toggle projects.

---

## Features

- Shared management command: `wait_for_resources`
  — Wait for database, Redis, Minio (S3) resources to be available before startup
- Create Initial Users: `create_initial_users`
    - Create Users with specified roles and permissions, useful to populate the database with default users during development or testing

---

## Installation

**Using [uv](https://github.com/astral-sh/uv):**
```bash
uv pip install "git+https://github.com/toggle-corp/banjo-utils.git@v0.1.0"
```

Or add to your `pyproject.toml`:
```toml
[project]
dependencies = [
    "banjo-utils",
]

[tool.uv.sources]
banjo-utils = { git = "https://github.com/toggle-corp/banjo-utils", tag = "v0.1.0" }
```

---

## Setup in Django

- **Add to `INSTALLED_APPS` in your Django project's `settings.py`:**

    ```python
    INSTALLED_APPS = [
        # ... your other apps ...
        "banjo_utils",
    ]
    ```

---

## Usage

**Access the management command:**
```bash
python manage.py wait_for_resources --db --redis
```

**Command options:**
- `--db`: Wait for database
- `--redis`: Wait for Redis server
- `--minio`: Wait for Minio (S3 storage)
- `--timeout`: Set max wait time (seconds)

**Examples:**
```bash
python manage.py wait_for_resources --db --redis
python manage.py wait_for_resources --timeout 300 --minio
python manage.py create_initial_users --users-json="
[
    {
        "username": "admin",
        "email": "test@example.com",
        "password": "admin123",
        "is_superuser": true,
        "is_staff": true
    },
    {
        "username": "user1",
        "email": "user1@gmail.com",
        "password": "user123",
        "is_superuser": false,
        "is_staff": false
    }
]'
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
4. Run commands for example project
    ```bash
    uv run --all-groups --all-extras python example/manage.py runserver
    uv run --all-groups --all-extras python example/manage.py wait_for_resources --db --redis
    ```

---

## License

Apache-2.0
