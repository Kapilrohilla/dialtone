from django.urls import path

from . import api, suggestions_api

urlpatterns = [
    path("workflows", api.WorkflowListView.as_view()),
    path("workflows/<int:pk>", api.WorkflowDetailView.as_view()),
    path("workflows/<int:pk>/validate", api.WorkflowValidateView.as_view()),
    path("workflows/<int:pk>/suggestions", suggestions_api.SuggestionsView.as_view()),
    path("workflows/<int:pk>/suggestions/current", suggestions_api.CurrentSuggestionsView.as_view()),
    path("workflows/<int:pk>/suggestions/<int:item_id>", suggestions_api.SuggestionItemView.as_view()),
    path("workflows/<int:pk>/suggestions/<int:set_id>/close", suggestions_api.CloseSuggestionsView.as_view()),
]
