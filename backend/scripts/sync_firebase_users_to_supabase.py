#!/usr/bin/env python3
"""
One-off: sync all Firebase Auth users into Supabase public.users.

- Lists all users from Firebase Auth (email + uid).
- For each: find by firebase_uid, else by email (link), else insert new row.
- Uses same logic as backend get_or_create_user_id (service role required).

Usage:
  Local (backend/.env):
    python -m backend.scripts.sync_firebase_users_to_supabase

  Production (load backend/.env.production first):
    python -m backend.scripts.sync_firebase_users_to_supabase --production

  Or specify env file:
    python -m backend.scripts.sync_firebase_users_to_supabase --env-file backend/.env.production

  Firebase credentials (required to list users): set one of
  - FIREBASE_SERVICE_ACCOUNT_JSON  (JSON string)
  - FIREBASE_SERVICE_ACCOUNT_PATH  (path to .json file, e.g. from Firebase Console > Project Settings > Service Accounts)
  - GOOGLE_APPLICATION_CREDENTIALS (path to .json file)

Optional: --dry-run to only list Firebase users (no DB writes).
"""
import sys
from pathlib import Path

backend = Path(__file__).resolve().parent.parent
if str(backend) not in sys.path:
    sys.path.insert(0, str(backend))


def _setup_env_for_script():
    """If --production: set LEDGERLENS_ENV=production so config loads backend/.env.production."""
    if "--production" in sys.argv:
        import os
        os.environ["LEDGERLENS_ENV"] = "production"


# Before importing app: use production env when requested
_setup_env_for_script()


def _collect_firebase_users(firebase_auth):
    """Collect (uid, email) from Firebase Auth (handles pagination via iterate_all)."""
    users = []
    page = firebase_auth.list_users(max_results=1000)
    for u in page.iterate_all():
        users.append((u.uid, (u.email or "").strip()))
    return users


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Sync Firebase users to Supabase public.users")
    parser.add_argument("--dry-run", action="store_true", help="Only list Firebase users and planned actions, no DB writes")
    parser.add_argument("--production", action="store_true", help="Load backend/.env.production instead of backend/.env")
    args = parser.parse_args()

    from app.services.auth.firebase_auth import _get_firebase_app, get_or_create_user_id

    try:
        _get_firebase_app()
    except ValueError as e:
        if "Firebase credentials" in str(e) or "FIREBASE_SERVICE_ACCOUNT" in str(e):
            print("Firebase credentials not found or invalid. To fix:")
            print("  1. If your Firebase config is in backend/.env.production, run with --production:")
            print("     python -m backend.scripts.sync_firebase_users_to_supabase --production [--dry-run]")
            print("  2. Or set FIREBASE_SERVICE_ACCOUNT_PATH in backend/.env to the path of your .json file")
            print("     (Firebase Console > Project Settings > Service Accounts > Generate new private key)")
            print("  3. If using FIREBASE_SERVICE_ACCOUNT_JSON in .env: use a single line; keep \\n inside the private_key value.")
        raise
    from firebase_admin import auth as firebase_auth

    try:
        users = _collect_firebase_users(firebase_auth)
    except Exception as e:
        print(f"Failed to list Firebase users: {e}")
        sys.exit(1)

    print(f"Found {len(users)} Firebase user(s).")
    if not users:
        print("Nothing to sync.")
        return

    if args.dry_run:
        for uid, email in users:
            print(f"  Would sync: uid={uid} email={email or '(no email)'}")
        print("Dry run done. Run without --dry-run to apply.")
        return

    ok = 0
    errors = 0
    for uid, email in users:
        try:
            user_id = get_or_create_user_id(uid, email)
            if user_id:
                ok += 1
                print(f"  OK: id={user_id} uid={uid} email={email or '-'}")
            else:
                errors += 1
                print(f"  ERROR: uid={uid} email={email or '-'}")
        except Exception as e:
            errors += 1
            print(f"  ERROR uid={uid} email={email or '-'}: {e}")

    print(f"\nDone: {ok} synced, {errors} errors.")


if __name__ == "__main__":
    main()
