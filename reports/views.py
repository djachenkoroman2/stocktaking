from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from accounts.access import access_for
from accounts.audit import log

from . import render as renderers
from .definitions import BY_SLUG, REPORTS, build
from .forms import ReportForm

CONTENT_TYPES = {
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'csv': 'text/csv; charset=utf-8',
    'pdf': 'application/pdf',
}


def report_list(request):
    access = access_for(request)
    return render(request, 'reports/list.html', {'reports': [r for r in REPORTS if r.available(access)]})


def report_view(request, slug):
    access = access_for(request)
    report = BY_SLUG.get(slug)
    if report is None:
        raise Http404
    access.require(report.available(access))
    form = ReportForm(request.GET or None, report=report, access=access)
    result = None
    fmt = request.GET.get('format', 'html')
    if fmt not in report.formats:
        raise Http404
    if request.GET and form.is_valid():
        params = form.cleaned_data
        result = build(report, access, params)
        result.params = form.describe()
        if report.allowed == 'contacts':  # просмотр и выгрузка контактов — в журнал аудита (ТЗ 9, отчёт 7)
            log(request, 'contacts_report', params.get('teacher'), format=fmt)
        if fmt != 'html':
            content = {'xlsx': renderers.to_xlsx, 'csv': renderers.to_csv, 'pdf': renderers.to_pdf}[fmt](
                report, result, request.user)
            response = HttpResponse(content, content_type=CONTENT_TYPES[fmt])
            name = f'otchet-{report.number}-{timezone.localdate():%Y%m%d}.{fmt}'
            response['Content-Disposition'] = f'attachment; filename="{name}"'
            log(request, 'report_export', None, report=report.number, format=fmt)
            return response
    return render(request, 'reports/report.html', {
        'report': report, 'form': form, 'result': result,
        'export_formats': [f for f in report.formats if f != 'html'],
        'query': request.GET.urlencode()})
