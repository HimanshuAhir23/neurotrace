from django.urls import path
from .views import (
    start_session,
    end_session,
    log_activity,
    dashboard_data,
    dashboard_view,
    signup_view,
    login_view,
    logout_view
)

urlpatterns = [
    # Auth URLs
    path('signup/', signup_view, name='signup'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    
    # Dashboard
    path('', dashboard_view, name='dashboard'),

    # API URLs
    path('api/start-session/', start_session, name='start_session'),
    path('api/end-session/<int:session_id>/', end_session, name='end_session'),
    path('api/log-activity/', log_activity, name='log_activity'),
    path('api/dashboard-data/', dashboard_data, name='dashboard_data'),
]