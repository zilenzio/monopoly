# Copyright (C) 2021 Games Computers Play <https://github.com/gamescomputersplay> and nopeless
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Monopoly Simulator
# Videos with some research using this simulator:
# https://www.youtube.com/watch?v=6EJrZeN0jNI
# https://www.youtube.com/watch?v=Dx1ofZHGUtI

import random
import math
import time
import matplotlib.pyplot as plt
import numpy as np
import progressbar

import util

# simulation settings
n_players = 4
nMoves = 1000
nSimulations = 1000
SEED = None
shuffle_players = True
realTime = False  # Allow step by step execution via space/enter key

# some game rules
settingStartingMoney = 1500
settingsSalary = 200
settingsLuxuryTax = 75
settingsPropertyTax = 200
settingJailFine = 50
settingHouseLimit = 32
settingHotelLimit = 12
settingsAllowUnEqualDevelopment = False  # default = False

# players behaviour settings
behave_unspendable_cash = 0  # Money I want to will have left after buying stuff
behaveUnmortgageCoeff = 3  # repay mortgage if you have times this cash
behaveDoTrade = True  # willing to trade property
behaveDoThreeWayTrade = True  # willing to trade property three-way
behaveBuildCheapest = False
behaveBuildRandom = False

# experimental settings
# for a player named exp:
expRefuseTrade = False  # refuse to trade property
expRefuseProperty = ""  # refuse to buy this group
expHouseBuildLimit = 100  # limit houses built
exp_unspendable_cash = 0  # unspendable money
expBuildCheapest = False
expBuildExpensive = False
expBuildThree = False
var_starting_money = []  # [1370, 1460, 1540, 1630] # [] to disable


# reporting settings
OUT_WIDTH = 80
show_progress_bar = True
showMap = False  # only for 1 game: show final board map
showResult = True  # only for 1 game: show final money score
showRemPlayers = True
writeLog = False  # write log with game events (log.txt file)

# Various raw data to output (to data.txt file)
# writeData = "none"
# writeData = "popular_cells" # Cells to land
# writeData = "last_turn" # Length of the game
writeData = "losers_names"  # Who lost
# writeData = "net_worth" # history of a game
# writeData = "remaining_players"

try:
    import config  # type: ignore

    items = util.get_vars(config)
    if items:
        log = items.get("log", True)
        if log:
            print("=" * OUT_WIDTH)
            print("Overrides (is now value << was value):")
        for k, v in items.items():
            if log:
                print(f"{f'  {k}={repr(v)}':30} << {locals()[k]}")
            locals()[k] = v
except ImportError:
    print("No config file found, using default settings")

# seed number generator
random_dice = random.Random(SEED)
random_shuffle = random.Random(SEED)


class Log:
    def __init__(self):
        for n in ["log.txt", "data.txt"]:
            with open(n, "w") as f:
                f.write("")
        # Use explicit form of append logging
        self.datafs = open("data.txt", "ab", 0)
        self.fs = open("log.txt", "ab", 0)

    def close(self):
        self.datafs.close()
        self.fs.close()

    def write(self, text, level=0, data=False):
        if data and writeData:
            self.datafs.write(bytes(text + "\n", "utf-8"))
            return
        if writeLog:
            if level < 2:
                self.fs.write(bytes("\n" * (2 - level), "utf-8"))
            self.fs.write(bytes("\t" * level + text + "\n", "utf-8"))


class Player:
    """Player class"""

    def __init__(self, name, starting_money):
        self.name = name
        self.position = 0
        self.money = starting_money
        self.consequent_doubles = 0
        self.in_jail = False
        self.days_in_jail = 0
        self.has_jail_card_chance = False
        self.has_jail_card_community = False
        self.is_bankrupt = False
        self.has_mortgages = []
        self.plots_wanted = []
        self.plots_offered = []
        self.plots_to_build = []
        self.cash_limit = (
            exp_unspendable_cash if name == "exp" else behave_unspendable_cash
        )
        self.dice = (0, 0)

    def __str__(self):
        return (
            "Player: "
            + self.name
            + ". Position: "
            + str(self.position)
            + ". Money: $"
            + str(self.money)
        )

    # some getters and setters

    def get_money(self):
        return self.money

    def get_name(self):
        return self.name

    # add money (salary, receive rent etc)
    def add_money(self, amount):
        self.money += amount

    # subtract money (pay rent, buy property etc)
    def take_money(self, amount):
        self.money -= amount

    # subtract money (pay rent, buy property etc)
    def move_to(self, position):
        self.position = position
        log.write(self.name + " moves to cell " + str(position), 3)

    # make a move procedure

    def make_a_move(self, board):

        go_again = False

        # Only proceed if player is alive (not bankrupt)
        if self.is_bankrupt:
            return

        # to track the popular cells to land
        if writeData == "popular_cells":
            log.write(str(self.position), data=True)

        log.write("Player " + self.name + " goes:", 2)

        # non-board actions: Trade, unmortgage, build
        # repay mortgage if you have X times more cashe than mortgage cost
        while self.repay_mortgage():
            board.recalculate_after_property_change()

        # build houses while you have pare cash
        while board.improve_property(self, self.money - self.cash_limit):
            pass

        # Calculate property player wants to get and ready to give away
        if expRefuseTrade and self.name == "exp":
            pass  # Experiment: do not trade
        elif behaveDoTrade:
            #  Make a trade
            if (
                not self.two_way_trade(board)
                and n_players >= 3
                and behaveDoThreeWayTrade
            ):
                self.three_way_trade(board)

        # roll dice
        dice1 = random_dice.randint(1, 6)
        dice2 = random_dice.randint(1, 6)
        log.write(
            self.name
            + " rolls "
            + str(dice1)
            + " and "
            + str(dice2)
            + " = "
            + str(dice1 + dice2),
            3,
        )
        self.dice = (dice1, dice2)

        # doubles
        if dice1 == dice2 and not self.in_jail:
            go_again = True  # go again if doubles
            self.consequent_doubles += 1
            log.write(
                "it's a number " + str(self.consequent_doubles) + " double in a row", 3
            )
            if self.consequent_doubles == 3:  # but go to jail if 3 times in a row
                self.in_jail = True
                log.write(self.name + " goes to jail on consequtive doubles", 3)
                self.move_to(10)
                self.consequent_doubles = 0
                return False
        else:
            self.consequent_doubles = 0  # reset doubles counter

        # Jail situation:
        # Stay unless you roll doubles
        if self.in_jail:
            if self.has_jail_card_chance:
                self.has_jail_card_chance = False
                board.chanceCards.append(1)  # return the card
                log.write(
                    self.name + " uses the Chance GOOJF card to get out of jail", 3
                )
            elif self.has_jail_card_community:
                self.has_jail_card_community = False
                board.communityCards.append(6)  # return the card
                log.write(
                    self.name + " uses the Community GOOJF card to get out of jail", 3
                )
            elif dice1 != dice2:
                self.days_in_jail += 1
                if self.days_in_jail < 3:
                    log.write(self.name + " spends this turn in jail", 3)
                    return False  # skip turn in jail
                else:
                    self.take_money(settingJailFine)  # get out on fine
                    self.days_in_jail = 0
                    log.write(self.name + " pays fine and gets out of jail", 3)
            else:  # get out of jail on doubles
                log.write(self.name + " rolls double and gets out of jail", 3)
                self.days_in_jail = 0
                go_again = False
        self.in_jail = False

        # move the piece
        self.position += dice1 + dice2

        # correction of the position if landed on GO or overshoot GO
        if self.position >= 40:
            # calculate correct cell
            self.position = self.position - 40
            # get salary for passing GO
            self.add_money(settingsSalary)
            log.write(self.name + " gets salary: $" + str(settingsSalary), 3)

        owner_str = ""
        if hasattr(board.b[self.position], "owner"):
            if hasattr(board.b[self.position].owner, "name"):
                owner_str = f" ({board.b[self.position].owner.name})"
        log.write(
            self.name
            + " moves to cell "
            + str(self.position)
            + ": "
            + board.b[self.position].name
            + owner_str,
            3,
        )

        # perform action of the cell player ended on
        board.action(self, self.position)

        # check if bankrupt after the action
        self.check_bankruptcy(board)

        if go_again:
            log.write(self.name + " will go again now", 3)
            return True  # make a move again
        return False  # no extra move

    # get the cheapest mortgage property (name, price)

    def cheapest_mortgage(self):
        cheapest = False
        for mortgage in self.has_mortgages:
            if not cheapest or mortgage[1] < cheapest[1]:
                cheapest = mortgage
        return cheapest

    # Chance card make general repairs: 25/house 100/hotel
    def make_repairs(self, board, repairtype):
        repair_cost = 0
        if repairtype == "chance":
            per_house, per_hotel = 25, 100
        else:
            per_house, per_hotel = 40, 115
        log.write(
            "Repair cost: $"
            + str(per_house)
            + " per house, $"
            + str(per_hotel)
            + " per hotel",
            3,
        )

        for plot in board.b:
            if type(plot) == Property and plot.owner == self:
                if plot.hasHouses == 5:
                    repair_cost += per_hotel
                else:
                    repair_cost += plot.hasHouses * per_house
        self.take_money(repair_cost)
        log.write(self.name + " pays total repair costs $" + str(repair_cost), 3)

    # check if player has negative money
    # if so, start selling stuff and mortgage plots
    # if that's not enough, player bankrupt

    def check_bankruptcy(self, board):
        if self.money < 0:
            log.write(self.name + " doesn't have enough cash", 3)
            while self.money < 0:
                worst_asset = board.choose_property_to_mortgage_downgrade(self)
                if not worst_asset:
                    self.is_bankrupt = True
                    board.sell_all(self)
                    board.recalculate_after_property_change()
                    log.write(
                        self.name
                        + " is now bankrupt. Their property is back on board.",
                        3,
                    )

                    # to track players who lost
                    if writeData == "losers_names":
                        log.write(self.name, data=True)

                    # to track cells to land one last time
                    if writeData == "popular_cells":
                        log.write(str(self.position), data=True)

                    return
                else:
                    board.b[worst_asset].mortgage(self, board)
                    board.recalculate_after_property_change()

    # Calculate net worth of a player (for property tax)
    def net_worth(self, board):
        worth = self.money
        for plot in board.b:
            if type(plot) == Property and plot.owner == self:
                if plot.is_mortgaged:
                    worth += plot.cost_base // 2
                else:
                    worth += plot.cost_base
                    worth += plot.cost_house * plot.hasHouses
        return worth

    # Behaviours

    # if there is a mortgage with pay less then current money // behaveUnmortgageCoeff
    # repay the mortgage
    def repay_mortgage(self):
        cheapest = self.cheapest_mortgage()
        if cheapest and self.money > cheapest[1] * behaveUnmortgageCoeff:
            cheapest[0].unmortgage(self)
            return True
        return False

    # does player want to buy a property
    def wants_to_buy(self, cost, group):

        if self.name == "exp" and group == expRefuseProperty:
            log.write(
                self.name + " refuses to buy " + expRefuseProperty + " property", 3
            )
            return False
        if self.money > cost + self.cash_limit:  # leave some money just in case
            return True
        else:
            return False

    # Look for and perform a two-way trade
    def two_way_trade(self, board):
        trade_happened = False
        for i_want in self.plots_wanted[::-1]:
            owner_of_wanted = board.b[i_want].owner
            if owner_of_wanted is None:
                continue
            # Find a match betwee what I want / they want / I have / they have
            for they_want in owner_of_wanted.plots_wanted[::-1]:
                if (
                    they_want in self.plots_offered
                    and board.b[i_want].group != board.b[they_want].group
                ):  # prevent exchanging in groups of 2
                    log.write(
                        "Trade match: "
                        + self.name
                        + " wants "
                        + board.b[i_want].name
                        + ", and "
                        + owner_of_wanted.name
                        + " wants "
                        + board.b[they_want].name,
                        3,
                    )

                    # Compensate that one plot is cheaper than another one
                    if board.b[i_want].cost_base < board.b[they_want].cost_base:
                        cheaper_one, expensive_one = i_want, they_want
                    else:
                        cheaper_one, expensive_one = they_want, i_want
                    price_diff = (
                        board.b[expensive_one].cost_base
                        - board.b[cheaper_one].cost_base
                    )
                    log.write("Price difference is $" + str(price_diff), 3)

                    # make sure they they can pay the money
                    if (
                        board.b[cheaper_one].owner.money - price_diff
                        >= board.b[cheaper_one].owner.cash_limit
                    ):
                        log.write("We have a deal. Money and property changed hands", 3)
                        # Money and property change hands
                        board.b[cheaper_one].owner.take_money(price_diff)
                        board.b[expensive_one].owner.add_money(price_diff)
                        board.b[cheaper_one].owner, board.b[expensive_one].owner = (
                            board.b[expensive_one].owner,
                            board.b[cheaper_one].owner,
                        )
                        trade_happened = True

                        # recalculated wanted and offered plots
                        board.recalculate_after_property_change()
        return trade_happened

    def three_way_trade(self, board):
        """Look for and perform a three-way trade"""
        trade_happened = False
        for wanted1 in self.plots_wanted[::-1]:
            owner_of_wanted1 = board.b[wanted1].owner
            if owner_of_wanted1 is None:
                continue
            for wanted2 in owner_of_wanted1.plots_wanted[::-1]:
                owner_of_wanted2 = board.b[wanted2].owner
                if owner_of_wanted2 is None:
                    continue
                for wanted3 in owner_of_wanted2.plots_wanted[::-1]:
                    if wanted3 in self.plots_offered:

                        # check we have property from 3 groups
                        # otherwise someone can give and take brown or indigo at the same time
                        check_diff_group = set()
                        check_diff_group.add(board.b[wanted1].group)
                        check_diff_group.add(board.b[wanted2].group)
                        check_diff_group.add(board.b[wanted3].group)
                        if len(check_diff_group) < 3:
                            continue

                        topay1 = board.b[wanted1].cost_base - board.b[wanted3].cost_base
                        topay2 = board.b[wanted2].cost_base - board.b[wanted1].cost_base
                        topay3 = board.b[wanted3].cost_base - board.b[wanted2].cost_base
                        if (
                            self.money - topay1 > self.cash_limit
                            and owner_of_wanted1.money - topay2
                            > owner_of_wanted1.cash_limit
                            and owner_of_wanted2.money - topay3
                            > owner_of_wanted2.cash_limit
                        ):
                            log.write("Tree way trade: ", 3)
                            log.write(
                                self.name
                                + " gives "
                                + board.b[wanted3].name
                                + " and $"
                                + str(topay1)
                                + " for "
                                + board.b[wanted1].name,
                                4,
                            )
                            log.write(
                                owner_of_wanted1.name
                                + " gives "
                                + board.b[wanted1].name
                                + " and $"
                                + str(topay2)
                                + " for "
                                + board.b[wanted2].name,
                                4,
                            )
                            log.write(
                                owner_of_wanted2.name
                                + " gives "
                                + board.b[wanted2].name
                                + " and $"
                                + str(topay3)
                                + " for "
                                + board.b[wanted3].name,
                                4,
                            )
                            # Money and property change hands
                            board.b[wanted1].owner = self
                            board.b[wanted2].owner = owner_of_wanted1
                            board.b[wanted3].owner = owner_of_wanted2
                            self.take_money(topay1)
                            owner_of_wanted1.take_money(topay2)
                            owner_of_wanted2.take_money(topay3)
                            trade_happened = True
                            # recalculated wanted and offered plots
                            board.recalculate_after_property_change()


class Cell:
    """Generic Cell Class, base for other classes"""

    def __init__(self, name):
        self.name = name
        self.group = ""

    def action(self, player):
        pass


class LuxuryTax(Cell):
    """Pay Luxury Tax cell (#38)"""

    def action(self, player):
        player.take_money(settingsLuxuryTax)
        log.write(player.name + " pays Luxury Tax $" + str(settingsLuxuryTax), 3)


class PropertyTax(Cell):
    """Pay Property Tax cell (200 or 10%) (#4)"""

    def action(self, player, board):
        to_pay = min(settingsPropertyTax, player.net_worth(board) // 10)
        log.write(player.name + " pays Property Tax $" + str(to_pay), 3)
        player.take_money(to_pay)


class GoToJail(Cell):
    """Go to Jail (#30)"""

    def action(self, player):
        player.move_to(10)
        player.in_jail = True
        log.write(player.name + " goes to jail from Go To Jail ", 3)


class Chance(Cell):
    """Chance cards"""

    def action(self, player, board):

        # Get the card
        chance_card = board.chanceCards.pop(0)

        # Actions for various cards

        # 0: Advance to St.Charles
        if chance_card == 0:
            log.write(player.name + " gets chance card: Advance to St.Charles", 3)
            if player.position >= 11:
                player.add_money(settingsSalary)
                log.write(player.name + " gets salary: $" + str(settingsSalary), 3)
            player.position = 11
            log.write(player.name + " goes to " + str(board.b[11].name), 3)
            board.action(player, player.position)

        # 1: Get Out Of Jail Free
        elif chance_card == 1:
            log.write(player.name + " gets chance card: Get Out Of Jail Free", 3)
            player.has_jail_card_chance = True

        # 2: Take a ride on the Reading
        elif chance_card == 2:
            log.write(player.name + " gets chance card: Take a ride on the Reading", 3)
            if player.position >= 5:
                player.add_money(settingsSalary)
                log.write(player.name + " gets salary: $" + str(settingsSalary), 3)
            player.position = 5
            log.write(player.name + " goes to " + str(board.b[player.position].name), 3)
            board.action(player, player.position)

        # 3: Move to the nearest railroad and pay double
        elif chance_card == 3:
            log.write(
                player.name
                + " gets chance card: Move to the nearest railroad and pay double",
                3,
            )
            # Don't get salary, even if you pass GO (card doesnt say to do it)
            # Dont move is already on a rail.
            # Also, I assume advance means you should go to the nearest in front of you, not behind
            player.position = (
                (player.position + 4) // 10 * 10 + 5
            ) % 40  # nearest railroad
            # twice for double rent, if needed
            board.action(player, player.position, special="from_chance")

        # 4: Advance to Illinois Avenue
        elif chance_card == 4:
            log.write(player.name + " gets chance card: Advance to Illinois Avenue", 3)
            if player.position >= 24:
                player.add_money(settingsSalary)
                log.write(player.name + " gets salary: $" + str(settingsSalary), 3)
            player.position = 24
            log.write(player.name + " goes to " + str(board.b[player.position].name), 3)
            board.action(player, player.position)

        # 5: Make general repairs to your property
        elif chance_card == 5:
            log.write(
                player.name
                + " gets chance card: Make general repairs to your property",
                3,
            )
            player.make_repairs(board, "chance")

        # 6: Advance to GO
        elif chance_card == 6:
            log.write(player.name + " gets chance card: Advance to GO", 3)
            player.add_money(settingsSalary)
            log.write(player.name + " gets salary: $" + str(settingsSalary), 3)
            player.position = 0
            log.write(player.name + " goes to " + str(board.b[player.position].name), 3)

        # 7: Bank pays you dividend $50
        elif chance_card == 7:
            log.write(player.name + " gets chance card: Bank pays you dividend $50", 3)
            player.add_money(50)

        # 8: Pay poor tax $15
        elif chance_card == 8:
            log.write(player.name + " gets chance card: Pay poor tax $15", 3)
            player.take_money(15)

        # 9: Advance to the nearest Utility and pay 10x dice
        elif chance_card == 9:
            log.write(
                player.name
                + " gets chance card: Advance to the nearest Utility and pay 10x dice",
                3,
            )
            if 12 < player.position <= 28:
                player.position = 28
            else:
                player.position = 12
            board.action(player, player.position, special="from_chance")

        # 10: Go Directly to Jail
        elif chance_card == 10:
            log.write(player.name + " gets chance card: Go Directly to Jail", 3)
            player.move_to(10)
            player.in_jail = True
            log.write(player.name + " goes to jail on Chance card", 3)

        # 11: You've been elected chairman. Pay each player $50
        elif chance_card == 11:
            log.write(
                player.name
                + " gets chance card: You've been elected chairman. Pay each player $50",
                3,
            )
            for other_player in board.players:
                if other_player != player and not other_player.is_bankrupt:
                    player.take_money(50)
                    other_player.add_money(50)

        # 12: Advance to BoardWalk
        elif chance_card == 12:
            log.write(player.name + " gets chance card: Advance to BoardWalk", 3)
            player.position = 39
            log.write(player.name + " goes to " + str(board.b[player.position].name), 3)
            board.action(player, player.position)

        # 13: Go back 3 spaces
        elif chance_card == 13:
            log.write(player.name + " gets chance card: Go back 3 spaces", 3)
            player.position -= 3
            log.write(player.name + " goes to " + str(board.b[player.position].name), 3)
            board.action(player, player.position)

        # 14: Your building loan matures. Receive $150.
        elif chance_card == 14:
            log.write(
                player.name
                + " gets chance card: Your building loan matures. Receive $150",
                3,
            )
            player.add_money(150)

        # 15: You have won a crossword competition. Collect $100
        elif chance_card == 15:
            log.write(
                player.name
                + " gets chance card: You have won a crossword competition. Collect $100",
                3,
            )
            player.add_money(100)

        # Put the card back
        if chance_card != 1:  # except GOOJF card
            board.chanceCards.append(chance_card)


class Community(Cell):
    """Community Chest cards"""

    def action(self, player, board):

        # Get the card
        community_card = board.communityCards.pop(0)

        # Actions for various cards

        # 0: Pay school tax $150
        if community_card == 0:
            log.write(player.name + " gets community card: Pay school tax $150", 3)
            player.take_money(150)

        # 1: Opera night: collect $50 from each player
        if community_card == 1:
            log.write(player.name + " Opera night: collect $50 from each player", 3)
            for other_player in board.players:
                if other_player != player and not other_player.is_bankrupt:
                    player.add_money(50)
                    other_player.take_money(50)
                    other_player.check_bankruptcy(board)

        # 2: You inherit $100
        if community_card == 2:
            log.write(player.name + " gets community card: You inherit $100", 3)
            player.add_money(100)

        # 3: Pay hospital $100
        if community_card == 3:
            log.write(player.name + " gets community card: Pay hospital $100", 3)
            player.take_money(100)

        # 4: Income tax refund $20
        if community_card == 4:
            log.write(player.name + " gets community card: Income tax refund $20", 3)
            player.add_money(20)

        # 5: Go Directly to Jail
        elif community_card == 5:
            log.write(player.name + " gets community card: Go Directly to Jail", 3)
            player.move_to(10)
            player.in_jail = True
            log.write(player.name + " goes to jail on Community card", 3)

        # 6: Get Out Of Jail Free
        elif community_card == 6:
            log.write(player.name + " gets community card: Get Out Of Jail Free", 3)
            player.has_jail_card_community = True

        # 7: Second prize in beauty contest $10
        if community_card == 7:
            log.write(
                player.name
                + " gets community card: Second prize in beauty contest $10",
                3,
            )
            player.add_money(10)

        # 8: You are assigned for street repairs
        elif community_card == 8:
            log.write(
                player.name
                + " gets community card: You are assigned for street repairs",
                3,
            )
            player.make_repairs(board, "community")

        # 9: Bank error in your favour: $200
        if community_card == 9:
            log.write(
                player.name + " gets community card: Bank error in your favour: $200", 3
            )
            player.add_money(200)

        # 10: Advance to GO
        elif community_card == 10:
            log.write(player.name + " gets community card: Advance to GO", 3)
            player.add_money(settingsSalary)
            log.write(player.name + " gets salary: $" + str(settingsSalary), 3)
            player.position = 0
            log.write(player.name + " goes to " + str(board.b[player.position].name), 3)

        # 11: X-Mas fund matured: $100
        if community_card == 11:
            log.write(player.name + " gets community card: X-Mas fund matured: $100", 3)
            player.add_money(100)

        # 12: Doctor's fee $50
        if community_card == 12:
            log.write(player.name + " gets community card: Doctor's fee $50", 3)
            player.take_money(50)

        # 13: From sale of stock you get $45
        if community_card == 13:
            log.write(
                player.name + " gets community card: From sale of stock you get $45", 3
            )
            player.add_money(45)

        # 14: Receive for services $25
        if community_card == 14:
            log.write(player.name + " gets community card: Receive for services $25", 3)
            player.add_money(25)

        # 15: Life insurance matures, collect $100
        if community_card == 15:
            log.write(
                player.name
                + " gets community card: Life insurance matures, collect $100",
                3,
            )
            player.add_money(100)

        # Put the card back
        if community_card != 6:  # except GOOJF card
            board.communityCards.append(community_card)


class Property(Cell):
    """Property Class (for Properties, Rails, Utilities)"""

    def __init__(
        self,
        name,
        cost_base,
        rent_base,
        cost_house,
        rent_house,
        group: util.PropertyGroup,
    ):
        Cell.__init__(self, name)
        self.cost_base = cost_base
        self.rent_base = rent_base
        self.cost_house = cost_house
        self.rent_house = rent_house
        self.group = group
        self.owner = None
        self.is_mortgaged = False
        self.is_monopoly = False
        self.hasHouses = 0

    def action(self, player, rent, board):
        """Player ended on a property"""

        # it's their property or mortgaged - do nothing
        if self.owner == player or self.is_mortgaged:
            log.write("No rent this time", 3)
            return

        # Property up for sale
        elif self.owner is None:
            if player.wants_to_buy(self.cost_base, self.group):
                log.write(
                    player.name
                    + " buys property "
                    + self.name
                    + " for $"
                    + str(self.cost_base),
                    3,
                )
                player.take_money(self.cost_base)
                self.owner = player
                board.recalculate_after_property_change()
            else:
                pass  # auction here
                log.write(player.name + " didn't buy the property.", 3)
                # Auction here
                # Decided not to implement it...
            return

        # someone else's property - pay the rent
        else:
            player.take_money(rent)
            self.owner.add_money(rent)
            log.write(
                player.name + " pays the rent $" + str(rent) + " to " + self.owner.name,
                3,
            )

    # mortgage the plot to the player / or sell the house
    def mortgage(self, player, board):
        """Sell hotel"""
        if self.hasHouses == 5:
            player.add_money(self.cost_house * 5 // 2)
            self.hasHouses = 0
            board.nHotels -= 1
            log.write(player.name + " sells hotel on " + self.name, 3)
        # Sell one house
        elif self.hasHouses > 0:
            player.add_money(self.cost_house // 2)
            self.hasHouses -= 1
            board.nHouses -= 1
            log.write(player.name + " sells house on " + self.name, 3)
        # Mortgage
        else:
            self.is_mortgaged = True
            player.add_money(self.cost_base // 2)
            # log name of the plot and money player need to pay to get it back
            player.has_mortgages.append((self, int((self.cost_base // 2) * 1.1)))
            log.write(player.name + " mortgages " + self.name, 3)

    # unmortgage thr plot

    def unmortgage(self, player):
        # print (player.hasMortgages)
        for mortgage in player.has_mortgages:
            if mortgage[0] == self:
                this_mortgage = mortgage
        self.is_mortgaged = False
        player.take_money(this_mortgage[1])
        player.has_mortgages.remove(this_mortgage)
        log.write(player.name + " unmortgages " + self.name, 3)


class Board:
    def __init__(self, players):
        """
        Board is a data for plots

        name: does not really matter, just convenience
        base_cost: used when buying plot, mortgage
        base_rent: used for rent and monopoly rent
         (for utilities and rail - in calculateRent method)
        house_cost: price of one house (or a hotel)
        house_rent: list of rent price with 1,2,3,4 houses and a hotel
        group: used to determine monopoly
        """

        # I know it is messy, but I need this for players to pay each other
        self.players = players

        self.b = []
        # 0-4
        self.b.append(Cell("Go"))
        self.b.append(
            Property(
                "A1 Mediterranean Avenue",
                60,
                2,
                50,
                (10, 30, 90, 160, 250),
                util.PropertyGroup.BROWN,
            )
        )
        self.b.append(Community("Community Chest"))
        self.b.append(
            Property(
                "A2 Baltic Avenue",
                60,
                4,
                50,
                (20, 60, 180, 320, 450),
                util.PropertyGroup.BROWN,
            )
        )
        self.b.append(PropertyTax("Property Tax"))
        # 5-9
        self.b.append(
            Property(
                "R1 Reading railroad",
                200,
                0,
                0,
                (0, 0, 0, 0, 0),
                util.PropertyGroup.RAILROAD,
            )
        )
        self.b.append(
            Property(
                "B1 Oriental Avenue",
                100,
                6,
                50,
                (30, 90, 270, 400, 550),
                util.PropertyGroup.LIGHT_BLUE,
            )
        )
        self.b.append(Chance("Chance"))
        self.b.append(
            Property(
                "B2 Vermont Avenue",
                100,
                6,
                50,
                (30, 90, 270, 400, 550),
                util.PropertyGroup.LIGHT_BLUE,
            )
        )
        self.b.append(
            Property(
                "B3 Connecticut Avenue",
                120,
                8,
                50,
                (40, 100, 300, 450, 600),
                util.PropertyGroup.LIGHT_BLUE,
            )
        )
        # 10-14
        self.b.append(Cell("Prison"))
        self.b.append(
            Property(
                "C1 St.Charles Place",
                140,
                10,
                100,
                (50, 150, 450, 625, 750),
                util.PropertyGroup.PINK,
            )
        )
        self.b.append(
            Property(
                "U1 Electric Company",
                150,
                0,
                0,
                (0, 0, 0, 0, 0),
                util.PropertyGroup.UTILITY,
            )
        )
        self.b.append(
            Property(
                "C2 States Avenue",
                140,
                10,
                100,
                (50, 150, 450, 625, 750),
                util.PropertyGroup.PINK,
            )
        )
        self.b.append(
            Property(
                "C3 Virginia Avenue",
                160,
                12,
                100,
                (60, 180, 500, 700, 900),
                util.PropertyGroup.PINK,
            )
        )
        # 15-19
        self.b.append(
            Property(
                "R2 Pennsylvania Railroad",
                200,
                0,
                0,
                (0, 0, 0, 0, 0),
                util.PropertyGroup.RAILROAD,
            )
        )
        self.b.append(
            Property(
                "D1 St.James Place",
                180,
                14,
                100,
                (70, 200, 550, 700, 950),
                util.PropertyGroup.ORANGE,
            )
        )
        self.b.append(Community("Community Chest"))
        self.b.append(
            Property(
                "D2 Tennessee Avenue",
                180,
                14,
                100,
                (70, 200, 550, 700, 950),
                util.PropertyGroup.ORANGE,
            )
        )
        self.b.append(
            Property(
                "D3 New York Avenue",
                200,
                16,
                100,
                (80, 220, 600, 800, 1000),
                util.PropertyGroup.ORANGE,
            )
        )
        # 20-24
        self.b.append(Cell("Free Parking"))
        self.b.append(
            Property(
                "E1 Kentucky Avenue",
                220,
                18,
                150,
                (90, 250, 700, 875, 1050),
                util.PropertyGroup.RED,
            )
        )
        self.b.append(Chance("Chance"))
        self.b.append(
            Property(
                "E2 Indiana Avenue",
                220,
                18,
                150,
                (90, 250, 700, 875, 1050),
                util.PropertyGroup.RED,
            )
        )
        self.b.append(
            Property(
                "E3 Illinois Avenue",
                240,
                20,
                150,
                (100, 300, 750, 925, 1100),
                util.PropertyGroup.RED,
            )
        )
        # 25-29
        self.b.append(
            Property(
                "R3 BnO Railroad",
                200,
                0,
                0,
                (0, 0, 0, 0, 0),
                util.PropertyGroup.RAILROAD,
            )
        )
        self.b.append(
            Property(
                "F1 Atlantic Avenue",
                260,
                22,
                150,
                (110, 330, 800, 975, 1150),
                util.PropertyGroup.YELLOW,
            )
        )
        self.b.append(
            Property(
                "F2 Ventinor Avenue",
                260,
                22,
                150,
                (110, 330, 800, 975, 1150),
                util.PropertyGroup.YELLOW,
            )
        )
        self.b.append(
            Property(
                "U2 Waterworks", 150, 0, 0, (0, 0, 0, 0, 0), util.PropertyGroup.UTILITY
            )
        )
        self.b.append(
            Property(
                "F3 Martin Gardens",
                280,
                24,
                150,
                (120, 360, 850, 1025, 1200),
                util.PropertyGroup.YELLOW,
            )
        )
        # 30-34
        self.b.append(GoToJail("Go To Jail"))
        self.b.append(
            Property(
                "G1 Pacific Avenue",
                300,
                26,
                200,
                (130, 390, 900, 1100, 1275),
                util.PropertyGroup.GREEN,
            )
        )
        self.b.append(
            Property(
                "G2 North Carolina Avenue",
                300,
                26,
                200,
                (130, 390, 900, 1100, 1275),
                util.PropertyGroup.GREEN,
            )
        )
        self.b.append(Community("Community Chest"))
        self.b.append(
            Property(
                "G3 Pennsylvania Avenue",
                320,
                28,
                200,
                (150, 450, 100, 1200, 1400),
                util.PropertyGroup.GREEN,
            )
        )
        # 35-39
        self.b.append(
            Property(
                "R4 Short Line", 200, 0, 0, (0, 0, 0, 0, 0), util.PropertyGroup.RAILROAD
            )
        )
        self.b.append(Chance("Chance"))
        self.b.append(
            Property(
                "H1 Park Place",
                350,
                35,
                200,
                (175, 500, 1100, 1300, 1500),
                util.PropertyGroup.INDIGO,
            )
        )
        self.b.append(LuxuryTax("Luxury Tax"))
        self.b.append(
            Property(
                "H2 Boardwalk",
                400,
                50,
                200,
                (200, 600, 1400, 1700, 2000),
                util.PropertyGroup.INDIGO,
            )
        )

        # number of built houses and hotels (to limit when needed)
        self.nHouses = 0
        self.nHotels = 0

        # Chance
        self.chanceCards = [i for i in range(16)]
        random_shuffle.shuffle(self.chanceCards)

        # Community Chest
        self.communityCards = [i for i in range(16)]
        random_shuffle.shuffle(self.communityCards)

    # Does the board have at least one monopoly
    # Used for statistics
    def has_monopoly(self):
        for i in range(len(self.b)):
            if self.b[i].is_monopoly:
                return True
        return False

    # Count the number of rails of the same owner as "position"
    # Used in rent calculations
    def count_rails(self, position):
        railcount = 0
        this_owner = self.b[position].owner
        if this_owner:
            for plot in self.b:
                if (
                    type(plot) == Property
                    and plot.group == util.PropertyGroup.RAILROAD
                    and plot.owner == this_owner
                ):
                    railcount += 1
        return railcount

    # What is the rent of plot "position"
    # Takes into account utilities, rails, monopoly

    def calculate_rent(self, position, dice, special=""):
        if type(self.b[position]) == Property:
            rent = 0
            dice_value = sum(dice)

            # utility
            if self.b[position].group == util.PropertyGroup.UTILITY:
                if self.b[position].is_monopoly or special == "from_chance":
                    rent = dice_value * 10
                else:
                    rent = dice_value * 4

            # rail
            elif self.b[position].group == util.PropertyGroup.RAILROAD:
                rails = self.count_rails(position)
                rent = 25 * rails
                if special == "from_chance":
                    rent *= 2

            # usual property
            else:
                if self.b[position].hasHouses > 0:
                    if self.b[position].hasHouses - 1 > 5:
                        print(self.b[position].hasHouses - 1)
                        print(position)
                        self.print_map()
                    rent = self.b[position].rent_house[self.b[position].hasHouses - 1]
                elif self.b[position].is_monopoly:
                    rent = 2 * self.b[position].rent_base
                else:
                    rent = self.b[position].rent_base
        return rent

    # What % of plots of this group does player have
    # Used in calculation of least valuable property
    def share_of_group(self, group, player):
        total = 0
        owned = 0
        for plot in self.b:
            if type(plot) == Property and plot.group == group:
                total += 1
                if plot.owner == player:
                    owned += 1
        return owned / total

    # What is the least valuable property / building
    # Used to pick what to mortgage / sell buildings

    def choose_property_to_mortgage_downgrade(self, player):
        # list all the items this player has:
        owned_stuff = []
        for i in range(len(self.b)):
            plot = self.b[i]
            if (
                type(plot) == Property
                and not plot.is_mortgaged
                and plot.owner == player
            ):
                owned_stuff.append(
                    (
                        i,
                        plot.cost_base,
                        self.b[i].is_monopoly,
                        self.share_of_group(plot.group, player),
                        plot.hasHouses,
                    )
                )
        if len(owned_stuff) == 0:
            return False
        # first to sel/mortgage are: least "monopolistic"; most houses
        owned_stuff.sort(key=lambda x: (x[3], -x[4]))
        return owned_stuff[0][0]

    # Chose Property to build the next house/hotel according to its value and available money
    def list_property_to_build(self, player):
        # list all the items this player could built on:
        to_build_stuff = []
        # smaller level of improvement in the group (to prevent unequal improvement)
        min_in_group = {}
        # start with listing all their monopolies
        for i in range(len(self.b)):
            plot = self.b[i]
            if (
                type(plot) == Property
                and self.b[i].is_monopoly
                and plot.owner == player
                and plot.group != util.PropertyGroup.RAILROAD
                and plot.group != util.PropertyGroup.UTILITY
                and plot.hasHouses < 5
            ):
                # limit max houses experiment
                if not (player.name == "exp" and expHouseBuildLimit == plot.hasHouses):
                    to_build_stuff.append(
                        (
                            i,
                            plot.name,
                            plot.group,
                            plot.hasHouses,
                            plot.cost_house,
                            plot.cost_base,
                        )
                    )
                    if plot.group in min_in_group:
                        min_in_group[plot.group] = min(
                            plot.hasHouses, min_in_group[plot.group]
                        )
                    else:
                        min_in_group[plot.group] = plot.hasHouses
        if len(to_build_stuff) == 0:
            return []

        # remove those that has more houses than other plots in monopoly (to ensure gradual development)
        to_build_stuff.sort(key=lambda x: (x[2].value, x[3]))
        for i in range(len(to_build_stuff) - 1, -1, -1):
            # if it has more houses than minimum in that group, remove
            if to_build_stuff[i][3] > min_in_group[to_build_stuff[i][2]]:
                if not settingsAllowUnEqualDevelopment:
                    to_build_stuff.pop(i)

        # sort by house price and base
        if behaveBuildRandom:
            random_shuffle.shuffle(to_build_stuff)
        elif behaveBuildCheapest:
            to_build_stuff.sort(key=lambda x: (-x[4], -x[5]))
        else:
            to_build_stuff.sort(key=lambda x: (x[4], x[5]))

        if expBuildCheapest and player.name == "exp":
            to_build_stuff.sort(key=lambda x: (-x[4], -x[5]))
        if expBuildExpensive and player.name == "exp":
            to_build_stuff.sort(key=lambda x: (x[4], x[5]))

        if expBuildThree and player.name == "exp":
            has_less_than_three = False
            for i in range(len(to_build_stuff)):
                if to_build_stuff[i][3] < 3:
                    has_less_than_three = True
            if has_less_than_three:
                for i in range(len(to_build_stuff) - 1, -1, -1):
                    if to_build_stuff[i][3] >= 3:
                        del to_build_stuff[i]
            to_build_stuff.sort(key=lambda x: (x[3], x[4], x[5]))
            # if len(to_build_stuff)>3:
            #    print (to_build_stuff)

        # if len(to_build_stuff)>5:
        # print (to_build_stuff)
        return to_build_stuff

    @staticmethod
    def choose_property_to_build(player, available_money):
        for i in range(len(player.plots_to_build) - 1, -1, -1):
            if player.plots_to_build[i][4] <= available_money:
                return player.plots_to_build[i][0]
        return False

    # Build one house/hotel with available money
    # return True if built, so this function will be called again

    def improve_property(self, player, available_money):
        property_to_improve = self.choose_property_to_build(player, available_money)
        if type(property_to_improve) == bool and not property_to_improve:
            return False

        # Check if we reached the limit of available Houses/Hotels
        this_is_hotel = True if self.b[property_to_improve].hasHouses == 4 else False
        if this_is_hotel:
            if self.nHotels == settingHotelLimit:
                log.write("reached hotel limit", 3)
                return False
        else:
            if self.nHouses == settingHouseLimit:
                log.write("reached house limit", 3)
                return False

        # add a building
        self.b[property_to_improve].hasHouses += 1
        # add to the counter
        if this_is_hotel:
            self.nHotels += 1
            self.nHouses -= 4
        else:
            self.nHouses += 1

        log.write(
            player.name
            + " builds house N"
            + str(self.b[property_to_improve].hasHouses)
            + " on "
            + self.b[property_to_improve].name,
            3,
        )
        player.take_money(self.b[property_to_improve].cost_house)
        player.plots_to_build = self.list_property_to_build(player)
        return True

    # When player is bankrupt - return all their property to market

    def sell_all(self, player):
        for plot in self.b:
            if type(plot) == Property and plot.owner == player:
                plot.owner = None
                plot.is_mortgaged = False

    # Get the list of plots player would want to get
    # that is he lacks one to for a monopoly

    def get_list_of_wanted_plots(self, player):
        groups = {}
        for plot in self.b:
            if plot.group != "":
                if plot.group in groups:
                    groups[plot.group][0] += 1
                else:
                    groups[plot.group] = [1, 0]
                if plot.owner == player:
                    groups[plot.group][1] += 1
        wanted = []
        for group in groups:
            if (
                group != util.PropertyGroup.UTILITY
                and groups[group][0] - groups[group][1] == 1
            ):
                for i in range(len(self.b)):
                    if (
                        type(self.b[i]) == Property
                        and self.b[i].group == group
                        and self.b[i].owner != player
                    ):
                        wanted.append(i)
        return sorted(wanted)

    # Get the list of plots player would want to offer for trade
    # that one random plot in a group
    def get_list_of_offered_plots(self, player):
        groups = {}
        for plot in self.b:
            if plot.group != "":
                if plot.group not in groups:
                    groups[plot.group] = 0
                if plot.owner == player:
                    groups[plot.group] += 1
        offered = []
        for group in groups:
            if group != util.PropertyGroup.UTILITY and groups[group] == 1:
                for i in range(len(self.b)):
                    if (
                        type(self.b[i]) == Property
                        and self.b[i].group == group
                        and self.b[i].owner == player
                        and not self.b[i].is_mortgaged
                    ):
                        offered.append(i)
        return sorted(offered)

    # update isMonopoly status for all plots
    def check_monopolies(self):
        groups = {}
        for i in range(len(self.b)):
            plot = self.b[i]
            if type(plot) == Property:
                if plot.owner is None:
                    groups[plot.group] = False
                else:
                    if plot.group in groups:
                        if groups[plot.group] != plot.owner:
                            groups[plot.group] = False
                    else:
                        groups[plot.group] = plot.owner
        for i in range(len(self.b)):
            plot = self.b[i]
            if type(plot) == Property:
                if groups[plot.group]:
                    plot.is_monopoly = True
                else:
                    plot.is_monopoly = False

    # calculating heavy tasks that we want to do after property change:
    # list of wanted and offered properties for each player
    def recalculate_after_property_change(self):
        self.check_monopolies()
        for player in self.players:
            player.plots_wanted = self.get_list_of_wanted_plots(player)
            player.plots_offered = self.get_list_of_offered_plots(player)
            player.plots_to_build = self.list_property_to_build(player)

    # perform action for a player on a plot

    def action(self, player, position, special=""):

        # Landed on a property - calculate rent first
        if type(self.b[position]) == Property:
            # calculate the rent one would have to pay (but not pay it yet)
            rent = self.calculate_rent(position, dice=player.dice, special=special)
            # pass action to to the cell
            self.b[position].action(player, rent, self)
        # landed on a chance, pass board, to track the chance cards
        elif (
            type(self.b[position]) == Chance
            or type(self.b[position]) == Community
            or type(self.b[position]) == PropertyTax
        ):
            self.b[position].action(player, self)
        # other cells
        else:
            self.b[position].action(player)

    def print_map(self):
        for i in range(len(self.b)):
            if type(self.b[i]) == Property:
                print(
                    i,
                    self.b[i].name,
                    "houses:",
                    self.b[i].hasHouses,
                    "mortgaged:",
                    self.b[i].is_mortgaged,
                    "owner:",
                    "none" if self.b[i].owner == "" else self.b[i].owner.name,
                    "monopoly" if self.b[i].is_monopoly else "",
                )
            else:
                pass
                # print (i, type(self.b[i]))


def is_game_over(players):
    """Check if there are more then 1 player left in the game"""
    alive = 0
    for player in players:
        if not player.is_bankrupt:
            alive += 1
    if alive > 1:
        return False
    else:
        return True


# simulate one game


def build_player_list(n: int, starting_monies=[]):
    if not 1 < n <= 8:
        raise ValueError("Number of Players must be 2-8")
    n = n_players
    names = [util.fetch_player_name(i) for i in range(n)]
    if not var_starting_money:
        starting_monies = [settingStartingMoney] * n
    else:
        starting_monies = [
            var_starting_money[i % len(var_starting_money)] for i in range(n)
        ]
    players_attributes = []
    for i in range(n):
        player_attributes = (names[i], starting_monies[i])
        players_attributes.append(player_attributes)
    if shuffle_players:
        random_shuffle.shuffle(players_attributes)
    players = [Player(pa[0], pa[1]) for pa in players_attributes]
    return players


def one_game():

    # create players
    players = build_player_list(n_players)

    # create board
    game_board = Board(players)

    #  net_worth history first point
    if writeData == "net_worth":
        networthstring = ""
        for player in players:
            networthstring += str(player.net_worth(game_board))
            if player != players[-1]:
                networthstring += "\t"
        log.write(networthstring, data=True)

    # game
    for i in range(nMoves):
        if realTime:
            input("Press enter to continue")
        if is_game_over(players):
            # to track length of the game
            if writeData == "last_turn":
                log.write(str(i - 1), data=True)
            break

        log.write("TURN " + str(i + 1), 1)
        for player in players:
            if player.money > 0:
                log.write(
                    f"{f'{player.name}: ':8} ${player.money} | position:"
                    + str(player.position),
                    2,
                )

        for player in players:
            if not is_game_over(players):  # Only continue if 2 or more players
                # returns True if player has to go again
                while player.make_a_move(game_board):
                    pass

        # track net_worth history of the game
        if writeData == "net_worth":
            networthstring = ""
            for player in players:
                networthstring += str(player.net_worth(game_board))
                if player != players[-1]:
                    networthstring += "\t"
            log.write(networthstring, data=True)

    # tests
    # for player in players:
    # player.threeWayTrade(game_board)

    # return final scores
    results = [players[i].get_money() for i in range(n_players)]

    # if it is an only simulation, print map and final score
    if nSimulations == 1 and showMap:
        game_board.print_map()
    if nSimulations == 1 and showResult:
        print(results)
    return results


def run_simulation():
    """run multiple game simulations"""
    results = []

    if show_progress_bar:
        widgets = [progressbar.Percentage(), progressbar.Bar(), progressbar.ETA()]
        pbar = progressbar.ProgressBar(
            widgets=widgets, term_width=OUT_WIDTH, maxval=nSimulations
        )
        pbar.start()

    for i in range(nSimulations):

        if show_progress_bar:
            pbar.update(i + 1)

        log.write("=" * 10 + " GAME " + str(i + 1) + " " + "=" * 10 + "\n")

        # remaining players - add to the results list
        results.append(one_game())

        # write remaining players in a data log
        if writeData == "remaining_players":
            rem_players = sum([1 for r in results[-1] if r > 0])
            log.write(str(rem_players), data=True)

    if show_progress_bar:
        pbar.finish()

    return results


def analyze_results(results):
    """Analyze results"""

    remaining_players = [
        0,
    ] * n_players
    for result in results:
        alive = 0
        for score in result:
            if score >= 0:
                alive += 1
        remaining_players[alive - 1] += 1

    if showRemPlayers:
        print("Remaining:", remaining_players)


def analyze_data():

    if (
        writeData == "losers_names"
        or writeData == "experiment"
        or writeData == "remaining_players"
    ):
        groups = {}
        with open("data.txt", "r") as fs:
            for line in fs:
                item = line.strip()
                if item in groups:
                    groups[item] += 1
                else:
                    groups[item] = 1
        experiment = 0
        control = 0
        for item in sorted(groups.keys()):
            count = groups[item] / nSimulations

            if writeData == "losers_names":
                count = 1 - count
            if item == "exp":
                experiment = count
            else:
                control += count

            margin = 1.96 * math.sqrt(count * (1 - count) / nSimulations)
            print("{}: {:.1%} +- {:.1%}".format(item, count, margin))

        if experiment != 0:
            print("Exp result: {:.1%}".format(experiment - control / (n_players - 1)))

    if writeData == "net_worth":
        print("graph here")
        npdata = np.transpose(np.loadtxt("data.txt", dtype=int, delimiter="\t"))
        x = np.arange(0, max([len(d) for d in npdata]))

        plt.ioff()
        fig, ax = plt.subplots()
        for i in range(n_players):
            ax.plot(x, npdata[i], label="1")
        plt.savefig("fig" + str(time.time()) + ".png")


if __name__ == "__main__":

    print("=" * OUT_WIDTH)

    t = time.time()
    log = Log()
    print(
        "Players:",
        n_players,
        " Turns:",
        nMoves,
        " Games:",
        nSimulations,
        " Seed:",
        SEED,
    )
    results = run_simulation()
    analyze_results(results)
    log.close()
    analyze_data()
    print("Done in {:.2f}s".format(time.time() - t))
