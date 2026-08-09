with open('counter_agent.py', 'r') as f:
    content = f.read()

content = "from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS\n" + content

with open('counter_agent.py', 'w') as f:
    f.write(content)
