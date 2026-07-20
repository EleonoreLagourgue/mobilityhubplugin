# -*- coding: utf-8 -*-
"""
Created on Thu Jul  9 16:38:33 2026

@author: eleonore.lagourgue
Code pour constuire les itinéraires pour le plug-in
"""

import networkx as nx
import  numpy as np
import osmnx as ox
import geopandas as gpd
import pandas as pd
import shapely
import matplotlib.pyplot as plt
import re
from scipy.spatial import cKDTree
import sqlalchemy

from qgis.core import *
import qgis.utils
from .optimization_model import ProblemData, Itinerary, WorkplaceProblemData, WorkplaceItinerary
from .network_routing import build_offline_graph, shortest_path_minutes, straight_line_time_minutes


modes = ["voiture", "velo", "marche", ]
modes = ["pt", "bs", "cs", "walk", "rs"]
max_transfers=2

def nodes(gdf):
    if gdf.crs != 2154:
        gdf.to_crs(2154)
    gdf["lon"] = gdf.geometry.centroid.x
    gdf["lat"] = gdf.geometry.centroid.y
    if "code_insee" in gdf.columns:
        gdf["hub_id"]    = gdf["code_insee"]
        
    else:
        gdf["hub_id"] = gdf.index
        
    gdf = gdf.set_index("hub_id")
    node_coords = dict(zip(gdf.index, zip(gdf["lat"], gdf["lon"])))
   
    return node_coords, gdf



def itineraires(origin: gpd.GeoDataFrame, 
                hubs_potentiels: gpd.GeoDataFrame,
                mat_car,
                mat_pt,
                mat_walk,
                mat_bike,
                dest: gpd.GeoDataFrame = None,
                max_ratio_vs_car=3.0,
                min_improvement=0.10):
    
    itineraries = []
    iid = 0 #compteur pour créer l'id de chaque itinéraire
    
    for i, orig in origin.iterrows():
        for j, dest in origin.iterrows():
            if orig.equals(dest):
                continue

            t_car = mat_car.loc[i, j] #temps en voiture
            t_pt  = mat_pt.loc[i, j] #temps de comparaison
            if t_car == np.inf or t_pt == np.inf:
                continue
            t_max = min(t_pt, max_ratio_vs_car * t_car)
            
            itineraries.append(Itinerary(
                origin=i, destination=j,
                mode_seq=["pt"], hubs_required=[],
                travel_time=t_pt, time_car = t_car, itinerary_id=iid
            ))
            iid += 1
            
            useful_hubs = get_useful_hubs(
                i, j, hubs_potentiels, 
                mat_pt, mat_walk,
                t_pt, t_max, min_improvement
            )
            
            for hub_id in useful_hubs:
                t1 = (mat_pt[i][hub_id] + TRANSFER_TIME
                      + mat_walk[hub_id][j])
                if t1 < t_pt * (1 - min_improvement) and t1 < t_max:
                    itineraries.append(Itinerary(
                        origin=orig, destination=dest,
                        mode_seq=["pt", "cs"],
                        hubs_required=[(hub_id, "cs")],
                        travel_time=t1, time_car = t_car, itinerary_id=iid
                    ))
                    iid += 1
                # Mode à demande jusqu'au hub, puis TC
                t2 = (mat_walk[i][hub_id] + TRANSFER_TIME
                      + mat_pt[hub_id][j])
                if t2 < t_pt * (1 - min_improvement) and t2 < t_max:
                    itineraries.append(Itinerary(
                        origin=orig, destination=dest,
                        mode_seq=["cs", "pt"],
                        hubs_required=[(hub_id, "cs")],
                        travel_time=t2,  time_car = t_car,itinerary_id=iid
                    ))
                    iid += 1
            
            
            useful_hubs = get_useful_hubs(
                i, j, hubs_potentiels, 
                mat_pt, mat_car,
                t_pt, t_max, min_improvement
            )
            
            for hub_id in useful_hubs:
                t1 = (mat_pt[i][hub_id] + TRANSFER_TIME
                      + mat_car[hub_id][j])
                if t1 < t_pt * (1 - min_improvement) and t1 < t_max:
                    itineraries.append(Itinerary(
                        origin=orig, destination=dest,
                        mode_seq=["pt", "cs"],
                        hubs_required=[(hub_id, "cs")],
                        travel_time=t1, time_car = t_car, itinerary_id=iid
                    ))
                    iid += 1
                # Mode à demande jusqu'au hub, puis TC
                t2 = (mat_car[i][hub_id] + TRANSFER_TIME
                      + mat_pt[hub_id][j])
                if t2 < t_pt * (1 - min_improvement) and t2 < t_max:
                    itineraries.append(Itinerary(
                        origin=orig, destination=dest,
                        mode_seq=["cs", "pt"],
                        hubs_required=[(hub_id, "cs")],
                        travel_time=t2, time_car = t_car, itinerary_id=iid
                    ))
                    iid += 1
                    
            #Bike sharing
            useful_hubs = get_useful_hubs(
                i, j, hubs_potentiels, 
                mat_pt, mat_bike,
                t_pt, t_max, min_improvement
            )
            
            for hub_id in useful_hubs:
                t1 = (mat_pt[i][hub_id] + TRANSFER_TIME
                      + mat_bike[hub_id][j])
                itineraries.append(Itinerary(
                    origin=orig, destination=dest,
                    mode_seq=["pt", "bs"],
                    hubs_required=[(hub_id, "bs")],
                    travel_time=t1, time_car = t_car, itinerary_id=iid
                ))
                iid += 1
                # Mode à demande jusqu'au hub, puis TC
                t2 = (mat_bike[i][hub_id] + TRANSFER_TIME
                      + mat_pt[hub_id][j])
                itineraries.append(Itinerary(
                    origin=orig, destination=dest,
                    mode_seq=["bs", "pt"],
                    hubs_required=[(hub_id, "bs")],
                    travel_time=t2, time_car = t_car, itinerary_id=iid
                ))
                iid += 1
            
            
    return elimination_itineraires_domines(itineraries)



    
    pass

def get_useful_hubs(i, j, hubs_potentiels, 
                    mat_pt, mat_car, t_pt, t_max, min_improvement):
    """
    Ne retourne que les hubs h tels que :
    - PT(i vers h) + CAR(h vers j) < t_pt * (1 - min_improvement)
    - ou CAR(i vers h) + PT(h vers j) < t_pt * (1 - min_improvement)
    Évite d'énumérer tous les hubs pour chaque paire O-D.
    """
    useful = []
    for hub_id in hubs_potentiels:
        print(hub_id)
         
        t1 = mat_pt[i][hub_id] + TRANSFER_TIME + mat_car[hub_id][j]
        t2 = mat_car[i][hub_id] + TRANSFER_TIME + mat_pt[hub_id][j]
        
        if (t1 < t_pt * (1 - min_improvement) and t1 < t_max) or \
           (t2 < t_pt * (1 - min_improvement) and t2 < t_max) :
            useful.append(hub_id)
    return useful
# =============================================================================
# 3. Suppressions des itinéraires dominés
# =============================================================================
def elimination_itineraires_domines(itineraires):
    by_od = defaultdict(list)
    for it in itineraires:
        by_od[(it.origin, it.destination)].append(it)
        #Construit dictionnaire avec comme clé origine& destination

    kept = []
    for od, itis in by_od.items():
        its_sorted = itis.sort_values(by = ["travel_time"])
        non_dominated = []
        for cand in its_sorted:
            dominated = False
            req_c = set(cand.hubs_required)
            for better in non_dominated:
                req_b = set(better.hubs_required)
                # cand dominé si ses requirements sont un surensemble de ceux de better
                # ET better est plus rapide (garanti par le tri i.e. sorted)
                if req_b.issubset(req_c):
                    dominated = True
                    break
            if not dominated:
                non_dominated.append(cand)
        kept.extend(non_dominated)

    return kept