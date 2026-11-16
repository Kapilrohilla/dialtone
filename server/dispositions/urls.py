from django.urls import path

from . import api

urlpatterns = [
    path("dispositions", api.DispositionListsView.as_view()),
    path("dispositions/<int:pk>", api.DispositionListView.as_view()),
    path("dispositions/<int:pk>/duplicate", api.DispositionListDuplicateView.as_view()),
]
