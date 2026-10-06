from django.contrib.auth.decorators import login_required
from django.shortcuts import render


def home(request):
    return render(request, 'home.html')


@login_required
def dashboard(request):
    is_new_user = request.session.pop('new_user', False)
    return render(request, 'dashboard.html', {'is_new_user': is_new_user})
