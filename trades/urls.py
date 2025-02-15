from django.urls import path
from . import views

app_name = 'trades'

urlpatterns = [
    path('', views.index, name='index'),

    # Wealth Data URLs
    path('wealth/', views.wealth_list, name='wealth_list'),
    path('wealth/add/', views.wealth_add, name='wealth_add'),
    path('wealth/edit/<int:pk>/', views.wealth_edit, name='wealth_edit'),
    path('wealth/delete/<int:pk>/', views.wealth_delete, name='wealth_delete'),
    path('wealth/mass-delete/', views.wealth_mass_delete, name='wealth_mass_delete'),

    # This route is the *wealth* chart across all years (formerly mislabeled “global-profit”).
    path('wealth/chart/', views.wealth_chart_all_years, name='wealth_chart_all_years'),

    # Transactions
    path('transactions/', views.transaction_list, name='transaction_list'),
    path('transaction/add/', views.transaction_add, name='transaction_add'),

    # Aliases
    path('alias/', views.alias_list, name='alias_list'),
    path('alias/add/', views.alias_add, name='alias_add'),

    # Membership
    path('membership/', views.membership_list, name='membership_list'),

    # Watchlist
    path('watchlist/', views.watchlist_list, name='watchlist_list'),

    # -------------------------------------------------------------------------
    # NEW routes for profit charts:
    # -------------------------------------------------------------------------
    # 1) Global realized profit chart (for the logged-in user)
    path('charts/global-profit/', views.global_profit_chart, name='global_profit_chart'),

    # Ensure you have EXACTLY this path + name:
    path('charts/item-price/', views.item_price_chart, name='item_price_chart'),

    # Example for item_profit_chart:
    path('charts/item-profit/', views.item_profit_chart, name='item_profit_chart'),

    # Account & Password Reset (custom view)
    path('account/', views.account_page, name='account_page'),
    path('account/password-reset/', views.password_reset_request, name='password_reset_request'),

    # Signup, Login, Logout, Recent Trades, and Admin Management
    path('signup/', views.signup_view, name='signup_view'),
    path('login/', views.login_view, name='login_view'),
    path('logout/', views.logout_view, name='logout_view'),
    path('recent-trades/', views.recent_trades, name='recent_trades'),
    path('manage/users/', views.user_management, name='user_management'),
]
