"""Backup SQLite → OCI Object Storage. Planifie a 03h00 Paris."""

import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

import pytz

PARIS_TZ = pytz.timezone("Europe/Paris")

# Chemins
DB_PATH = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./instafarm.db")
BACKUP_DIR = Path(__file__).resolve().parent.parent.parent / "backups"
MAX_LOCAL_BACKUPS = 7  # Garde les 7 derniers backups locaux


def _get_db_path() -> Path:
    """Extrait le chemin du fichier SQLite depuis DATABASE_URL."""
    url = DB_PATH
    # sqlite+aiosqlite:///./instafarm.db → ./instafarm.db
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            return Path(url[len(prefix):])
    return Path("instafarm.db")


def backup_sqlite() -> Path:
    """
    Backup SQLite avec VACUUM INTO (copie propre sans WAL).
    Retourne le chemin du fichier backup.
    """
    BACKUP_DIR.mkdir(exist_ok=True)

    now = datetime.now(PARIS_TZ)
    filename = f"instafarm_{now.strftime('%Y%m%d_%H%M%S')}.db"
    backup_path = BACKUP_DIR / filename

    db_path = _get_db_path()

    if not db_path.exists():
        raise FileNotFoundError(f"DB non trouvee: {db_path}")

    # VACUUM INTO = copie atomique propre
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(f"VACUUM INTO '{backup_path}'")
    finally:
        conn.close()

    print(f"Backup local: {backup_path} ({backup_path.stat().st_size / 1024:.1f} KB)")
    return backup_path


def cleanup_old_backups():
    """Supprime les backups locaux au-dela de MAX_LOCAL_BACKUPS."""
    if not BACKUP_DIR.exists():
        return

    backups = sorted(BACKUP_DIR.glob("instafarm_*.db"), reverse=True)
    for old_backup in backups[MAX_LOCAL_BACKUPS:]:
        old_backup.unlink()
        print(f"Ancien backup supprime: {old_backup.name}")


def upload_to_oci(backup_path: Path) -> bool:
    """
    Upload vers OCI Object Storage.
    Retourne True si succes, False si OCI non configure.
    """
    bucket_name = os.getenv("OCI_BUCKET_NAME")
    namespace = os.getenv("OCI_NAMESPACE")

    if not bucket_name or not namespace:
        print("OCI non configure (OCI_BUCKET_NAME / OCI_NAMESPACE manquants). Backup local uniquement.")
        return False

    try:
        import oci

        config = oci.config.from_file()
        client = oci.object_storage.ObjectStorageClient(config)

        object_name = f"backups/{backup_path.name}"

        with open(backup_path, "rb") as f:
            client.put_object(
                namespace_name=namespace,
                bucket_name=bucket_name,
                object_name=object_name,
                put_object_body=f,
            )

        print(f"Upload OCI OK: {object_name}")
        return True

    except ImportError:
        print("Module oci non installe. pip install oci")
        return False
    except Exception as e:
        print(f"Upload OCI echoue: {e}")
        return False


def run_backup():
    """Backup complet : local + OCI + cleanup."""
    print(f"=== Backup InstaFarm — {datetime.now(PARIS_TZ).isoformat()} ===")

    backup_path = backup_sqlite()
    upload_to_oci(backup_path)
    cleanup_old_backups()

    print("=== Backup termine ===")
    return backup_path


if __name__ == "__main__":
    run_backup()
