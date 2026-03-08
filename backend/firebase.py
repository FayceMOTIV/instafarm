"""Connexion Firebase Admin SDK — Firestore pour le pipeline TikTok."""

import json
import os
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore

_app = None
_db = None


def get_db():
    """Retourne le client Firestore (singleton).

    Supporte 3 modes :
    1. GOOGLE_APPLICATION_CREDENTIALS_JSON (env var avec le JSON inline — Railway)
    2. GOOGLE_APPLICATION_CREDENTIALS (chemin fichier)
    3. backend/firebase-credentials.json (dev local)
    """
    global _app, _db
    if _db is not None:
        return _db

    # Mode 1 — JSON inline (Railway / cloud)
    json_str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if json_str:
        cred_dict = json.loads(json_str)
        cred = credentials.Certificate(cred_dict)
        _app = firebase_admin.initialize_app(cred)
        _db = firestore.client()
        print("[FIREBASE] Connected via GOOGLE_APPLICATION_CREDENTIALS_JSON")
        return _db

    # Mode 2/3 — Fichier local
    cred_path = os.getenv(
        "GOOGLE_APPLICATION_CREDENTIALS",
        str(Path(__file__).parent / "firebase-credentials.json"),
    )

    if not os.path.exists(cred_path):
        raise FileNotFoundError(
            f"Firebase credentials not found at {cred_path}. "
            "Set GOOGLE_APPLICATION_CREDENTIALS_JSON or place firebase-credentials.json in backend/"
        )

    cred = credentials.Certificate(cred_path)
    _app = firebase_admin.initialize_app(cred)
    _db = firestore.client()
    print(f"[FIREBASE] Connected to {cred_path}")
    return _db


db = get_db()
