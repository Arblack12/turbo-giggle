#!/usr/bin/env python
"""Django views for the trades app."""
import io
import pandas as pd
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponse
from django.db.models import Sum, Avg, Max
from django.utils import timezone
from django.urls import reverse
from django.utils.http import urlencode
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.models import User
from django.db import transaction  # For atomic transactions
import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter

# Force matplotlib to use a non-interactive backend so that no GUI is started.
import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.ticker import StrMethodFormatter

from .models import WealthData, UserBan
from .forms import WealthDataForm
from django.db.models import Q

from .models import (
    Transaction, Item, Alias, AccumulationPrice, TargetSellPrice,
    Membership, WealthData, Watchlist
)
from .forms import (
    TransactionManualItemForm, TransactionEditForm, AliasForm, AccumulationPriceForm,
    TargetSellPriceForm, MembershipForm, WealthDataForm, WatchlistForm
)


def index(request):
    """
    Unified homepage.
    Only shows the transactions belonging to the logged-in user (if authenticated).
    """
    if not request.user.is_authenticated:
        return redirect('trades:login_view')

    timeframe = request.GET.get('timeframe', 'Daily')
    edit_form = None

    if 'edit_trans' in request.GET:
        try:
            t_id = int(request.GET['edit_trans'])
            t_obj = Transaction.objects.get(id=t_id, user=request.user)
            form = TransactionEditForm()
            form.load_initial(t_obj)
            edit_form = form
        except Transaction.DoesNotExist:
            pass

    if request.method == 'POST':
        # ADD a new transaction
        if 'add_transaction' in request.POST:
            tform = TransactionManualItemForm(request.POST)
            if tform.is_valid():
                new_trans = tform.save(user=request.user)
                messages.success(request, f"Transaction for {new_trans.item.name} added successfully!")
                calculate_fifo_for_user(request.user)  # Recalculate only for this user
                # Redirect with ?search=<item_name>
                url = reverse('trades:index')
                qs = urlencode({'search': new_trans.item.name})
                return redirect(f"{url}?{qs}")
            else:
                messages.error(request, "Error in the Add Transaction form.")

        # UPDATE accumulation price
        elif 'update_accumulation' in request.POST:
            item_id = request.POST.get('acc_item_id')
            acc_price = request.POST.get('accumulation_price')
            if item_id and acc_price:
                try:
                    item_obj = Item.objects.get(id=item_id)
                    ap, _ = AccumulationPrice.objects.get_or_create(item=item_obj)
                    ap.accumulation_price = float(acc_price)
                    ap.save()
                    messages.success(request, f"Accumulation price updated for {item_obj.name}.")
                except Item.DoesNotExist:
                    messages.error(request, "Item not found for accumulation update.")
            return redirect('trades:index')

        # UPDATE target sell price
        elif 'update_target_sell' in request.POST:
            item_id = request.POST.get('ts_item_id')
            ts_price = request.POST.get('target_sell_price')
            if item_id and ts_price:
                try:
                    item_obj = Item.objects.get(id=item_id)
                    tsp, _ = TargetSellPrice.objects.get_or_create(item=item_obj)
                    tsp.target_sell_price = float(ts_price)
                    tsp.save()
                    messages.success(request, f"Target sell price updated for {item_obj.name}.")
                except Item.DoesNotExist:
                    messages.error(request, "Item not found for target sell update.")
            return redirect('trades:index')

        # DELETE a transaction
        elif 'delete_transaction' in request.POST:
            t_id = request.POST.get('transaction_id')
            if t_id:
                try:
                    t_obj = Transaction.objects.get(id=t_id, user=request.user)
                    item_name = t_obj.item.name
                    t_obj.delete()
                    messages.success(request, "Transaction deleted.")
                    calculate_fifo_for_user(request.user)
                    # Redirect with ?search=the item name
                    url = reverse('trades:index')
                    qs = urlencode({'search': item_name})
                    return redirect(f"{url}?{qs}")
                except Transaction.DoesNotExist:
                    messages.error(request, "Transaction not found or not owned by you.")
            return redirect('trades:index')

        # UPDATE (EDIT) a transaction
        elif 'update_transaction' in request.POST:
            ef = TransactionEditForm(request.POST)
            if ef.is_valid():
                updated_trans = ef.update_transaction(user=request.user)
                messages.success(request, "Transaction updated.")
                calculate_fifo_for_user(request.user)
                url = reverse('trades:index')
                qs = urlencode({'search': updated_trans.item.name})
                return redirect(f"{url}?{qs}")
            else:
                messages.error(request, "Error updating transaction.")
                edit_form = ef
        else:
            # Ensure 'form' is defined even if no expected key is in POST.
            form = AliasForm()
    else:
        # GET request: if 'edit_id' exists, use it to pre-fill the form.
        if 'edit_id' in request.GET:
            try:
                edit_id = request.GET['edit_id']
                edit_alias = get_object_or_404(Alias, id=edit_id)
            except Exception:
                edit_alias = None
            if edit_alias:
                form = AliasForm(instance=edit_alias)
            else:
                form = AliasForm()
        else:
            form = AliasForm()

    # Handle an optional search for an item or alias.
    search_query = request.GET.get('search', '').strip()
    item_obj = None
    item_alias = None
    accumulation_obj = None
    target_obj = None
    item_transactions = []
    total_sold = 0
    remaining_qty = 0
    avg_sold_price = 0
    item_profit = 0
    global_realised_profit = Transaction.objects.filter(user=request.user).aggregate(total=Max('cumulative_profit'))['total'] or 0
    item_image_url = ""

    if search_query:
        alias_match = Alias.objects.filter(short_name__iexact=search_query).first()
        if not alias_match:
            alias_match = Alias.objects.filter(full_name__iexact=search_query).first()
        if alias_match:
            item_obj = Item.objects.filter(name__iexact=alias_match.full_name).first()
            item_alias = alias_match
        else:
            item_obj = Item.objects.filter(name__iexact=search_query).first()

        if item_obj:
            if item_alias is None:
                item_alias = Alias.objects.filter(full_name__iexact=item_obj.name).first()
            accumulation_obj = AccumulationPrice.objects.filter(item=item_obj).first()
            target_obj = TargetSellPrice.objects.filter(item=item_obj).first()
            item_transactions = Transaction.objects.filter(item=item_obj, user=request.user).order_by('-date_of_holding')
            sells = item_transactions.filter(trans_type='Sell')
            total_sold = sells.aggregate(sold_sum=Sum('quantity'))['sold_sum'] or 0
            buys_qty = item_transactions.filter(trans_type='Buy').aggregate(buy_sum=Sum('quantity'))['buy_sum'] or 0
            remaining_qty = buys_qty - total_sold
            if total_sold > 0:
                avg_sold_price = sells.aggregate(avg_price=Avg('price'))['avg_price'] or 0
            item_profit = item_transactions.aggregate(item_profit_sum=Sum('realised_profit'))['item_profit_sum'] or 0
            if item_alias and item_alias.image_file:
                item_image_url = item_alias.image_file.url
        else:
            messages.warning(request, f"No item or alias found matching '{search_query}'.")

    all_transactions = Transaction.objects.filter(user=request.user).order_by('-date_of_holding')

    context = {
        'transaction_form': TransactionManualItemForm(),
        'edit_form': edit_form,
        'timeframe': timeframe,
        'search_query': search_query,
        'item_obj': item_obj,
        'item_alias': item_alias,
        'accumulation_obj': accumulation_obj,
        'target_obj': target_obj,
        'item_transactions': item_transactions,
        'total_sold': total_sold,
        'remaining_qty': remaining_qty,
        'avg_sold_price': avg_sold_price,
        'item_profit': item_profit,
        'global_realised_profit': global_realised_profit,
        'item_image_url': item_image_url,
        'all_transactions': all_transactions,
        'form': form,  # Alias add/edit form.
    }
    return render(request, 'trades/index.html', context)


from django.db.models import Case, When, F, CharField

def alias_list(request):
    if not request.user.is_authenticated:
        return redirect('trades:login_view')

    edit_alias = None
    if 'edit_id' in request.GET:
        edit_id = request.GET['edit_id']
        edit_alias = get_object_or_404(Alias, id=edit_id)

    if request.method == 'POST':
        # Handle deletion
        if 'delete_alias' in request.POST:
            alias_id = request.POST.get('alias_id', '')
            if alias_id:
                try:
                    alias_obj = Alias.objects.get(id=alias_id)
                    alias_obj.delete()
                    messages.success(request, "Alias deleted.")
                except Alias.DoesNotExist:
                    messages.error(request, "Alias not found.")
            return redirect('trades:alias_list')
        else:
            # Handle add/update
            alias_id = request.POST.get('alias_id', '')
            if alias_id:
                alias_obj = get_object_or_404(Alias, id=alias_id)
                form = AliasForm(request.POST, request.FILES, instance=alias_obj)
            else:
                form = AliasForm(request.POST, request.FILES)
            if form.is_valid():
                form.save()
                messages.success(request, "Alias saved!")
                return redirect('trades:alias_list')
            else:
                messages.error(request, "Error saving alias.")
    else:
        form = AliasForm()

    letter = request.GET.get('letter', '')
    if letter:
        qs = Alias.objects.filter(full_name__istartswith=letter)
    else:
        qs = Alias.objects.all()
    aliases = qs.order_by('full_name')

    letters = [chr(i) for i in range(ord('A'), ord('Z') + 1)]
    return render(request, 'trades/alias_list.html', {
        'form': form,
        'aliases': aliases,
        'edit_alias': edit_alias,
        'letters': letters,
    })


def alias_add(request):
    if not request.user.is_authenticated:
        return redirect('trades:login_view')
    # Simply redirect to alias_list, where the alias form is processed.
    return redirect('trades:alias_list')


@login_required
def membership_list(request):
    """
    Show only the membership record for the logged-in user.
    """
    # Assuming Membership.account_name corresponds to the user's username.
    memberships = Membership.objects.filter(account_name=request.user.username)
    return render(request, 'trades/membership_list.html', {
        'memberships': memberships,
    })


@login_required
def watchlist_list(request):
    """
    Show watchlist items only for the logged-in user.
    """
    # Assuming Watchlist.account_name corresponds to the user's username.
    watchlist_items = Watchlist.objects.filter(account_name=request.user.username).order_by('-date_added')
    return render(request, 'trades/watchlist_list.html', {
        'watchlist_items': watchlist_items,
    })


@login_required
def wealth_list(request):
    """
    Display all wealth data records for a selected year (defaulting to the current year)
    and compute the combined wealth totals for every month.
    """
    current_year = datetime.now().year
    wealth_records = WealthData.objects.all().order_by('year', 'account_name')
    years = WealthData.objects.values_list('year', flat=True).distinct().order_by('-year')

    selected_year = request.GET.get('year')
    if selected_year:
        try:
            selected_year = int(selected_year)
            wealth_records = wealth_records.filter(year=selected_year)
        except ValueError:
            selected_year = current_year
            wealth_records = wealth_records.filter(year=selected_year)
    else:
        selected_year = current_year
        wealth_records = wealth_records.filter(year=selected_year)

    # Compute monthly totals with cleaning
    months = ["january", "february", "march", "april", "may",
              "june", "july", "august", "september", "october", "november", "december"]
    monthly_totals = {}
    for m in months:
        total = 0
        for rec in wealth_records:
            try:
                # Remove commas and whitespace from the value
                value_str = (getattr(rec, m) or "0").replace(',', '').strip()
                total += float(value_str)
            except Exception as e:
                total += 0
        monthly_totals[m] = total

    context = {
        'wealth_records': wealth_records,
        'years': years,
        'selected_year': selected_year,
        'monthly_totals': monthly_totals,
    }
    return render(request, 'trades/wealth_list.html', context)


@login_required
def wealth_add(request):
    """
    Add a new wealth data record.
    The account_name is entered as plain text.
    """
    if request.method == 'POST':
        form = WealthDataForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Wealth data added successfully!")
            return redirect('trades:wealth_list')
        else:
            messages.error(request, "There was an error adding the wealth data.")
    else:
        form = WealthDataForm()
    return render(request, 'trades/wealth_form.html', {'form': form, 'action': 'Add'})


@login_required
def wealth_edit(request, pk):
    """
    Edit an existing wealth data record.
    """
    wealth_data = get_object_or_404(WealthData, pk=pk)
    if request.method == 'POST':
        form = WealthDataForm(request.POST, instance=wealth_data)
        if form.is_valid():
            form.save()
            messages.success(request, "Wealth data updated successfully!")
            return redirect('trades:wealth_list')
        else:
            messages.error(request, "There was an error updating the wealth data.")
    else:
        form = WealthDataForm(instance=wealth_data)
    return render(request, 'trades/wealth_form.html', {'form': form, 'action': 'Edit'})


@login_required
def wealth_delete(request, pk):
    """
    Delete a single wealth data record.
    """
    wealth_data = get_object_or_404(WealthData, pk=pk)
    if request.method == 'POST':
        wealth_data.delete()
        messages.success(request, "Wealth data deleted successfully!")
        return redirect('trades:wealth_list')
    return render(request, 'trades/wealth_confirm_delete.html', {'wealth_data': wealth_data})


@login_required
def wealth_mass_delete(request):
    """
    Delete multiple wealth data records selected via checkboxes.
    """
    if request.method == 'POST':
        delete_ids = request.POST.getlist('delete_ids')
        if delete_ids:
            WealthData.objects.filter(pk__in=delete_ids).delete()
            messages.success(request, "Selected wealth data records have been deleted!")
        else:
            messages.error(request, "No records selected for deletion.")
    return redirect('trades:wealth_list')


@login_required
def wealth_chart(request):
    """
    Generate a line chart showing the combined wealth totals for every month
    for the selected year (defaulting to current year if not provided).
    """
    current_year = datetime.now().year
    selected_year = request.GET.get('year')
    if selected_year:
        try:
            selected_year = int(selected_year)
        except:
            selected_year = current_year
    else:
        selected_year = current_year

    wealth_records = WealthData.objects.filter(year=selected_year)
    months = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]
    monthly_totals = []
    for m in months:
        total = 0
        for rec in wealth_records:
            try:
                val = float(getattr(rec, m.lower()) or 0)
            except:
                val = 0
            total += val
        monthly_totals.append(total)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(months, monthly_totals, marker='o', linestyle='-', color='green')
    ax.set_xlabel("Month")
    ax.set_ylabel("Total Wealth")
    ax.set_title(f"Combined Wealth Totals for {selected_year}")
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
    plt.xticks(rotation=45)
    fig.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png')


@login_required
def wealth_chart_all_years(request):
    """
    (Renamed route) Generate a line chart showing combined wealth totals for each month
    across all years, but only plot months that have nonzero data.
    Previously this was incorrectly called 'global_profit_chart' in URLs.
    """
    wealth_records = WealthData.objects.all().order_by('year')
    months = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]
    monthly_totals = {}  # key: "YYYY-MM", value: total

    # Accumulate totals per month for each record
    for rec in wealth_records:
        year = rec.year
        for i, m in enumerate(months, start=1):
            try:
                value_str = (getattr(rec, m.lower()) or "0").replace(',', '').strip()
                value = float(value_str)
            except:
                value = 0
            key = f"{year}-{i:02d}"
            monthly_totals[key] = monthly_totals.get(key, 0) + value

    # Sort keys chronologically
    sorted_keys = sorted(monthly_totals.keys())
    x_labels = []
    y_values = []
    for key in sorted_keys:
        year_part, month_part = key.split('-')
        month_idx = int(month_part)
        label = f"{months[month_idx-1][:3]} {year_part}"
        x_labels.append(label)
        y_values.append(monthly_totals[key])

    # Filter out months with a 0 total, if desired
    filtered_x = []
    filtered_y = []
    for label, val in zip(x_labels, y_values):
        if val != 0:
            filtered_x.append(label)
            filtered_y.append(val)
    if filtered_x:
        x_labels = filtered_x
        y_values = filtered_y
    else:
        # If all are zero, fall back to just 12 months
        x_labels = months
        y_values = [0]*12

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(x_labels, y_values, marker='o', linestyle='-', color='green')
    ax.set_xlabel("Month-Year")
    ax.set_ylabel("Total Wealth")
    ax.set_title("Combined Wealth Totals Across All Years")
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
    plt.xticks(rotation=45)
    fig.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png')


@login_required
def account_page(request):
    return render(request, 'trades/account.html')


def password_reset_request(request):
    if not request.user.is_authenticated:
        return redirect('trades:login_view')
    if request.method == 'POST':
        email = request.POST.get('email')
        messages.success(request, f'Password reset instructions have been sent to {email}.')
        return redirect('trades:account_page')
    return render(request, 'trades/password_reset_request.html')


@login_required
def transaction_list(request):
    transactions = Transaction.objects.filter(user=request.user).order_by('-date_of_holding')
    return render(request, 'trades/transaction_list.html', {'transactions': transactions})


@login_required
def transaction_add(request):
    if request.method == 'POST':
        form = TransactionManualItemForm(request.POST)
        if form.is_valid():
            new_trans = form.save(user=request.user)
            messages.success(request, f"Transaction for {new_trans.item.name} added.")
            calculate_fifo_for_user(request.user)
            return redirect('trades:transaction_list')
    else:
        form = TransactionManualItemForm()
    return render(request, 'trades/transaction_add.html', {'form': form})


def login_view(request):
    """Simple login form using Django's built-in authentication with ban check."""
    if request.user.is_authenticated:
        return redirect('trades:index')
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user:
            # Ensure 'Arblack' is admin
            if user.username == "Arblack" and not user.is_superuser:
                user.is_superuser = True
                user.is_staff = True
                user.save()
            # Check if user is banned
            if hasattr(user, "ban_info") and user.ban_info.is_banned():
                ban_msg = "User is banned permanently" if user.ban_info.permanent else f"User is temporarily banned for {user.ban_info.remaining_ban_duration()}"
                messages.error(request, ban_msg)
                return redirect('trades:login_view')
            login(request, user)
            return redirect('trades:index')
        else:
            messages.error(request, "Incorrect details")
    return render(request, 'trades/login.html')


def signup_view(request):
    """Simple sign-up form to create a new user with email."""
    if request.user.is_authenticated:
        return redirect('trades:index')
    if request.method == 'POST':
        username = request.POST.get('username').strip()
        email = request.POST.get('email').strip()
        password = request.POST.get('password').strip()
        if not username or not email or not password:
            messages.error(request, "Username, Email, and Password cannot be empty.")
        else:
            if User.objects.filter(username=username).exists():
                messages.error(request, "Username already taken.")
            else:
                user = User.objects.create_user(username=username, email=email, password=password)
                login(request, user)
                return redirect('trades:index')
    return render(request, 'trades/signup.html')


def recent_trades(request):
    """
    Show the most recent 50 transactions for the logged-in user.
    """
    if not request.user.is_authenticated:
        return redirect('trades:login_view')
    transactions = Transaction.objects.select_related('item', 'user').filter(
        user=request.user
    ).order_by('-id')[:50]
    for t in transactions:
        first_alias_with_image = Alias.objects.filter(
            full_name__iexact=t.item.name,
            image_file__isnull=False
        ).first()
        if first_alias_with_image and first_alias_with_image.image_file:
            t.first_image_url = first_alias_with_image.image_file.url
        else:
            t.first_image_url = None
    context = {'transactions': transactions}
    return render(request, 'trades/recent_trades.html', context)


def logout_view(request):
    """Custom logout view that handles GET and then redirects to login."""
    logout(request)
    messages.info(request, "Logged out successfully.")
    return redirect('trades:login_view')


# ------------------------------------------------------------------------
# FIFO RECALC METHODS
# ------------------------------------------------------------------------
def calculate_fifo_for_user(user):
    """
    FIFO logic for *one* user.
    Resets realized & cumulative profit for that user, then re-walks transactions.
    Wrapped in a single atomic block to reduce database locking.
    """
    with transaction.atomic():
        Transaction.objects.filter(user=user).update(realised_profit=0.0, cumulative_profit=0.0)
        purchase_lots = {}  # {item_id: [ {qty, price}, ... ] }
        cumulative_sum = 0.0
        user_trans = Transaction.objects.filter(user=user).order_by('date_of_holding', 'trans_type', 'id')
        for trans in user_trans:
            item_id = trans.item_id
            if item_id not in purchase_lots:
                purchase_lots[item_id] = []
            if trans.trans_type == 'Buy':
                purchase_lots[item_id].append({'qty': trans.quantity, 'price': trans.price})
                trans.realised_profit = 0.0
            else:  # Sell
                qty_to_sell = trans.quantity
                sell_price = trans.price
                profit = 0.0
                while qty_to_sell > 0 and purchase_lots[item_id]:
                    lot = purchase_lots[item_id][0]
                    used = min(qty_to_sell, lot['qty'])
                    # Example includes 2% fee
                    partial_profit = (sell_price * used * 0.98) - (lot['price'] * used)
                    profit += partial_profit
                    lot['qty'] -= used
                    qty_to_sell -= used
                    if lot['qty'] <= 0:
                        purchase_lots[item_id].pop(0)
                trans.realised_profit = profit
            cumulative_sum += trans.realised_profit
            trans.cumulative_profit = cumulative_sum
            trans.save()


def calculate_fifo_for_all_users():
    """
    Used rarely (like after big CSV imports).
    Recalculates for *every* user in the system.
    """
    all_users = User.objects.filter(transaction__isnull=False).distinct()
    for u in all_users:
        calculate_fifo_for_user(u)


# --- Admin functionality: user management (list users & ban them) ---
@login_required
def user_management(request):
    if request.user.username != "Arblack":
        messages.error(request, "Access denied.")
        return redirect('trades:index')
    users = User.objects.all()
    if request.method == 'POST':
        ban_user_id = request.POST.get('ban_user_id')
        ban_duration = request.POST.get('ban_duration')  # duration in hours
        permanent = request.POST.get('permanent') == 'on'
        try:
            target_user = User.objects.get(id=ban_user_id)
            from django.utils import timezone
            if permanent:
                ban_until = None
            else:
                try:
                    hours = float(ban_duration)
                except:
                    hours = 0
                ban_until = timezone.now() + timezone.timedelta(hours=hours) if hours > 0 else None
            user_ban, created = UserBan.objects.get_or_create(user=target_user)
            user_ban.permanent = permanent
            user_ban.ban_until = ban_until
            user_ban.save()
            messages.success(request, f"User '{target_user.username}' banned successfully.")
        except User.DoesNotExist:
            messages.error(request, "User not found.")
        return redirect('trades:user_management')
    return render(request, 'trades/user_management.html', {'users': users})


# ----------------------------------------------------------------------------
# NEW VIEWS FOR REALISED PROFIT CHARTS
# ----------------------------------------------------------------------------
@login_required
def global_profit_chart(request):
    """
    Shows the logged-in user's global realized (cumulative) profit over time.
    Plots the transaction.cumulative_profit in chronological order.
    """
    user = request.user
    queryset = Transaction.objects.filter(user=user).order_by('date_of_holding', 'id')

    # Prepare X and Y data
    x_dates = []
    y_cumulative = []
    for tx in queryset:
        x_dates.append(tx.date_of_holding)
        y_cumulative.append(tx.cumulative_profit)

    # Plot
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(x_dates, y_cumulative, marker='o', linestyle='-', color='blue', label='Cumulative Profit')
    ax.set_xlabel('Date of Holding')
    ax.set_ylabel('Cumulative Profit')
    ax.set_title(f"Global Realized Profit: {user.username}")
    ax.legend()
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
    plt.xticks(rotation=45)
    fig.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png')


@login_required
def item_price_chart(request):
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import StrMethodFormatter
    import pandas as pd

    user = request.user
    search_query = request.GET.get('search', '').strip()
    timeframe = request.GET.get('timeframe', 'Daily')  # e.g. 'Daily','Monthly','Yearly'

    # 1) If no item specified, return a tiny placeholder
    if not search_query:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No item specified", ha='center', va='center')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

    # 2) Find the item (via alias or direct name)
    alias = Alias.objects.filter(short_name__iexact=search_query).first()
    if not alias:
        alias = Alias.objects.filter(full_name__iexact=search_query).first()
    if alias:
        item_obj = Item.objects.filter(name__iexact=alias.full_name).first()
    else:
        item_obj = Item.objects.filter(name__iexact=search_query).first()

    if not item_obj:
        # Show error if item not found
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, f"Item '{search_query}' not found", ha='center', va='center')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

    # 3) Query the user’s buy/sell transactions for this item
    qs = Transaction.objects.filter(user=user, item=item_obj).order_by('date_of_holding', 'id')
    if not qs.exists():
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, f"No transactions for '{item_obj.name}'", ha='center', va='center')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

    # 4) Build a DataFrame for grouping
    rows = []
    for t in qs:
        rows.append({
            'trans_type': t.trans_type,
            'price': t.price,
            'quantity': t.quantity,
            'date_of_holding': t.date_of_holding
        })
    df = pd.DataFrame(rows)

    # Helper: group by day vs. month vs. year
    def date_key(d):
        if timeframe == 'Monthly':
            return (d.year, d.month)
        elif timeframe == 'Yearly':
            return d.year
        else:
            return d  # daily = actual date

    df['group_key'] = df['date_of_holding'].apply(date_key)

    # Weighted‐avg buy price per group
    buy_df = df[df['trans_type'] == 'Buy'].groupby('group_key').apply(
        lambda g: (g['price']*g['quantity']).sum()/g['quantity'].sum()
    ).rename('buy_price').reset_index()

    # Weighted‐avg sell price per group
    sell_df = df[df['trans_type'] == 'Sell'].groupby('group_key').apply(
        lambda g: (g['price']*g['quantity']).sum()/g['quantity'].sum()
    ).rename('sell_price').reset_index()

    # Merge
    merged = pd.merge(buy_df, sell_df, on='group_key', how='outer')
    merged['buy_price'] = merged['buy_price'].fillna(0)
    merged['sell_price'] = merged['sell_price'].fillna(0)

    # Sort by group_key in chronological order
    def group_key_sorter(k):
        if isinstance(k, tuple):  # (year,month)
            return (k[0], k[1], 1)
        elif isinstance(k, int):  # year
            return (k, 1, 1)
        else:
            # daily date
            return (k.year, k.month, k.day)
    merged['sort_val'] = merged['group_key'].apply(group_key_sorter)
    merged.sort_values('sort_val', inplace=True)

    # X labels
    def group_key_label(k):
        if isinstance(k, tuple):  # (yr, mo)
            return f"{k[0]:04d}-{k[1]:02d}"
        elif isinstance(k, int):
            return str(k)
        else:
            return str(k)  # daily = 'YYYY-MM-DD'

    merged['x_label'] = merged['group_key'].apply(group_key_label)

    # 5) Plot buy/sell lines in one figure
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(
        merged['x_label'], merged['buy_price'],
        color='green', linewidth=1, marker='', label='Buy Price'
    )
    ax.plot(
        merged['x_label'], merged['sell_price'],
        color='red', linewidth=1, marker='', label='Sell Price'
    )
    ax.set_title(f"{item_obj.name} Price History ({timeframe})")
    ax.set_ylabel("Price")
    ax.legend()
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
    if timeframe in ('Daily', 'Monthly'):
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right')

    fig.tight_layout()

    # Return as PNG
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png')

@login_required
def item_profit_chart(request):
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import StrMethodFormatter
    import pandas as pd

    user = request.user
    search_query = request.GET.get('search', '').strip()
    timeframe = request.GET.get('timeframe', 'Daily')  # daily|monthly|yearly

    # If no search
    if not search_query:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No item specified", ha='center', va='center')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

    # Find item
    alias = Alias.objects.filter(short_name__iexact=search_query).first()
    if not alias:
        alias = Alias.objects.filter(full_name__iexact=search_query).first()
    if alias:
        item_obj = Item.objects.filter(name__iexact=alias.full_name).first()
    else:
        item_obj = Item.objects.filter(name__iexact=search_query).first()

    if not item_obj:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, f"Item '{search_query}' not found", ha='center', va='center')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

    # Query user’s transactions for this item
    qs = Transaction.objects.filter(user=user, item=item_obj).order_by('date_of_holding', 'id')
    if not qs.exists():
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, f"No transactions for '{item_obj.name}'", ha='center', va='center')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

    # Build DataFrame
    rows = []
    for t in qs:
        rows.append({
            'realised_profit': t.realised_profit,
            'date_of_holding': t.date_of_holding
        })
    df = pd.DataFrame(rows)

    # group daily/monthly/yearly
    def date_key(d):
        if timeframe == 'Monthly':
            return (d.year, d.month)
        elif timeframe == 'Yearly':
            return d.year
        else:
            return d

    df['group_key'] = df['date_of_holding'].apply(date_key)
    gp = df.groupby('group_key')['realised_profit'].sum().reset_index()
    gp.rename(columns={'realised_profit': 'bucket_profit'}, inplace=True)

    # Sort
    def sort_key(k):
        if isinstance(k, tuple):
            return (k[0], k[1], 1)
        elif isinstance(k, int):
            return (k, 1, 1)
        else:
            return (k.year, k.month, k.day)

    gp['sort_val'] = gp['group_key'].apply(sort_key)
    gp.sort_values('sort_val', inplace=True)

    # Cumulative sum
    gp['cumulative_profit'] = gp['bucket_profit'].cumsum()

    def group_label(k):
        if isinstance(k, tuple):
            return f"{k[0]:04d}-{k[1]:02d}"
        elif isinstance(k, int):
            return str(k)
        else:
            return str(k)

    gp['x_label'] = gp['group_key'].apply(group_label)

    # Plot single line for cumulative profit
    fig, ax = plt.subplots(figsize=(10,4))
    ax.plot(
        gp['x_label'], gp['cumulative_profit'],
        color='blue', linewidth=1, marker='', label='Cumulative Profit'
    )
    ax.set_title(f"{item_obj.name} - Cumulative Profit ({timeframe})")
    ax.set_xlabel("Date")
    ax.set_ylabel("Profit")
    ax.legend()
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
    if timeframe in ('Daily','Monthly'):
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right')

    fig.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png')



