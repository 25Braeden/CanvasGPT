# CanvasGPT

CanvasGPT converts Canvas assignments into editable checklists and personalized study schedules.

## Local setup

### 1. Create a virtual environment

```bash
python -m venv .venv
```

### 2. Activate the virtual environment

On Windows Git Bash:

```bash
source .venv/Scripts/activate
```

On macOS / Linux / WSL:

```bash
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Create your local environment file

```bash
cp .env.example .env
```

### 5. Generate and set a Django secret key

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Copy the output into `.env` as `DJANGO_SECRET_KEY`.

### 6. Configure environment variables

Set these values in `.env`:

```dotenv
DJANGO_SECRET_KEY='your-generated-secret-key'
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
CANVAS_TOKEN='your-canvas-access-token'
```

### 7. Run migrations

```bash
python manage.py migrate
```

### 8. Start the development server

```bash
python manage.py runserver
```

Open http://127.0.0.1:8000/.

## Study planner

Signed-in students can schedule their checklist tasks around their own time:

1. Open **Availability** in the navigation bar and add weekly blocks (for example, every Monday 6:00–8:00 PM) or one-time blocks on a specific date.
2. Open **Study plan** and click **Generate plan**. Incomplete tasks are placed into your availability, earliest due date first, in sessions sized by the session length and break settings on your profile. Every session ends before the assignment is due and no two sessions overlap.
3. Tasks that can't be scheduled (no due date, already past due, or not enough free time before the due date) are listed under **Couldn't schedule** with the reason.
4. Browse the Monday–Sunday list using **Previous week**, **This week**, and **Next week**. Dates and session times use your profile timezone; every date appears, with **No sessions** for empty days. Sessions belong to the week in which they start.
5. Mark sessions complete as you go. When every session for a task is complete, the task is checked off on its assignment checklist. Regenerating keeps completed sessions and only schedules the remaining time. Completion and regeneration keep the selected week.

Weekly links use `?week=YYYY-MM-DD`; any valid date selects its containing Monday–Sunday week. Missing, invalid, or out-of-range values fall back to the current week in your profile timezone.

With JavaScript and session storage enabled, form actions returning to the same page restore your scroll position across the site. Navigation to different pages keeps normal behavior. If an action shortens the page, the browser restores as close to the previous position as the new page height allows. Forms still work without JavaScript.

The dashboard moves assignments to **Past due** when their exact deadline is reached, including deadlines earlier today. **Due soon** continues to use your configured number of days in your timezone; zero-point assignments remain separate.

## Tests

Run the Django suite:

```bash
python manage.py test
```

Run the shared scroll-restoration tests (requires Node.js 18 or later; no npm dependencies):

```bash
node --test tests/preserve-scroll.test.cjs
```

For browser verification, scroll down a populated study week, toggle a session, and regenerate the plan: the selected week and scroll position should remain. Also check checklist actions, profile saves, and availability deletion. Week navigation should open the selected week normally, and navigation to a different page must not inherit the previous page's scroll position.
