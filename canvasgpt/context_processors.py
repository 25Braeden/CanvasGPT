from .views import get_dashboard_context


def dashboard_panel(request):
    """Keep the dashboard alongside authenticated application pages."""
    match = request.resolver_match
    if (
        not request.user.is_authenticated
        or match is None
        or match.url_name in {'home', 'login', 'logout', 'signup'}
        or match.app_name == 'admin'
    ):
        return {}
    return {
        'dashboard_panel': get_dashboard_context(request),
        'workspace_panel_open': match.view_name != 'dashboard',
    }
