"""
Implémentation du modèle d'optimisation "accessibilité aux POI"
(Frank, Dirks & Walther, 2021 - Section 3.2.2, équations 1-12).

Les données d'entrée (nœuds, hubs candidats, itinéraires potentiels,
temps de trajet, seuils) doivent être préparées en amont (cf. algo_itineraires.py)
à partir des couches QGIS, puis passées ici sous forme de structures Python simples.
Le solveur ne dépend pas de QGIS : il peut donc être testé indépendamment.
"""
from dataclasses import dataclass, field
import pulp
from collections import defaultdict
import time
import datetime

import cProfile, pstats
@dataclass
class Itinerary:
    id: str
    node: str            # population node i
    poi_category: str    # POI category p
    travel_time: float    # t_s
    hubs_required: list  # [(hub_location, mode), ...]
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
    big_m: dict = None

@dataclass
class WorkplaceItinerary:
    id: str
    origin: str            # population node i
    destination: str        # population node j
    travel_time: float       # t_s (temps du trajet)
    ratio_car: float         # r_s = temps voiture / temps de ce trajet (eq. 13)
    hubs_required: list    # [(hub_location, mode), ...]
    parking_demand: dict      # {(hub_location, mode): delta_lms}

@dataclass
class WorkplaceProblemData :
    commuting_volume: dict          # {(i, j): w_ij}
    hub_locations: list        # list of l
    modes: list                 # list of m
    itineraries: list           # list[Itinerary]
    fixed_cost_hub: float        # c^F
    fixed_cost_mode: dict        # {mode: c_m^f}
    budget: float                 # B

def solve_by_subregion():
    pass

def solve_poi_model(feedback, data: ProblemData, time_limit_s: int = 300,
                    allow_unimodal_cs = False):
    """Résout le MIP d'accessibilité aux POI et renvoie les décisions."""
    
    used_hubs = {l for it in data.itineraries for (l, m) in it.hubs_required}
    hub_locations = [l for l in data.hub_locations if l in used_hubs]
    
    
    prob = pulp.LpProblem("poi_accessibility", pulp.LpMaximize)
    t0 = time.time()
    # --- variables ---
    y = {(l, m): pulp.LpVariable(f"y_{l}_{m}", cat="Binary") #Hub installé en l avec mode m ?
         for l in hub_locations for m in data.modes}
    e = {l: pulp.LpVariable(f"e_{l}", lowBound=0, upBound=data.fixed_cost_hub) #Coûts d'installation
         for l in hub_locations}
    u = {(l, m): pulp.LpVariable(f"u_{l}_{m}", lowBound=0, cat="Integer") #Nombre de places de parking au hub
         for l in hub_locations for m in data.modes}

    x = {it.id: pulp.LpVariable(f"x_{it.id}", cat="Binary") for it in data.itineraries} #Itinéraire réalisable ?
    z = {it.id: pulp.LpVariable(f"z_{it.id}", cat="Binary") for it in data.itineraries} #Itinéraire permet de connecter
    #catégorie p de Poi ?
    feedback.pushInfo("Initialisation des variables")
    
    nodes_pois = {(it.node, it.poi_category) for it in data.itineraries}
    a = {np_: pulp.LpVariable(f"a_{np_[0]}_{np_[1]}", cat="Binary") for np_ in nodes_pois} #Itinéraire permet de connecter
    #catégorie p dans la limite de temps ?
    
    #Diagnostic
    problematic = []
    for (i, j) in nodes_pois:
        its_ij = [it for it in data.itineraries if it.node == i and it.poi_category == j]
        viable = [
            it for it in its_ij
            if allow_unimodal_cs or not any("cs" in (l, m) for (l, m) in it.hubs_required)
        ]
        if not viable:
            problematic.append((i, j, len(its_ij)))
    feedback.pushInfo(f"Paires OD sans itinéraire viable : {len(problematic)} / {len(nodes_pois)}")
    for i, j, n in problematic[:10]:
        feedback.pushInfo(f"  {i} -> {j} : {n} itinéraires, tous forcés à 0 (cs unimodal)")
        
    # --- Objectif ---
    total_pop = sum(data.population.values())
    n_cat = len(data.poi_categories)
    prob += pulp.lpSum(
        data.population[node] * a[(node, cat)] for (node, cat) in nodes_pois
    ) / (total_pop * n_cat)
    feedback.pushInfo("Objectif ajouté")

    # --- contraintes : par itinéraire ---
    parking_by_hub_mode = defaultdict(list)  
    by_node_cat = defaultdict(list)
    for it in data.itineraries:
        by_node_cat[(it.node, it.poi_category)].append(it)
        for (l, m) in it.hubs_required:
            if not allow_unimodal_cs and ("cs" in l or "cs" in m):
                prob += x[it.id] == 0
            prob += x[it.id] <= y[(l, m)]                       # (2)
        prob += z[it.id] <= x[it.id]                            # (3)        
        for (l, m), demand in it.parking_demand.items():
            if demand:  # ignore les 0 explicites
                parking_by_hub_mode[(l, m)].append((it.id, demand))
    
    for (node, cat), its in by_node_cat.items():
        its = [it for it in data.itineraries if it.node == node and it.poi_category == cat]
        prob += pulp.lpSum(z[it.id] for it in its) == 1           # (4)
        for it in its:
            print(cat)
            t_hat = data.travel_time_threshold[cat]
            print("Limite temps : ",t_hat)
            
            print("M : ", data.big_m[cat])
            print("a : ",  a[(node, cat)])
            print("z : ", z[it.id])
            prob += it.travel_time * z[it.id] <= t_hat + data.big_m[cat] * (1 - a[(node, cat)])  # (5)

    # --- contrainte : places de parking ---
    
    for l in hub_locations:
        for m in data.modes:
            pairs = parking_by_hub_mode.get((l, m), [])
            demand = pulp.lpSum(
                d * x[it.id] for it_id, d in pairs
            )
            prob += demand <= u[(l, m)]

    # --- contraintes : coûts d'installation / budget ---
    for l in hub_locations:
        for m in data.modes:
            prob += data.fixed_cost_hub * y[(l, m)] <= e[l]        # (7)
        prob += e[l] <= data.fixed_cost_hub

    prob += pulp.lpSum(
        e[l] + pulp.lpSum(data.fixed_cost_mode[m] * u[(l, m)] for m in data.modes)
        for l in hub_locations
    ) <= data.budget                                                # (8)

    feedback.pushInfo("Contraintes ajoutées")

    # --- résolution ---
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit_s,
                               threads=4, gapRel=0.02,)
    prob.solve(solver)
    #Vérif
    for v in prob.variables():
        #feedback.pushInfo(f"{v.name}, {v.varValue}")
        if v.varValue is None:
            feedback.pushInfo(f"Variable non résolue : {v.name}")
            
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

def solve_workplace_model(feedback,data: WorkplaceProblemData , time_limit_s: int = 300,
                          allow_unimodal_cs = False):
    prob = pulp.LpProblem("workplace_accessibility", pulp.LpMaximize)
    used_hubs = {l for it in data.itineraries for (l, m) in it.hubs_required}
    hub_locations = [l for l in data.hub_locations if l in used_hubs]
    profiler = cProfile.Profile()
    profiler.enable()
    
    feedback.pushInfo(f"Hubs candidats : {len(data.hub_locations)} -> {len(hub_locations)} réellement utilisés")
    
    y = {(l, m): pulp.LpVariable(f"y_{l}_{m}", cat="Binary")
         for l in hub_locations for m in data.modes}
    e = {l: pulp.LpVariable(f"e_{l}", lowBound=0, upBound=data.fixed_cost_hub)
         for l in hub_locations}
    u = {(l, m): pulp.LpVariable(f"u_{l}_{m}", lowBound=0, cat="Integer")
         for l in hub_locations for m in data.modes}
    x = {it.id: pulp.LpVariable(f"x_{it.id}", cat="Binary") for it in data.itineraries}

    od_pairs = {(it.origin, it.destination) for it in data.itineraries}
    t0 = datetime.datetime.now()
    print("Temps 0",t0)
    
    problematic = []
    
    #Diagnostic
    for (i, j) in od_pairs:
        its_ij = [it for it in data.itineraries if it.origin == i and it.destination == j]
        viable = [
            it for it in its_ij
            if allow_unimodal_cs or not any("cs" in (l, m) for (l, m) in it.hubs_required)
        ]
        if not viable:
            problematic.append((i, j, len(its_ij)))
    feedback.pushInfo(f"Paires OD sans itinéraire viable : {len(problematic)} / {len(od_pairs)}")
    for i, j, n in problematic[:10]:
        feedback.pushInfo(f"  {i} -> {j} : {n} itinéraires, tous forcés à 0 (cs unimodal)")
    
    # --- objectif (13) ---
    #obj_var = pulp.LpVariable("obj_wp", lowBound=0, upBound=1)
    feedback.pushInfo(f"Vérification dictionnaire : {type(data.commuting_volume)}")
    feedback.pushInfo(f"Exemple clé commuting_volume : {list(data.commuting_volume.keys())[:3]}")
    feedback.pushInfo(f"Types clé : {[(type(k[0]), type(k[1])) for k in list(data.commuting_volume.keys())[:3]]}")
    # feedback.pushInfo(f"Exemple od_pairs : {list(od_pairs)[:3]}")
    # feedback.pushInfo(f"Types od_pairs : {[(type(o[0]), type(o[1])) for o in list(od_pairs)[:3]]}")

    # for od in od_pairs:
    #     feedback.pushInfo(f"Volume par od : {data.commuting_volume.get(od, 0)}")

    total_w = sum(data.commuting_volume.get(od, 0) for od in od_pairs) or 1.0
    feedback.pushInfo(f"Volume total : {total_w}")
    
    obj = pulp.lpSum(
        data.commuting_volume.get((it.origin, it.destination), 0) * it.ratio_car * x[it.id]
        for it in data.itineraries
    ) / total_w
    prob += obj

    #total_flux = sum(data.commuting_volume.values())
    feedback.pushInfo("Objectif ajouté")
    # --- contrainte (14) : feasibilité selon hubs/modes choisis ---
    
    by_od = defaultdict(list)
    parking_by_hub_mode = defaultdict(list)  
    for it in data.itineraries:
        by_od[(it.origin, it.destination)].append(it)
        for (l, m) in it.hubs_required:
            if not allow_unimodal_cs and ("cs" in l or "cs" in m):
                prob += x[it.id] == 0
            prob += x[it.id] <= y[(l, m)]
        for (l, m), demand in it.parking_demand.items():
            if demand:  # ignore les 0 explicites
                parking_by_hub_mode[(l, m)].append((it.id, demand))
            
    t1 = datetime.datetime.now()
    print("Temps 2", t1)
    print("Temps entre 1 et 2", t1-t0)
    # --- contrainte (15) : exactement un itinéraire choisi par connexion (i,j) ---
    for (i, j), its in by_od.items():
        its_ij = [it for it in data.itineraries if it.origin == i and it.destination == j]
        prob += pulp.lpSum(x[it.id] for it in its_ij) == 1
        
    # --- contrainte (16) : places de parking ---
    for l in hub_locations:
        for m in data.modes:
            pairs = parking_by_hub_mode.get((l, m), [])
            demand = pulp.lpSum(
                d * x[it.id] for it_id, d in pairs
            )
            prob += demand <= u[(l, m)]
    profiler.disable()
    stats = pstats.Stats(profiler).sort_stats('cumulative')
    stats.print_stats(15)
    t2 = datetime.datetime.now()
    print("Temps 3", t2)
    print("Temps entre 3 et 2", t2-t1)
    feedback.pushInfo(f"Avant bloc budget : {len(prob.variables())} variables, {len(prob.constraints)} contraintes")
    feedback.pushInfo(f"len(data.modes) = {len(data.modes)}")
    
    # --- contraintes (17)-(19) : coûts d'installation / budget ---
    for l in hub_locations:
        for m in data.modes:
            prob += data.fixed_cost_hub * y[(l, m)] <= e[l]
        prob += e[l] <= data.fixed_cost_hub
    profiler.disable()
    stats = pstats.Stats(profiler).sort_stats('cumulative')
    stats.print_stats(15)
    t3 = datetime.datetime.now()
    print("Temps 4", t3)
    print("Temps entre 3 et 4", t3-t2)
    prob += pulp.lpSum(
        e[l] + pulp.lpSum(data.fixed_cost_mode[m] * u[(l, m)] for m in data.modes)
        for l in hub_locations
    ) <= data.budget
    feedback.pushInfo("Contraintes ajoutées")
    
    modes_utilises = {m for it in data.itineraries for (l, m) in it.hubs_required}
    cout_min_estime = len(set(l for it in data.itineraries for (l, m) in it.hubs_required)) * data.fixed_cost_hub
    feedback.pushInfo(f"Budget : {data.budget}, coût minimal approximatif (tous hubs actifs) : {cout_min_estime}")

    # --- résolution ---
    #solver = pulp.PULP_CBC_CMD(msg=True, timeLimit=time_limit_s,
                               #threads=4, gapRel=0.02,)
    solver = pulp.getSolver('HiGHS', msg=True, timeLimit=time_limit_s)
    t1 = datetime.datetime.now()
    print(t1)
    prob.solve(solver)
    feedback.pushInfo("Résolution faite")
    status = pulp.LpStatus[prob.status]
    feedback.pushInfo(f"Statut : {status}")
    feedback.pushInfo(f"Objectif : {str(pulp.value(prob.objective))}")
    feedback.pushInfo(f"Hubs : {str(pulp.value(y[(l, m)]))}")
    
    if pulp.value(prob.objective) is None:
        #feedback.pushInfo(f"Aucune solution trouvée (statut : {status})")
        return {
            "status": status,
            "objective": None,
            "hubs": {},
            "parking_spaces": {},
            "itineraries_used": [],
        }
    
    #Vérif
    for v in prob.variables():
        feedback.pushInfo(f"{v.name}, {v.varValue}")
        if v.varValue is None:
            feedback.pushInfo(f"Variable non résolue : {v.name}")
    

    hubs_selected = {(l, m): pulp.value(y[(l, m)]) for (l, m) in y if pulp.value(y[(l, m)]) > 0.5}
    parking = {(l, m): pulp.value(u[(l, m)]) for (l, m) in u if pulp.value(u[(l, m)]) and pulp.value(u[(l, m)]) > 0}
    itineraries_used = [it.id for it in data.itineraries if pulp.value(x[it.id]) > 0.5]



    
    return {
        "status": status,
        "objective": pulp.value(prob.objective),
        "hubs": hubs_selected,
        "parking_spaces": parking,
        "itineraries_used": itineraries_used,
    }


def cout_minimal_couverture(data, allow_unimodal_cs=False):
    prob = pulp.LpProblem("min_cost_cover_full", pulp.LpMinimize)

    hub_mode_pairs = {(l, m) for it in data.itineraries for (l, m) in it.hubs_required}
    y = {(l, m): pulp.LpVariable(f"y_{l}_{m}", cat="Binary") for (l, m) in hub_mode_pairs}
    e = {l: pulp.LpVariable(f"e_{l}", lowBound=0, upBound=data.fixed_cost_hub)
         for l in {l for (l, m) in hub_mode_pairs}}
    u = {(l, m): pulp.LpVariable(f"u_{l}_{m}", lowBound=0, cat="Integer") for (l, m) in hub_mode_pairs}
    x = {it.id: pulp.LpVariable(f"x_{it.id}", cat="Binary") for it in data.itineraries}

    prob += pulp.lpSum(e[l] for l in e) + pulp.lpSum(
        data.fixed_cost_mode[m] * u[(l, m)] for (l, m) in hub_mode_pairs
    )

    od_pairs = {(it.origin, it.destination) for it in data.itineraries}
    for (i, j) in od_pairs:
        its = [it for it in data.itineraries if it.origin == i and it.destination == j]
        prob += pulp.lpSum(x[it.id] for it in its) == 1

    for it in data.itineraries:
        for (l, m) in it.hubs_required:
            if not allow_unimodal_cs and "cs" in (l, m):
                prob += x[it.id] == 0
            prob += x[it.id] <= y[(l, m)]

    for l in {l for (l, m) in hub_mode_pairs}:
        for m in data.modes:
            if (l, m) in y:
                prob += data.fixed_cost_hub * y[(l, m)] <= e[l]

    # parking, cette fois inclus
    for (l, m) in hub_mode_pairs:
        demand = pulp.lpSum(
            it.parking_demand.get((l, m), 0) * x[it.id] for it in data.itineraries
        )
        prob += demand <= u[(l, m)]

    solver = pulp.getSolver('HiGHS', msg=False, timeLimit=120)
    prob.solve(solver)
    return pulp.LpStatus[prob.status], pulp.value(prob.objective)



