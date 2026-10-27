"""Create users and reset passwords from the command line. The password is generated and printed once.

    python -m app.manage_users add <username>
    python -m app.manage_users reset <username>   # also logs the user out of every browser
    python -m app.manage_users list

On the server use scripts/users.sh, which runs this inside the app container.
"""

import argparse
import asyncio
import secrets
import string
import sys

from sqlalchemy import delete, select

from app.auth import hash_password
from app.db import SessionLocal
from app.models import AuthSession, User

ALPHABET = string.ascii_letters + string.digits


def generate_password(length: int = 20) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


async def add(username: str) -> str:
    async with SessionLocal() as db:
        if await db.scalar(select(User).where(User.username == username)):
            sys.exit(f"user {username!r} already exists (use `reset` to give it a new password)")
        password = generate_password()
        db.add(User(username=username, password_hash=hash_password(password)))
        await db.commit()
    return password


async def reset(username: str) -> str:
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == username))
        if user is None:
            sys.exit(f"no user {username!r} (use `add` to create it)")
        password = generate_password()
        user.password_hash = hash_password(password)
        # Log out every browser; API tokens (the phone upload shortcut) keep working.
        await db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.kind == "browser"))
        await db.commit()
    return password


async def list_users() -> None:
    async with SessionLocal() as db:
        for user in (await db.execute(select(User).order_by(User.created_at))).scalars():
            print(f"{user.username}\t(created {user.created_at:%Y-%m-%d})")


def main() -> None:
    parser = argparse.ArgumentParser(prog="manage_users", description="Create users and reset passwords.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("add", "create a user with a random password"), ("reset", "give a user a new random password")):
        sub.add_parser(name, help=text).add_argument("username")
    sub.add_parser("list", help="list users")
    args = parser.parse_args()

    if args.command == "list":
        asyncio.run(list_users())
        return
    username = args.username.strip()
    if not username or len(username) > 100:
        sys.exit("username must be 1-100 characters")
    password = asyncio.run(add(username) if args.command == "add" else reset(username))
    verb = "created" if args.command == "add" else "reset password for"
    print(f"{verb} {username!r}\npassword: {password}\n(shown only now: save it in a password manager)")


if __name__ == "__main__":
    main()
