"""Peewee migrations -- 999_add_user_email_to_files.py.

Add user_email column to file table for Supabase sync.
"""

import peewee as pw
from peewee_migrate import Migrator


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    """Add user_email column to file table."""
    
    migrator.add_fields(
        'file',
        user_email=pw.CharField(max_length=255, null=True)
    )


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    """Remove user_email column from file table."""
    
    migrator.remove_fields('file', 'user_email')
