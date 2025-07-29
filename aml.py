#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Pardon our temporary mess during construction.

This is a WIP toward generating synthetic data for bank transactions
which emulate typical tradecraft patterns employed in money laundering.
"""

import datetime
import random
import typing

from icecream import ic
from pydantic import BaseModel, NonNegativeFloat
import numpy as np


SHELL_CORPS: typing.Dict[ str, list ] = {
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


class Simulation:
    """
Simulating patterns of money laundering tradecraft.
    """
    XACT_LIMIT: NonNegativeFloat = 99000.0

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
        ) -> datetime:
        """
Sample random dates between two `datetime` objects.
        """
        delta: timedelta = finish - start
        rand_sec: int = random.randrange((delta.days * 24 * 60 * 60) + delta.seconds)

        return start + timedelta(seconds = rand_sec)


    def gen_xact_amount (
        self,
        ) -> NonNegativeFloat:
        """
Generate the amount for a transaction, based on a random variable.

returns:
    `amount`: transaction amount, non-negative, rounded to two decimal points.
        """
        gen_amount: float = self.rng_gaussian(
            mean = self.XACT_LIMIT / 2.0,
            stdev = self.XACT_LIMIT / 10.0,
        )

        amount: NonNegativeFloat = round(self.XACT_LIMIT - gen_amount, 2)

        return amount


class ShellCorp (BaseModel):
    """
A data class representing one shell company.
    """
    name: str
    address: str
    bank: str
    balance: NonNegativeFloat = 0.0


class Transaction (BaseModel):
    """
A data class representing one money transfer transaction.
    """
    date: datetime.datetime
    amount: NonNegativeFloat
    remitter: str
    receiver: str
    description: str


if __name__ == "__main__":
    sim: Simulation = Simulation()
    xact_log: typing.List[ Transaction ] = []

    ## instantiate the ShellCorp objects, assigning bank accounts
    shells: typing.List[ ShellCorp ] = [
        ShellCorp(
            name = name,
            address = addrs[0],
            bank = random.choice(sim.SKETCH_BANKS),
        )
        for name, addrs in SHELL_CORPS.items()
    ]

    ## create opening balances
    for shell in shells:
        for _ in range(random.randint(1, 5)):
            xact = Transaction(
                date = sim.start + datetime.timedelta(days = random.randint(1, 7)),
                amount = round(sim.gen_xact_amount(), -3),
                remitter = shell.bank,
                receiver = shell.name,
                description = "local deposit",
            )

            xact_log.append(xact)
            shell.balance += xact.amount


    ic(xact_log)
    ic(shells)


## 1. origins
## 2. layering
## 3. deals

## plausible `origins`
##  - local bank transfer
##  - Rosoboronexport
##  - Amazon merchandise sales

## plausible `layering` tradecraft
##  - RMF bleed off N% on each step
##  - initial burst in volume after opening
##  - mutual payers/remitters
##  - overnight balance low compared with total activity
##  - reused invoices

## plausible `deals`
##  - local bank transfer
##  - merchandise for Amazon
##  - Hermitage Capital Management
##  - cryptocoin exchanges (BitMEX)
##  - real estate, property management, leases
##  - payroll outsourcing for "staff"
