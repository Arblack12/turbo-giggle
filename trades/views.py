# trades/views.py

#!/usr/bin/env python
"""Django views for the trades app."""
import io
import numpy as np  # <-- ADDED for NaN replacements
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


from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from datetime import datetime
from .models import WealthData
from .forms import WealthDataForm
import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter

@login_required
def wealth_list(request):
    """
    Display all wealth data records for the logged-in user,
    either for a selected year or for all years (?year=all).
    Then compute combined wealth totals for the filtered records.
    """
    current_year = datetime.now().year

    # Only this user’s data
    all_records = WealthData.objects.filter(account_name=request.user.username).order_by('year', 'account_name')
    years_for_user = (WealthData.objects
                      .filter(account_name=request.user.username)
                      .values_list('year', flat=True)
                      .distinct()
                      .order_by('-year'))

    selected_year_param = request.GET.get('year', '')
    if selected_year_param.lower() == 'all':
        # "All" => show every year for this user
        selected_year = 'all'
        wealth_records = all_records
    elif selected_year_param:
        # Try parse a year
        try:
            selected_year_int = int(selected_year_param)
            wealth_records = all_records.filter(year=selected_year_int)
            selected_year = selected_year_int
        except ValueError:
            # fallback if parse fails
            selected_year = current_year
            wealth_records = all_records.filter(year=current_year)
    else:
        # No ?year => default to current year
        selected_year = current_year
        wealth_records = all_records.filter(year=current_year)

    # Build monthly totals from the filtered records
    months = ["january", "february", "march", "april", "may",
              "june", "july", "august", "september", "october", "november", "december"]
    monthly_totals = {}
    for m in months:
        total = 0
        for rec in wealth_records:
            val_str = (getattr(rec, m) or "0").replace(',', '').strip()
            try:
                total += float(val_str)
            except:
                total += 0
        monthly_totals[m] = total

    context = {
        'wealth_records': wealth_records,
        'years': years_for_user,  # used for the year nav
        'selected_year': selected_year,  # can be 'all' or int
        'monthly_totals': monthly_totals,
    }
    return render(request, 'trades/wealth_list.html', context)


@login_required
def wealth_add(request):
    """
    Add a new wealth data record, forcibly setting account_name to the current user.
    """
    if request.method == 'POST':
        form = WealthDataForm(request.POST)
        if form.is_valid():
            wealth_obj = form.save(commit=False)
            # Force the account_name to be the current user's username
            wealth_obj.account_name = request.user.username
            wealth_obj.save()
            messages.success(request, "Wealth data added successfully!")
            return redirect('trades:wealth_list')
        else:
            messages.error(request, "There was an error adding the wealth data.")
    else:
        # Pre-fill the account_name as a convenience
        form = WealthDataForm(initial={'account_name': request.user.username})
    return render(request, 'trades/wealth_form.html', {'form': form, 'action': 'Add'})


@login_required
def wealth_edit(request, pk):
    """
    Edit an existing wealth data record, ensuring it belongs to this user.
    Force the account_name to remain the user's username on save.
    """
    wealth_data = get_object_or_404(WealthData, pk=pk)
    if wealth_data.account_name != request.user.username:
        messages.error(request, "Access denied: not your data.")
        return redirect('trades:wealth_list')

    if request.method == 'POST':
        form = WealthDataForm(request.POST, instance=wealth_data)
        if form.is_valid():
            updated_obj = form.save(commit=False)
            # Force the account_name to remain the current user's username
            updated_obj.account_name = request.user.username
            updated_obj.save()
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
    Delete a single wealth data record, ensuring it belongs to this user.
    """
    wealth_data = get_object_or_404(WealthData, pk=pk)
    if wealth_data.account_name != request.user.username:
        messages.error(request, "Access denied: not your data.")
        return redirect('trades:wealth_list')

    if request.method == 'POST':
        wealth_data.delete()
        messages.success(request, "Wealth data deleted successfully!")
        return redirect('trades:wealth_list')
    return render(request, 'trades/wealth_confirm_delete.html', {'wealth_data': wealth_data})


@login_required
def wealth_mass_delete(request):
    """
    Delete multiple wealth data records, but only those that belong to this user.
    """
    if request.method == 'POST':
        delete_ids = request.POST.getlist('delete_ids')
        if delete_ids:
            WealthData.objects.filter(pk__in=delete_ids, account_name=request.user.username).delete()
            messages.success(request, "Selected wealth data records have been deleted!")
        else:
            messages.error(request, "No records selected for deletion.")
    return redirect('trades:wealth_list')


@login_required
def wealth_chart(request):
    """
    Show a line chart for the current user, for a selected year or default year.
    """
    current_year = datetime.now().year
    selected_year = request.GET.get('year')
    if selected_year:
        try:
            selected_year = int(selected_year)
        except ValueError:
            selected_year = current_year
    else:
        selected_year = current_year

    # Filter only for this user and this year
    wealth_records = WealthData.objects.filter(
        account_name=request.user.username,
        year=selected_year
    )
    months = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]
    monthly_totals = []
    for m in months:
        total = 0
        for rec in wealth_records:
            try:
                val_str = (getattr(rec, m.lower()) or "0").replace(',', '').strip()
                total += float(val_str)
            except:
                total += 0
        monthly_totals.append(total)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(months, monthly_totals, linestyle='-', color='green', linewidth=1)
    ax.set_xlabel("Month")
    ax.set_ylabel("Total Wealth")
    ax.set_title(f"Wealth Totals for {selected_year} (You Only)")
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
    Show a line chart for the current user across all years,
    or optionally for a specific ?year= param if you want.
    Currently we just show everything for this user.
    """
    selected_year = request.GET.get('year', '')
    if selected_year.lower() == 'all':
        wealth_records = WealthData.objects.filter(account_name=request.user.username).order_by('year')
    else:
        # If user passes a numeric year, they get that year. If nothing, we do same.
        # But typically, we do all years for the chart.
        # For simplicity, let's do all if we want to replicate "All" behavior.
        wealth_records = WealthData.objects.filter(account_name=request.user.username).order_by('year')

    months = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]
    monthly_totals = {}
    for rec in wealth_records:
        year = rec.year
        for i, m in enumerate(months, start=1):
            try:
                val_str = (getattr(rec, m.lower()) or "0").replace(',', '').strip()
                val = float(val_str)
            except:
                val = 0
            key = f"{year}-{i:02d}"
            monthly_totals[key] = monthly_totals.get(key, 0) + val

    # Sort keys and build the chart
    sorted_keys = sorted(monthly_totals.keys())  # e.g. ['2023-01','2023-02',...]
    x_labels = []
    y_values = []
    for key in sorted_keys:
        yr, mo = key.split('-')
        mo_int = int(mo)
        label = f"{months[mo_int-1][:3]} {yr}"
        x_labels.append(label)
        y_values.append(monthly_totals[key])

    # Filter out zero months if you like
    filtered_x = []
    filtered_y = []
    for lbl, val in zip(x_labels, y_values):
        if val != 0:
            filtered_x.append(lbl)
            filtered_y.append(val)

    if filtered_x:
        x_labels = filtered_x
        y_values = filtered_y
    else:
        # fallback if all zero
        x_labels = months
        y_values = [0]*12

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(x_labels, y_values, linestyle='-', color='green', linewidth=1)
    ax.set_xlabel("Month-Year")
    ax.set_ylabel("Total Wealth")
    ax.set_title("All-Year Wealth Totals (You Only)")
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
    Show the most recent 50 transactions across all users.
    (If you want only your own trades, add back the filter(user=request.user)).
    """
    if not request.user.is_authenticated:
        return redirect('trades:login_view')
    transactions = (
        Transaction.objects
        .select_related('item', 'user')
        .order_by('-id')[:50]
    )
    for t in transactions:
        first_alias = Alias.objects.filter(
            full_name__iexact=t.item.name,
            image_file__isnull=False
        ).first()
        # Only set first_image_url if the alias has an associated file
        if first_alias and first_alias.image_file and first_alias.image_file.name:
            t.first_image_url = first_alias.image_file.url
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
# NEW VIEWS FOR REALISED PROFIT CHARTS (UPDATED to handle timeframe + forward-fill)
# ----------------------------------------------------------------------------
import matplotlib
matplotlib.use("Agg")
from matplotlib.ticker import StrMethodFormatter, MaxNLocator
from django.shortcuts import HttpResponse
from django.contrib.auth.decorators import login_required

@login_required
def global_profit_chart(request):
    """
    Shows the logged-in user's global realized (cumulative) profit over time,
    with a thin line and no markers. We also allow timeframe grouping
    (Daily/Monthly/Yearly) and forward-fill missing dates to keep
    the line continuous (no zero dips). Also uses MaxNLocator to reduce x-ticks.
    """
    user = request.user
    timeframe = request.GET.get('timeframe', 'Daily')

    queryset = Transaction.objects.filter(user=user).order_by('date_of_holding', 'id')
    if not queryset.exists():
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No transactions found for global chart", ha='center', va='center')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

    # Build DataFrame
    rows = []
    for tx in queryset:
        rows.append({
            'date': tx.date_of_holding,
            'cumulative_profit': tx.cumulative_profit
        })
    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)

    # Resample based on timeframe
    if timeframe == 'Monthly':
        df = df.resample('MS').last()  # "Month Start"
    elif timeframe == 'Yearly':
        df = df.resample('YS').last()  # "Year Start"
    else:
        # Daily
        df = df.resample('D').last()

    # Forward-fill missing data
    df['cumulative_profit'] = df['cumulative_profit'].ffill()

    # Build x-label column for plotting
    if timeframe == 'Monthly':
        df['x_label'] = df.index.strftime('%Y-%m')
    elif timeframe == 'Yearly':
        df['x_label'] = df.index.strftime('%Y')
    else:
        df['x_label'] = df.index.strftime('%Y-%m-%d')

    # Plot
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(df['x_label'], df['cumulative_profit'], color='blue', linewidth=1, marker='')
    ax.set_xlabel('Date')
    ax.set_ylabel('Cumulative Profit')
    ax.set_title(f"Global Realized Profit: {user.username} ({timeframe})")
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
    # Reduce the x-ticks to avoid overlap
    ax.xaxis.set_major_locator(MaxNLocator(10))
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    fig.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png')


@login_required
def item_price_chart(request):
    """
    Plot buy/sell price lines for the requested item,
    grouping by (Daily/Monthly/Yearly). Now forward-fills missing days
    so lines remain continuous, and uses MaxNLocator to reduce date label clutter.
    """
    import io
    user = request.user
    search_query = request.GET.get('search', '').strip()
    timeframe = request.GET.get('timeframe', 'Daily')

    if not search_query:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No item specified", ha='center', va='center')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

    # Resolve item from short_name or full_name
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

    qs = Transaction.objects.filter(user=user, item=item_obj).order_by('date_of_holding', 'id')
    if not qs.exists():
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, f"No transactions for '{item_obj.name}'", ha='center', va='center')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

    # Build raw DataFrame
    rows = []
    for t in qs:
        rows.append({
            'trans_type': t.trans_type,
            'price': t.price,
            'quantity': t.quantity,
            'date': t.date_of_holding
        })
    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)

    # If you want to resample daily, do it here so lines connect across missing days
    if timeframe == 'Monthly':
        df = df.resample('MS').apply({
            'trans_type': 'last',
            'price': 'mean',      # or maybe a last known?
            'quantity': 'sum'     # or whatever grouping logic you need
        })
    elif timeframe == 'Yearly':
        df = df.resample('YS').apply({
            'trans_type': 'last',
            'price': 'mean',
            'quantity': 'sum'
        })
    else:
        # daily
        df = df.resample('D').apply({
            'trans_type': 'last',
            'price': 'mean',
            'quantity': 'sum'
        })

    # Now we have 1 row per daily/monthly/yearly bucket.
    # Next: separate buys vs sells within each group if needed.
    # Weighted‐avg approach can be re-done with the original groupby code or you can keep it simpler.

    # If you specifically want Weighted average buy/sell lines:
    # (We re-run the group logic you had, then resample daily to forward-fill.)
    # For brevity, let's do a simplified approach: just separate Buy vs Sell, forward-fill.

    # We'll do the exact weighted average approach you had:
    # 1) revert to the original df (unresampled)
    df_orig = pd.DataFrame(rows)
    df_orig['date'] = pd.to_datetime(df_orig['date'])
    # group by the "timeframe" key
    def date_key(d):
        if timeframe == 'Monthly':
            return (d.year, d.month)
        elif timeframe == 'Yearly':
            return d.year
        else:
            return d

    df_orig['group_key'] = df_orig['date'].apply(date_key)

    buy_df = df_orig[df_orig['trans_type'] == 'Buy'].groupby('group_key').apply(
        lambda g: (g['price'] * g['quantity']).sum() / g['quantity'].sum()
    ).rename('buy_price').reset_index()

    sell_df = df_orig[df_orig['trans_type'] == 'Sell'].groupby('group_key').apply(
        lambda g: (g['price'] * g['quantity']).sum() / g['quantity'].sum()
    ).rename('sell_price').reset_index()

    merged = pd.merge(buy_df, sell_df, on='group_key', how='outer')

    # Convert group_key back to a real date. If daily, we can use it directly.
    # If monthly or yearly, pick an arbitrary day in that month/year:
    def key_to_date(k):
        if isinstance(k, tuple):  # (year, month)
            return pd.to_datetime(f"{k[0]}-{k[1]:02d}-01")
        elif isinstance(k, int):  # year
            return pd.to_datetime(f"{k}-01-01")
        else:
            return pd.to_datetime(k)  # daily is already a date

    merged['date'] = merged['group_key'].apply(key_to_date)
    merged.set_index('date', inplace=True)
    # Replace 0 with NaN to avoid dropping to zero lines
    merged['buy_price'] = merged['buy_price'].replace(0, pd.NA)
    merged['sell_price'] = merged['sell_price'].replace(0, pd.NA)

    # Resample daily so lines are continuous; forward-fill
    # (If timeframe is monthly/yearly, you might prefer monthly steps, but daily ensures continuous lines).
    merged = merged.resample('D').asfreq()
    merged['buy_price'] = merged['buy_price'].ffill()
    merged['sell_price'] = merged['sell_price'].ffill()

    # Build a string x_label
    merged['x_label'] = merged.index.strftime('%Y-%m-%d')

    # Drop rows that are entirely NaN if you prefer, or keep them so lines remain connected.
    # merged.dropna(how='all', subset=['buy_price','sell_price'], inplace=True)

    # Plot
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(merged['x_label'], merged['buy_price'], color='green', linewidth=1, marker='', label='Buy Price')
    ax.plot(merged['x_label'], merged['sell_price'], color='red', linewidth=1, marker='', label='Sell Price')
    ax.set_title(f"{item_obj.name} Price History ({timeframe})")
    ax.set_ylabel("Price")
    ax.legend()
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))

    # Limit x-axis labels
    ax.xaxis.set_major_locator(MaxNLocator(10))
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    fig.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png')


@login_required
def item_profit_chart(request):
    """
    Plot item-specific cumulative profit. Now uses MaxNLocator to reduce date labels,
    and still does the monthly/yearly grouping if requested.
    """
    import io
    user = request.user
    search_query = request.GET.get('search', '').strip()
    timeframe = request.GET.get('timeframe', 'Daily')

    if not search_query:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No item specified", ha='center', va='center')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

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
            'date': t.date_of_holding,
            'realised_profit': t.realised_profit
        })
    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])

    # Group by timeframe (Daily/Monthly/Yearly) and sum realized profits in each bucket
    def date_key(d):
        if timeframe == 'Monthly':
            return (d.year, d.month)
        elif timeframe == 'Yearly':
            return d.year
        else:
            return d

    df['group_key'] = df['date'].apply(date_key)
    gp = df.groupby('group_key')['realised_profit'].sum().reset_index()
    gp.rename(columns={'realised_profit': 'bucket_profit'}, inplace=True)

    # Convert group_key back to a date/time index so we can resample or plot easily
    def key_to_date(k):
        if isinstance(k, tuple):
            return pd.to_datetime(f"{k[0]}-{k[1]:02d}-01")
        elif isinstance(k, int):
            return pd.to_datetime(f"{k}-01-01")
        else:
            return pd.to_datetime(k)

    gp['date'] = gp['group_key'].apply(key_to_date)
    gp.sort_values('date', inplace=True)
    gp.set_index('date', inplace=True)

    # Now compute cumulative sum
    gp['cumulative_profit'] = gp['bucket_profit'].cumsum()

    # Forward-fill daily if timeframe == Daily. If monthly or yearly,
    # you can do something similar or just plot as-is:
    if timeframe == 'Daily':
        # Reindex to daily range
        all_days = pd.date_range(gp.index.min(), gp.index.max(), freq='D')
        gp = gp.reindex(all_days)
        gp['cumulative_profit'] = gp['cumulative_profit'].ffill()

    # Build string x_label
    if timeframe == 'Monthly':
        gp['x_label'] = gp.index.strftime('%Y-%m')
    elif timeframe == 'Yearly':
        gp['x_label'] = gp.index.strftime('%Y')
    else:
        gp['x_label'] = gp.index.strftime('%Y-%m-%d')

    # Plot
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

    # Limit x-axis ticks
    ax.xaxis.set_major_locator(MaxNLocator(10))
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')

    fig.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png')

