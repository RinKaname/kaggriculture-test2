"""SubinStyleRule — Stateless rule-based recreation of the Subin An strategy.

Reverse-engineered from episode 89945750 (Subin An, 629/644 win rate):
  - Day 0: Hire 2 hands, BUY 1 cow immediately, plant 6+ melons + wheat
  - Days 0-3: Build pastures, place cows + sheep, CARE + FEED daily
  - Days 2-12: Water crops, collect fertilizer, sell fertilizer + wheat
  - Day 10-15: Harvest melons in bulk, start strawberry phase
  - Day 12+: Scale livestock (2nd cow/sheep wave), expand land
  - Day 20+: Pure milk/wool/strawberry harvest + endgame sell

Key insight: Cows → fertilizer → strawberry yield bonus → more revenue than
either pure melons or pure cows alone. The cross-subsidy is the strategy.

Unlike subin_an_tape.py (328KB pre-recorded trace), this agent is STATELESS —
it reads the current game observation and decides, so it works at any step.
"""
import math
from src.baseline import (
    CROPS, NW_PASTURES, NE_PASTURES, SW_PASTURES, SHED_ACCESS,
    get_step_towards, get_bfs_step, ZScoreMarketTracker,
)
from src.strategy_params import StrategyParams, PARAMS_SUBIN

# Base prices for sell threshold calculation (from README)
_BASE_PRICE = {
    "WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120,
    "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100,
}

# Products that can be sold (not animals)
_SELLABLE = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
             "EGG", "MILK", "WOOL", "FERTILIZER"]


class SubinStyleRule:
    """
    Stateless rule-based agent inspired by the Subin An strategy.

    Usage:
        agent = SubinStyleRule()
        action = agent.act(obs, params)   # params optionally neural-adjusted
    """

    def __init__(self):
        # Z-score tracker is per-instance so it accumulates price history across turns
        self._market_tracker = ZScoreMarketTracker(window=24)

    def act(self, obs: dict, params: StrategyParams = None) -> dict:
        """
        Produce one action dict for the current observation.
        `params` defaults to PARAMS_SUBIN if not provided.
        """
        if params is None:
            params = PARAMS_SUBIN

        player_id = obs.get("player", 0)
        farms = obs.get("farms", [])
        if len(farms) <= player_id:
            return {"farmer": ["PASS"], "hands": [], "market": []}

        farm     = farms[player_id]
        private  = obs.get("private", {})
        day      = int(obs.get("day", 0) or 0)
        hour     = int(obs.get("hour", 0) or 0)
        step     = int(obs.get("step", 0) or 0)
        money    = float(farm.get("money", 0) or 0)
        shed     = private.get("shed", {}) or {}
        seeds    = private.get("seeds", {}) or {}
        inv_list = private.get("inventories", []) or []
        prices   = (obs.get("market", {}) or {}).get("prices", {}) or {}

        unlocked_quads = farm.get("unlocked_quadrants", ["NW"])
        all_tiles      = farm.get("tiles", [])

        # --- Build tile index ---
        unlocked, crop_tiles, pasture_slots = self._index_tiles(
            all_tiles, unlocked_quads
        )

        # --- Animals census ---
        placed_cows   = sum(1 for t in self._iter_tiles(all_tiles)
                            if isinstance(t, dict) and t.get("animal") == "COW")
        placed_sheep  = sum(1 for t in self._iter_tiles(all_tiles)
                            if isinstance(t, dict) and t.get("animal") == "SHEEP")
        shed_cows     = int(shed.get("COW", 0) or 0)
        shed_sheep    = int(shed.get("SHEEP", 0) or 0)
        inv_cows      = sum(int(iv.get("COW", 0) or 0) for iv in inv_list)
        inv_sheep     = sum(int(iv.get("SHEEP", 0) or 0) for iv in inv_list)
        total_cows    = placed_cows  + shed_cows  + inv_cows
        total_sheep   = placed_sheep + shed_sheep + inv_sheep
        total_animals = total_cows + total_sheep

        # --- Crop census ---
        active_melons = sum(1 for (x, y) in crop_tiles
                            if isinstance(all_tiles[y][x], dict)
                            and all_tiles[y][x].get("crop") == "MELON")
        active_straw  = sum(1 for (x, y) in crop_tiles
                            if isinstance(all_tiles[y][x], dict)
                            and all_tiles[y][x].get("crop") == "STRAWBERRY")
        held_melon_seeds = int(seeds.get("MELON", 0) or 0)
        held_straw_seeds = int(seeds.get("STRAWBERRY", 0) or 0)

        # --- Shed totals ---
        total_shed = sum(int(v or 0) for v in shed.values())
        is_endgame = day >= params.endgame_liquidation_day

        # ---------------------------------------------------------------
        # MARKET ORDERS
        # ---------------------------------------------------------------
        market = []

        # 1. Land expansion
        if len(unlocked_quads) == 1 and money >= params.expand_cash_reserve and day >= params.expand_day and len(market) < 10:
            market.append(["BUY_LAND"])
        elif len(unlocked_quads) == 2 and money >= 3000 and day >= params.expand_day + 4 and len(market) < 10:
            market.append(["BUY_LAND"])

        # 2. Worker hiring (early each day only)
        current_workers = 1 + len(farm.get("hands", []))
        needed = min(params.hire_target + 1, 18)  # +1 for farmer itself
        if current_workers < needed and hour <= params.hire_cutoff_hour and money >= 50:
            for _ in range(min(2, needed - current_workers)):
                if len(market) < 10:
                    market.append(["HIRE"])

        # 3. Wheat feed buffer
        placed_animals = placed_cows + placed_sheep
        if placed_animals > 0:
            wheat_need = placed_animals * 2 - int(shed.get("WHEAT", 0) or 0)
            if wheat_need > 0 and money >= wheat_need * 30 and len(market) < 10:
                market.append(["BUY_PRODUCT", "WHEAT", min(wheat_need, 8)])

        # 4. Buy livestock
        if day <= params.animal_cutoff_day and money >= params.animal_min_cash:
            if total_cows < params.cow_target and shed_cows == 0 and inv_cows == 0 and len(market) < 10:
                market.append(["BUY_ANIMAL", "COW", 1])
            if total_sheep < params.sheep_target and shed_sheep == 0 and inv_sheep == 0 and len(market) < 10:
                market.append(["BUY_ANIMAL", "SHEEP", 1])

        # 5. Buy melon seeds
        if day <= params.melon_cutoff_day:
            want = params.melon_target - (active_melons + held_melon_seeds)
            if want > 0 and money >= 80 * want and len(market) < 10:
                market.append(["BUY_SEED", "MELON", min(want, 4)])

        # 6. Buy strawberry seeds
        if params.straw_start_day <= day <= 24:
            want = params.straw_target - (active_straw + held_straw_seeds)
            if want > 0 and money >= 100 * want and len(market) < 10:
                market.append(["BUY_SEED", "STRAWBERRY", min(want, 4)])

        # 7. Wheat filler seeds (only if we have empty tiles and spare cash)
        empty_crop = sum(1 for (x, y) in crop_tiles if all_tiles[y][x] is None)
        total_held_seeds = sum(int(v or 0) for v in seeds.values())
        if day < 27 and empty_crop > total_held_seeds and money >= 10 and len(market) < 10:
            market.append(["BUY_SEED", "WHEAT", min(empty_crop - total_held_seeds, 6)])

        # 8. Sell produce — Z-score market timing
        self._market_tracker.update(prices)
        is_emergency = total_shed >= params.emergency_shed_cap or is_endgame
        for item in _SELLABLE:
            qty = int(shed.get(item, 0) or 0)
            if qty <= 0 or len(market) >= 10:
                continue
            cur_p = float(prices.get(item, _BASE_PRICE.get(item, 50)) or 0)
            if is_emergency or self._market_tracker.should_sell(
                    item, cur_p, day, total_shed, _BASE_PRICE):
                batch = qty if (is_emergency or day >= 27) else min(qty, params.sell_batch_size)
                if batch > 0:
                    market.append(["SELL", item, batch])

        # ---------------------------------------------------------------
        # WORKER ACTIONS
        # ---------------------------------------------------------------
        all_workers = [farm.get("farmer", [4, 4])] + farm.get("hands", [])
        sorted_crops = sorted(crop_tiles, key=lambda p: (p[1], p[0]))
        chunk = max(1, math.ceil(len(sorted_crops) / max(1, len(all_workers))))
        tiles_grid = farm.get("tiles", [])

        worker_actions = []
        for w_idx, w_pos in enumerate(all_workers):
            my_tiles = sorted_crops[w_idx * chunk: (w_idx + 1) * chunk]
            inv = inv_list[w_idx] if w_idx < len(inv_list) else {}

            # --- Goods deposit phase: if carrying 4+ items or after hour 17,
            #     move to shed so nothing gets stuck in unit inventory. ---
            _carry_goods = ["MILK", "WOOL", "EGG", "STRAWBERRY", "MELON",
                            "CARROT", "TOMATO", "WHEAT"]
            _goods_count = sum(int(inv.get(g, 0) or 0) for g in _carry_goods)
            _at_shed = tuple(w_pos) in SHED_ACCESS
            if _goods_count >= 4 and not _at_shed:
                # Navigate to nearest shed-adjacent tile via BFS
                closest = min(SHED_ACCESS,
                              key=lambda s: abs(w_pos[0]-s[0]) + abs(w_pos[1]-s[1]))
                step = get_bfs_step(tuple(w_pos), closest, tiles_grid)
                if step:
                    worker_actions.append([step])
                    continue

            act = self._worker_act(
                w_pos, my_tiles, pasture_slots,
                farm, private, day, hour, inv, w_idx, params
            )
            worker_actions.append(act)

        return {
            "farmer": worker_actions[0] if worker_actions else ["PASS"],
            "hands":  worker_actions[1:],
            "market": market[:10],
        }

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _iter_tiles(self, tiles):
        for row in tiles:
            for t in row:
                yield t

    def _index_tiles(self, tiles, unlocked_quads):
        """Return (unlocked, crop_tiles, pasture_slots) position lists."""
        pastures = list(NW_PASTURES)
        if "NE" in unlocked_quads:
            pastures += NE_PASTURES
        if "SW" in unlocked_quads:
            pastures += SW_PASTURES

        unlocked, crop_tiles = [], []
        board = len(tiles)
        for y in range(board):
            for x in range(len(tiles[y])):
                t = tiles[y][x]
                if t != "LOCKED":
                    unlocked.append((x, y))
                    if (x, y) not in pastures:
                        crop_tiles.append((x, y))
        return unlocked, crop_tiles, pastures

    def _worker_act(self, pos, assigned_tiles, pasture_slots,
                    farm, private, day, hour, inv, w_idx, params):
        """Single-worker decision (mirrors ApexGrandmasterAgent._get_worker_action)."""
        cx, cy    = pos
        tiles     = farm.get("tiles", [])
        shed      = private.get("shed", {}) or {}
        seeds     = private.get("seeds", {}) or {}
        cur_tile  = tiles[cy][cx] if cy < len(tiles) and cx < len(tiles[cy]) else None
        at_shed   = tuple(pos) in SHED_ACCESS

        # 1. Pasture setup
        if (cx, cy) in pasture_slots:
            if isinstance(cur_tile, dict) and cur_tile.get("kind") == "WEED":
                return ["DIG"]
            if cur_tile is None:
                return ["BUILD_PASTURE"]

        # 2. Animal placement from inventory
        for a_type in ("COW", "SHEEP"):
            if int(inv.get(a_type, 0) or 0) > 0:
                if (cx, cy) in pasture_slots and isinstance(cur_tile, dict) \
                        and cur_tile.get("kind") == "PASTURE" and cur_tile.get("animal") is None:
                    return ["PLACE", a_type]
                for (px, py) in pasture_slots:
                    if py < len(tiles) and px < len(tiles[py]):
                        t = tiles[py][px]
                        if isinstance(t, dict) and t.get("kind") == "PASTURE" and t.get("animal") is None:
                            step = get_step_towards((cx, cy), (px, py))
                            if step:
                                return [step]

        # 3. Shed interaction
        if at_shed:
            for it in ("MILK", "WOOL", "STRAWBERRY", "MELON", "CARROT", "TOMATO"):
                if int(inv.get(it, 0) or 0) > 0:
                    return ["PLACE", it, int(inv[it])]
            if int(inv.get("WHEAT", 0) or 0) > 4:
                return ["PLACE", "WHEAT", int(inv["WHEAT"]) - 2]
            for a_type in ("COW", "SHEEP"):
                if int(shed.get(a_type, 0) or 0) > 0 and int(inv.get(a_type, 0) or 0) == 0:
                    return ["PICKUP", a_type, 1]
            if int(inv.get("WHEAT", 0) or 0) < 3 and int(shed.get("WHEAT", 0) or 0) > 0 and hour <= 12:
                qty = min(3 - int(inv.get("WHEAT", 0) or 0), int(shed.get("WHEAT", 0) or 0))
                if qty > 0:
                    return ["PICKUP", "WHEAT", qty]
            if day >= params.fert_start_day and int(inv.get("FERTILIZER", 0) or 0) < 2 \
                    and int(shed.get("FERTILIZER", 0) or 0) > 0 and hour <= 12:
                qty = min(2 - int(inv.get("FERTILIZER", 0) or 0), int(shed.get("FERTILIZER", 0) or 0))
                if qty > 0:
                    return ["PICKUP", "FERTILIZER", qty]

        # 4. Current tile is an animal structure
        if isinstance(cur_tile, dict) and cur_tile.get("animal") is not None:
            if not cur_tile.get("fed_today") and int(inv.get("WHEAT", 0) or 0) > 0:
                return ["FEED"]
            if not cur_tile.get("cared_today"):
                return ["CARE"]
            if cur_tile.get("fertilizer_available"):
                return ["COLLECT_FERTILIZER"]
            if int(cur_tile.get("yield_units", 0) or 0) > 0:
                return ["HARVEST"]

        # 5. MELON WINDOW PRIORITY: water unwatered melons before animal sweep
        # During the bonus window (days 6-12), missing a water costs ~1 yield unit.
        # This is the bug the meta notebook explicitly flags: yield 70 vs 96.
        _in_melon_window = 6 <= day <= 12
        if _in_melon_window:
            for (tx, ty) in assigned_tiles:
                if ty >= len(tiles) or tx >= len(tiles[ty]):
                    continue
                t = tiles[ty][tx]
                if isinstance(t, dict) and t.get("kind") == "PLANT" \
                        and t.get("crop") == "MELON" \
                        and not t.get("watered_today"):
                    if (tx, ty) == (cx, cy):
                        return ["WATER"]
                    step = get_step_towards((cx, cy), (tx, ty))
                    if step:
                        return [step]

        # 6. Morning animal sweep (first `animal_keepers` workers)
        # Skipped during melon window for crop-assigned workers so watering wins.
        if hour <= 12 and w_idx < params.animal_keepers and not _in_melon_window:
            for (px, py) in pasture_slots:
                if py < len(tiles) and px < len(tiles[py]):
                    t = tiles[py][px]
                    if isinstance(t, dict) and t.get("animal") is not None:
                        needs = (
                            (not t.get("fed_today") and int(inv.get("WHEAT", 0) or 0) > 0)
                            or not t.get("cared_today")
                            or t.get("fertilizer_available")
                            or int(t.get("yield_units", 0) or 0) > 0
                        )
                        if needs:
                            step = get_step_towards((cx, cy), (px, py))
                            if step:
                                return [step]
        elif hour <= 12 and w_idx < params.animal_keepers and _in_melon_window:
            # During melon window: animal_keepers still feed (survival critical)
            # but skip CARE/COLLECT to free up turns for watering
            for (px, py) in pasture_slots:
                if py < len(tiles) and px < len(tiles[py]):
                    t = tiles[py][px]
                    if isinstance(t, dict) and t.get("animal") is not None:
                        if not t.get("fed_today") and int(inv.get("WHEAT", 0) or 0) > 0:
                            step = get_step_towards((cx, cy), (px, py))
                            if step:
                                return [step]

        # 6. Current crop tile
        if cur_tile != "LOCKED" and (cx, cy) not in pasture_slots:
            if isinstance(cur_tile, dict):
                kind = cur_tile.get("kind")
                if kind == "WEED":
                    return ["DIG"]
                elif kind == "PLANT":
                    crop = cur_tile.get("crop", "")
                    cd   = CROPS.get(crop, {})
                    age  = day - int(cur_tile.get("planted_day", day) or day)
                    # Harvest?
                    if cd.get("ongoing"):
                        if int(cur_tile.get("yield_units", 0) or 0) > 0:
                            return ["HARVEST"]
                    else:
                        if age >= cd.get("max_yield_day", 99) or (day >= 27 and age >= cd.get("first_yield_day", 99)):
                            return ["HARVEST"]
                    # Fertilize if eligible
                    if day >= params.fert_start_day and int(inv.get("FERTILIZER", 0) or 0) > 0 \
                            and crop in ("STRAWBERRY", "MELON") \
                            and int(cur_tile.get("fertilized_until_day", 0) or 0) <= day:
                        return ["FERTILIZE"]
                    # Water
                    if not cur_tile.get("watered_today"):
                        return ["WATER"]
            elif cur_tile is None and day < 27:
                for c in ("STRAWBERRY", "MELON", "WHEAT", "CARROT"):
                    if int(seeds.get(c, 0) or 0) > 0:
                        return ["PLANT", c]

        # 7. Move produce to shed
        has_produce = any(int(inv.get(it, 0) or 0) > 0
                          for it in ("MILK", "WOOL", "STRAWBERRY", "MELON", "CARROT", "TOMATO"))
        if has_produce and (hour >= 17 or sum(int(v or 0) for v in inv.values()) >= 5):
            closest = min(SHED_ACCESS, key=lambda s: abs(cx - s[0]) + abs(cy - s[1]))
            step = get_step_towards((cx, cy), closest)
            if step:
                return [step]

        # 8. Move to priority assigned tile
        target = None
        for (tx, ty) in assigned_tiles:
            if ty >= len(tiles) or tx >= len(tiles[ty]):
                continue
            t = tiles[ty][tx]
            if t == "LOCKED":
                continue
            if isinstance(t, dict):
                kind = t.get("kind")
                if kind == "WEED":
                    target = (tx, ty); break
                elif kind == "PLANT":
                    crop = t.get("crop", "")
                    cd   = CROPS.get(crop, {})
                    age  = day - int(t.get("planted_day", day) or day)
                    harvestable = (
                        (cd.get("ongoing") and int(t.get("yield_units", 0) or 0) > 0)
                        or (not cd.get("ongoing") and age >= cd.get("max_yield_day", 99))
                        or (day >= 27 and age >= cd.get("first_yield_day", 99))
                    )
                    if harvestable or not t.get("watered_today"):
                        target = (tx, ty); break
            elif t is None and day < 27 and any(int(v or 0) > 0 for v in seeds.values()):
                target = (tx, ty); break

        if target:
            step = get_step_towards((cx, cy), target)
            if step:
                return [step]

        # 9. Navigate toward an empty pasture slot
        for (px, py) in pasture_slots:
            if py < len(tiles) and px < len(tiles[py]) and tiles[py][px] is None:
                step = get_step_towards((cx, cy), (px, py))
                if step:
                    return [step]

        # 10. Return to home tile
        if assigned_tiles and (cx, cy) != assigned_tiles[0]:
            step = get_step_towards((cx, cy), assigned_tiles[0])
            if step:
                return [step]

        return ["PASS"]
