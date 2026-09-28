"""Script for creating or updating an administrator / observer in the database.

Usage:
    python create_admin.py --username observer --password observer_password
    python create_admin.py --username observer --password observer_password --clear-data
"""

import argparse
import sys

from sqlalchemy import text

from app.core.security import hash_password
from app.db.session import get_engine


def clear_business_data(engine, target_username: str | None = None):
    """Clean all domain tables in topological order to respect foreign keys."""
    ordered_tables = [
        # Tickets and history
        "ticket_assignment_events",
        "ticket_comments",
        "ticket_appliances",
        "ticket_appliance_states",
        "work_events",
        "routes",
        "planning_plan_routes",
        "planning_plans",
        "day_plan_revisions",
        "worker_day_states",
        "equipment_movements",
        "worker_equipment",
        "appliance_movements",
        "appliance_operations",
        "worker_appliances",
        "office_kit_reserves",
        "appliance_stocks",
        "tickets",
        # Brigades and workers
        "brigade_members",
        "brigades",
        "worker_skill_assignments",
        "workers",
        "worker_skills",
        # Source imports
        "data_imports",
        "source_records",
        "source_addresses",
        "source_imports",
        # Geography and infrastructure
        "locations",
        "entrances",
        "buildings",
        "streets",
        "districts",
        "service_areas",
        "offices",
        "cities",
        # System
        "push_subscriptions",
        "refresh_tokens",
        "notification_events",
        "work_types",
        "work_type_planning_rules",
        "work_type_required_skills",
        "work_type_required_appliances",
        "divisions",
    ]
    with engine.connect() as conn:
        for t in ordered_tables:
            try:
                with conn.begin():
                    conn.execute(text(f'DELETE FROM "{t}"'))
            except Exception:
                pass

        if target_username:
            try:
                with conn.begin():
                    conn.execute(
                        text("DELETE FROM users WHERE lower(username) != lower(:u)"),
                        {"u": target_username.strip()},
                    )
            except Exception:
                pass

        print("[OK] Бизнес-данные успешно очищены. База полностью пустая.", flush=True)


def create_or_update_admin(
    username: str,
    password: str,
    name: str = "Диспетчер",
    surname: str = "Администратор",
    lastname: str | None = None,
    role: str = "observer",
):
    """Create or update administrator/observer account."""
    if len(password) < 8:
        print("[ERROR] Пароль должен быть не короче 8 символов.", file=sys.stderr)
        sys.exit(1)

    engine = get_engine()
    with engine.begin() as conn:
        pwd_hash = hash_password(password)

        existing = conn.execute(
            text("SELECT id, username, role FROM users WHERE lower(username) = lower(:username)"),
            {"username": username.strip()},
        ).fetchone()

        if existing:
            user_id = existing[0]
            conn.execute(
                text(
                    """
                    UPDATE users
                    SET password_hash = :pwd_hash,
                        role = :role,
                        archived_at = NULL,
                        updated_at = NOW()
                    WHERE id = :user_id
                    """
                ),
                {"pwd_hash": pwd_hash, "role": role, "user_id": user_id},
            )
            print(
                f"[OK] Пользователь '{username}' (ID: {user_id}) найден. "
                f"Пароль и роль '{role}' обновлены."
            )
            return user_id
        else:
            new_id = conn.execute(
                text(
                    """
                    INSERT INTO users (name, surname, lastname, username, password_hash, role)
                    VALUES (:name, :surname, :lastname, :username, :pwd_hash, :role)
                    RETURNING id
                    """
                ),
                {
                    "name": name.strip(),
                    "surname": surname.strip(),
                    "lastname": lastname.strip() if lastname else None,
                    "username": username.strip(),
                    "pwd_hash": pwd_hash,
                    "role": role,
                },
            ).scalar()
            print(
                f"[OK] Успешно создан новый пользователь '{username}' "
                f"(ID: {new_id}, роль: '{role}')."
            )
            return new_id


def main():
    parser = argparse.ArgumentParser(
        description="Создание или обновление администратора (observer) в БД."
    )
    parser.add_argument(
        "--username",
        default="observer",
        help="Логин пользователя (по умолчанию: observer)",
    )
    parser.add_argument(
        "--password",
        default="observer_password",
        help="Пароль пользователя (мин. 8 символов)",
    )
    parser.add_argument(
        "--name",
        default="Диспетчер",
        help="Имя пользователя (по умолчанию: Диспетчер)",
    )
    parser.add_argument(
        "--surname",
        default="Администратор",
        help="Фамилия пользователя (по умолчанию: Администратор)",
    )
    parser.add_argument(
        "--role",
        default="observer",
        choices=["observer", "foreman", "worker"],
        help="Роль пользователя (по умолчанию: observer)",
    )
    parser.add_argument(
        "--clear-data",
        action="store_true",
        help="Очистить все бизнес-данные, оставив чистую базу с пользователем",
    )

    args = parser.parse_args()
    engine = get_engine()

    if args.clear_data:
        print("Очистка существующих данных...", flush=True)
        clear_business_data(engine, target_username=args.username)

    create_or_update_admin(
        username=args.username,
        password=args.password,
        name=args.name,
        surname=args.surname,
        role=args.role,
    )
    print("\nГотово! Теперь можно войти в систему:")
    print(f"  Логин:  {args.username}")
    print(f"  Пароль: {args.password}")
    print(f"  Роль:   {args.role}")


if __name__ == "__main__":
    main()
