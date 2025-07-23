import catanatron

def main():
    game = catanatron.Game()
    game.add_player(catanatron.Player('Player 1', catanatron.HumanAgent()))
    game.add_player(catanatron.Player('Player 2', catanatron.GreedyAgent()))
    game.add_player(catanatron.Player('Player 3', catanatron.RandomAgent()))
    game.add_player(catanatron.Player('Player 4', catanatron.RandomAgent()))    
    game.start()
    while not game.is_game_over():
        current_player = game.get_current_player()
        available_actions = current_player.agent.available_actions(game)
        action = current_player.agent.choose_action(game, available_actions)
        if action:
            game.take_action(action)
    print(game.get_scores())
    return game.get_scores() 

if __name__ == "__main__":
    main()
