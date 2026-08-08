from kaggle_environments import make

# Setup the environment
env = make("kaggriculture", configuration={"episodeSteps": 720}, debug=True)

print("Starting match: CounterAgent vs Baseline")
# Run a match between our newly created counter agent and the baseline
env.run(["counter_agent.py", "main.py"])

final = env.steps[-1]
for i, s in enumerate(final):
    print(f"Player {i}: reward={s.reward}, status={s.status}")

# Calculate who won
p0_reward = final[0].reward
p1_reward = final[1].reward

if p0_reward > p1_reward:
    print(f"CounterAgent WON! Margin: {p0_reward - p1_reward}")
elif p1_reward > p0_reward:
    print(f"Baseline WON. Margin: {p1_reward - p0_reward}")
else:
    print("It's a TIE!")
