# CanvasGPT

CanvasGPT converts Canvas assignments into editable checklists and personalized study schedules.

## Local setup

1. Create and activate the virtual environment:
   python -m venv .venv
   source .venv/Scripts/activate

2. Install dependencies:
   python -m pip install -r requirements.txt
   Make sure requirements.txt includes python-dotenv alongside Django.

3. Create the local environment file:
   cp .env.example .env

4. Generate a secret key:
   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   Put the output in .env as the quoted value of DJANGO_SECRET_KEY.

5. Set up the database and start Django:
   python manage.py migrate
   python manage.py runserver
   Open http://127.0.0.1:8000/.