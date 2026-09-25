# KEF LSX Web Control

Interface web pour contrôler des enceintes KEF LSX (1ère génération) sur le LAN :
FastAPI + frontend Fluent Design 2, servis par un conteneur Docker.

> ### v2 — from desktop to web
> La **v1** de ce dépôt était une application desktop Python/CustomTkinter
> (`main.py` à la racine, packagée avec PyInstaller) : elle reste accessible sous le
> tag [`v1`](https://github.com/apierrr/Kef_Desktop_Control/tree/v1).
>
> La **v2** reprend la même logique de protocole binaire (port 50001, préservation de
> `standby_time` et de l'orientation, contournement du bug d'extinction) et l'expose en
> API REST + interface web, utilisable depuis un téléphone sans rien installer.
> Le protocole, découvert par reverse-engineering, est documenté dans [`Doc.md`](Doc.md).

## Fonctionnalités

- Sources : Wifi, Bluetooth, Aux, Optical (USB retiré)
- Volume avec slider (drag fluide, pas de snap-back)
- Extinction (avec workaround du bug standby = 20 min)
- Polling auto de l'état toutes les 5 s
- UI Fluent Design 2 (Mica + Acrylic + Reveal effect)
- Préserve les réglages utilisateur (EQ, distance du mur, etc. — jamais touchés)
- Protocole implémenté en direct, sans dépendance à `aiokef`

## Prérequis

- Docker et Docker Compose
- L'IP de l'enceinte sur le LAN (port TCP 50001 joignable depuis l'hôte)

## Installation

```bash
git clone https://github.com/apierrr/Kef_Desktop_Control.git kef-web-control
cd kef-web-control
```

Crée un `.env` avec l'IP de ton enceinte (ce fichier n'est pas versionné) :

```bash
cat > .env <<'ENV'
KEF_IP=192.168.1.12
KEF_PORT=50001
ENV
```

Puis :

```bash
docker compose up -d
```

L'interface est disponible sur `http://<ton-serveur>:8765`.

> Le `docker-compose.yml` démarre aussi un service `lms` (Lyrion Music Server) qui sert
> à diffuser la musique vers l'enceinte en UPnP/DLNA. Si tu ne veux que le contrôle KEF,
> supprime ce service : `docker compose up -d kef-control`.

## Mise à jour de l'IP

Modifier `KEF_IP` dans `.env` puis :

```bash
docker compose up -d
```

(Pas besoin de rebuild : c'est juste une variable d'environnement.)

## Exposition via un tunnel Cloudflare

Ajouter une règle dans le tunnel :

```
kef.example.com  →  http://localhost:8765
```

## Endpoints API

| Méthode | URL | Body |
|---|---|---|
| GET | `/api/state` | — |
| POST | `/api/source` | `{"source": "Wifi"\|"Bluetooth"\|"Aux"\|"Opt"}` |
| POST | `/api/volume` | `{"volume": 0..100}` |
| POST | `/api/off` | — |
| GET | `/healthz` | — |

## Logs

```bash
docker compose logs -f kef-control
```

## Structure

```
.
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .dockerignore
├── Doc.md                   # protocole KEF LSX (reverse-engineering)
└── app/
    ├── main.py              # FastAPI + logique KEF (protocole binaire)
    └── static/
        ├── index.html
        ├── style.css        # Fluent Design 2
        └── app.js
```

## Notes

- L'enceinte est jointe en TCP sur `KEF_IP:50001` depuis le container
  (réseau bridge Docker par défaut, pas besoin de `network_mode: host`).
- La connexion est keep-alive (~1 s) puis re-créée à la demande, comme dans
  l'app desktop d'origine.
- Quand l'enceinte est éteinte, certaines lectures peuvent échouer — l'UI
  affiche alors « Hors ligne » et retente toutes les 5 s.
- Les données runtime de LMS (`lms-config/`, `lms-music/`, `lms-playlists/`) ne sont
  **pas** versionnées : elles contiennent les jetons d'authentification des plugins,
  les logs et un cache de plusieurs centaines de Mo.
