# Beitragen / Contributing

Contributions in English or German are welcome.

Hinweis: Der bestehende Code wurde vollständig KI-generiert (siehe `AI_DISCLOSURE.md`). Reviews,
Tests an echter Hardware und Fehlerberichte von Menschen sind besonders wertvoll. Mit einem Beitrag
stimmen Sie zu, dass er unter der MIT-Lizenz des Projekts veröffentlicht wird.

## Grundregeln

1. **Keine Hersteller-, Produkt- oder Markennamen** in Code, Kommentaren, Beispieldaten oder UI.
   Beispiele bleiben neutral (`ecu_a`, `vendor_x`, `provider_a`).
2. **Keine** proprietären Bibliotheken, Seeds, Keys, Passwörter, Teilenummern oder „magischen“
   Adressen einchecken. Gerätespezifisches gehört in lokale Konfig-Pakete (git-ignoriert).
3. Abweichungen von ISO 14229 / ISO 15765 nur als **dokumentierte Konfigurationsoption**.
4. Schichten trennen: keine Protokolllogik in der UI; jede Funktion muss über die API erreichbar sein.

## Workflow

* Branches: `feature/…`, `fix/…`, `docs/…`; Pull Requests gegen `main`.
* **Conventional Commits** (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `ci:`, `build:`).
* Vor dem Push:

```bash
ruff check backend && ruff format --check backend && mypy && pytest
cd frontend && npm run lint && npm run format:check && npm test && npm run build
```

* Neue Protokollfunktionen brauchen Tests – bei Transport/Timing in der Konformitäts-Suite
  (`@pytest.mark.conformance`), Ende-zu-Ende gegen das ECU-Testdouble.
* UI-Texte zentral in `frontend/src/i18n/` (Deutsch ist Standard).
* Releases: Eintrag in `CHANGELOG.md`, Version in `pyproject.toml` und `backend/udsbench/__init__.py`,
  Tag `vX.Y.Z` → CI baut Wheel und Ein-Datei-Builds je Plattform.
* Keine echten Spezifikationen, Traces oder Konfig-Pakete realer Steuergeräte in Issues oder Pull
  Requests anhängen – sie können vertraulich sein.
