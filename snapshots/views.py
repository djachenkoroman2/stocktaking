"""Страница «Администрирование → Выгрузка в JSON». Только суперпользователь; восстановление — командой."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.audit import log

from .models import SnapshotExport
from .service import request_export


def _require_superuser(request):
    if not request.user.is_superuser:
        raise PermissionDenied


def _job(pk):
    job = SnapshotExport.objects.filter(pk=pk).first()
    if job is None:
        raise Http404
    return job


def export_list(request):
    _require_superuser(request)
    if request.method == 'POST':
        job = request_export(request.user, include_media=bool(request.POST.get('include_media')))
        if job.state == SnapshotExport.State.DONE:
            messages.success(request, f'Выгрузка готова: {job.file_name}.')
        elif job.state == SnapshotExport.State.FAILED:
            messages.error(request, f'Выгрузка не выполнена: {job.error}')
        else:
            messages.info(request, 'Выгрузка выполняется в фоне; страница обновится сама.')
        return redirect('export_list')
    jobs = SnapshotExport.objects.select_related('created_by')[:100]
    return render(request, 'snapshots/export_list.html', {
        'jobs': jobs, 'refresh': any(job.is_active for job in jobs)})


def export_download(request, pk):
    _require_superuser(request)
    job = _job(pk)
    if job.state != SnapshotExport.State.DONE or not job.path or not job.path.exists():
        raise Http404
    log(request, 'json_export_download', job, file=job.file_name)
    return FileResponse(job.path.open('rb'), as_attachment=True, filename=job.file_name,
                        content_type='application/zip')


@require_POST
def export_delete(request, pk):
    _require_superuser(request)
    job = _job(pk)
    if job.is_active:
        messages.error(request, 'Выгрузка ещё выполняется.')
        return redirect('export_list')
    if job.path:
        job.path.unlink(missing_ok=True)
    log(request, 'json_export_delete', job, file=job.file_name)
    job.delete()
    messages.success(request, 'Архив удалён с сервера.')
    return redirect('export_list')
