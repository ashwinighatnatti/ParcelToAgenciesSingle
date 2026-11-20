# Run steps (Windows / PowerShell)

## One-time setup
1. Install Python 3.12+ and git.
2. Clone and enter the repo:
   `git clone <repo-url>` then `cd <repo>`
3. Create a virtual environment and install dependencies:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python -m playwright install chromium
   ```
4. Create the two secret files (never committed):
   - `copy .env.example .env`, then fill in `AZURE_ANTHROPIC_API_KEY`, `AZURE_ANTHROPIC_API_ENDPOINT`, `AZURE_ANTHROPIC_DEPLOYMENT_NAME`.
   - Only for the Triage tab: create `single_collector\.env_typesafe` with `TYPESAFE_API_KEY=...` and `TYPESAFE_DEFAULT_MODEL=jev-1.12`.

## Start the UI
```
.\start_server.ps1
```
It applies database migrations, starts Django in the background and waits until http://127.0.0.1:8000/ responds.
(Foreground alternative: `python django_ui/manage.py migrate` then `python django_ui/manage.py runserver`.)
If PowerShell blocks scripts, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or prefix with `powershell -ExecutionPolicy Bypass -File`.

## Use it
Open http://127.0.0.1:8000/ : search a single parcel, run a batch, view history, jurisdictions, state ranking and triage.
Server output goes to `django_run.log` and `django_run.err`.

## Stop and clean up
```
.\stop_server.ps1            # stop the server, stray pipeline runs and Playwright browsers; delete __pycache__ and logs
.\stop_server.ps1 -Deep      # also delete output\, downloads\ and the search-history database (asks first)
.\stop_server.ps1 -Port 8001 # if you started on another port
```
It matches any Django `runserver` or `single_collector` pipeline process on the machine, so stop other copies of this app first if you run several.
It never deletes `.env`, `.env_typesafe` or source files.

## Troubleshooting
- "Missing AZURE_ANTHROPIC_..." : `.env` is missing or incomplete.
- Port 8000 busy: run `.\stop_server.ps1`, or use `.\start_server.ps1 -Port 8001`.
- After `-Deep`, run `python django_ui/manage.py migrate` (start_server.ps1 does this for you).
