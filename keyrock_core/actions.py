"""Registre d'actions — façade unique déclenchée par la TUI comme par le shell.

Objectif : un clic de souris, une touche et une commande shell appellent
exactement le même code métier. Aucune implémentation dupliquée.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from keyrock_core.service import LONGUEURS_PRESETS, GenerationResultat, GenerationService

__all__ = ["Action", "ActionRegistry", "ActionResultat"]

COMPOSITIONS = ("majuscules", "minuscules", "chiffres", "symboles")


@dataclass(frozen=True, slots=True)
class ActionResultat:
    """Retour uniforme de toute action : succès, message, et données éventuelles."""

    succes: bool
    message: str
    resultat: GenerationResultat | None = None
    donnees: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Action:
    """Une action nommée, avec son Libellé d'aide."""

    nom: str
    description: str
    executer: Callable[..., ActionResultat]


class ActionRegistry:
    """Table d'actions unique — aucun accès direct au `CoreGenerator` ici."""

    #: Dernier résultat produit (jamais journalisé).
    _dernier: GenerationResultat | None = None

    def __init__(self, service: GenerationService) -> None:
        self.service = service
        self._actions: dict[str, Action] = {}
        self._enregistrer_defauts()

    # -- Construction ------------------------------------------------------
    def enregistrer(self, action: Action) -> None:
        self._actions[action.nom] = action

    def _enregistrer_defauts(self) -> None:
        self.enregistrer(Action("generate", "Générer des tokens", self._generer))
        self.enregistrer(Action("regenerate", "Régénérer des tokens", self._regenerer))
        self.enregistrer(Action("copy", "Copier un token", self._copier))
        self.enregistrer(Action("password", "Générer un mot de passe", self._mot_de_passe))
        self.enregistrer(Action("token", "Générer un token", self._token))
        self.enregistrer(Action("set_length", "Définir la longueur", self._set_longueur))
        self.enregistrer(Action("toggle", "Basculer une catégorie", self._basculer))
        self.enregistrer(Action("reset", "Réinitialiser la configuration", self._reset))
        self.enregistrer(Action("info", "État et configuration", self._info))
        self.enregistrer(Action("clear", "Effacer l'écran", self._clear))
        self.enregistrer(Action("exit", "Quitter", self._exit))

    # -- Accès -------------------------------------------------------------
    def noms(self) -> list[str]:
        return sorted(self._actions)

    def decrire(self) -> list[tuple[str, str]]:
        return [(n, self._actions[n].description) for n in self.noms()]

    def executer(self, nom: str, **kwargs: Any) -> ActionResultat:
        """Exécute une action. Ne lève pas : retourne un `ActionResultat` en cas d'échec."""
        action = self._actions.get(nom)
        if action is None:
            return ActionResultat(
                succes=False, message=f"Action inconnue : {nom!r}", donnees={"actions": self.noms()}
            )
        try:
            return action.executer(**kwargs)
        except ValueError as exc:
            return ActionResultat(succes=False, message=str(exc))
        except Exception as exc:  # garde-fou : aucun détail interne au terminal
            return ActionResultat(succes=False, message=f"Erreur interne ({type(exc).__name__}).")

    # -- Implémentation ----------------------------------------------------
    def _generer(self, nombre: int = 2) -> ActionResultat:
        resultat = self.service.generer(nombre)
        self._dernier = resultat
        return ActionResultat(
            succes=True,
            message=f"{len(resultat.tokens)} token(s) de {resultat.longueur} caractères.",
            resultat=resultat,
        )

    def _regenerer(self) -> ActionResultat:
        return self._generer(nombre=2)

    def _copier(self, index: int = 0) -> ActionResultat:
        from keyrock_cli.display import copier_vers_presse_papier

        dernier = getattr(self, "_dernier", None)
        if not isinstance(dernier, GenerationResultat):
            return ActionResultat(
                succes=False, message="Rien à copier : générez d'abord des tokens."
            )
        if not 0 <= index < len(dernier.tokens):
            return ActionResultat(succes=False, message=f"Index de token invalide : {index}")
        copie = copier_vers_presse_papier(dernier.tokens[index], delai_secondes=30.0)
        self._dernier = dernier
        if copie:
            return ActionResultat(
                succes=True,
                message="Presse-papier copié — effacement automatique dans 30 s.",
            )
        return ActionResultat(succes=False, message="Presse-papier indisponible sur ce système.")

    def _mot_de_passe(self, longueur: int = 24) -> ActionResultat:
        resultat = self.service.generer_avec(
            longueur, nombre=1, composition=dict.fromkeys(COMPOSITIONS, True)
        )
        self._dernier = resultat
        return ActionResultat(
            succes=True,
            message=f"Mot de passe de {resultat.longueur} caractères.",
            resultat=resultat,
        )

    def _token(self, longueur: int = 64) -> ActionResultat:
        resultat = self.service.generer_avec(
            longueur, nombre=1, composition=dict.fromkeys(COMPOSITIONS, True)
        )
        self._dernier = resultat
        return ActionResultat(
            succes=True,
            message=f"Token de {resultat.longueur} caractères.",
            resultat=resultat,
        )

    def _set_longueur(self, longueur: int) -> ActionResultat:
        self.service.set_longueur(longueur)
        return ActionResultat(
            succes=True,
            message=f"Longueur fixée à {longueur} ({self.service.entropie()} bits).",
            donnees={"longueur": self.service.longueur(), "entropie": self.service.entropie()},
        )

    def _basculer(self, champ: str) -> ActionResultat:
        valeur = self.service.basculer(champ)
        return ActionResultat(
            succes=True,
            message=f"{champ} {'activé' if valeur else 'désactivé'}.",
            donnees={champ: valeur},
        )

    def _reset(self) -> ActionResultat:
        self.service.reinitialiser()
        self._dernier = None
        return ActionResultat(succes=True, message="Configuration réinitialisée.")

    def _info(self) -> ActionResultat:
        return ActionResultat(
            succes=True,
            message="État courant.",
            donnees={
                "longueur": self.service.longueur(),
                "entropie_bits": self.service.entropie(),
                "alphabet": len(self.service.alphabet()),
                "composition": self.service.composition(),
                "presets": list(LONGUEURS_PRESETS),
            },
        )

    def _clear(self) -> ActionResultat:
        from keyrock_cli.display import effacer_ecran_et_scrollback, vider_presse_papier

        effacer_ecran_et_scrollback()
        vider_presse_papier()
        return ActionResultat(succes=True, message="Écran et presse-papier purgés.")

    def _exit(self) -> ActionResultat:
        return ActionResultat(succes=True, message="Fermeture.", donnees={"exit": True})

    def memoriser(self, resultat: GenerationResultat) -> None:
        self._dernier = resultat

    def dernier(self) -> GenerationResultat | None:
        return self._dernier
