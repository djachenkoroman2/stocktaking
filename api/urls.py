from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('departments', views.DepartmentViewSet, basename='api-department')
router.register('groups', views.GroupViewSet, basename='api-group')
router.register('teachers', views.TeacherViewSet, basename='api-teacher')
router.register('students', views.StudentViewSet, basename='api-student')
router.register('works', views.WorkViewSet, basename='api-work')

urlpatterns = router.urls
