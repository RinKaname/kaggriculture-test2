from kaggle_environments import make
import json

env = make("kaggriculture", configuration={"episodeSteps": 720}, debug=True)
env.run(["counter_agent.py", "main.py"])

print(f"CounterAgent Money: {env.steps[-1][0].reward}")
print(f"Baseline Money: {env.steps[-1][1].reward}")
