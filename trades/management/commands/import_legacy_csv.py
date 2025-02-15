# trades/management/commands/import_legacy_csv.py

import os
import csv
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction as db_transaction

from trades.models import (
    Alias, Item, AccumulationPrice, TargetSellPrice,
    Membership, WealthData, Watchlist, Transaction
)
# Use the new function that can recalc for all users, but only once at end.
from trades.views import calculate_fifo_for_all_users


class Command(BaseCommand):
    help = "Import CSV data from old scripts into the new Django models."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csvdir",
            type=str,
            default=".",
            help="Directory containing the CSV files (default current directory).",
        )

    @db_transaction.atomic
    def handle(self, *args, **options):
        csv_dir = options["csvdir"]

        self.stdout.write(self.style.SUCCESS(f"Starting CSV import from directory: {csv_dir}"))

        # --- NEW CODE: Delete old transaction data to avoid duplicates ---
        Transaction.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("Old transaction data deleted."))

        aliases_csv = os.path.join(csv_dir, "item_aliases.csv")
        if os.path.exists(aliases_csv):
            self.import_aliases(aliases_csv)
        else:
            self.stdout.write(self.style.WARNING(f"File not found: {aliases_csv} (skipping)"))

        accum_csv = os.path.join(csv_dir, "accumulation_prices.csv")
        if os.path.exists(accum_csv):
            self.import_accumulation_prices(accum_csv)
        else:
            self.stdout.write(self.style.WARNING(f"File not found: {accum_csv} (skipping)"))

        membership_csv = os.path.join(csv_dir, "membership_data.csv")
        if os.path.exists(membership_csv):
            self.import_memberships(membership_csv)
        else:
            self.stdout.write(self.style.WARNING(f"File not found: {membership_csv} (skipping)"))

        target_csv = os.path.join(csv_dir, "target_sell_prices.csv")
        if os.path.exists(target_csv):
            self.import_target_sell_prices(target_csv)
        else:
            self.stdout.write(self.style.WARNING(f"File not found: {target_csv} (skipping)"))

        transactions_csv = os.path.join(csv_dir, "transactions.csv")
        if os.path.exists(transactions_csv):
            self.import_transactions(transactions_csv)
        else:
            self.stdout.write(self.style.WARNING(f"File not found: {transactions_csv} (skipping)"))

        watchlist_csv = os.path.join(csv_dir, "watchlist.csv")
        if os.path.exists(watchlist_csv):
            self.import_watchlist(watchlist_csv)
        else:
            self.stdout.write(self.style.WARNING(f"File not found: {watchlist_csv} (skipping)"))

        wealth_csv = os.path.join(csv_dir, "wealth_data.csv")
        if os.path.exists(wealth_csv):
            self.import_wealth_data(wealth_csv)
        else:
            self.stdout.write(self.style.WARNING(f"File not found: {wealth_csv} (skipping)"))

        # Recalc FIFO for all users (only once, after entire import).
        self.stdout.write(self.style.SUCCESS("Recalculating FIFO profits for all users..."))
        calculate_fifo_for_all_users()

        self.stdout.write(self.style.SUCCESS("All CSV imports completed successfully!"))

    def import_aliases(self, filepath):
        self.stdout.write(f"Importing aliases from {filepath}...")
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                full_name = row["FullName"].strip()
                short_name = row["ShortName"].strip()
                image_path = row["ImagePath"].strip()
                alias, _ = Alias.objects.get_or_create(
                    full_name=full_name,
                    short_name=short_name
                )
                alias.image_path = image_path
                alias.save()
        self.stdout.write(self.style.SUCCESS("Aliases imported."))

    def import_accumulation_prices(self, filepath):
        self.stdout.write(f"Importing accumulation prices from {filepath}...")
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                item_name = row["Name"].strip()
                acc_price = float(row["Accumulation Price"] or 0)
                item_obj, _ = Item.objects.get_or_create(name=item_name)
                ap, _ = AccumulationPrice.objects.get_or_create(item=item_obj)
                ap.accumulation_price = acc_price
                ap.save()
        self.stdout.write(self.style.SUCCESS("Accumulation Prices imported."))

    def import_memberships(self, filepath):
        self.stdout.write(f"Importing memberships from {filepath}...")
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                acct_name = row["Account Name"].strip()
                mem_stat = row["Membership Status"].strip()
                end_date_str = row["Membership End Date"].strip()
                end_date = None
                if end_date_str:
                    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                m, _ = Membership.objects.get_or_create(account_name=acct_name)
                m.membership_status = mem_stat if mem_stat else "No"
                m.membership_end_date = end_date
                m.save()
        self.stdout.write(self.style.SUCCESS("Membership data imported."))

    def import_target_sell_prices(self, filepath):
        self.stdout.write(f"Importing target sell prices from {filepath}...")
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                item_name = row["Name"].strip()
                target_price = float(row["Target Sell Price"] or 0)
                item_obj, _ = Item.objects.get_or_create(name=item_name)
                tsp, _ = TargetSellPrice.objects.get_or_create(item=item_obj)
                tsp.target_sell_price = target_price
                tsp.save()
        self.stdout.write(self.style.SUCCESS("Target Sell Prices imported."))

    def import_transactions(self, filepath):
        self.stdout.write(f"Importing transactions from {filepath}...")
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                item_name = row["Name"].strip()
                trans_type = row["Type"].strip()
                price = float(row["Price"] or 0)
                qty = float(row["Quantity"] or 0)
                date_str = row["Date of Holding"].strip()
                realized = float(row.get("Realised Profit", 0) or 0)
                cumulative = float(row.get("Cumulative Profit", 0) or 0)
                if date_str:
                    date_of_holding = datetime.strptime(date_str, "%Y-%m-%d").date()
                else:
                    date_of_holding = datetime.today().date()

                item_obj, _ = Item.objects.get_or_create(name=item_name)
                # Example: always link to a single user, or handle logic for multiple
                user = User.objects.get(username="Arblack")
                Transaction.objects.create(
                    user=user,
                    item=item_obj,
                    trans_type=trans_type,
                    price=price,
                    quantity=qty,
                    date_of_holding=date_of_holding,
                    realised_profit=realized,
                    cumulative_profit=cumulative,
                )
        self.stdout.write(self.style.SUCCESS("Transactions imported."))

    def import_watchlist(self, filepath):
        self.stdout.write(f"Importing watchlist from {filepath}...")
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row["Name"].strip()
                desired_price = float(row["Desired Price"] or 0)
                date_added_str = row["Date Added"].strip()
                buy_or_sell = row["Buy or Sell"].strip()
                account_name = row["Account Name"].strip()
                wished_qty = float(row["Wished Quantity"] or 0)
                current_holding = float(row["Current Holding"] or 0)
                total_value = float(row["Total Value"] or 0)
                membership_status = row["Membership Status"].strip()
                membership_end_str = row["Membership End Date"].strip()

                try:
                    date_added = datetime.strptime(date_added_str, "%Y-%m-%d").date()
                except ValueError:
                    date_added = datetime.today().date()

                membership_end = None
                if membership_end_str:
                    try:
                        membership_end = datetime.strptime(membership_end_str, "%Y-%m-%d").date()
                    except ValueError:
                        membership_end = None

                Watchlist.objects.create(
                    name=name,
                    desired_price=desired_price,
                    date_added=date_added,
                    buy_or_sell=buy_or_sell if buy_or_sell in ["Buy", "Sell"] else "Buy",
                    account_name=account_name,
                    wished_quantity=wished_qty,
                    total_value=total_value,
                    current_holding=current_holding,
                    membership_status=membership_status,
                    membership_end_date=membership_end,
                )
        self.stdout.write(self.style.SUCCESS("Watchlist imported."))

    def import_wealth_data(self, filepath):
        self.stdout.write(f"Importing wealth data from {filepath}...")
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                year = int(row["Year"].strip())
                acct_name = row["Account Name"].strip()
                WealthData.objects.create(
                    account_name=acct_name,
                    year=year,
                    january=row["January"].strip(),
                    february=row["February"].strip(),
                    march=row["March"].strip(),
                    april=row["April"].strip(),
                    may=row["May"].strip(),
                    june=row["June"].strip(),
                    july=row["July"].strip(),
                    august=row["August"].strip(),
                    september=row["September"].strip(),
                    october=row["October"].strip(),
                    november=row["November"].strip(),
                    december=row["December"].strip(),
                )
        self.stdout.write(self.style.SUCCESS("Wealth data imported."))
