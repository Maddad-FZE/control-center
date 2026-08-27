from django.db.backends.signals import connection_created
from django.dispatch import receiver


@receiver(connection_created)
def enable_sqlite_wal(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL;")
