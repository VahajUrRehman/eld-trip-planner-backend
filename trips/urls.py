from django.urls import path
from .views import PlanTripView

urlpatterns = [
    path("trip/plan/", PlanTripView.as_view(), name="plan-trip"),
]
