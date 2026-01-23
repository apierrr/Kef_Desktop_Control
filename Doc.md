# Documentation du Protocole KEF LSX (1ère génération)

## Résumé

Ce document décrit le protocole de communication des enceintes KEF LSX (1ère génération) découvert par reverse-engineering, ainsi que les solutions implémentées pour contrôler les enceintes sans écraser les réglages utilisateur.

---

## 1. Architecture Réseau des Enceintes KEF LSX

### Ports Ouverts

| Port | Protocole | Usage |
|------|-----------|-------|
| **50001** | TCP - Binaire propriétaire | Contrôle principal (source, volume, power) |
| **80** | HTTP | Interface web (limitée) |
| **443** | HTTPS | Interface web sécurisée |
| **8080** | HTTP - UPnP/SOAP | Contrôle UPnP (volume uniquement) |
| **7000** | TCP | AirPlay |
| **1900** | UDP | UPnP Discovery (SSDP) |

### Port Principal : 50001

C'est le port utilisé par l'application KEF Control et la bibliothèque `aiokef`. Il utilise un protocole binaire propriétaire.

---

## 2. Protocole Binaire (Port 50001)

### Structure des Commandes

Toutes les commandes suivent ce format :

```
[OPCODE] [REGISTRE] [LONGUEUR] [DONNÉES...]
```

### Opcodes

| Opcode | Signification |
|--------|---------------|
| `0x47` | GET (lecture) |
| `0x53` | SET (écriture) |

### Registres Principaux

| Registre | Contenu |
|----------|---------|
| `0x30` | Source + Standby Time + Orientation L/R |
| `0x25` | Volume (0-100) |
| `0x1E` | Startup sound, LED, etc. |

### Exemples de Commandes

#### Lire la source actuelle
```
Envoi:    47 30 80
Réponse:  52 30 81 [CODE_SOURCE]
```

#### Lire le volume
```
Envoi:    47 25 80
Réponse:  52 25 81 [VOLUME]
```

#### Changer le volume à 50
```
Envoi:    53 25 81 32    (0x32 = 50 en décimal)
Réponse:  52 25 81 32
```

#### Changer la source
```
Envoi:    53 30 81 [CODE_SOURCE]
Réponse:  52 30 81 [CODE_SOURCE]
```

#### Éteindre l'enceinte
```
Envoi:    53 30 81 EC    (0xEC = 236)
Réponse:  52 30 81 EC
```

---

## 3. Encodage des Sources (Le Problème Principal)

### Découverte Critique

Le byte de source (`0x30`) encode **trois informations** en un seul octet :
1. La source audio (Wifi, Bluetooth, Optical, etc.)
2. Le temps de veille automatique (20min, 60min, jamais)
3. L'orientation des enceintes (L/R ou R/L inversé)

### Formule de Calcul

```
CODE = BASE_SOURCE + (STANDBY_INDEX × 16) + (ORIENTATION × 64)
```

Où :
- `BASE_SOURCE` : Code de base pour la source (voir tableau)
- `STANDBY_INDEX` : 0 = 20min, 1 = 60min, 2 = jamais
- `ORIENTATION` : 0 = L/R normal, 1 = R/L inversé

### Codes de Base par Source (20min, L/R)

| Source | Code Base |
|--------|-----------|
| Wifi | 2 |
| Bluetooth | 9 |
| Aux | 10 |
| Optical | 11 |
| USB | 12 |

### Table Complète des Codes

```
Source      | 20min L/R | 20min R/L | 60min L/R | 60min R/L | Never L/R | Never R/L
------------|-----------|-----------|-----------|-----------|-----------|----------
Wifi        |     2     |    66     |    18     |    82     |    34     |    98
Bluetooth   |     9     |    73     |    25     |    89     |    41     |   105
Aux         |    10     |    74     |    26     |    90     |    42     |   106
Optical     |    11     |    75     |    27     |    91     |    43     |   107
USB         |    12     |    76     |    28     |    92     |    44     |   108
```

### Le Bug de aiokef

La bibliothèque `aiokef` utilisait des valeurs **codées en dur** :
- Standby = 20 minutes
- Orientation = L/R

Donc à chaque changement de source, elle écrasait ces réglages avec les valeurs par défaut !

---

## 4. Solution Implémentée

### Principe

1. **Lire** l'état actuel avant de changer la source
2. **Décoder** le standby_time et l'orientation actuels
3. **Recalculer** le nouveau code avec la nouvelle source mais les anciens réglages
4. **Écrire** le nouveau code

### Code de Décodage (Python)

```python
INPUT_SOURCES_20_MINUTES_LR = {
    "Bluetooth": 9,
    "Aux": 10,
    "Opt": 11,
    "Usb": 12,
    "Wifi": 2,
}

STANDBY_OPTIONS = [20, 60, None]  # None = jamais

# Construire le mapping complet
INPUT_SOURCES = {}
for source, code in INPUT_SOURCES_20_MINUTES_LR.items():
    LR_mapping = {t: code + i * 16 for i, t in enumerate(STANDBY_OPTIONS)}
    INPUT_SOURCES[source] = {t: (LR, LR + 64) for t, LR in LR_mapping.items()}

# Mapping inverse pour décodage
INPUT_SOURCES_RESPONSE = {}
for source, mapping in INPUT_SOURCES.items():
    for t, (LR, RL) in mapping.items():
        INPUT_SOURCES_RESPONSE[LR] = (source, t, "L/R")
        INPUT_SOURCES_RESPONSE[RL] = (source, t, "R/L")
```

### Fonction de Changement de Source

```python
async def set_source_preserving_settings(conn, new_source):
    # 1. Lire l'état actuel
    current_code, standby_time, orientation = await get_current_state(conn)
    
    # 2. Calculer le nouveau code
    orientation_index = 0 if orientation == "L/R" else 1
    codes = INPUT_SOURCES[new_source][standby_time]
    new_code = codes[orientation_index]
    
    # 3. Envoyer la commande
    await conn.send_command(bytes([0x53, 0x30, 0x81, new_code]))
```

---

## 5. Protocole UPnP (Port 8080)

### Découverte

L'enceinte répond aux requêtes UPnP SOAP sur le port 8080.

### Services Disponibles

- `RenderingControl` : Contrôle du volume ✅
- `AVTransport` : Transport média (non testé)
- `ConnectionManager` : Gestion des connexions

### Contrôle du Volume via UPnP

```python
import requests

def set_volume_upnp(ip, volume):
    url = f"http://{ip}:8080/upnp/control/RenderingControl"
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": '"urn:schemas-upnp-org:service:RenderingControl:1#SetVolume"'
    }
    body = f'''<?xml version="1.0" encoding="utf-8"?>
    <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" 
                s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
        <s:Body>
            <u:SetVolume xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1">
                <InstanceID>0</InstanceID>
                <Channel>Master</Channel>
                <DesiredVolume>{volume}</DesiredVolume>
            </u:SetVolume>
        </s:Body>
    </s:Envelope>'''
    response = requests.post(url, headers=headers, data=body)
    return response.status_code == 200
```

### Limitation UPnP

⚠️ **Le changement de source n'est PAS possible via UPnP** - il faut obligatoirement utiliser le port 50001.

---

## 6. Registres Non Modifiés

Le script ne touche **jamais** aux registres suivants :

| Réglage | Registre | Statut |
|---------|----------|--------|
| Distance du mur | Inconnu | ❌ Jamais accédé |
| EQ (Treble/Bass) | Inconnu | ❌ Jamais accédé |
| Bass Extension | Inconnu | ❌ Jamais accédé |
| Startup Sound | 0x1E | ❌ Jamais accédé |
| LED | 0x1E | ❌ Jamais accédé |

Ces réglages restent donc **intacts** quelles que soient les opérations effectuées.

---

## 7. Connexion Keep-Alive

### Problème

L'enceinte ferme la connexion après quelques secondes d'inactivité.

### Solution

Maintenir une connexion persistante avec reconnexion automatique :

```python
class KefConnection:
    def __init__(self, host, port=50001):
        self.host = host
        self.port = port
        self.socket = None
    
    async def _ensure_connected(self):
        if self.socket is None:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(3.0)
            self.socket.connect((self.host, self.port))
    
    async def send_command(self, command):
        try:
            await self._ensure_connected()
            self.socket.send(command)
            return self.socket.recv(64)
        except:
            self.socket = None
            raise
```

---

## 8. Codes Spéciaux

| Code | Signification |
|------|---------------|
| 236 (0xEC) | Enceinte éteinte (standby) |
| 15 | Bluetooth appairé (variante) |
| 48 | Wifi (variante 60min R/L) |

---

## 9. Outils de Diagnostic

### Scanner les ports
```python
import socket

def scan_ports(ip, ports):
    for port in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((ip, port))
        status = "OPEN" if result == 0 else "CLOSED"
        print(f"Port {port}: {status}")
        sock.close()
```

### Tester le protocole binaire
```python
async def test_protocol(ip):
    conn = KefConnection(ip)
    
    # Lire source
    response = await conn.send_command(bytes([0x47, 0x30, 0x80]))
    print(f"Source: {response.hex()}")
    
    # Lire volume
    response = await conn.send_command(bytes([0x47, 0x25, 0x80]))
    print(f"Volume: {response[3]}")
```

---

## 10. Résumé des Fichiers

| Fichier | Description |
|---------|-------------|
| `main.py` | Application principale avec GUI CustomTkinter |
| `test_kef_protocol.py` | Tests du protocole binaire |
| `test_upnp.py` | Tests du protocole UPnP |
| `test_source_aiokef_logic.py` | Validation du mapping des sources |

---

## 11. Références

- **aiokef** : https://github.com/basnijholt/aiokef (bibliothèque Python originale)
- **KEF LSX** : Enceintes sans fil première génération
- **UPnP/DLNA** : Standard de contrôle multimédia

---

*Document généré le 23 janvier 2026*
