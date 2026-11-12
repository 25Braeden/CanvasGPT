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

## Task suggestions: browser demo (no API key)

The assignment page has a **Generate demo suggestions** button and persistent
pending drafts. Demo is the default generation mode: it uses fixed, generic
mocked suggestions, not AI-generated tasks tailored to the assignment. No API
request is made in demo mode, even if an OpenAI key is present in `.env`.

```dotenv
AI_SUGGESTIONS_MODE=demo
OPENAI_API_KEY=
```

Provider selection is server-side only; submitted form values cannot change it.

To try it:

1. Install dependencies (`python -m pip install -r requirements.txt`).
2. Configure the existing Django settings in `.env` as described in Local setup.
   Keep `AI_SUGGESTIONS_MODE=demo` (also the default if unset) and leave
   `OPENAI_API_KEY` blank. Run `python manage.py migrate` to create the new
   `SuggestionDraft` table.
3. Run `python manage.py runserver`, sign in, and open a synchronized assignment
   with a description or rubric criteria.
4. Click **Generate demo suggestions**. A preview appears above the unchanged
   checklist. A metadata-only `AIRequest` is recorded with model name
   `demo-task-suggestions` so demo attempts cannot be mistaken for real AI calls.
5. Confirm that existing tasks and completed work are unchanged. Refresh or
   leave and return: the pending draft is still displayed without another AI
   call/audit entry. Drafts expire after 24 hours and cannot be accepted or
   edited yet. Successful regeneration replaces the pending draft; failed
   generation or storage leaves the previous draft available.
6. An assignment with no description or rubric shows a safe failure message;
   manual task creation remains available.

The button submits a CSRF-protected POST and requires assignment ownership.
With JavaScript enabled, generation updates only the preview in place, without
reloading the page or restoring scroll after a reload. The button is disabled
and progress is announced during the request. Network/session errors show a
safe inline message and allow retry; requests are not automatically resubmitted.
The form still works without JavaScript (or without `fetch`), using the shared
scroll-preservation behavior on full-page responses. In that fallback mode,
refreshing a POST response may ask to resubmit and create another audit attempt,
but never adds checklist tasks.

## Switching providers (optional; keep demo mode for offline testing)

Draft persistence is provider-independent: `ai_assistant/drafts.py` selects a
provider and uses the same validated result contract for demo and OpenAI. To
explicitly opt into live generation later, change `.env` and restart Django:

```dotenv
AI_SUGGESTIONS_MODE=openai
OPENAI_API_KEY=replace-with-your-own-openai-api-key
OPENAI_MODEL=gpt-4o-mini
OPENAI_TIMEOUT_SECONDS=30
```

Use a model that supports Chat Completions strict JSON-schema output. The timeout
must be greater than zero and at most 120 seconds; automatic SDK retries are
disabled. Never commit real credentials. Missing/invalid configuration disables
live suggestions, not the offline browser demo, manual checklist creation, or
the rest of the application. Restart Django after changing `.env`. Real API
requests may incur charges. There is no automatic demo/live fallback. Unknown
modes fail safely; merely adding an API key never enables live requests. Canvas
credentials are configured separately and are never sent to OpenAI.

Saved drafts record their original provider mode/model. Switching the current
mode does not relabel a saved demo draft as live-generated. The button and source
text notice reflect the configured mode; the preview reflects its saved origin.

`ai_assistant.services.generate_task_suggestions(assignment=assignment, user=user)`
returns a `SuggestionResult` with immutable `suggestions` on success, or an empty
suggestion tuple, a safe `failure` code, and a manual-creation fallback `message`.
Call it only on an explicit generation action, not during page rendering.

Only the selected assignment's plain-text description and rubric titles and
descriptions are sent to OpenAI. Assignment text is treated as untrusted input;
no tools or link fetching are enabled. Canvas tokens, student account details,
other assignments, and existing checklist tasks are not included. Source text
is still sent to an external provider: review your institution's data policy.
Requests use `store=False`; this is not a guarantee of zero provider retention.

The service requires 1–20 suggestions, descriptions of 1–500 trimmed characters,
and integer estimates of 1–480 minutes. Malformed, empty, refused, truncated, or
partially invalid responses are rejected in full. Input is limited to 50,000
source-text characters and 50 rubric criteria; entirely empty input is rejected.

Every authorized generation attempt records only the user association, request
type, timestamp, configured model, and success status in `AIRequest`. Configuration
and input failures are unsuccessful attempts; invalid live model configuration
uses `(unconfigured)` in the audit. Demo attempts use `demo-task-suggestions`
and bypass OpenAI credential, model, and timeout configuration. Unauthorized attempts do not call the provider or
create an audit. Prompts, responses, secrets, and raw provider errors are not
logged by the service. Audit-write failure withholds suggestions.

**Generation never saves `TaskItem` rows or changes checklist/planner work.**
The browser offers saved, read-only drafts. A separate review workflow must
still let students select/edit suggestions and explicitly accept them before
creating tasks. `SuggestionDraft` stores only validated descriptions and duration
estimates, the student/assignment association, provider mode/model, timestamps,
and lifecycle status—not source prompts or raw provider responses. `AIRequest`
remains metadata-only. Generation success in the audit means provider output
passed validation; draft storage can separately fail safely.

There is at most one pending draft per student/assignment. Successful replacement
marks the previous draft `superseded` in a transaction. `accepted` and `discarded`
statuses are reserved for the future review workflow; no acceptance/discard
endpoint is implemented yet. Expired and terminal-status drafts are not shown.
Acceptance must later lock the assignment/draft, revalidate values and ownership,
and append rather than replace existing tasks. Manual checklist actions remain
available unchanged.

Expiry hides drafts but does not automatically remove their stored content.
Schedule this cleanup command (for example, hourly) to delete expired draft
rows, including superseded drafts, without changing tasks, plans, or audits:

```bash
python manage.py purge_expired_suggestion_drafts
```

Run the isolated mocked tests with no API key or external requests:

```bash
python manage.py test ai_assistant.test_services ai_assistant.test_suggestion_views ai_assistant.test_drafts
```

Tests inject an SDK-compatible client or patch its constructor; do not configure
a live key for tests.

## Study planner

Signed-in students can schedule their checklist tasks around their own time:

1. Open **Availability** in the navigation bar and add weekly blocks (for example, every Monday 6:00–8:00 PM) or one-time blocks on a specific date.
2. Open **Study plan** and click **Generate plan**. Incomplete tasks are placed into your availability, earliest due date first, in sessions sized by the session length and break settings on your profile. Every session ends before the assignment is due and no two sessions overlap.
3. Tasks that can't be scheduled (no due date, already past due, or not enough free time before the due date) are listed under **Couldn't schedule** with the reason. Use **Review assignment** for missing or past-due dates, or **Adjust availability** for availability-related warnings. Tasks added after generation may also be missing from the plan; regenerate after adding tasks or changing availability.
4. Browse the Monday–Sunday list using **Previous week**, **This week**, and **Next week**. Dates and session times use your profile timezone; every date appears, with **No sessions** for empty days. Sessions belong to the week in which they start.
5. Mark sessions complete as you go. When every session for a task is complete, the task is checked off on its assignment checklist. Regenerating keeps completed sessions and only schedules the remaining time. Completion and regeneration keep the selected week.

Above the weekly schedule, **Entire active plan** shows scheduled unfinished minutes, completed session minutes, and the number of tasks not scheduled. Minutes come from actual session durations, not task estimates. These totals cover the entire active plan and stay the same when browsing different weeks; inactive plans and other students' records are excluded.

Without an active plan, the page guides you to add availability and generate a plan instead of showing totals or scheduling-failure warnings. With no tasks or sessions to display, it links to assignment sync and checklist creation instead of showing all-zero totals. Completed-only plans retain their completed minutes and show a completion message. Plans with tasks that could not fit still show accurate zero-minute totals and actionable warnings.

Weekly links use `?week=YYYY-MM-DD`; any valid date selects its containing Monday–Sunday week. Missing, invalid, or out-of-range values fall back to the current week in your profile timezone.

With JavaScript and session storage enabled, form actions returning to the same page restore your scroll position across the site. **Previous week**, **This week**, and **Next week** also preserve scroll position while changing the selected week. Navigation to different pages keeps normal behavior. If an action shortens the page, the browser restores as close to the previous position as the new page height allows. Forms still work without JavaScript.

The dashboard moves assignments to **Past due** when their exact deadline is reached, including deadlines earlier today. **Due soon** continues to use your configured number of days in your timezone; zero-point assignments remain separate.

## Tests

Run the Django suite:

```bash
python manage.py test
```

Run the shared scroll-restoration tests (requires Node.js 18 or later; no npm dependencies):

```bash
node --test tests/preserve-scroll.test.cjs tests/suggestions.test.cjs
```

For summary browser verification, check both desktop and narrow/mobile widths. Confirm that the summary wraps without horizontal overflow, appears above the weekly schedule, and stays unchanged when navigating to another week (including an empty week). Toggle a session and confirm minutes move between unfinished and completed totals. Check **Adjust availability** and **Review assignment** beside the appropriate warning reasons. Also check no-plan, no-task, completed-only, and wholly unscheduled plans for the guidance described above.

For browser verification, scroll down a populated study week, toggle a session, and regenerate the plan: the selected week and scroll position should remain. Also check checklist actions, profile saves, and availability deletion. Click each week-navigation link and confirm the selected week changes while your scroll position remains (subject to the new page height). Navigation to a different page must not inherit the previous page's scroll position.
