import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

User = get_user_model()


@pytest.mark.django_db
def test_create_users_command():
    users_json = json.dumps(
        [
            {
                "username": "admin",
                "email": "admin@example.com",
                "password": "plainpassword",
                "is_superuser": True,
                "is_staff": True,
            },
            {
                "username": "guest",
                "email": "guest@example.com",
                "password": "pbkdf2_sha256$600000$example$hashhere",
                "is_superuser": False,
                "is_staff": False,
            },
            {
                "first_name": "John",
                "last_name": "Doe",
                "email": "john@example.com",
                "password": "pbkdf2_sha256$600000$example$hashhere",
                "is_superuser": False,
                "is_staff": False,
            },
        ],
    )

    call_command("create_initial_users", users_json=users_json)

    admin_user: User = User.objects.get(username="admin")
    assert admin_user.email == "admin@example.com"  # type: ignore[reportUnknownMemberType]
    assert admin_user.is_superuser is True  # type: ignore[reportUnknownMemberType]
    assert admin_user.is_staff is True  # type: ignore[reportUnknownMemberType]

    # password should be hashed, not equal to the plain text
    assert admin_user.check_password("plainpassword") is True

    guest_user: User = User.objects.get(username="guest")
    assert guest_user.email == "guest@example.com"  # type: ignore[reportUnknownMemberType]
    assert guest_user.is_superuser is False  # type: ignore[reportUnknownMemberType]
    assert guest_user.is_staff is False  # type: ignore[reportUnknownMemberType]
    assert guest_user.check_password("pbkdf2_sha256$600000$example$hashhere") is False  # type: ignore[reportUnknownMemberType]

    # The user with email as username should be created with email as username
    john_user: User = User.objects.get(email="john@example.com")
    assert john_user.username == john_user.email  # type: ignore[reportUnknownMemberType]
    assert john_user.first_name == "John"  # type: ignore[reportUnknownMemberType]
    assert john_user.last_name == "Doe"  # type: ignore[reportUnknownMemberType]
