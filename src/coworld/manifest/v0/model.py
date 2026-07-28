"""Coworld manifest v0.

V0 and the runtime model intentionally alias today's ``CoworldManifest`` to
avoid duplicating the current model. On the first schema change that must not
apply to v0, copy the affected class or classes into this module and freeze
them here. Runtime evolution after that point belongs in the runtime model, and
compatibility belongs in ``converter.py``.

``V0StoredManifest`` widens the STORED-READ contract only: the prod corpus
contains pre-v0 rows (uploaded before docs/readme were required and before
protocol docs were typed) that the authoring contract never accepted. Uploads
keep validating against the strict ``V0Manifest``; the registry reads stored
rows through ``V0StoredManifest``, whose lift normalizes those historical
shapes into the current one. The lift is documented field by field below —
each branch corresponds to a shape that exists in the stored corpus today.
"""

import copy
from typing import Any

from pydantic import model_validator

from coworld.types import CoworldManifest as V0Manifest


class V0StoredManifest(V0Manifest):
    """V0 reader for stored rows: current contract plus pre-v0 historical shapes."""

    @model_validator(mode="before")
    @classmethod
    def _lift_pre_v0_shapes(cls, document: Any) -> Any:
        if not isinstance(document, dict) or not isinstance(document.get("game"), dict):
            return document
        game = document["game"]
        protocols = game.get("protocols")
        docs = game.get("docs")
        needs_lift = (
            (isinstance(protocols, dict) and any(isinstance(protocols.get(k), str) for k in ("player", "global")))
            or not isinstance(docs, dict)
            or "readme" not in docs
        )
        if not needs_lift:
            return document

        # Never mutate the input: it is the row's raw JSONB document.
        document = copy.deepcopy(document)
        game = document["game"]

        # Pre-v0 rows stored protocol docs as bare Markdown strings before the
        # typed {"type": "text"|"uri", "value": ...} contract existed.
        protocols = game.get("protocols")
        if isinstance(protocols, dict):
            for key in ("player", "global"):
                if isinstance(protocols.get(key), str):
                    protocols[key] = {"type": "text", "value": protocols[key]}

        # Pre-v0 rows predate required docs (missing entirely) or required
        # docs.readme (pages only). These worlds never had a readable README;
        # the game description is the honest stand-in.
        docs = game.setdefault("docs", {})
        if isinstance(docs, dict) and "readme" not in docs:
            docs["readme"] = {"type": "text", "value": game.get("description") or game.get("name") or "(no README)"}
        return document


__all__ = ["V0Manifest", "V0StoredManifest"]
