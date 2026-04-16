from __future__ import annotations

import json
import pathlib
import typing
from typing import Any, override

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import identify_hasher
from django.core.management.base import BaseCommand, CommandError

if typing.TYPE_CHECKING:
    from django.core.management.base import CommandParser


class Command(BaseCommand):
    help = "Create/update users using JSON input"

    @override
    def add_arguments(self, parser: CommandParser):
        parser.add_argument(
            "--users-json",
            type=str,
            required=True,
            help="JSON string containing list of users",
        )

    def is_hashed(self, password: str) -> bool:
        try:
            identify_hasher(password)
            return True
        except Exception:
            return False

    def load_json_string(self, json_str: str) -> list[dict[str, Any]]:
        try:
            data = json.loads(json_str)
            if not isinstance(data, list):
                raise ValueError("JSON must be a list of users")
            return data
        except Exception as e:
            raise CommandError(f"Invalid JSON: {e}") from e

    def load_json_file(self, path: str) -> list[dict[str, Any]]:
        try:
            with pathlib.Path(path).open(encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    raise ValueError("JSON must be a list of users")
                return data
        except Exception as e:
            raise CommandError(f"Error reading file {path}: {e}") from e

    @override
    def handle(self, *_, **options: Any):
        User = get_user_model()
        user_data = self.load_json_string(options["users_json"])

        if not user_data:
            raise CommandError("No users provided")

        for user_info in user_data:
            email = user_info.pop("email", None)
            username = user_info.pop("username", email)
            password = user_info.pop("password", None)

            if not email or not password:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping user (missing email/password): {user_info}",
                    ),
                )
                continue

            defaults = {k: v for k, v in user_info.items()}
            user, created = User.objects.update_or_create(
                username=username,
                email=email,
                defaults=defaults,
            )

            if self.is_hashed(password):
                user.password = password
            else:
                user.set_password(password)

            user.save()

            if created:
                self.stdout.write(
                    self.style.SUCCESS(f"Created user: {email}"),
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"Updated user: {email}"),
                )
