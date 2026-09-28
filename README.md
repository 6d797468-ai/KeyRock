# KeyRock

Générateur de clés & tokens cryptographiques — **usage unique de Vextra Agency**.
Développé par Nawfel Reghai.

CSPRNG (`secrets`), validation d'entropie NIST SP 800-63B, **zéro persistance** :
aucun token n'est écrit sur disque, ni conservé dans le scrollback du terminal,
ni journalisé.

---

## Architecture

```
                    ┌──────────────┐
        humain ────▶│  keyrock_cli │◀──── TUI Rich (clavier)
        souris  ───▶│  (tui.py)    │◀──── TUI Textual (souris + clavier)
                    └──────┬───────┘
                           │
        script   ────▶┌────┴───────┐
                       │keyrock_shell│  dispatcher `kr`
                       └──────┬──────┘
                              │
                    ┌─────────┴──────────┐
                    │  keyrock_core      │
                    │  service.py        │  GenerationService
                    │  actions.py        │  ActionRegistry (source unique)
                    │  generator.py      │  CoreGenerator + secrets
                    │  config.py         │  Pydantic Settings
                    └─────────┬──────────┘
                              │
        API  ────▶┌──────────┴─────────┐
                   │    keyrock_api     │
                   └────────────────────┘
```

`CoreGenerator` est le **seul** à appeler `secrets`. Un clic de souris, une
touche et une commande shell déclenchent le même `ActionRegistry` — jamais
trois implémentations.

```
keyrock/
├── main.py                 # lanceur de compatibilité (python main.py)
├── keyrock_core/           # Logique métier — importable, sans UI
│   ├── generator.py        # CoreGenerator + GenerationOptions (frozen)
│   ├── service.py          # GenerationService (orchestration + validations)
│   ├── actions.py          # ActionRegistry (actions partagées TUI/shell)
│   ├── banner.py -> ../keyrock_cli/banner.py
│   └── config.py           # Pydantic Settings (KEYROCK_*)
├── keyrock_cli/            # Interface terminal
│   ├── banner.py           # art ASCII d'origine + crédits
│   ├── display.py          # effacement écran + scrollback, presse-papier
│   ├── interactions.py     # bornes de longueur, confirmations
│   ├── tui.py              # TUI Textual (souris + clavier) + mode dégradé
│   └── app.py              # TUI Rich (KeyRockCLI)
├── keyrock_shell/          # Dispatcher `kr` (shell-first, scripts, CI)
│   ├── cli.py              # grammaire de commandes, --json, garde-fous
│   └── install.py          # install-shell / uninstall-shell (idempotent)
├── keyrock_api/            # API REST FastAPI
│   ├── main.py             # routes, cycle de vie, handlers d'erreurs
│   ├── models.py           # Pydantic request/response + validation entropie
│   └── middleware.py       # rate limiting, en-têtes, logs structurés
├── tests/                  # pytest (306 tests)
├── Dockerfile              # multi-stage, USER non-root, HEALTHCHECK
├── docker-compose.yml      # API + Traefik (HTTPS, rate limit, HSTS)
├── requirements.txt
└── .env.example
```

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .            # installe l'exécutable `kr`
# ou : pip install -r requirements.txt
```

## Utilisation — `kr` (shell-first)

```bash
kr                 # ouvre la TUI (souris + clavier si le terminal le permet)
kr 32              # 2 tokens de 32 caractères
kr gen 64          # forme explicite
kr c 32            # génère puis copie (presse-papier purgé)
kr p 24            # mot de passe
kr t 64            # token
kr r 32            # régénération
kr info            # état et configuration
kr help            # aide
kr gen 32 --json   # sortie machine-readable (scripts, CI)
kr 32 -n 5         # 5 tokens
kr gen 32 alpha    # composition : alpha | alnum | ascii
kr install-shell   # ajoute le bloc KEYROCK au .bashrc / .zshrc (idempotent)
kr uninstall-shell # le retire (idempotent)
```

Deux personnalités, **un seul moteur** :

| Usage        | Commande               |
|--------------|------------------------|
| Humain       | `kr 32`                |
| Automatisé   | `kr gen 32 --json`     |

> **Aucun secret n'est accepté en argument.** Seules les longueurs, les
> commandes et les compositions nommées sont reconnues ; tout le reste est
> refusé avant exécution (fail-closed). Le message de refus est **unique et
> muet** : il ne rejoue jamais la valeur refusée, afin de ne rien laisser dans
> l'historique du shell, les journaux de CI ou un rapport de bug. Un secret ne
> quitte jamais la mémoire du processus.

| Code | Signification |
|---|---|
| `0` | succès |
| `1` | refus d'un argument (secret, commande inconnue) ou erreur métier |
| `2` | erreur de syntaxe de la ligne de commande (option inconnue, valeur invalide) |

`1` ne distingue pas « secret » de « faute de frappe » : le message est le
même dans les deux cas, donc `kr` ne peut pas servir d'oracle pour tester des
secrets.`

### Intégration shell

`kr install-shell` écrit un bloc délimité et **idempotent** :

```bash
# >>> KEYROCK >>>
# Bloc géré par KeyRock. Ne pas éditer à la main.
# `kr install-shell` / `kr uninstall-shell` le gèrent de façon idempotente.
export PATH="$HOME/.local/bin:$PATH"
# <<< KEYROCK <<<
```

Plus des complétions dans `~/.config/keyrock/shell/`. La TUI ne dépend
**jamais** de ce bloc : elle fonctionne sans shell configuré.

## Utilisation — TUI

```bash
kr          # ou : python main.py  (ou : keyrock)
```

- Terminal interactif complet → **TUI Textual** : boutons cliquables à la souris,
  navigation clavier (`Tab` / `Enter`), raccourcis `g` générer, `c` copier,
  `r` réinitialiser, `q` quitter.
- Terminal sans souris → **TUI Rich** (clavier seul), même moteur métier.
- Sortie non interactive (pipe, cron, CI) → le `CLI` de `keyrock_shell`.

Les tokens s'affichent dans le **buffer d'écran alternatif** et sont purgés
(écran `\033[2J` + scrollback `\033[3J`) dès validation.

La copie presse-papier (`kr c 32`) reste collable après la sortie de `kr`, puis
disparaît d'elle-même au bout de 30 s. L'effacement est confié à un processus
détaché, entièrement détaché des tubes du script appelant : le token ne survit
jamais au délai, et un script n'attend pas un lecteur de presse-papier.

## API REST

```bash
uvicorn keyrock_api.main:app --host 0.0.0.0 --port 8000
```

| Méthode | Chemin | Rôle |
|---|---|---|
| `GET`  | `/health` | sonde Docker / Traefik |
| `GET`  | `/api/v1/meta` | métadonnées et bornes |
| `POST` | `/api/v1/generate` | génération (1 à 16 tokens) |

```bash
curl -X POST http://localhost:8000/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"longueur": 32, "symboles": true}'
```

```json
{
  "token1": "o^s2Ljfd]=zfP",
  "token2": "Qa3#xTr-91wZm",
  "longueur": 32,
  "entropie_bits": 209.75,
  "alphabet": 94
}
```

## Règles de sécurité appliquées

| Règle | Mise en œuvre |
|---|---|
| CSPRNG obligatoire | `secrets.choice()` — jamais `random` (test de non-régression dédié) |
| Entropie ≥ 80 bits | `longueur × log2(|alphabet|)`, rejet fail-fast côté CLI **et** API |
| Longueur bornée | `LONGEUR_MIN = 8`, `LONGEUR_MAX = 1024` |
| Zéro scrollback | `\033[3J\033[2J\033[H` + buffer d'écran alternatif |
| Zéro persistance | aucun token journalisé, mis en cache ou écrit sur disque |
| Zéro fuite d'erreur | handlers JSON standardisés, sans stack trace |
| En-têtes durcis | HSTS, `nosniff`, `DENY`, `no-referrer`, `Cache-Control: no-store` |
| Quota | rate limiting mémoire par IP + middleware Traefik |
| Aucun secret en argv | `kr` refuse tout argument qui n'est pas une longueur/commande/composition |
| Presse-papier | purgé 30 s après la copie par un processus détaché, sans bloquer ni l'appelant ni le script appelant |
| Processus de purge | `start_new_session` + E/S sur `/dev/null` : aucun tube hérité, aucun processus zombie |
| Conteneur durci | utilisateur non-root, `read_only`, `cap_drop: ALL` |

## Configuration

Copiez `.env.example` en `.env`. Variables : `KEYROCK_API_HOST`,
`KEYROCK_API_PORT`, `KEYROCK_LOG_LEVEL`, `KEYROCK_TOKEN_MIN_LENGTH`,
`KEYROCK_TOKEN_MAX_LENGTH`, `KEYROCK_TOKEN_MIN_ENTROPY`,
`KEYROCK_RATE_LIMIT_PER_MINUTE`, `KEYROCK_CORS_ALLOW_ORIGINS`.

## Déploiement

```bash
KEYROCK_DOMAIN=api.exemple.tld docker compose up --build -d
docker compose ps        # keyrock-api-1 doit être « (healthy) »
```

L'API n'est **pas** publiée sur l'hôte : elle n'est atteignable que via
Traefik, en TLS. Publier `8000` en clair court-circuiterait le TLS, le HSTS et
le rate-limit Traefik — c'est délibéré.

```bash
# Sonde
curl -sk --resolve api.exemple.tld:443:127.0.0.1 https://api.exemple.tld/health

# Génération
curl -sk --resolve api.exemple.tld:443:127.0.0.1 \
  -X POST https://api.exemple.tld/api/v1/generate \
  -H 'Content-Type: application/json' -d '{"longueur": 32, "nombre": 2}'

# Débogage : entrée directe dans le conteneur
docker compose exec api python -c \
  "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/health').read())"
```

En développement local, sans Traefik :

```bash
uvicorn keyrock_api.main:app --host 127.0.0.1 --port 8000
```

Le conteneur API tourne en `read_only`, `cap_drop: ALL`,
`no-new-privileges`, avec des ressources plafonnées (1 CPU / 256 Mo).

## Qualité

```bash
python -m pytest tests/ -v
ruff check keyrock_core/ keyrock_cli/ keyrock_api/ keyrock_shell/ tests/
ruff format --check keyrock_core/ keyrock_cli/ keyrock_api/ keyrock_shell/ tests/
mypy keyrock_core/ keyrock_cli/ keyrock_api/ keyrock_shell/
```

## Décisions d'architecture

| Sujet | Position retenue | État |
|---|---|---|
| Reverse proxy | Traefik (labels Docker, TLS Let's Encrypt, HSTS, rate-limit) | Implémenté — `docker-compose.yml` |
| Authentification API | **Aucune** ; l'API n'est exposée que via Traefik, jamais sur l'hôte | À valider avec Vextra Agency |
| Rate limiting | En mémoire, par IP, par process | Implémenté — `keyrock_api/middleware.py` |
| CORS | Désactivé par défaut, à activer explicitement via `KEYROCK_CORS_ALLOW_ORIGINS` | Implémenté |
| CSPRNG | `secrets.choice()` (wrapper CPython de `os.urandom`) | Implémenté |
| Entropie minimale | 80 bits (NIST SP 800-63B) | Implémenté |
| Bornes de longueur | 8 à 1024 | Implémenté |

### Points en attente de Vextra Agency

**1. Authentification de l'API.** L'API est aujourd'hui ouverte à quiconque
atteint le domaine, limitée par le rate limiting. C'est acceptable pour un
usage interne (réseau privé, ou domaine non publié), insuffisant si l'API est
exposée publiquement. Si une authentification est requise, OAuth2 / JWT
apporte une dépendance et un stockage de clés — à arbitrer avec la contrainte
« zéro persistance ».

**2. Équilibrage de charge et « zéro persistance ».** Le rate limiting tient
en mémoire d'un seul process. Passer à plusieurs réplicas le rendrait
incontournablement faux (chaque process compte de son côté) et exigerait un
état partagé — typiquement Redis, qui entre en tension directe avec le
« zéro persistance ».

Position par défaut retenue : **une seule instance**, cohérente avec la
contrainte de zéro persistance. Toute montée en charge suppose de revisiting
explicitement ce point.

**3. Cache applicatif.** Aucun cache n'existe et aucun ne doit être ajouté :
`Cache-Control: no-store` est posé sur toutes les réponses, et un cache de
jetons serait une fuite par définition. À maintenir.
