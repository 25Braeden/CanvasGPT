from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render

from .forms import SignUpForm, StudentProfileForm, UserDetailsForm
from .models import StudentProfile


def signup(request):
    if request.user.is_authenticated:
        return redirect('/dashboard/')

    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            request.session['new_user'] = True
            return redirect('/dashboard/')
    else:
        form = SignUpForm()

    return render(request, 'accounts/signup.html', {'form': form})


@login_required
def profile(request):
    student_profile, _ = StudentProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        user_form = UserDetailsForm(request.POST, instance=request.user)
        profile_form = StudentProfileForm(request.POST, instance=student_profile)
        if user_form.is_valid() and profile_form.is_valid():
            with transaction.atomic():
                user_form.save()
                profile_form.save()
            return redirect('accounts:profile')
    else:
        user_form = UserDetailsForm(instance=request.user)
        profile_form = StudentProfileForm(instance=student_profile)

    return render(
        request,
        'accounts/profile.html',
        {'user_form': user_form, 'profile_form': profile_form},
    )
