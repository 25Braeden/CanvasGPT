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
