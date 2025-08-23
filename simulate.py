#!/usr/bin/env python3
"""
Fantasy Football Draft Assistant - Simulation Module
"""

import argparse
import sys
import json
import pandas as pd
import numpy as np
from enum import IntEnum
import time

class Position(IntEnum):
    QB = 0
    RB = 1
    WR = 2
    TE = 3
    K = 4
    DST = 5

TEAM_COMPOSITION = [1, 5, 5, 1, 1, 1]

def reset_tracking_dicts(team_composition, team_rounds_picked, team_roster, num_teams, keepers_df):
    for i in range(num_teams):
        team_composition[i+1] = [0]*len(Position.__members__)
    
    for i in range(num_teams):
        team_rounds_picked[i+1] = []
    
    for i in range(num_teams):
        team_roster[i+1] = []
    
    if keepers_df is not None:
        for _, row in keepers_df.iterrows():
            team_composition[row['Team']][Position[row['Position']].value] += 1
            team_rounds_picked[row['Team']].append(row['Round'])
            team_roster[row['Team']].append(row['Player'])



def sample_discrete_pareto(alpha, size=1, x_max=15):
    """
    Sample from a discretized Pareto with x_m = 1:
    P(X=x) = (1/x)^alpha - (1/(x+1))^alpha
    
    Parameters:
        alpha (float): Pareto shape parameter (>0)
        size (int): Number of samples
        x_max (int): Maximum x value for truncation
    
    Returns:
        samples (np.ndarray): Samples from the distribution
    """
    x = np.arange(1, x_max+1, dtype=np.float64)  # 1, 2, ..., x_max
    pmf = (1 / x**alpha) - (1 / (x + 1)**alpha)
    pmf /= pmf.sum()  # Normalize to ensure sum = 1

    return np.random.choice(np.arange(1, x_max+1), size=size, p=pmf)

def generate_pick(team, draft_round, team_composition, team_rounds_picked, team_roster, player_df):
    """
    Generate a pick for a team in a given round.
    team: the team number
    draft_round: the round number
    team_composition: a dict mapping team number to a list containing the number of players drafted at each position (QB, RB, WR, TE, K, DST)
    team_rounds_picked: a dict mapping team number to a list containing the rounds picked for each team
    player_df: a pandas dataframe containing the player data

    Discretized Pareto Sampling based on available players ordered by ADP in ascending order and a given alpha
    ensure that the team has <= max number of players at each position; otherwise, re-sample
    """
    #find the next available player in the draft
    #update team_composition and team_rounds_picked
    #return the player_df after removing the player

    pos_slots_avail = np.array(TEAM_COMPOSITION) - np.array(team_composition[team])
    indices = np.where(pos_slots_avail == 0)[0]
    unavailable_positions = [Position(i).name for i in indices]
    if team_composition[team][Position.RB.value] <= 1 and team_composition[team][Position.WR.value] >= 3:
        unavailable_positions.append('WR')
    if team_composition[team][Position.RB.value] >= 3 and team_composition[team][Position.WR.value] <= 1:
        unavailable_positions.append('RB')
    
    available_players = player_df[~player_df['Position'].isin(unavailable_positions)].reset_index(drop=True)
    if draft_round <= 11:
        available_players = available_players[~available_players['Position'].isin(['DST', 'K'])].reset_index(drop=True)

    num_attempts = 0
    while True:
        if num_attempts > 1000:
                raise Exception("Failed to find a valid pick after 1000 attempts")
        alpha = 2.0
        pick = sample_discrete_pareto(alpha, size=1, x_max=15)
        num_attempts += 1
        player_row = available_players.iloc[pick-1]
        pos = player_row['Position'].item()
        rank = player_row['Rank'].item()
        if pos_slots_avail[Position[pos].value] == 0:
            continue
        else:
            team_composition[team][Position[pos].value] += 1
            team_roster[team].append(player_row['Player'].item())
            player_df = player_df.drop(player_df[(player_df['Rank'] == rank) & (player_df['Player'] == player_row['Player'].item())].index)
            break

    team_rounds_picked[team].append(draft_round)
    

    return player_df


def main():
    """Main function that runs when the script is executed directly."""
    parser = argparse.ArgumentParser(
        description="Fantasy Football Draft Assistant - Simulation Module",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # Required arguments
    parser.add_argument(
        '--num_sims',
        type=int,
        default=1000,
        help='Number of draft simulations to run (optional; default is 1000)'
    )

    parser.add_argument(
        '--num_teams',
        type=int,
        required=True,
        help='Number of teams in your league (required)'
    )
    
    parser.add_argument(
        '--pick',
        type=int,
        required=True,
        help='Your draft pick position (required); must be between 1 and num_teams (inclusive)'
    )

    parser.add_argument(
        '--draft_rounds',
        type=int,
        required=True,
        help='Number of draft rounds (required); must be between 1 and 14 (inclusive)'
    )
    
    # Optional arguments
    parser.add_argument(
        '--keepers_csv_file',
        type=str,
        required=False,
        default=None,
        help='Absolute path to a csv file of keepers for the league; the csv schema must be: \'Player (str), Position (str), Round (int), Team (int)\'. Player corresponds to the NFL player\'s name. Position is the player\'s position and must be one of: QB, RB, WR, TE, K, DST. Round is the draft round being used to keep the player. Round must be between 1 and draft_rounds (inclusive). Team is the team that the player will be kept on where Team 1 is the first team to draft and Team 2 is the second team to draft in the first round and so on. Team must be between 1 and num_teams (inclusive).'
    )
    
    parser.add_argument(
        '--adp_csv_file',
        type=str,
        required=True,
        help='Absolute path to a csv file of player data; the csv schema must be: \'Rank (int), Player (str), ADP (float), POS (str)\' where \'POS\' is one of: QB, RB, WR, TE, K, DST and \'ADP\' is the average draft position of the player; the data must be sorted by \'ADP\' in ascending order'
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    if args.num_sims <= 0:
        print("Error: num_sims must be a positive integer", file=sys.stderr)
        sys.exit(1)
    
    # Validate arguments
    if args.num_teams <= 0 or args.num_teams > 14:
        print("Error: num_teams must be a positive integer between 1 and 14 (inclusive)", file=sys.stderr)
        sys.exit(1)
    
    if args.pick <= 0 or args.pick > args.num_teams:
        print(f"Error: pick must be between 1 and {args.num_teams}", file=sys.stderr)
        sys.exit(1)

    if args.draft_rounds <= 0 or args.draft_rounds > 14:
        print("Error: draft_rounds must be a positive integer between 1 and 14 (inclusive)", file=sys.stderr)
        sys.exit(1)


    # Load Keepers CSV data
    keepers_df = None
    if args.keepers_csv_file is not None:
        try:
            keepers_df = pd.read_csv(args.keepers_csv_file, header=0, index_col=False)
        except Exception as e:
            print(f"Error reading in keepers csv file: {e}", file=sys.stderr)
            sys.exit(1)
        
        if not (keepers_df.columns == ['Player', 'Position', 'Round', 'Team']).all():
            print("Error: keepers_data must have the columns: 'Player', 'POS', 'Round', 'Team'", file=sys.stderr)
            sys.exit(1)
        
        if not keepers_df['Position'].isin(Position.__members__).all():
            print("Error: Position must be one of: QB, RB, WR, TE, K, DST", file=sys.stderr)
            sys.exit(1)
        
        if not keepers_df['Round'].between(1, args.draft_rounds).all():
            print("Error: Round must be between 1 and draft_rounds (inclusive)", file=sys.stderr)
            sys.exit(1)
        
        if not keepers_df['Team'].between(1, args.num_teams).all():
            print("Error: Team must be between 1 and num_teams (inclusive)", file=sys.stderr)
            sys.exit(1)
        
        if keepers_df['Player'].dtype != 'object':
            print("Error: Player column must be string type", file=sys.stderr)
            sys.exit(1)
  

    # Load ADP CSV data
    try:
        original_player_df = pd.read_csv(args.adp_csv_file, header=0, index_col=False)
    except Exception as e:
        print(f"Error reading in CSV data of the players: {e}", file=sys.stderr)
        sys.exit(1)
    
    if not (original_player_df.columns == ['Rank', 'Player', 'ADP', 'Position']).all():
        print("Error: adp_data must have the columns: 'Rank', 'Player', 'ADP', 'Position'", file=sys.stderr)
        sys.exit(1)
    
    if not original_player_df['Position'].isin(Position.__members__).all():
        print("Error: Position must be one of: QB, RB, WR, TE, K, DST", file=sys.stderr)
        sys.exit(1)
    
    if original_player_df['ADP'].dtype != 'float64':
        print("Error: ADP column must be float type", file=sys.stderr)
        sys.exit(1)

    if not pd.api.types.is_integer_dtype(original_player_df['Rank']):
        print("Error: Rank column must be integer type", file=sys.stderr)
        sys.exit(1)

    if original_player_df['Player'].dtype != 'object':
        print("Error: Player column must be string type", file=sys.stderr)
        sys.exit(1)

    team_composition = {} #maps team number to a list contaiing the number of players drafted at each position (QB, RB, WR, TE, K, DST)    
    team_rounds_picked = {} #maps team number to a list containing the rounds picked for each team
    team_roster = {} #maps team number to a list containing the players drafted for each team

    available_players_tracking = {}
    for draft_round in range(1, 15):
        available_players_tracking[draft_round] = {}

    # Simulate draft
    for sim in range(args.num_sims):     
        # get CSV data of players fresh for each simulation and reset tracking dicts
        player_df = original_player_df.copy()
        reset_tracking_dicts(team_composition, team_rounds_picked, team_roster, args.num_teams, keepers_df)
        for draft_round in range(1, 15):
            for team_pos_in_round in range(1, args.num_teams+1):

                # Snake draft
                if draft_round % 2 == 0:
                    team = args.num_teams + 1 - team_pos_in_round
                else:
                    team = team_pos_in_round

                if draft_round in team_rounds_picked[team]:
                    #keeper used
                    continue

                if team == args.pick:
                    #your pick
                    if len(player_df) >= 10:
                        pos_slots_avail = np.array(TEAM_COMPOSITION) - np.array(team_composition[team])
                        indices = np.where(pos_slots_avail == 0)[0]
                        unavailable_positions = [Position(i).name for i in indices]
                        if team_composition[team][Position.RB.value] <= 1 and team_composition[team][Position.WR.value] >= 3:
                            unavailable_positions.append('WR')
                        if team_composition[team][Position.RB.value] >= 3 and team_composition[team][Position.WR.value] <= 1:
                            unavailable_positions.append('RB')
                        
                        available_players = player_df[~player_df['Position'].isin(unavailable_positions)].reset_index(drop=True)
                        if draft_round <= 11:
                            available_players = available_players[~available_players['Position'].isin(['DST', 'K'])].reset_index(drop=True)
                        top_10_players = available_players.head(10)
                        for _, player_row in top_10_players.iterrows():
                            player_name = player_row['Player']
                            if player_name in available_players_tracking[draft_round]:
                                available_players_tracking[draft_round][player_name] += 1
                            else:
                                available_players_tracking[draft_round][player_name] = 1
                    
                    player_df = generate_pick(team, draft_round, team_composition, team_rounds_picked, team_roster, player_df)
                    continue
                else:
                    #someone else's pick
                    player_df = generate_pick(team, draft_round, team_composition, team_rounds_picked, team_roster, player_df)
                    continue
    

    for draft_round in range(1, 15):
        sorted_dict = dict(sorted(available_players_tracking[draft_round].items(), key=lambda item: item[1], reverse=True))
        print(f"Most Likely Top 10 Players Available in Round {draft_round}:")
        for player, count in list(sorted_dict.items())[:10]:
            print(f"{player}")
        print('--------------------------------')
        print("\n")

if __name__ == "__main__":
    start_time = time.time()
    main()
    end_time = time.time()
    print(f"Time taken: {end_time - start_time} seconds")
