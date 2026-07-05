"""
One-shot migration of real ContactosWH data into Warhammer Fantasy Tools.

Run manually, once, AFTER the code merge has been deployed and verified against
empty tables. Never run this automatically (not wired into `flask init-db`).

Usage:
    python scripts/migrate_contactos_data.py \
        --source-db-url "mysql+pymysql://user:pass@host:3306/contactos_db_name" \
        --target-db-url "mysql+pymysql://user:pass@host:3306/wft" \
        [--force]

Both URLs are read from the command line (or the SOURCE_DB_URL / TARGET_DB_URL
env vars) on purpose — never hardcode real hosts/credentials in this file,
since this repo is public.

What it does:
    1. Refuses to run if the target already has contacts, unless --force.
    2. Migrates users: matches existing WFT users by username (then email);
       the ContactosWH "admin" account maps onto WFT's own existing admin
       instead of being duplicated. Any unmatched user is created fresh with
       a newly generated password (ContactosWH's password hashes are pbkdf2,
       WFT's are bcrypt - NOT portable) and must_change_password=True. Temp
       passwords are printed once at the end for the admin to hand out
       out-of-band - there is no email infrastructure to send them.
    3. Migrates field_definitions, contacts, contact_values, personas
       (renamed from "characters"), persona links (renamed from
       "character_contacts", relationship -> relationship_note), and notes -
       remapping every foreign key through the ID maps built along the way.
"""
import argparse
import os
import secrets
import string
import sys

import bcrypt
import pymysql
import pymysql.cursors


def generate_secure_password(length=16):
    alphabet = string.ascii_letters + string.digits + '!@#$%^&*'
    while True:
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.isupper() for c in password) and any(c.islower() for c in password)
                and any(c.isdigit() for c in password) and any(c in '!@#$%^&*' for c in password)):
            return password


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def connect(url: str):
    # Expect mysql+pymysql://user:pass@host:port/dbname
    assert url.startswith('mysql+pymysql://'), 'Only mysql+pymysql:// URLs are supported'
    rest = url[len('mysql+pymysql://'):]
    creds, hostpart = rest.split('@', 1)
    user, password = creds.split(':', 1)
    hostport, dbname = hostpart.split('/', 1)
    host, port = (hostport.split(':', 1) + ['3306'])[:2]
    return pymysql.connect(
        host=host, port=int(port), user=user, password=password, database=dbname,
        charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-db-url', default=os.environ.get('SOURCE_DB_URL'),
                        help='ContactosWH MariaDB URL (mysql+pymysql://...)')
    parser.add_argument('--target-db-url', default=os.environ.get('TARGET_DB_URL'),
                        help='WFT MySQL URL (mysql+pymysql://...)')
    parser.add_argument('--force', action='store_true',
                        help='Proceed even if the target already has contacts')
    args = parser.parse_args()

    if not args.source_db_url or not args.target_db_url:
        print('ERROR: --source-db-url and --target-db-url are required '
              '(or SOURCE_DB_URL / TARGET_DB_URL env vars).', file=sys.stderr)
        sys.exit(1)

    src = connect(args.source_db_url)
    dst = connect(args.target_db_url)

    with dst.cursor() as c:
        c.execute('SELECT COUNT(*) AS n FROM contacts')
        existing = c.fetchone()['n']
    if existing and not args.force:
        print(f'ERROR: target already has {existing} contact(s). Pass --force to proceed anyway.',
              file=sys.stderr)
        sys.exit(1)

    temp_passwords = []  # (username, password) for the final report

    # ── 1. Users ──────────────────────────────────────────────────────────
    user_id_map = {}  # source user id -> target user id

    with src.cursor() as c:
        c.execute('SELECT id, username, email, role, is_active, created_at FROM users')
        src_users = c.fetchall()

    with dst.cursor() as c:
        c.execute('SELECT id, username, email FROM users')
        dst_users = c.fetchall()
    dst_by_username = {u['username'].lower(): u for u in dst_users}
    dst_by_email = {u['email'].lower(): u for u in dst_users}

    for su in src_users:
        match = dst_by_username.get(su['username'].lower()) or dst_by_email.get(su['email'].lower())
        if match:
            user_id_map[su['id']] = match['id']
            by_username = su['username'].lower() in dst_by_username
            by_email = su['email'].lower() in dst_by_email
            if by_username != by_email:
                print(f'  WARNING: user "{su["username"]}" matched by only one of '
                      f'username/email against WFT user #{match["id"]} - verify manually.')
            continue

        password = generate_secure_password()
        with dst.cursor() as c:
            c.execute(
                'INSERT INTO users (username, email, password_hash, role, active, '
                'must_change_password, created_at) VALUES (%s, %s, %s, %s, %s, 1, %s)',
                (su['username'], su['email'], hash_password(password),
                 su['role'] if su['role'] in ('admin', 'user') else 'user',
                 bool(su['is_active']), su['created_at']),
            )
            new_id = c.lastrowid
        user_id_map[su['id']] = new_id
        temp_passwords.append((su['username'], password))

    dst.commit()
    print(f'Users: {len(user_id_map)} resolved ({len(temp_passwords)} newly created).')

    # created_by_id lineage, second pass (needs all users to already exist)
    with src.cursor() as c:
        c.execute('SELECT id, created_by_id FROM users WHERE created_by_id IS NOT NULL')
        for row in c.fetchall():
            new_creator = user_id_map.get(row['created_by_id'])
            new_self = user_id_map.get(row['id'])
            if new_creator and new_self:
                with dst.cursor() as c2:
                    c2.execute('UPDATE users SET created_by_id = %s WHERE id = %s',
                              (new_creator, new_self))
    dst.commit()

    # ── 2. Field definitions ─────────────────────────────────────────────
    field_id_map = {}
    with src.cursor() as c:
        c.execute('SELECT id, name, display_name, is_visible, field_order, created_at FROM field_definitions')
        src_fields = c.fetchall()
    for f in src_fields:
        with dst.cursor() as c:
            c.execute(
                'INSERT INTO field_definitions (name, display_name, is_visible, field_order, created_at) '
                'VALUES (%s, %s, %s, %s, %s)',
                (f['name'], f['display_name'], bool(f['is_visible']), f['field_order'], f['created_at']),
            )
            field_id_map[f['id']] = c.lastrowid
    dst.commit()
    print(f'Field definitions: {len(field_id_map)} migrated.')

    # ── 3. Contacts ───────────────────────────────────────────────────────
    contact_id_map = {}
    with src.cursor() as c:
        c.execute('SELECT id, is_visible, created_at, updated_at, created_by_id FROM contacts')
        src_contacts = c.fetchall()
    for ct in src_contacts:
        new_creator = user_id_map.get(ct['created_by_id']) if ct['created_by_id'] else None
        with dst.cursor() as c:
            c.execute(
                'INSERT INTO contacts (is_visible, created_at, updated_at, created_by_id) '
                'VALUES (%s, %s, %s, %s)',
                (bool(ct['is_visible']), ct['created_at'], ct['updated_at'], new_creator),
            )
            contact_id_map[ct['id']] = c.lastrowid
    dst.commit()
    print(f'Contacts: {len(contact_id_map)} migrated.')

    # ── 4. Contact values ────────────────────────────────────────────────
    with src.cursor() as c:
        c.execute('SELECT contact_id, field_id, value FROM contact_values')
        src_values = c.fetchall()
    count = 0
    for v in src_values:
        new_contact = contact_id_map.get(v['contact_id'])
        new_field = field_id_map.get(v['field_id'])
        if new_contact and new_field:
            with dst.cursor() as c:
                c.execute(
                    'INSERT INTO contact_values (contact_id, field_id, value) VALUES (%s, %s, %s)',
                    (new_contact, new_field, v['value']),
                )
            count += 1
    dst.commit()
    print(f'Contact values: {count} migrated.')

    # ── 5. Personas (was "characters") ───────────────────────────────────
    persona_id_map = {}
    with src.cursor() as c:
        c.execute('SELECT id, name, user_id, is_active, created_at FROM characters')
        src_personas = c.fetchall()
    for p in src_personas:
        new_user = user_id_map.get(p['user_id']) if p['user_id'] else None
        with dst.cursor() as c:
            c.execute(
                'INSERT INTO contact_personas (name, user_id, is_active, created_at) '
                'VALUES (%s, %s, %s, %s)',
                (p['name'], new_user, bool(p['is_active']), p['created_at']),
            )
            persona_id_map[p['id']] = c.lastrowid
    dst.commit()
    print(f'Personas: {len(persona_id_map)} migrated.')

    # ── 6. Persona links (was "character_contacts") ──────────────────────
    with src.cursor() as c:
        c.execute('SELECT character_id, contact_id, relationship, updated_at FROM character_contacts')
        src_links = c.fetchall()
    count = 0
    for link in src_links:
        new_persona = persona_id_map.get(link['character_id'])
        new_contact = contact_id_map.get(link['contact_id'])
        if new_persona and new_contact:
            with dst.cursor() as c:
                c.execute(
                    'INSERT INTO contact_persona_links (persona_id, contact_id, relationship_note, updated_at) '
                    'VALUES (%s, %s, %s, %s)',
                    (new_persona, new_contact, link['relationship'], link['updated_at']),
                )
            count += 1
    dst.commit()
    print(f'Persona links: {count} migrated.')

    # ── 7. Notes ──────────────────────────────────────────────────────────
    with src.cursor() as c:
        c.execute('SELECT contact_id, author_id, content, is_global, created_at, updated_at FROM contact_notes')
        src_notes = c.fetchall()
    count = 0
    for n in src_notes:
        new_contact = contact_id_map.get(n['contact_id'])
        new_author = user_id_map.get(n['author_id'])
        if new_contact and new_author:
            with dst.cursor() as c:
                c.execute(
                    'INSERT INTO contact_notes (contact_id, author_id, content, is_global, created_at, updated_at) '
                    'VALUES (%s, %s, %s, %s, %s, %s)',
                    (new_contact, new_author, n['content'], bool(n['is_global']),
                     n['created_at'], n['updated_at']),
                )
            count += 1
    dst.commit()
    print(f'Notes: {count} migrated.')

    src.close()
    dst.close()

    print('\nMigration complete.')
    if temp_passwords:
        print('\nNewly created users - hand out these temporary passwords out-of-band:')
        for username, password in temp_passwords:
            print(f'  {username}: {password}')


if __name__ == '__main__':
    main()
