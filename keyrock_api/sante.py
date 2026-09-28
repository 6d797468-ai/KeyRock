"""Contrôles de santé effectifs de l'API KeyRock.

`/health` renvoyait un « ok » statique, quel que soit l'état réel : une
configuration qui rend l'API incapable de produire le moindre token
répondait « ok » et le conteneur restait considéré sain.

Ces contrôles portent sur ce qui est vérifiable **sans** la clé de signature,
donc avant l'étape 1 du plan. Le contrôle de la clé de signature viendra
s'y greffer ; il est volontairement absent plutôt que simulé par un `ok`.

Distinction importante : un contrôle **bloquant** rend le service indisponible
(503), un contrôle **d'avertissement** le signale sans le faire tomber. Un
avertissement traité comme bloquant provoquerait une boucle de redémarrage
sur une configuration par ailleurs fonctionnelle.
"""

from __future__ import annotations

from dataclasses import dataclass

from keyrock_api.middleware import parse_reseau
from keyrock_core.config import KeyRockSettings
from keyrock_core.generator import CoreGenerator, GenerationOptions

__all__ = ["Controle", "RapportSante", "verifier_sante"]


@dataclass(frozen=True, slots=True)
class Controle:
    """Résultat d'un contrôle nommé."""

    nom: str
    ok: bool
    bloquant: bool
    detail: str


@dataclass(frozen=True, slots=True)
class RapportSante:
    """Ensemble des contrôles, avec statut agrégé."""

    controles: tuple[Controle, ...]

    @property
    def statut(self) -> str:
        if any(c.bloquant and not c.ok for c in self.controles):
            return "ko"
        if any(not c.ok for c in self.controles):
            return "degraded"
        return "ok"

    @property
    def disponible(self) -> bool:
        """Faux seulement si un contrôle bloquant a échoué."""
        return not any(c.bloquant and not c.ok for c in self.controles)


def verifier_sante(settings: KeyRockSettings) -> RapportSante:
    """Vérifie que la configuration permet effectivement de servir."""
    return RapportSante((_entropie_atteignable(settings), _proxies_de_confiance(settings)))


def _entropie_atteignable(settings: KeyRockSettings) -> Controle:
    """Le couple (bornes, seuil) doit admettre au moins une longueur servable.

    Condition nécessaire et suffisante : la longueur maximale autorisée
    atteint-elle le seuil d'entropie avec l'alphabet complet ? Si non, aucune
    requête ne peut aboutir et l'API est en panne en ne le signalant pas.
    """
    nom = "entropie_atteignable"
    meilleure = max(
        CoreGenerator.calculer_entropie(GenerationOptions(longueur=settings.token_max_length)),
        CoreGenerator.calculer_entropie(GenerationOptions(longueur=settings.token_min_length)),
    )
    if meilleure >= settings.token_min_entropy:
        return Controle(
            nom=nom,
            ok=True,
            bloquant=True,
            detail=(
                f"{meilleure} bits au maximum, seuil {settings.token_min_entropy} bits : "
                "au moins une longueur est servable"
            ),
        )
    return Controle(
        nom=nom,
        ok=False,
        bloquant=True,
        detail=(
            f"aucune longueur entre {settings.token_min_length} et "
            f"{settings.token_max_length} n'atteint {settings.token_min_entropy} bits avec "
            f"l'alphabet complet (maximum {meilleure} bits) : toute requête recevra un 422"
        ),
    )


def _proxies_de_confiance(settings: KeyRockSettings) -> Controle:
    """Signale une liste de proxies déclarés dont une partie a été écartée.

    `parse_reseau` ignore volontairement les entrées invalides pour dégrader
    vers « aucune confiance » plutôt que vers « tout est fiable ». Ce choix est
    sûr pour la sécurité mais silencieux pour l'exploitant : une faute de
    frappe dans `KEYROCK_TRUSTED_PROXIES` désactive la confiance des en-têtes
    sans aucun signal, et tout le trafic se retrouve mutualisé sur le proxy.
    Non bloquant : le service reste correct, seulement moins fin.

    Le détail ne reprend pas la valeur rejetée : `/health` est public et une
    valeur de configuration n'a pas à y être exposée.
    """
    nom = "proxies_de_confiance"
    declare = settings.trusted_proxies.strip()
    if not declare:
        return Controle(
            nom=nom,
            ok=True,
            bloquant=False,
            detail="aucun proxy déclaré : l'adresse socket fait foi",
        )
    valides = parse_reseau(declare)
    liste = [morceau for morceau in declare.replace(";", ",").split(",") if morceau.strip()]
    ecartes = len(liste) - len(valides)
    if ecartes:
        return Controle(
            nom=nom,
            ok=False,
            bloquant=False,
            detail=(
                f"{ecartes} entrée(s) écartée(s) sur {len(valides) + ecartes} : les en-têtes "
                "X-Forwarded-For de ces proxys ne sont pas crus"
            ),
        )
    return Controle(
        nom=nom,
        ok=True,
        bloquant=False,
        detail=f"{len(valides)} réseau(x) de confiance déclaré(s)",
    )
