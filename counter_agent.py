from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS
import math
import copy

class CounterAgent:
    def __init__(self):
        self.core = None

    def act(self, obs: dict) -> dict:
        if self.core is None:
            from main import ApexGrandmasterAgent
            self.core = ApexGrandmasterAgent()

            # Revert to the dictionary structure but ensure the baseline executes cleanly.
            self.core.p = {
                "sell_thresh": 0.65,
                "straw_target": 20,
                "melon_target": 15,
                "melon_cutoff_day": 17,
                "max_animals_quad2": 10,
                "animal_cutoff_day": 14,
                "animal_min_cash": 900,
                "feed_buffer_per_animal": 2,
                "tiles_per_worker": 5.0,
                "animal_keepers": 2,
                "hire_cutoff_hour": 4,
                "quad2_day_cutoff": 8,
                "quad3_day_cutoff": 12,
                "quad4_enable": True,
                "milk_wool_thresh": 0.55,
                "sell_batch_size": 6,
                "emergency_shed_cap": 70,
                "endgame_liquidation_day": 27,
                "strawberry_start_day": 12,
                "fert_start_day": 10
            }

        action = self.core.act(obs)
        day = obs["day"]
        hour = obs["hour"]
        shed = obs["private"].get("shed", {})

        opp = obs["farms"][1 - obs["player"]]
        opp_melons = sum(1 for row in opp["tiles"] for t in row if isinstance(t, dict) and t.get("crop") == "MELON")
        opp_strawberries = sum(1 for row in opp["tiles"] for t in row if isinstance(t, dict) and t.get("crop") == "STRAWBERRY")

        if not hasattr(self, "prev_opp_melons"):
            self.prev_opp_melons = opp_melons
            self.prev_opp_strawberries = opp_strawberries
            self.dumping = False
            self.dump_item = None

        harvest_detected = False
        if opp_melons < self.prev_opp_melons - 1:
            harvest_detected = True
            self.dump_item = "MELON"
            self.dumping = True
        elif opp_strawberries < self.prev_opp_strawberries - 1:
            harvest_detected = True
            self.dump_item = "STRAWBERRY"
            self.dumping = True

        self.prev_opp_melons = opp_melons
        self.prev_opp_strawberries = opp_strawberries

        filtered_market = []
        for order in action.get("market", []):
            if order[0] == "SELL":
                # Hoard Melons and Strawberries.
                if order[1] in ["MELON", "STRAWBERRY"] and day < 26 and not self.dumping and sum(shed.values()) < 80:
                    continue
                else:
                    filtered_market.append(order)
            else:
                filtered_market.append(order)

        # Execute the dump
        if self.dumping and self.dump_item:
            qty = shed.get(self.dump_item, 0)
            if qty > 0 and len(filtered_market) < 10:
                filtered_market.append(["SELL", self.dump_item, qty])
            else:
                self.dumping = False

        # End game dump
        if day >= 26:
            for item in ["MELON", "STRAWBERRY", "MILK", "WOOL"]:
                if shed.get(item, 0) > 0 and len(filtered_market) < 10:
                    filtered_market.append(["SELL", item, shed[item]])

        action["market"] = filtered_market[:10]
        return action

_agent_instance = None
def agent(obs):
    global _agent_instance
    if _agent_instance is None or obs["step"] == 0:
        _agent_instance = CounterAgent()
    return _agent_instance.act(obs)
