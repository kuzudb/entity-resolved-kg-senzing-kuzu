#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Pardon our temporary mess during construction.

This is a WIP toward generating synthetic data for bank transactions
which emulate typical tradecraft patterns employed in money laundering.
"""

from enum import StrEnum, auto
import datetime
import json
import random
import sys
import typing

from icecream import ic
from pydantic import BaseModel, NonNegativeFloat
import numpy as np
import polars as pl


SHELL_DATA: typing.Dict[ str, list ] = {
    "BARLLOWS SERVICES LTD": [
        "3 Market Parade, 41 East Street, Bromley, BR1 1QN",
        "31 Quernmore Close, Bromley, Kent, United Kingdom, BR1 4EL",
    ],
    "LMAR (GB) LTD": [
        "31 Quernmore Close, Bromley, Kent, United Kingdom, BR1 4EL",
    ],
    "WELLHANCIA HEALTH CARE LTD": [
        "31 Quernmore Close, Bromley, BR1 4EL",
    ],
}


class Transaction (BaseModel):
    """
A data class representing one money transfer transaction.
    """
    date: datetime.datetime
    amount: NonNegativeFloat
    remitter: str
    receiver: str
    descript: str


class ShellCorp (BaseModel):
    """
A data class representing one shell company.
    """
    name: str
    address: str
    bank: str
    balance: NonNegativeFloat = 0.0
    last_active: datetime.datetime = datetime.datetime.today()

    def take_xact (
        self,
        xact: Transaction,
        *,
        deposit: bool = True,
        ) -> None:
        """
Handle one transaction.
        """
        self.last_active = max(self.last_active, xact.date)

        if deposit:
            self.balance += xact.amount
        else:
            self.balance -= xact.amount


class TradecraftDeal (StrEnum):
    ## cryptocoin exchanges
    CRYPTO = auto()
    ## merchandise for Amazon
    AMZN = auto()


class Simulation:
    """
Simulating patterns of money laundering tradecraft.

Money laundering process via shell companies:
  1. origins
  2. layering
  3. deals

plausible `origins` for deposits
  - local bank transfer
  - cryptocoin exchanges
  - Amazon Marketplace sales
  - Rosoboronexport weapon sales kick-backs

plausible `layering` tradecraft:
  - initial burst in volume after opening
  - mutual payers/remitters
  - RMF bleed off N% on each step
  - overnight balance low compared with total activity
  - reuse of invoices

plausible `deals` for payments:
  - local bank transfer
  - cryptocoin exchanges
  - merchandise for Amazon Marketplace
  - Hermitage Capital Management
  - real estate, property management, leases
  - payroll outsourcing for "staff"
    """

    XACT_LIMIT: NonNegativeFloat = 99000.0

    INTERDAY_MEDIAN: float = 8.7
    INTERDAY_STDEV: float = 32.745006

    SKETCH_BANKS: typing.List[ str ] = [
        "BCCI",
        "Liberty Reserve",
        "Arab Bank",
        "Banca Socială",
        "Ranchlander National Bank",
        "Banco Alas",
        "Santa Anna National Bank",
        "Pulaski Savings",
    ]

    SKETCH_CRYPTO: typing.List[ str ] = [
        "BitMEX",
        "BIPPAX",
        "FX Alliance Traders",
        "Pinance.io",
        "DCEX Exchange",
        "Bityard",
        "CoinWpro",
        "Coinegg",
    ]


    def __init__ (
        self,
        *,
        start: datetime.datetime = datetime.datetime.today()
        ) -> None:
        """
Constructor.
        """
        self.start: datetime.datetime = start
        self.rng: np.random.Generator = np.random.default_rng()
        self.shells: typing.List[ ShellCorp ] = []
        self.xact_log: typing.List[ Transaction ] = []


    def rng_gaussian (
        self,
        *,
        mean: float = 0.0,
        stdev: float = 1.0,
        ) -> float:
        """
Sample random numbers from a Gaussian distribution.
        """
        return float(self.rng.normal(loc = mean, scale = stdev, size = 1)[0])


    def rng_exponential (
        self,
        *,
        scale: float = 1.0,
        ) -> float:
        """
Sample random numbers from an Exponential distribution.
        """
        return float(self.rng.exponential(scale = scale, size = 1)[0])


    def rng_poisson (
        self,
        *,
        lambda_: float = 1.0,
        ) -> float:
        """
Sample random numbers from a Poisson distribution.
        """
        return float(self.rng.poisson(lam = lambda_, size = 1)[0])


    @classmethod
    def rng_uniform_datetime (
        cls,
        start: datetime.datetime,
        finish: datetime.datetime,
        ) -> datetime.datetime:
        """
Sample random dates between two `datetime` objects.
        """
        delta: datetime.timedelta = finish - start
        rand_sec: int = random.randrange((delta.days * 24 * 60 * 60) + delta.seconds)

        return start + datetime.timedelta(seconds = rand_sec)


    def gen_xact_amount (
        self,
        ) -> NonNegativeFloat:
        """
Generate the amount for a transaction, based on a random variable,
while staying under the banks' threshold limit for AML checks.

returns:
    `amount`: transaction amount, non-negative, rounded to two decimal points.
        """
        gen_amount: float = self.rng_gaussian(
            mean = self.XACT_LIMIT / 2.0,
            stdev = self.XACT_LIMIT / 10.0,
        )

        amount: NonNegativeFloat = round(self.XACT_LIMIT - gen_amount, 2)

        return amount


    def gen_xact_timing (
        self,
        start: datetime.datetime,
        ) -> datetime.datetime:
        """
Generate the timing for a transaction, based on a random variable.

returns:
    `timing`: transaction datetime offset
        """
        gen_offset: float = self.rng_poisson(lambda_ = self.INTERDAY_MEDIAN)
        timing: datetime.datetime = start + datetime.timedelta(hours = gen_offset * 24.0)

        return timing


    def gen_shell_corps (
        self,
        shell_data: dict,
        ) -> None:
        """
Instantiate the list of ShellCorp objects, assigning bank accounts
and creating opening balances.
        """
        self.shells = [
            ShellCorp(
                name = name,
                address = addrs[0],
                bank = random.choice(self.SKETCH_BANKS),
            )
            for name, addrs in shell_data.items()
        ]

        ## create opening balances
        for shell in self.shells:
            for _ in range(random.randint(1, 5)):
                xact: Transaction = Transaction(
                    date = self.start + datetime.timedelta(days = random.randint(1, 7)),
                    amount = round(round(self.gen_xact_amount(), -3), 2),
                    remitter = shell.bank,
                    receiver = shell.name,
                    descript = "local deposit",
                )

                self.xact_log.append(xact)
                shell.take_xact(xact)


    def layer_rmf (
        self,
        ) -> None:
        """
Simulate layering based on _rapid movement of funds_ (RMF) tradecraft.
        """
        shell_seq: list = random.sample(self.shells, len(self.shells))

        # generate origin of funds
        lead_shell: ShellCorp = shell_seq[0]

        remitter: str = random.choice([
            "Amazon Marketplace",
            "Rosoboronexport",
            "Hermitage Capital Management",
        ])

        date: datetime.datetime = self.gen_xact_timing(lead_shell.last_active)
        amount: NonNegativeFloat = round(round(self.gen_xact_amount(), -3), 2)

        xact: Transaction = Transaction(
            date = date,
            amount = amount,
            remitter = remitter,
            receiver = lead_shell.name,
            descript = "invoiced services",
        )

        self.xact_log.append(xact)
        lead_shell.take_xact(xact)

        # layer through other shell companies,
        # bleeding off N% at each step,
        # until dumping back to the first one
        for ind, shell in enumerate(shell_seq):
            next_shell: ShellCorp = shell_seq[(ind + 1) % len(shell_seq)]
            date = self.gen_xact_timing(date)
            amount *= 1.0 - self.rng_exponential(scale = .1)

            xact = Transaction(
                date = date,
                amount = round(amount, 2),
                remitter = shell.name,
                receiver = next_shell.name,
                descript = "invoiced services",
            )

            self.xact_log.append(xact)
            next_shell.take_xact(xact)


    def gen_deal (
        self,
        shell: ShellCorp,
        ) -> None:
        """
Perform a "deal" to drain some of the laundered funds from a shell
company's bank account.
        """
        amount: NonNegativeFloat = min(shell.balance, round(self.gen_xact_amount(), -3))
        date: datetime.datetime = self.gen_xact_timing(shell.last_active)

        ## for now, only crypto coin purchases
        ## later we'll add other deals, e.g., real estate
        deal: TradecraftDeal = TradecraftDeal.CRYPTO

        match deal:
            case TradecraftDeal.CRYPTO:
                receiver: str = random.choice(self.SKETCH_CRYPTO)
                descript: str = "investment"

        xact: Transaction = Transaction(
            date = date,
            amount = round(amount, 2),
            remitter = shell.name,
            receiver = receiver,
            descript = descript,
        )

        self.xact_log.append(xact)
        shell.take_xact(xact, deposit = False)


    def drain_into_deals (
        self,
        ) -> None:
        """
Generate deals to drain the remaining balances for each shell company.
        """
        for shell in self.shells:
            while shell.balance > 0.0:
                self.gen_deal(shell)


    def get_xact_df (
        self,
        ) -> pl.DataFrame:
        """
Returns a `polars` DataFrame of the generated transactions.
        """
        return pl.DataFrame([
            json.loads(xact.model_dump_json())
            for xact in self.xact_log
        ]).sort("date")


if __name__ == "__main__":
    sim: Simulation = Simulation()
    sim.gen_shell_corps(SHELL_DATA)

    ## perform _layering_ to shuffle sources of funds,
    ## and rinse/lather/repeat a few times
    PRESS_YOUR_LUCK: int = 3

    for _ in range(PRESS_YOUR_LUCK):
        sim.layer_rmf()

    ## cash out: drain accounts into deals
    sim.drain_into_deals()

    ## export synthetic data
    df: pl.DataFrame = sim.get_xact_df()
    ic(df)
