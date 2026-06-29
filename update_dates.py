"""
Script pour mettre à jour les dates d'upload des images avec des dates aléatoires
sur les 30 derniers jours pour rendre le graphique d'évolution temporelle cohérent.
"""
import sqlite3
import random
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database.db"

def update_random_dates():
    """Assigne des dates aléatoires sur les 30 derniers jours à toutes les images."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Récupérer toutes les images
    images = conn.execute("SELECT id FROM images").fetchall()
    total_images = len(images)

    print(f"Mise à jour des dates pour {total_images} images...")

    # Date actuelle
    now = datetime.now()

    # Distribution réaliste : plus d'images récentes que anciennes
    # On utilise une distribution pondérée
    updated = 0

    for image in images:
        # Générer un nombre aléatoire entre 0 et 30 (jours dans le passé)
        # Avec une pondération vers les jours récents (0-10 jours plus probables)
        weights = [3] * 10 + [2] * 10 + [1] * 10  # Plus de poids pour les 10 premiers jours
        days_ago = random.choices(range(30), weights=weights)[0]

        # Générer une heure aléatoire dans la journée
        random_hour = random.randint(6, 22)  # Entre 6h et 22h
        random_minute = random.randint(0, 59)
        random_second = random.randint(0, 59)

        # Calculer la date
        random_date = now - timedelta(
            days=days_ago,
            hours=now.hour - random_hour,
            minutes=now.minute - random_minute,
            seconds=now.second - random_second
        )

        # Format ISO 8601
        upload_date = random_date.strftime("%Y-%m-%d %H:%M:%S")

        # Mettre à jour
        conn.execute(
            "UPDATE images SET upload_date = ? WHERE id = ?",
            (upload_date, image["id"])
        )
        updated += 1

    conn.commit()
    conn.close()

    print(f"OK {updated} dates mises a jour avec succes")
    print(f"  - Distribution sur 30 jours avec ponderation vers les jours recents")
    print(f"  - Heures aleatoires entre 6h et 22h")

if __name__ == "__main__":
    update_random_dates()
