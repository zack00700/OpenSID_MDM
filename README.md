# MDM Platform — MVP v1

Interface d'administration sécurisée pour le **Master Data Management** (MDM).

## Fonctionnalités

| Module | Description |
|--------|-------------|
| 🔐 Authentification | Login sécurisé avec JWT, gestion des sessions |
| 📥 Import | CSV et Excel, logs d'import, drag & drop |
| 📋 Entités (CRUD) | Créer, lire, modifier, supprimer avec recherche et filtres |
| 🔍 Détection doublons | Matching exact ou fuzzy (approximatif) sur champs configurables |
| ✅ Golden Record | Fusion manuelle avec sélection champ par champ |
| 📤 Export CSV | Export des entités actives et/ou des Golden Records |

## Démarrage rapide

### Prérequis

- Python 3.9+

### Installation & Lancement

```bash
# Cloner / dézipper le projet
cd mdm-app

# Démarrer (installe les dépendances automatiquement)
python start.py
```

Puis ouvrir : **http://localhost:3000**

| Champ | Valeur |
|-------|--------|
| Email | `admin@mdm.local` |
| Mot de passe | `admin123` |

---

## Architecture

```
mdm-app/
├── start.py                  # Script de démarrage
├── requirements.txt          # Dépendances Python
├── data/
│   └── mdm.db               # Base SQLite (créée automatiquement)
├── uploads/                  # Fichiers importés (temporaires)
├── backend/
│   └── app.py               # API Flask (port 5000)
└── frontend/
    ├── server.py             # Serveur frontend Flask (port 3000)
    ├── templates/
    │   └── index.html        # Application SPA (Tailwind + JS)
    └── static/
        └── js/
            └── app.js        # Logique frontend
```

## API Endpoints

| Méthode | Route | Description |
|---------|-------|-------------|
| POST | `/api/auth/login` | Authentification |
| GET | `/api/dashboard/stats` | Statistiques générales |
| POST | `/api/import/csv` | Import fichier CSV/Excel |
| GET | `/api/import/logs` | Historique des imports |
| GET | `/api/entities` | Liste des entités (pagination, filtres) |
| POST | `/api/entities` | Créer une entité |
| PUT | `/api/entities/:id` | Modifier une entité |
| DELETE | `/api/entities/:id` | Supprimer une entité |
| POST | `/api/duplicates/detect` | Lancer la détection de doublons |
| GET | `/api/duplicates` | Lister les doublons |
| POST | `/api/golden-records/merge` | Fusionner → Golden Record |
| GET | `/api/golden-records` | Lister les Golden Records |
| POST | `/api/golden-records/ignore` | Ignorer un doublon |
| GET | `/api/export/csv` | Exporter entités CSV |
| GET | `/api/export/golden-records/csv` | Exporter Golden Records CSV |

## Stack Technique

- **Backend** : Python / Flask · SQLite (prod : remplacer par PostgreSQL)
- **Authentification** : JWT (PyJWT) + bcrypt
- **Import** : pandas + openpyxl
- **Matching flou** : thefuzz (Levenshtein)
- **Frontend** : HTML5 / Vanilla JS / Tailwind CSS
- **Base de données** : SQLite (fichier `data/mdm.db`)

## Pour passer en production

1. Remplacer SQLite par PostgreSQL (changer `DB_PATH` par une URL PostgreSQL dans `backend/app.py`)
2. Changer `MDM_SECRET` par une clé secrète forte (variable d'environnement)
3. Utiliser Gunicorn ou uWSGI pour le backend
4. Déployer le frontend avec Nginx

```bash
# Exemple variable d'environnement
export MDM_SECRET="votre-clé-secrète-très-longue-et-aléatoire"
```
