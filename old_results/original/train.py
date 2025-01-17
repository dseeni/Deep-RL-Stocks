import gym
from gym import spaces
import pandas as pd
import numpy as np
from tqdm import tqdm
from model import TD3, ReplayBuffer
import random
import re
import datetime
import utils
import os.path

NUMBER_OF_ITERATIONS = 50000
MAX_LIMIT = 10
START_TIMESTEPS = 2500
BATCH_SIZE = 128
STD_GAUSSIAN_EXPLORATION_NOISE = 0.1


class StockEnv(gym.Env):
    """
    The current environment of the agent.

    The environment keeps track of where the agent is after taking action a in 
    state s.
    """

    def __init__(
        self,
        stock_names,
        start_date,
        end_date,
        starting_amount_lower=10000,
        starting_amount_upper=50000,
        random_start=False,
    ):
        """
        Initializes the environment.
        
        Parameter stock_name: the name of the stock for this environment.
        Precondition: stock_name must be a str of a stock (or etf)'s ticker

        Parameter start_date: the starting date of this environment.
        Precondition: start_date must be a string in this format: YYYY-DD-MM

        Parameter end_date: the ending date of this environment.
        Precondition: end_date must be a string in this format: YYYY-DD-MM and 
                    end_date must be after start_date
        """
        super(StockEnv, self).__init__()
        self.random_start = random_start
        self.dataframes = dict()
        if type(stock_names) == str:
            stock_names = [stock_names]
        for stock_name in stock_names:
            filename = f"data/price_data/{stock_name}.csv"
            try:
                self.dataframes[stock_name] = pd.read_csv(filename, index_col="Date")
            except:
                raise AssertionError(stock_name + " is not a stock or ETF.")
        self.number_of_stocks = len(stock_names)
        self.stock_names = stock_names
        self.initialize_date(start_date, end_date), "Date preconditions failed"
        self.starting_amount_lower = starting_amount_lower
        self.starting_amount_upper = starting_amount_upper
        self.starting_amount = self.starting_amount_upper
        self.reset()

        self.action_space = spaces.Box(
            low=-MAX_LIMIT, high=MAX_LIMIT, shape=(self.number_of_stocks,), dtype=np.int
        )

    def calculate_reward(self, holdings, remaining_money, stock_prices_new):
        r = (
            remaining_money
            + np.sum(holdings * (stock_prices_new))
            - self.starting_amount
        )
        return r

    def step(self, action):
        """
        Takes action in the current state to get to the next state

        Returns an array [new_state, reward, done] where:
            - new_state (State object): state after taking action in the current state
            - reward (float): reward for taking action in the current state 
            - done (boolean): whether or not the run is done 
        """

        stock_prices_old = self.get_stock_prices()
        # perform action: if buying, add positions. if selling, subtract positions.
        # change buying power
        holdings, remaining_money = self.get_new_holdings(action, stock_prices_old)
        self.increment_date()
        stock_prices_new = self.get_stock_prices()
     
        new_state = np.concatenate([
            np.array([remaining_money]), holdings, stock_prices_new
        ])  

        reward = self.calculate_reward(holdings, remaining_money, stock_prices_new)
        self.state = new_state
        return self.state, reward, self.is_done()
        
    def get_holdings(self):
        """
        Returns: the current holdings
        """
        return self.state[1:1+self.number_of_stocks]

    def get_new_holdings(self, action, stock_prices):
        """
        Gets the new holdingd after taking action
        """
        old_holdings = self.state[1 : 1 + self.number_of_stocks]
        current_cash = self.state[0]
        new_holdings = []
        for a, holding, price in zip(action, old_holdings, stock_prices):
            if current_cash - (a * price) >= 0 and holding + a >= 0:
                new_holdings.append(max(0, holding + a))
                current_cash -= a * price
            else:
                new_holdings.append(holding)
        return np.array(new_holdings), current_cash

    def increment_date(self):
        """
        Increments the date by one epoch
        """
        incr = 1
        start_arr = list(map(lambda x: int(x), re.split(r"[\-]", self.start_date)))
        date_obj = datetime.date(start_arr[2], start_arr[0], start_arr[1])
        s = self.stock_names[0]
        adjusted_date = str(date_obj + datetime.timedelta((self.epochs + incr) // 2))
        while not (
            adjusted_date
            in self.dataframes[s].index
        ):
            incr += 1
            adjusted_date = str(date_obj + datetime.timedelta((self.epochs + incr) // 2))
            if incr >= 20:
                raise Exception(f"{adjusted_date} is out of range")
        self.epochs += incr

    def is_done(self):
        """
        Returns: True if the episode is done. False otherwise
        """
        return self.epochs >= self.max_epochs 

    def reset(self):
        """
        Resets the environment to a random date in the first 33% of the range 
        with a random amount of positions and random amount of buying power
        """
        if self.random_start:
            starting_money = [random.randint(
                self.starting_amount_lower, self.starting_amount_upper
            )]
            starting_shares = [
                random.randint(0, 10) for _ in range(self.number_of_stocks)
            ]
        else:
            starting_money = [self.starting_amount_upper]
            starting_shares = [0 for _ in range(self.number_of_stocks)]
        starting_money = np.array(starting_money)
        starting_shares = np.array(starting_shares)
        self.initialize_starting_epoch(self.start_date, self.end_date)

        stock_prices = self.get_stock_prices()        
        self.state = np.concatenate([
            starting_money, starting_shares, self.get_stock_prices()
        ])
        self.starting_amount = self.calculate_portfolio_value()
        return self.state

    def get_stock_prices(self):
        """
        Gets the current stock price at this epoch
        """
        current_date, current_time = self.get_date_and_time()
        result = []
        for stock in self.stock_names:
            price = self.dataframes[stock].loc[current_date][current_time]
            result.append(price)
        return np.array(result)

    def get_date_and_time(self):
        """
        Gets current date and time
        """
        time = "Open" if self.epochs % 2 == 0 else "Close"
        start_arr = list(map(lambda x: int(x), re.split(r"[\-]", self.start_date)))
        date_obj = datetime.date(
            start_arr[2], start_arr[0], start_arr[1]
        ) + datetime.timedelta(self.epochs // 2)
        return str(date_obj), time

    def calculate_portfolio_value(self):
        """
        Calculates the current portfolio value
        """
        return self.state[0] + np.sum(
            self.state[1 : 1 + self.number_of_stocks]
            * self.state[1 + self.number_of_stocks : 1 + 2 * self.number_of_stocks]
        )

    def initialize_date(self, start_date, end_date):
        """
        Returns: True if start_date and end_date are in the right format.
                False otherwise
        """
        start_arr = re.split(r"[\-]", start_date)
        end_arr = re.split(r"[\-]", end_date)
        date_is_valid = True
        for x, y in zip(start_arr, end_arr):
            date_is_valid = x.isdigit() and y.isdigit() and date_is_valid
            if date_is_valid:
                date_is_valid = date_is_valid and int(x) > 0 and int(y) > 0
            else:
                return date_is_valid
        date1 = [int(x) for x in re.split(r"[\-]", start_date)]
        date2 = [int(x) for x in re.split(r"[\-]", end_date)]
        date1_obj = datetime.date(date1[2], date1[0], date1[1])
        date2_obj = datetime.date(date2[2], date2[0], date2[1])
        epochs = (date2_obj - date1_obj).days
        if not (date_is_valid and epochs >= 0):
            raise ValueError("Date is not valid")
        self.max_epochs = epochs * 2
        self.start_date = start_date
        self.end_date = end_date

    def initialize_starting_epoch(self, start_date, end_date):
        """
        Gets the starting epoch of a cycle
        """
        if self.random_start:
            date1 = [int(x) for x in re.split(r"[\-]", start_date)]
            date2 = [int(x) for x in re.split(r"[\-]", end_date)]
            date1_obj = datetime.date(date1[0], date1[1], date1[2])
            date2_obj = datetime.date(date2[0], date2[1], date2[2])
            self.epochs = random.randint(-1, int((date2_obj - date1_obj).days * 0.2))
        else:
            self.epochs = -1
        self.increment_date()  # needed to be sure we're not on a weekend/holiday


def run(stock_names, 
        start_date, 
        end_date, 
        random_start=True, 
        save_location="initial_policy"):
    env = StockEnv(stock_names, start_date, end_date, random_start=random_start)
    
    utils.log_info("Environment Initilized")
    policy = TD3(env.state.shape[0], env.action_space.shape[0], max_action=MAX_LIMIT)
    # os.path.exists('initial_policy')
    if os.path.exists(save_location + "_actor"):
        print("Loaded policy")
        policy.load(save_location)

    replay_buffer = ReplayBuffer(env.state.shape[0], env.action_space.shape[0])
    state, done = env.reset(), False
    episode_reward = 0
    episode_timesteps = 0
    episode_num = 0

    with tqdm(total=NUMBER_OF_ITERATIONS) as pbar:
        for t in range(NUMBER_OF_ITERATIONS):
            episode_timesteps += 1

            # Select action randomly or according to policy
            if t < START_TIMESTEPS:
                action = env.action_space.sample()
            else:
                action = (
                    policy.select_action(np.array(state))
                    + np.random.normal(
                        0,
                        MAX_LIMIT * STD_GAUSSIAN_EXPLORATION_NOISE,
                        size=env.action_space.shape[0],
                    )
                ).clip(-MAX_LIMIT, MAX_LIMIT)
                action = action.astype(int)
            # Perform action
            next_state, reward, done = env.step(action)
            if pbar.n % 50 == 0:
                # utils.log_info(f"Date and Time: {env.get_date_and_time()}")
                # utils.log_info(f"Current Portfolio Value: {env.calculate_portfolio_value()}")
                pbar.set_description(f"Reward: {reward} | Action: {action}")

            done_bool = float(done) if episode_timesteps < env.max_epochs else 0

            # Store data in replay buffer
            replay_buffer.add(state, action, next_state, reward, done_bool)

            state = next_state
            episode_reward += reward

            # Train agent after collecting sufficient data
            if t >= START_TIMESTEPS:
                policy.train(replay_buffer, BATCH_SIZE)

            if done:
                # +1 to account for 0 indexing. +0 on ep_timesteps since it will increment +1 even if done=True
                # print(
                #     f"Total T: {t+1} Episode Num: {episode_num+1} Episode T: {episode_timesteps} Reward: {episode_reward:.3f}"
                # )
                # Reset environment
                state, done = env.reset(), False
                episode_reward = 0
                episode_timesteps = 0
                episode_num += 1
                policy.save(save_location)
            pbar.update()
    return policy, replay_buffer
    
def append_portfolio_value(df, env):
    value = env.calculate_portfolio_value()
    date, time = env.get_date_and_time()
    time = '09:30AM' if time == 'Open' else '04:00PM'
    datetime = date + " " + time
    return df.append(pd.DataFrame([round(value, 2)], columns=['Portfolio Value'], index=[datetime]))

def test(stock_names,
        start_date,
        end_date,
        policy,
        replay_buffer,
        ):
    env = StockEnv(stock_names, start_date=start_date, end_date=end_date, random_start=False)
    utils.log_info("Testing policy")
    state, done = env.reset(), False
    episode_reward = 0
    df = pd.DataFrame(columns=['Portfolio Value'])
    df = append_portfolio_value(df, env)
    
    while not done:
        # print(env.get_date_and_time())
        action = (policy.select_action(np.array(state))
                        + np.random.normal(
                            0,
                            MAX_LIMIT * STD_GAUSSIAN_EXPLORATION_NOISE,
                            size=env.action_space.shape[0],
                        )
                    ).clip(-MAX_LIMIT, MAX_LIMIT)
        next_state, reward, done = env.step(action)
        state = next_state
        episode_reward += reward
        policy.train(replay_buffer, BATCH_SIZE)
        df = append_portfolio_value(df, env)            
    df.to_csv('results/test_results.csv', index_label='Date')
