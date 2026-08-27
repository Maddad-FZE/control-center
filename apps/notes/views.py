from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Note


@login_required
def note_list(request):
    notes = Note.objects.filter(user=request.user)
    return render(request, "notes/list.html", {"notes": notes})


@login_required
@require_POST
def note_create(request):
    title = request.POST.get("title", "").strip() or "Untitled"
    body = request.POST.get("body", "")
    Note.objects.create(user=request.user, title=title, body=body)
    return redirect("notes:list")


@login_required
@require_POST
def note_delete(request, pk):
    note = get_object_or_404(Note, pk=pk, user=request.user)
    note.delete()
    return redirect("notes:list")
