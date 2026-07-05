from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from api.metrics import metrics_view
from api.views import (
    LogoutView,
    ThrottledTokenObtainPairView,
    ThrottledTokenRefreshView,
    health_check,
    portfolio_home,
    readiness_check,
)

# API-08 versioning: every resource/business endpoint lives under
# `/api/v1/...`. Infrastructure endpoints that are not "the API" in the
# versioned-contract sense — health checks, the metrics endpoint, the
# OpenAPI schema/docs routes, and the Django admin — are deliberately left
# unversioned, since they describe/operate the service rather than being
# part of the versioned resource contract a client codes against. See
# README "API Versioning & Deprecation Policy" for the full policy this
# implements.
urlpatterns = [
    path('', portfolio_home, name='home'),
    path('admin/', admin.site.urls),
    path('health/', health_check, name='health'),
    path('health/ready/', readiness_check, name='health-ready'),
    path('metrics/', metrics_view, name='metrics'),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/v1/auth/token/', ThrottledTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/v1/auth/token/refresh/', ThrottledTokenRefreshView.as_view(), name='token_refresh'),
    path('api/v1/auth/logout/', LogoutView.as_view(), name='token_logout'),
    path('api/v1/', include('api.urls')),
]
