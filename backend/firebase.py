"""Connexion Firebase Admin SDK — Firestore pour le pipeline TikTok."""

import os
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore

_app = None
_db = None


def get_db():
    """Retourne le client Firestore (singleton)."""
    global _app, _db
    if _db is not None:
        return _db

    cred_path = os.getenv(
        "GOOGLE_APPLICATION_CREDENTIALS",
        str(Path(__file__).parent / "firebase-credentials.json"),
    )

    if not os.path.exists(cred_path):
        raise FileNotFoundError(
            f"Firebase credentials not found at {cred_path}. "
            "Set GOOGLE_APPLICATION_CREDENTIALS or place firebase-credentials.json in backend/"
        )

    cred = credentials.Certificate(cred_path)
    _app = firebase_admin.initialize_app(cred)
    _db = firestore.client()
    print(f"[FIREBASE] Connected to {cred_path}")
    return _db


db = get_db()
