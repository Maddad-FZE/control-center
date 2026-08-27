from django.contrib.auth.decorators import login_not_required
from django.shortcuts import render


@login_not_required
def public_landing(request):
    return render(request, "notes/public_landing.html")
