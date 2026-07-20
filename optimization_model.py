"""
Implémentation du modèle d'optimisation "accessibilité aux POI"
(Frank, Dirks & Walther, 2021 - Section 3.2.2, équations 1-12).

Les données d'entrée (nœuds, hubs candidats, itinéraires potentiels,
temps de trajet, seuils) doivent être préparées en amont (cf. build_itineraries.py)
à partir des couches QGIS, puis passées ici sous forme de structures Python simples.
Le solveur ne dépend pas de QGIS : il peut donc être testé indépendamment.
"""
from dataclasses import dataclass, field
import pulp


@dataclass
class Itinerary:
    id: str
    node: str            # population node i
    poi_category: str    # POI category p
    travel_time: float    # t_s
    hub_requirements: list  # [(hub_location, mode), ...]
    parking_demand: dict  # {(hub_location, mode): delta_lms}


@dataclass
class ProblemData:
    population: dict          # {node: n_i}
    poi_categories: list       # list of p
    hub_locations: list        # list of l
    modes: list                 # list of m
    itineraries: list           # list[Itinerary], grouped implicitly by (node, poi_category)
    travel_time_threshold: dict  # {poi_category: t_hat_p}
    fixed_cost_hub: float        # c^F
    fixed_cost_mode: dict        # {mode: c_m^f}
    budget: float                 # B
    big_m: float = 1e6

@dataclass
class WorkplaceItinerary:
    id: str
    origin: str            # population node i
    destination: str        # population node j
    travel_time: float       # t_s (temps du trajet public/intermodal)
    ratio_car: float          # r_s = temps voiture / temps de ce trajet (eq. 13)
    hub_requirements: list    # [(hub_location, mode), ...]
    parking_demand: dict      # {(hub_location, mode): delta_lms}

@dataclass
class WorkplaceProblemData :
    commuting_volume: dict          # {node: n_i}
    hub_locations: list        # list of l
    flux: list                  #
    modes: list                 # list of m
    itineraries: list           # list[Itinerary]
    fixed_cost_hub: float        # c^F
    fixed_cost_mode: dict        # {mode: c_m^f}
    budget: float                 # B


def solve_poi_model(data: ProblemData, time_limit_s: int = 300):
    """Résout le MIP d'accessibilité aux POI et renvoie les décisions."""
    prob = pulp.LpProblem("poi_accessibility", pulp.LpMaximize)

    # --- variables ---
    y = {(l, m): pulp.LpVariable(f"y_{l}_{m}", cat="Binary")
         for l in data.hub_locations for m in data.modes}
    e = {l: pulp.LpVariable(f"e_{l}", lowBound=0, upBound=data.fixed_cost_hub)
         for l in data.hub_locations}
    u = {(l, m): pulp.LpVariable(f"u_{l}_{m}", lowBound=0, cat="Integer")
         for l in data.hub_locations for m in data.modes}

    x = {it.id: pulp.LpVariable(f"x_{it.id}", cat="Binary") for it in data.itineraries}
    z = {it.id: pulp.LpVariable(f"z_{it.id}", cat="Binary") for it in data.itineraries}

    nodes_pois = {(it.node, it.poi_category) for it in data.itineraries}
    a = {np_: pulp.LpVariable(f"a_{np_[0]}_{np_[1]}", cat="Binary") for np_ in nodes_pois}

    # --- objectif (1) ---
    total_pop = sum(data.population.values())
    n_cat = len(data.poi_categories)
    prob += pulp.lpSum(
        data.population[node] * a[(node, cat)] for (node, cat) in nodes_pois
    ) / (total_pop * n_cat)

    # --- contraintes (2)-(5) : par itinéraire ---
    for it in data.itineraries:
        for (l, m) in it.hub_requirements:
            prob += x[it.id] <= y[(l, m)]                       # (2)
        prob += z[it.id] <= x[it.id]                              # (3)

    for (node, cat) in nodes_pois:
        its = [it for it in data.itineraries if it.node == node and it.poi_category == cat]
        prob += pulp.lpSum(z[it.id] for it in its) == 1           # (4)
        for it in its:
            t_hat = data.travel_time_threshold[cat]
            prob += it.travel_time * z[it.id] <= t_hat + data.big_m * (1 - a[(node, cat)])  # (5)

    # --- contrainte (6) : places de parking ---
    for l in data.hub_locations:
        for m in data.modes:
            demand = pulp.lpSum(
                it.parking_demand.get((l, m), 0) * x[it.id] for it in data.itineraries
            )
            prob += demand <= u[(l, m)]

    # --- contraintes (7)-(9) : coûts d'installation / budget ---
    for l in data.hub_locations:
        for m in data.modes:
            prob += data.fixed_cost_hub * y[(l, m)] <= e[l]        # (7)
        prob += e[l] <= data.fixed_cost_hub

    prob += pulp.lpSum(
        e[l] + pulp.lpSum(data.fixed_cost_mode[m] * u[(l, m)] for m in data.modes)
        for l in data.hub_locations
    ) <= data.budget                                                # (8)

    # --- résolution ---
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit_s)
    prob.solve(solver)

    hubs_selected = {(l, m): pulp.value(y[(l, m)]) for (l, m) in y if pulp.value(y[(l, m)]) > 0.5}
    parking = {(l, m): pulp.value(u[(l, m)]) for (l, m) in u if pulp.value(u[(l, m)]) and pulp.value(u[(l, m)]) > 0}
    itineraries_used = [it.id for it in data.itineraries if pulp.value(x[it.id]) > 0.5]

    return {
        "status": pulp.LpStatus[prob.status],
        "objective": pulp.value(prob.objective),
        "hubs": hubs_selected,
        "parking_spaces": parking,
        "itineraries_used": itineraries_used,
    }

def solve_workplace_model(data: WorkplaceProblemData , time_limit_s: int = 300):
    prob = pulp.LpProblem("workplace_accessibility", pulp.LpMaximize)
    y = {(l, m): pulp.LpVariable(f"y_{l}_{m}", cat="Binary")
         for l in data.hub_locations for m in data.modes}
    e = {l: pulp.LpVariable(f"e_{l}", lowBound=0, upBound=data.fixed_cost_hub)
         for l in data.hub_locations}
    u = {(l, m): pulp.LpVariable(f"u_{l}_{m}", lowBound=0, cat="Integer")
         for l in data.hub_locations for m in data.modes}
    x = {it.id: pulp.LpVariable(f"x_{it.id}", cat="Binary") for it in data.itineraries}

    od_pairs = {(it.origin, it.destination) for it in data.itineraries}

    # --- objectif (13) ---
    total_w = sum(data.commuting_volume.get(od, 0) for od in od_pairs) or 1.0
    prob += pulp.lpSum(
        data.commuting_volume.get((it.origin, it.destination), 0) * it.ratio_car * x[it.id]
        for it in data.itineraries
    ) / total_w

    total_flux = data.commuting_volume["volume"].sum()
    # prob += (
    #     pulp.lpSum(
    #         flux_dict.get((it.origin, it.destination), 0)
    #         * (travel_matrix_car[node_ids.index(it.origin)]
    #                             [node_ids.index(it.destination)]
    #            / max(it.travel_time, 1))
    #         * x[it.itinerary_id]
    #         for it in itineraries
    #     ) / total_flux
    # )
    obj_var = pulp.LpVariable("obj_wp", lowBound=0, upBound=1)
    prob += pulp.lpSum(
        data.population[node] * a[(node, cat)] for (node, cat) in nodes_pois
    ) / (total_pop * n_cat)
    prob += obj_var == (
        pulp.lpSum(flux_dict.get((it.origin, it.destination), 0)
        * (travel_matrix_car[node_ids.index(it.origin)]
                            [node_ids.index(it.destination)]
           / max(it.travel_time, 1))
        * x[it.itinerary_id]
        for it in itineraries)
     / total_flux
    )
    
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit_s)
    prob.solve(solver)

    hubs_selected = {(l, m): pulp.value(y[(l, m)]) for (l, m) in y if pulp.value(y[(l, m)]) > 0.5}
    parking = {(l, m): pulp.value(u[(l, m)]) for (l, m) in u if pulp.value(u[(l, m)]) and pulp.value(u[(l, m)]) > 0}
    itineraries_used = [it.id for it in data.itineraries if pulp.value(x[it.id]) > 0.5]

    return {
        "status": pulp.LpStatus[prob.status],
        "objective": pulp.value(prob.objective),
        "hubs": hubs_selected,
        "parking_spaces": parking,
        "itineraries_used": itineraries_used,
    }