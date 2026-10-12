"""Импорт, возврат, журнал, шаблон формы и выдача копий (ТЗ 7, 8, 10)."""
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.access import ALL, access_for
from accounts.audit import log
from registry.models import Student, Teacher

from . import adapters, copies as copy_service
from .apply import ApplyError, is_ready, reject_document, save_document, save_ready
from .forms import CopyForm, DecisionForm, RejectForm, TemplateForm, UploadForm
from .matching import analyze
from .models import DocState, FormTemplate, ImportBatch, ImportedDocument, IssuedCopy
from .processing import collect, create_batch, mark_returned, reprocess
from .returns import batch_return_text


def _require_import(request):
    access = access_for(request)
    access.require(access.can_import)
    return access


def _document(request, pk):
    access = _require_import(request)
    document = access.documents().select_related('batch', 'work', 'duplicate_of', 'resubmission').filter(pk=pk).first()
    if document is None:
        raise Http404
    return access, document


def upload(request):
    access = _require_import(request)
    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        intake = collect(form.cleaned_data['files'])
        for message in intake.skipped:
            messages.warning(request, message)
        if not intake.files:
            messages.error(request, 'Нет файлов для загрузки.')
            return redirect('import_upload')
        batch = create_batch(request.user, intake.files)
        log(request, 'import_upload', batch, files=len(intake.files))
        if batch.background:
            messages.info(request, f'Файлов: {len(intake.files)}. Пакет обрабатывается в фоне; страница обновится сама.')
        return redirect('batch_detail', batch.pk)
    return render(request, 'imports/upload.html', {'form': form, 'access': access})


def batch_list(request):
    access = _require_import(request)
    visible = access.documents()
    batches = (ImportBatch.objects.filter(documents__in=visible).distinct()
               .annotate(total=Count('documents', distinct=True)).select_related('created_by').order_by('-created_at'))
    page = Paginator(batches, 50).get_page(request.GET.get('page'))
    return render(request, 'imports/batch_list.html', {'page': page})


def batch_detail(request, pk):
    access = _require_import(request)
    batch = ImportBatch.objects.filter(pk=pk, documents__in=access.documents()).distinct().first()
    if batch is None:
        raise Http404
    documents = list(access.documents(batch.documents.all()).order_by('original_name', 'id'))
    rows = []
    for document in documents:
        ready = None
        if document.state == DocState.PENDING:
            ready = is_ready(analyze(document))
        rows.append((document, ready))
    counts = {}
    for document, ready in rows:
        key = 'ready' if ready else document.state
        counts[key] = counts.get(key, 0) + 1
    return render(request, 'imports/batch_detail.html', {
        'batch': batch, 'rows': rows, 'counts': counts, 'states': DocState,
        'queued': any(d.state == DocState.QUEUED for d in documents),
        'ready_count': sum(1 for _, ready in rows if ready),
        'to_return_count': sum(1 for d in documents if d.state == DocState.TO_RETURN)})


@require_POST
def batch_save_ready(request, pk):
    access = _require_import(request)
    documents = access.documents(ImportedDocument.objects.filter(batch_id=pk, state=DocState.PENDING)).order_by('id')
    try:
        saved, skipped = save_ready(documents, request.user)
    except ApplyError as error:
        messages.error(request, str(error))
        return redirect('batch_detail', pk)
    log(request, 'import_save_ready', None, batch=pk, saved=saved)
    messages.success(request, f'Сохранено: {saved}. Требуют решения: {skipped}.')
    return redirect('batch_detail', pk)


def batch_return_texts(request, pk):
    access = _require_import(request)
    documents = access.documents(ImportedDocument.objects.filter(
        batch_id=pk, state__in=(DocState.TO_RETURN, DocState.RETURNED))).order_by('teacher_name', 'original_name')
    response = HttpResponse(batch_return_text(documents), content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="vozvrat-paket-{pk}.txt"'
    return response


@require_POST
def batch_mark_returned(request, pk):
    access = _require_import(request)
    documents = access.documents(ImportedDocument.objects.filter(batch_id=pk, state=DocState.TO_RETURN))
    count = 0
    for document in documents:
        mark_returned(document, request.user)
        log(request, 'import_return', document)
        count += 1
    messages.success(request, f'Отмечено как возвращённые: {count}.')
    return redirect('batch_detail', pk)


def document_list(request):
    access = _require_import(request)
    qs = access.documents().select_related('uploaded_by', 'work', 'batch')
    f = request.GET
    if f.get('state'):
        qs = qs.filter(state=f['state'])
    if f.get('q'):
        q = f['q'].strip()
        qs = qs.filter(Q(original_name__icontains=q) | Q(questionnaire_id__icontains=q)
                       | Q(student_name__icontains=q) | Q(teacher_name__icontains=q))
    if f.get('date_from'):
        qs = qs.filter(uploaded_at__date__gte=f['date_from'])
    if f.get('date_to'):
        qs = qs.filter(uploaded_at__date__lte=f['date_to'])
    if f.get('state') == DocState.RETURNED:
        qs = qs.filter(resubmission__isnull=True)
    page = Paginator(qs.order_by('-uploaded_at', '-id'), 50).get_page(f.get('page'))
    return render(request, 'imports/document_list.html', {'page': page, 'states': DocState.choices, 'filters': f})


def document_detail(request, pk):
    access, document = _document(request, pk)
    context = {'document': document, 'show_contacts': access.is_responsible,
               'can_download': access.can_download_document(document), 'reject_form': RejectForm(),
               'data': adapters.to_neutral(document),
               'offer_copy': document.state in (DocState.TO_RETURN, DocState.RETURNED) and not document.extracted}
    if document.state == DocState.PENDING:
        analysis = analyze(document)
        form = DecisionForm(request.POST or None, analysis=analysis, teachers=access.teachers(edit=True),
                            departments=access.departments(edit=True),
                            can_create_department=access.is_admin or access.responsible_scope is ALL)
        if request.method == 'POST' and form.is_valid():
            decision = form.to_decision()
            teacher_department = (Teacher.objects.get(pk=decision.teacher_id).department_id
                                  if decision.teacher_id else decision.department_id)
            if teacher_department is not None and not access.can_edit_department(teacher_department):
                messages.error(request, 'Эта кафедра вне вашей области данных.')
            else:
                try:
                    work = save_document(document, decision, request.user)
                except ApplyError as error:
                    messages.error(request, str(error))
                else:
                    log(request, 'import_save', document, work=work.pk)
                    messages.success(request, 'Анкета сохранена.')
                    following = _next_pending(access, document)
                    if following:
                        return redirect('document_detail', following.pk)
                    return redirect('batch_detail', document.batch_id)
        context.update(analysis=analysis, form=form, ready=is_ready(analysis))
    return render(request, 'imports/document_detail.html', context)


def _next_pending(access, document):
    return access.documents(ImportedDocument.objects.filter(
        batch_id=document.batch_id, state=DocState.PENDING)).order_by('original_name', 'id').first()


@require_POST
def document_reject(request, pk):
    access, document = _document(request, pk)
    if document.state != DocState.PENDING:
        raise Http404
    form = RejectForm(request.POST)
    if form.is_valid():
        reject_document(document, request.user, form.cleaned_data['note'])
        log(request, 'import_reject', document)
        messages.success(request, 'Анкета отклонена.')
        return redirect('batch_detail', document.batch_id)
    messages.error(request, 'Укажите причину отклонения.')
    return redirect('document_detail', pk)


@require_POST
def document_mark_returned(request, pk):
    access, document = _document(request, pk)
    if document.state != DocState.TO_RETURN:
        raise Http404
    mark_returned(document, request.user)
    log(request, 'import_return', document)
    messages.success(request, 'Анкета отмечена как возвращённая преподавателю.')
    return redirect('document_detail', pk)


def document_return_text(request, pk):
    access, document = _document(request, pk)
    if not document.return_message:
        raise Http404
    response = HttpResponse(document.return_message, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="vozvrat-{document.pk}.txt"'
    return response


@require_POST
def document_reprocess(request, pk):
    access, document = _document(request, pk)
    if document.state not in (DocState.UNSUPPORTED, DocState.REJECTED_CHECK) or not document.file:
        raise Http404
    reprocess(document)
    log(request, 'import_reprocess', document)
    messages.info(request, f'Обработано заново: {document.get_state_display()}.')
    return redirect('document_detail', pk)


@require_POST
def document_delete(request, pk):
    access, document = _document(request, pk)
    if document.state not in (DocState.REJECTED_CHECK, DocState.REJECTED_USER, DocState.DUPLICATE):
        raise Http404
    batch_id = document.batch_id
    log(request, 'import_delete', document, name=document.original_name)
    document.file.delete(save=False)
    document.delete()
    messages.success(request, 'Загрузка удалена из журнала.')
    return redirect('batch_detail', batch_id) if ImportedDocument.objects.filter(batch_id=batch_id).exists() \
        else redirect('batch_list')


def document_download(request, pk):
    access, document = _document(request, pk)
    access.require(access.can_download_document(document))
    if not document.file or not document.file.storage.exists(document.file.name):
        raise Http404('Файла нет на сервере.')
    log(request, 'pdf_download', document)
    return FileResponse(document.file.open('rb'), as_attachment=True, filename=document.original_name,
                        content_type='application/pdf')


# Шаблон формы

def template_list(request):
    access = access_for(request)
    access.require(access.is_admin)
    form = TemplateForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        uploaded = form.cleaned_data['file']
        try:
            template = copy_service.register_template(uploaded.name, uploaded.read(), request.user)
        except copy_service.CopyError as error:
            messages.error(request, str(error))
        else:
            log(request, 'template_upload', template)
            messages.success(request, 'Шаблон формы загружен и стал текущим.')
            return redirect('template_list')
    return render(request, 'imports/template_list.html', {
        'form': form, 'templates': FormTemplate.objects.annotate(copies_count=Count('copies'))})


@require_POST
def template_make_current(request, pk):
    access = access_for(request)
    access.require(access.is_admin)
    template = FormTemplate.objects.filter(pk=pk).first()
    if template is None:
        raise Http404
    FormTemplate.objects.update(is_current=False)
    template.is_current = True
    template.save(update_fields=['is_current'])
    messages.success(request, 'Текущий шаблон изменён.')
    return redirect('template_list')


# Выдача копий

def copy_list(request):
    access = _require_import(request)
    copies = (IssuedCopy.objects.filter(teacher__in=access.teachers(edit=True))
              .select_related('teacher', 'student', 'work', 'issued_by'))
    if request.GET.get('teacher'):
        copies = copies.filter(teacher_id=request.GET['teacher'])
    page = Paginator(copies, 50).get_page(request.GET.get('page'))
    return render(request, 'imports/copy_list.html', {'page': page, 'template': copy_service.current_template()})


def copy_create(request):
    access = _require_import(request)
    replaces = None
    if request.GET.get('replaces'):
        replaces = access.documents().filter(pk=request.GET['replaces'], state__in=(
            DocState.TO_RETURN, DocState.RETURNED)).first()
    initial = {'count': 0 if request.GET.get('student') else 1}
    if request.GET.get('teacher'):
        initial['teacher'] = request.GET['teacher']
    if request.GET.get('student'):
        initial['students'] = [request.GET['student']]
    students = access.students(edit=True) if not access.is_admin else Student.objects.all()
    form = CopyForm(request.POST or None, initial=initial, teachers=access.teachers(edit=True).filter(is_active=True),
                    students=students.filter(is_active=True).select_related('group'))
    if request.method == 'POST' and form.is_valid():
        try:
            created = copy_service.issue_copies(form.cleaned_data['teacher'], form.cleaned_data['students'],
                                                form.cleaned_data['count'], request.user, replaces=replaces)
        except copy_service.CopyError as error:
            messages.error(request, str(error))
        else:
            log(request, 'copies_issue', form.cleaned_data['teacher'], count=len(created))
            messages.success(request, f'Подготовлено копий: {len(created)}.')
            ids = ','.join(str(c.pk) for c in created)
            return render(request, 'imports/copy_done.html', {'copies': created, 'ids': ids})
    return render(request, 'imports/copy_form.html', {'form': form, 'replaces': replaces,
                                                      'template': copy_service.current_template()})


def _copies(request, ids):
    access = _require_import(request)
    return list(IssuedCopy.objects.filter(pk__in=ids, teacher__in=access.teachers(edit=True)).select_related('teacher'))


def copy_download(request, pk):
    found = _copies(request, [pk])
    if not found or not found[0].file.storage.exists(found[0].file.name):
        raise Http404
    return FileResponse(found[0].file.open('rb'), as_attachment=True, filename=found[0].download_name,
                        content_type='application/pdf')


def copy_download_zip(request):
    try:
        ids = [int(x) for x in request.GET.get('ids', '').split(',') if x]
    except ValueError:
        raise Http404
    found = [c for c in _copies(request, ids) if c.file.storage.exists(c.file.name)]
    if not found:
        raise Http404
    response = HttpResponse(copy_service.zip_copies(found), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="kopii-{timezone.localdate():%Y%m%d}.zip"'
    return response
